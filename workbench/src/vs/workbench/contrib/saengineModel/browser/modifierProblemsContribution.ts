/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { localize } from '../../../../nls.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IMarkerData, IMarkerService, MarkerSeverity } from '../../../../platform/markers/common/markers.js';
import { IWorkbenchContribution } from '../../../common/contributions.js';
import { ISaenginePartStatusService, PART_CHECKS_FILE } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { ModifierPart, modifierProblems, onDidChangeModifierProblems } from './modifierProblems.js';
import { partFile } from './projectDocuments.js';

/** The owner of the markers this contribution sets. */
const MARKER_OWNER = 'saengine.modifiers';
const PARTS: readonly ModifierPart[] = ['objects', 'floorPlan'];

/**
 * Puts the problems of the stiffness modifiers and design overwrites (modifierProblems.ts: a
 * typed value that cannot be stored, a stored value the checks refuse) where problems are seen:
 *
 * - the Problems list, on the part's file (and so the problem count in the status bar);
 * - the status of 4 Objects in the parts list, through its checks file: with a problem it is
 *   not done. The Floor Plan's checks file is the plot checks' (pipeline/run_all.py), so its
 *   problems go to the Problems list only.
 */
export class ModifierProblemsContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.modifierProblems';

	private readonly scheduler = this._register(new RunOnceScheduler(() => void this.update(), 300));
	private readonly modelListeners = this._register(new DisposableStore());
	/** Problems last reported to the checks of 4 Objects: none reported yet is undefined. */
	private reported: number | undefined;
	private generation = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IModelService private readonly modelService: IModelService,
		@IFileService private readonly fileService: IFileService,
		@IMarkerService private readonly markerService: IMarkerService,
		@ISaenginePartStatusService private readonly partStatus: ISaenginePartStatusService,
	) {
		super();
		this._register(onDidChangeModifierProblems(() => this.scheduler.schedule()));
		this._register(projectService.onDidChangeProject(() => this.reset()));
		this._register(modelService.onModelAdded(model => this.watchModel(model)));
		this._register(fileService.onDidFilesChange(e => {
			if (this.resources().some(resource => e.contains(resource))) {
				this.scheduler.schedule();
			}
		}));
		this.reset();
	}

	private resources(): URI[] {
		const root = this.projectService.project?.root;
		return root ? PARTS.map(part => partFile(root, part)) : [];
	}

	private reset(): void {
		this.markerService.remove(MARKER_OWNER, this.markerService.read({ owner: MARKER_OWNER }).map(m => m.resource));
		this.modelListeners.clear();
		this.reported = undefined;
		for (const model of this.modelService.getModels()) {
			this.watchModel(model);
		}
		this.scheduler.schedule();
	}

	/** Follows the unsaved edits of the parts' files. */
	private watchModel(model: ITextModel): void {
		if (this.resources().some(resource => isEqual(resource, model.uri))) {
			this.modelListeners.add(model.onDidChangeContent(() => this.scheduler.schedule()));
			this.scheduler.schedule();
		}
	}

	private async update(): Promise<void> {
		const root = this.projectService.project?.root;
		if (!root) {
			return;
		}
		const generation = ++this.generation;
		for (const part of PARTS) {
			const resource = partFile(root, part);
			const doc = await this.document(resource);
			if (generation !== this.generation) {
				return;
			}
			const problems = modifierProblems(part, doc);
			this.markerService.changeOne(MARKER_OWNER, resource, problems.map((message): IMarkerData => ({
				severity: MarkerSeverity.Error,
				message,
				source: localize('modifierProblems.source', "Modifiers and overwrites"),
				startLineNumber: 1, startColumn: 1, endLineNumber: 1, endColumn: 1,
			})));
			// A checks file is written once there is a problem, and kept up to date after (also
			// one left by an earlier session, which may count a value typed then).
			if (part === 'objects' && (problems.length || this.reported || this.reported === undefined && await this.fileService.exists(joinPath(dirname(resource), PART_CHECKS_FILE)))) {
				this.reported = problems.length;
				await this.partStatus.reportChecks('objects', {
					problems: problems.length,
					items: problems.map(message => ({ severity: 'error' as const, message })),
				});
			}
		}
	}

	/** The part's document, unsaved edits included; undefined when missing or not JSON. */
	private async document(resource: URI): Promise<unknown> {
		let text = this.modelService.getModel(resource)?.getValue();
		if (text === undefined) {
			try {
				text = (await this.fileService.readFile(resource)).value.toString();
			} catch {
				return undefined;
			}
		}
		try {
			return JSON.parse(text);
		} catch {
			return undefined;
		}
	}
}
