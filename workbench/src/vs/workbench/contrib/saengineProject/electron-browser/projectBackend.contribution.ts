/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { Schemas } from '../../../../base/common/network.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, ConfigurationScope, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ICadOpenResult, IFemSolverService, ProjectPlatformMethod } from '../../../../platform/saengine/common/femSolver.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { FemAnalysisRunner } from '../../saengineFem/electron-browser/femAnalysisRunner.js';
import { ARCHIVE_EXPORT_COMMAND, ARCHIVE_EXTENSION, ARCHIVE_IMPORT_COMMAND, ARCHIVE_INSPECT_COMMAND, CAD_OPEN_COMMAND, DWG_TO_DXF_COMMAND, OPEN_ARCHIVE_UI_COMMAND, PDF_TO_DXF_COMMAND, WORKBOOK_EXPORT_COMMAND, WORKBOOK_IMPORT_COMMAND } from '../browser/projectArchiveModel.js';
import { ProjectOverviewInput } from '../browser/projectOverviewInput.js';
import { StartEditorInput } from '../browser/startEditorInput.js';
import { VERSIONS_DIFF_COMMAND, VERSIONS_LIST_COMMAND, VERSIONS_MARK_ISSUED_COMMAND, VERSIONS_RESTORE_COMMAND, VERSIONS_SAVE_COMMAND, VERSIONS_STATUS_COMMAND } from '../browser/versionsModel.js';

/*
 * The backend of the project archive (`.civil`), the version history and the CAD hand-off: the
 * commands the UI of `../browser/projectPlatform.contribution.ts` calls by id, forwarded to the
 * Python backend (`saengine.project.archive` and `saengine.project.versions` over JSON-RPC) and
 * to the shared process (LibreCAD); DWG drawings are converted to DXF by the backend (LibreDWG), PDF pages by pypdf; the
 * model workbook (Excel round trip) is written and read by the backend too. Also opens a `.civil` file the operating system hands over.
 */

/** The author of saved versions, "Name <email>". */
export const VERSIONS_AUTHOR_SETTING = 'saengine.versions.author';
/** A CAD program for DXF drawings, preferred over the bundled LibreCAD. */
export const CAD_PROGRAM_SETTING = 'saengine.cad.program';

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'saengine',
	title: localize('saengine.configurationTitle', "SAEngine"),
	type: 'object',
	properties: {
		[VERSIONS_AUTHOR_SETTING]: {
			type: 'string',
			default: '',
			scope: ConfigurationScope.APPLICATION,
			markdownDescription: localize('saengine.versions.author', "Who saves versions of a project, as `Name <email>` (shown in Versions and in any git client). When empty, versions are saved as \"SAEngine user\"."),
		},
		[CAD_PROGRAM_SETTING]: {
			type: 'string',
			default: '',
			// A program SAEngine starts: never from a project's .vscode/settings.json.
			scope: ConfigurationScope.MACHINE,
			restricted: true,
			markdownDescription: localize('saengine.cad.program', "The CAD program DXF drawings open in (the full path of its `.exe`). When empty, the LibreCAD bundled with SAEngine, else an installed LibreCAD, else the program Windows opens DXF files with."),
		},
	},
});

type Bag = { readonly [key: string]: unknown };

function bag(value: unknown): Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Bag : {};
}

function str(value: unknown): string | undefined {
	return typeof value === 'string' && value.trim() ? value : undefined;
}

/** A refusal of the backend (`{ok: false, message}`) becomes an error the caller shows. */
function orThrow(result: object): object {
	const answer = bag(result);
	if (answer.ok === false && typeof answer.message === 'string') {
		throw new Error(answer.message);
	}
	return result;
}

function call(accessor: ServicesAccessor, method: ProjectPlatformMethod, params: object): Promise<object> {
	const python = accessor.get(IInstantiationService).createInstance(FemAnalysisRunner).resolvePython();
	return accessor.get(IFemSolverService).projectPlatform(python, method, params);
}

function author(accessor: ServicesAccessor, args: Bag): string | undefined {
	return str(args.author) ?? str(accessor.get(IConfigurationService).getValue<string>(VERSIONS_AUTHOR_SETTING)?.trim());
}

// --- The project archive ----------------------------------------------------------------------

CommandsRegistry.registerCommand(ARCHIVE_EXPORT_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'project/exportArchive', {
		projectRoot: args.projectRoot,
		outPath: args.outPath,
		includeResults: args.includeResults === true,
		includeVersions: args.includeVersions === true,
		includeExports: args.includeExports !== false,
		note: str(args.note),
		// No version from here: the backend writes its own, as the design report does (one source).
	}));
});

CommandsRegistry.registerCommand(ARCHIVE_INSPECT_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(typeof raw === 'string' ? { path: raw } : raw);
	const result = bag(await call(accessor, 'project/inspectArchive', { path: args.path }));
	// A file that could not be read at all: its reason as the archive's problem.
	const problems = Array.isArray(result.problems) ? result.problems : [];
	if (result.ok === false && !problems.length && typeof result.message === 'string') {
		return { ...result, problems: [{ code: result.code ?? 'unreadable', severity: 'error', message: result.message }] };
	}
	return result;
});

CommandsRegistry.registerCommand(ARCHIVE_IMPORT_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	const result = bag(orThrow(await call(accessor, 'project/importArchive', {
		path: args.path,
		destParent: args.destParent,
		name: str(args.name),
		overwrite: args.overwrite === true,
		// The backend compares with its own version (one source, as the archive and the report write).
	})));
	// What the import migrated, and what it leaves to the engineer, shown with its warnings.
	const notes = [
		...(Array.isArray(result.migrated) ? result.migrated : []).map(m => ({ code: 'migrated', severity: 'info', message: bag(m).message })),
		...(Array.isArray(result.pending) ? result.pending : []).map(m => ({ code: 'pending', severity: 'info', message: bag(m).message, command: bag(m).command })),
	].filter(n => typeof n.message === 'string');
	return notes.length ? { ...result, problems: [...(Array.isArray(result.problems) ? result.problems : []), ...notes] } : result;
});

// --- Versions ---------------------------------------------------------------------------------

CommandsRegistry.registerCommand(VERSIONS_STATUS_COMMAND, async (accessor, raw: unknown) => {
	return orThrow(await call(accessor, 'versions/status', { projectRoot: bag(raw).projectRoot }));
});

CommandsRegistry.registerCommand(VERSIONS_LIST_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'versions/list', { projectRoot: args.projectRoot, limit: typeof args.limit === 'number' ? args.limit : 200 }));
});

CommandsRegistry.registerCommand(VERSIONS_SAVE_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'versions/save', {
		projectRoot: args.projectRoot,
		message: typeof args.message === 'string' ? args.message : '',
		author: author(accessor, args),
		issued: args.issued === true,
		label: str(args.label),
	}));
});

CommandsRegistry.registerCommand(VERSIONS_DIFF_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'versions/diff', { projectRoot: args.projectRoot, fromVersion: str(args.from), toVersion: str(args.to) }));
});

CommandsRegistry.registerCommand(VERSIONS_RESTORE_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'versions/restore', {
		projectRoot: args.projectRoot,
		version: args.version,
		parts: Array.isArray(args.parts) ? args.parts.filter(p => typeof p === 'string') : undefined,
		author: author(accessor, args),
		commit: args.commit !== false,
	}));
});

CommandsRegistry.registerCommand(VERSIONS_MARK_ISSUED_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'versions/markIssued', { projectRoot: args.projectRoot, version: args.version, label: args.label, author: author(accessor, args) }));
});

// --- Code packs -------------------------------------------------------------------------------
// The commands the Design code selector (Project Settings) and the Code Packs page call by id
// (`../../saengineLibrary/browser/codePacksModel.ts`), forwarded to `saengine.codes`.

CommandsRegistry.registerCommand('saengine.codes.list', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return call(accessor, 'codes/list', { root: str(args.root), kind: str(args.kind) });
});

CommandsRegistry.registerCommand('saengine.codes.remove', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'codes/remove', { id: args.id, scope: args.scope === 'project' ? 'project' : 'user', kind: str(args.kind), root: str(args.root) }));
});

CommandsRegistry.registerCommand('saengine.codes.show', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'codes/show', { id: args.id, root: str(args.root) }));
});

CommandsRegistry.registerCommand('saengine.codes.new', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'codes/new', { id: args.id, name: str(args.name), extends: str(args.extends), scope: args.scope === 'project' ? 'project' : 'user', dest: str(args.dest), root: str(args.root) }));
});

CommandsRegistry.registerCommand('saengine.codes.install', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'codes/install', { path: args.path, scope: args.scope === 'project' ? 'project' : 'user', root: str(args.root), replace: args.replace === true }));
});

CommandsRegistry.registerCommand('saengine.codes.validate', async (accessor, raw: unknown) => {
	const args = bag(typeof raw === 'string' ? { path: raw } : raw);
	return call(accessor, 'codes/validate', { path: args.path, root: str(args.root) });
});

CommandsRegistry.registerCommand('saengine.codes.trust', async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'codes/trust', { id: args.id, trusted: args.trusted === true, root: str(args.root) }));
});

// --- CAD --------------------------------------------------------------------------------------

/**
 * `{path, dryRun?}` -> `{ok, program, args, source?}`: opens a DXF in LibreCAD (the setting's
 * program, the bundled copy, an installed one), else hands it to the program Windows opens DXF
 * files with (`program: 'system'`). `dryRun` only says which would be used.
 */
CommandsRegistry.registerCommand(CAD_OPEN_COMMAND, async (accessor, raw: unknown): Promise<ICadOpenResult> => {
	const args = bag(typeof raw === 'string' ? { path: raw } : raw);
	const path = str(args.path) ?? '';
	const result = await accessor.get(IFemSolverService).openInCad({
		path,
		program: accessor.get(IConfigurationService).getValue<string>(CAD_PROGRAM_SETTING) || undefined,
		dryRun: args.dryRun === true,
	});
	if (!result.ok || result.program) {
		return result;
	}
	const url = URI.file(path).toString(true);
	if (args.dryRun === true) {
		return { ok: true, program: 'system', args: [url] };
	}
	// The operating system's handler for .dxf files (ShellExecute on Windows): no shell string.
	const ok = await accessor.get(INativeHostService).openExternal(url);
	return { ok, program: 'system', args: [url] };
});

/** `{path}` -> `{ok, dxf, warnings, cached}` or `{ok: false, code, message}`: a DWG as DXF. */
CommandsRegistry.registerCommand(DWG_TO_DXF_COMMAND, async (accessor, raw: unknown) => {
	return call(accessor, 'cad/convertDwg', { path: str(bag(typeof raw === 'string' ? { path: raw } : raw).path) ?? '' });
});

/** `{path, page?}` -> one page of a PDF drawing as DXF, with its lines for object snaps. */
CommandsRegistry.registerCommand(PDF_TO_DXF_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(typeof raw === 'string' ? { path: raw } : raw);
	return call(accessor, 'cad/convertPdf', { path: str(args.path) ?? '', page: typeof args.page === 'number' ? args.page : 1 });
});

// --- The model workbook (Excel round trip) ----------------------------------------------------

CommandsRegistry.registerCommand(WORKBOOK_EXPORT_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return orThrow(await call(accessor, 'workbook/export', { outPath: args.outPath, floorPlanText: args.floorPlanText, objectsText: args.objectsText, loadsText: args.loadsText }));
});

CommandsRegistry.registerCommand(WORKBOOK_IMPORT_COMMAND, async (accessor, raw: unknown) => {
	const args = bag(raw);
	return call(accessor, 'workbook/import', { path: args.path, floorPlanText: args.floorPlanText, objectsText: args.objectsText, loadsText: args.loadsText });
});

// --- A .civil file opened from the operating system ----------------------------------------

/**
 * A `.civil` file double-clicked in Explorer (or given on the command line) reaches the window
 * as a file to open: instead of showing the archive as text, Open Project Archive runs on it
 * (what it holds, where to unpack it, then the project opens). Meanwhile the start page (or the
 * open project's overview) is shown.
 */
class ArchiveFileOpener extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.archiveFileOpener';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ICommandService commandService: ICommandService,
		@ISaengineProjectService projectService: ISaengineProjectService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`*.${ARCHIVE_EXTENSION}`,
			{
				id: 'workbench.editor.saengine.archive',
				label: localize('archiveOpener.label', "Open Project Archive"),
				detail: localize('archiveOpener.detail', "SAEngine"),
				priority: RegisteredEditorPriority.exclusive,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => resource.scheme === Schemas.file,
			},
			{
				createEditorInput: ({ resource, options }) => {
					// After this editor has opened: the flow asks questions in dialogs.
					setTimeout(() => void commandService.executeCommand(OPEN_ARCHIVE_UI_COMMAND, { path: resource.fsPath }), 0);
					return { editor: projectService.project ? ProjectOverviewInput.instance : StartEditorInput.instance, options };
				},
			}
		));
	}
}

registerWorkbenchContribution2(ArchiveFileOpener.ID, ArchiveFileOpener, WorkbenchPhase.BlockStartup);
