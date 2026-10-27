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
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { flushModifierFields } from './modifiersPanel.js';
import { setProjectCode } from './modifiersModel.js';
import { partFile } from './projectDocuments.js';

/** The Code Packs commands (saengineLibrary/browser/codePacksModel.ts), answered by the backend. */
const CODES_SHOW_COMMAND = 'saengine.codes.show';
/** The pack a project without `codePack` follows (saengine.library.settings). */
const DEFAULT_PACK = 'bnbc2020';
/** The pack table holding `crackedStiffness` (BNBC 2020 Part 6 Sec 6.3.10.4.1 in the built-in pack). */
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
			return;
		}
		const settings = await this.json(partFile(root, 'settings'));
		const packId = isObject(settings) && typeof settings.codePack === 'string' ? settings.codePack : DEFAULT_PACK;
		let crackedTable: Json | undefined;
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
			}
		} catch {
			// No backend (web) or the pack cannot be found: the fields say "code".
		}
		if (generation === this.generation) {
			setProjectCode({ settings, crackedTable, packName });
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
