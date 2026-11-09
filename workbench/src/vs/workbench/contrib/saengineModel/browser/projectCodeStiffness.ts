/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { DEFAULT_CODE_PACK_ID, setActiveCodePack } from '../../../services/saengineProject/common/activeCodePack.js';
import { setActiveBarNames, setActiveDisplayUnits } from '../../../services/saengineProject/common/displayUnits.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { flushModifierFields } from './modifiersPanel.js';
import { setProjectCode } from './modifiersModel.js';
import { partFile } from './projectDocuments.js';

/** The Code Packs commands (saengineLibrary/browser/codePacksModel.ts), answered by the backend. */
const CODES_SHOW_COMMAND = 'saengine.codes.show';
/** The pack a project without `codePack` follows (saengine.library.settings). */
const DEFAULT_PACK = DEFAULT_CODE_PACK_ID;
/** The pack table holding `crackedStiffness` (the default pack's Part 6 Sec 6.3.10.4.1). */
const CONCRETE_TABLE = 'data/concrete.json';

type Json = { [key: string]: unknown };

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Reads the open project's settings and its code pack's cracked-section factors for the stiffness
 * modifiers (modifiersModel.ts `setProjectCode`), so an empty modifier field shows the factor
 * that applies ("0.7") instead of "code". The pack's `crackedStiffness` is merged along its
 * `extends` chain, the pack's own keys over its parents', as the backend merges a table's keys.
 *
 * Also stores the modifier fields typed but not yet stored before any file is saved, so Ctrl+S
 * in a field keeps the value.
 */
export class ProjectCodeStiffnessContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.projectCodeStiffness';

	private readonly scheduler = this._register(new RunOnceScheduler(() => void this.read(), 200));
	private generation = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@ITextFileService textFileService: ITextFileService,
	) {
		super();
		this._register(textFileService.files.addSaveParticipant({
			ordinal: -100,
			participate: async () => flushModifierFields(),
		}));
		this._register(projectService.onDidChangeProject(() => this.scheduler.schedule()));
		this._register(fileService.onDidFilesChange(e => {
			const root = projectService.project?.root;
			if (root && e.contains(partFile(root, 'settings'))) {
				this.scheduler.schedule();
			}
		}));
		this.scheduler.schedule();
	}

	private async read(): Promise<void> {
		const generation = ++this.generation;
		const root = this.projectService.project?.root;
		if (!root) {
			setProjectCode({});
			setActiveCodePack(undefined, undefined);
			setActiveDisplayUnits(undefined);
			return;
		}
		const settings = await this.json(partFile(root, 'settings'));
		if (generation === this.generation) {
			// C13: the editors show and read numbers in the project's display units (displayUnits.ts).
			setActiveDisplayUnits(isObject(settings) ? settings.units : undefined);
		}
		const packId = isObject(settings) && typeof settings.codePack === 'string' ? settings.codePack : DEFAULT_PACK;
		let crackedTable: Json | undefined;
		// C13b: the pack's bar names (concrete.barNames), shown in every unit system (alpha 9 C26)
		let barNames: Json = {};
		let packName: string | undefined;
		try {
			const pack = await this.show(packId, root);
			packName = typeof pack?.edition === 'string' ? pack.edition : typeof pack?.name === 'string' ? pack.name : undefined;
			const chain = Array.isArray(pack?.chain) ? pack.chain.filter((id): id is string => typeof id === 'string') : [packId];
			// From the root ancestor down to the pack: each one's keys over its parent's.
			for (const id of [...chain].reverse()) {
				const info = id === packId ? pack : await this.show(id, root);
				const table = typeof info?.path === 'string' ? await this.json(joinPath(URI.file(info.path), CONCRETE_TABLE)) : undefined;
				if (isObject(table) && isObject(table.crackedStiffness)) {
					crackedTable = { ...crackedTable, ...table.crackedStiffness };
				}
				if (isObject(table) && isObject(table.barNames)) {
					// Alpha 9 C26: a pack's "$replace" drops its parent's names (Myanmar's metric bars are not US No. 3 ...).
					barNames = table.barNames.$replace === true ? { ...table.barNames } : { ...barNames, ...table.barNames };
				}
			}
		} catch {
			// No backend (web) or the pack cannot be found: the fields say "code".
		}
		if (generation === this.generation) {
			setProjectCode({ settings, crackedTable, packName });
			// The editors name the project's code pack in their text (activeCodePack.ts).
			setActiveCodePack(packId, packName);
			setActiveBarNames(barNames);
		}
	}

	private async show(id: string, root: URI): Promise<Json | undefined> {
		const answer = await this.commandService.executeCommand<unknown>(CODES_SHOW_COMMAND, { id, root: root.fsPath });
		return isObject(answer) ? answer : undefined;
	}

	private async json(resource: URI): Promise<unknown> {
		try {
			return JSON.parse((await this.fileService.readFile(resource)).value.toString());
		} catch {
			return undefined;
		}
	}
}
