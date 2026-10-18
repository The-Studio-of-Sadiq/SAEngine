/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { computePartStatuses, DESIGN_SUMMARY_FILE, EXPORT_DXF_FOLDER, EXPORT_IFC_FOLDER, exportKind, FEM_RESULTS_FOLDER, FEM_RESULTS_MANIFEST, IPartStatus, IPartStatusInputs, ISaenginePartStatusService, MEP_SUMMARY_FILE, REPORT_FILE, SUBSTRUCTURE_SUMMARY_FILE } from '../common/partStatus.js';
import { ALL_PARTS, ISaengineProject, ISaengineProjectService, partById } from '../common/saengineProject.js';

/** How long file changes settle before the statuses are computed again [ms]. */
const REFRESH_DELAY = 300;

export class SaenginePartStatusService extends Disposable implements ISaenginePartStatusService {

	declare readonly _serviceBrand: undefined;

	private _statuses: readonly IPartStatus[] = [];
	get statuses(): readonly IPartStatus[] { return this._statuses; }

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	private readonly projectDisposables = this._register(new DisposableStore());
	private readonly refreshScheduler = this._register(new RunOnceScheduler(() => void this.refresh(), REFRESH_DELAY));
	private generation = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(project => this.watch(project)));
		this.watch(this.projectService.project);
	}

	statusOf(part: string): IPartStatus | undefined {
		return this._statuses.find(s => s.part === part);
	}

	private watch(project: ISaengineProject | undefined): void {
		this.projectDisposables.clear();
		if (!project) {
			this.generation++;
			this.setStatuses([]);
			return;
		}
		// The project is the workspace folder, which the workbench already watches recursively
		// (correlated watchers are not recursive).
		this.projectDisposables.add(this.fileService.onDidFilesChange(e => {
			if (e.affects(project.root)) {
				this.refreshScheduler.schedule();
			}
		}));
		void this.refresh();
	}

	private async refresh(): Promise<void> {
		const project = this.projectService.project;
		const generation = ++this.generation;
		if (!project) {
			this.setStatuses([]);
			return;
		}
		try {
			const inputs = await this.readInputs(project);
			if (generation === this.generation) {
				this.setStatuses(computePartStatuses(this.projectService.parts, inputs));
			}
		} catch (error) {
			this.logService.warn(`[saengine] could not compute the part statuses of ${project.root.toString()}: ${error}`);
		}
	}

	private async readInputs(project: ISaengineProject): Promise<IPartStatusInputs> {
		const texts = new Map<string, string | undefined>();
		// The sources of a derived part may belong to the other project type's Part 5 (never both).
		await Promise.all(ALL_PARTS.map(async part => {
			if (part.mainFile) {
				texts.set(part.id, await this.readText(joinPath(project.root, part.folder, part.mainFile)));
			}
		}));
		const fem = partById('fem')!;
		const femFolder = joinPath(project.root, fem.folder);
		const results = joinPath(femFolder, FEM_RESULTS_FOLDER);
		const exportsFolder = joinPath(project.root, partById('exports')!.folder);
		const substructure = partById('substructure');
		const substructureFolder = substructure && joinPath(project.root, substructure.folder);
		const mep = partById('mep');
		const mepFolder = mep && joinPath(project.root, mep.folder);
		const [mepSummaryTime, mepSummaryText] = await Promise.all([
			mepFolder ? this.mtime(joinPath(mepFolder, MEP_SUMMARY_FILE)) : undefined,
			mepFolder ? this.readText(joinPath(mepFolder, MEP_SUMMARY_FILE)) : undefined,
		]);
		const [femModelTime, femResultsTime, designSummaryTime, designSummaryText, reportTime, exportFiles, substructureTime, substructureSummaryTime, substructureSummaryText] = await Promise.all([
			this.mtime(joinPath(femFolder, fem.mainFile!)),
			this.mtime(joinPath(results, FEM_RESULTS_MANIFEST)),
			this.mtime(joinPath(results, DESIGN_SUMMARY_FILE)),
			this.readText(joinPath(results, DESIGN_SUMMARY_FILE)),
			this.mtime(joinPath(exportsFolder, REPORT_FILE)),
			this.countExports(exportsFolder),
			substructureFolder && substructure.mainFile ? this.mtime(joinPath(substructureFolder, substructure.mainFile)) : undefined,
			substructureFolder ? this.mtime(joinPath(substructureFolder, SUBSTRUCTURE_SUMMARY_FILE)) : undefined,
			substructureFolder ? this.readText(joinPath(substructureFolder, SUBSTRUCTURE_SUMMARY_FILE)) : undefined,
		]);
		return { texts, femModelTime, femResultsTime, designSummaryTime, designSummaryText, reportTime, exportFiles, substructureTime, substructureSummaryTime, substructureSummaryText, mepSummaryTime, mepSummaryText };
	}

	/** The exports in `folder` other than the report: IFC, DXF floor plans and CSV tables. */
	private async countExports(folder: URI): Promise<number> {
		const names = async (path: string) => {
			try {
				const stat = await this.fileService.resolve(path ? joinPath(folder, path) : folder);
				return (stat.children ?? []).filter(child => child.isFile).map(child => path ? `${path}/${child.name}` : child.name);
			} catch {
				return [];
			}
		};
		const files = (await Promise.all(['', EXPORT_IFC_FOLDER, EXPORT_DXF_FOLDER].map(names))).flat();
		return files.filter(file => {
			const kind = exportKind(file);
			return kind !== undefined && kind !== 'report';
		}).length;
	}

	private async readText(resource: URI): Promise<string | undefined> {
		try {
			return (await this.fileService.readFile(resource)).value.toString();
		} catch {
			return undefined;
		}
	}

	private async mtime(resource: URI): Promise<number | undefined> {
		try {
			return (await this.fileService.stat(resource)).mtime;
		} catch {
			return undefined;
		}
	}

	private setStatuses(statuses: readonly IPartStatus[]): void {
		if (JSON.stringify(statuses) === JSON.stringify(this._statuses)) {
			return;
		}
		this._statuses = statuses;
		this._onDidChange.fire();
	}
}

registerSingleton(ISaenginePartStatusService, SaenginePartStatusService, InstantiationType.Delayed);
