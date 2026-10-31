/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { applyEdits, setProperty } from '../../../../base/common/jsonEdit.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { extUriBiasedIgnorePathCase, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { IQuickInputService, IQuickPickItem, IQuickPickSeparator } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { LibraryEditorInput } from '../../saengineLibrary/browser/libraryEditorInput.js';
import { BUILD_REPORT_COMMAND_ID, CONFIGURE_REPORT_COMMAND_ID, CREATE_REPORT_TEMPLATE_COMMAND_ID, EXPORT_WORD_REPORT_COMMAND_ID, IReportBuildRequest, IReportBuildResult, IReportTemplates, PRINT_REPORT_COMMAND_ID, REPORT_TEMPLATES_COMMAND_ID, REPORT_TEMPLATES_FOLDER, ReportFormat, reportProblems, reportWrittenMessage, templateId, USE_REPORT_TEMPLATE_COMMAND_ID } from './reportBuild.js';
import { ReportTemplateEditor } from './reportTemplateEditor.js';
import { worksheetKinds, WorksheetEditor } from './worksheetEditor.js';
import { IWorksheetInfo, IWorksheetKind, kindsByGroup, NEW_WORKSHEET_COMMAND_ID, OPEN_WORKSHEETS_COMMAND_ID, worksheetId, WORKSHEETS_FOLDER, WORKSHEETS_REQUEST_COMMAND_ID } from './worksheetModel.js';

const category = localize2('saengine.category', "SAEngine");

/** Set by the SAEngine model contribution while a project is open. */
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

/** The view the Model Explorer contributes; the command sits in its title bar overflow. */
const MODEL_EXPLORER_VIEW_ID = 'saengine.modelExplorer';

/** Command id of the file explorer's "Reveal in File Explorer" (desktop only). */
const REVEAL_IN_OS_COMMAND_ID = 'revealFileInOS';

/** Optional argument of the print and export commands: the report template to follow. */
interface IReportCommandArgs {
	readonly template?: string;
}

/**
 * Writes the design report (PDF or Word) with the template `template` (the project settings'
 * when undefined), opens it in the system's viewer and says what it holds.
 */
async function writeReport(accessor: ServicesAccessor, format: ReportFormat, template: string | undefined): Promise<void> {
	const projectService = accessor.get(ISaengineProjectService);
	const commandService = accessor.get(ICommandService);
	const progressService = accessor.get(IProgressService);
	const notificationService = accessor.get(INotificationService);
	const openerService = accessor.get(IOpenerService);

	const project = projectService.project;
	if (!project) {
		notificationService.info(localize('report.noProject', "Open a SAEngine project to print its design report."));
		return;
	}

	const request: IReportBuildRequest = { projectRoot: project.root.fsPath, format, template };
	let result: IReportBuildResult | undefined;
	try {
		result = await progressService.withProgress({
			location: ProgressLocation.Notification,
			title: format === 'docx'
				? localize('report.progressWord', "Writing the design report of {0} as Word", project.name)
				: localize('report.progress', "Printing the design report of {0}", project.name),
		}, () => commandService.executeCommand<IReportBuildResult>(BUILD_REPORT_COMMAND_ID, request));
	} catch (error) {
		notificationService.error(localize('report.failed', "The design report could not be printed: {0}", toErrorMessage(error)));
		return;
	}

	const problems = reportProblems(result);
	if (problems.length || !result?.path) {
		notificationService.notify({
			severity: Severity.Error,
			message: problems.length === 1
				? localize('report.problem', "The design report was not printed: {0}", problems[0])
				: localize('report.problems', "The design report was not printed: {0}", problems.join(' ')),
		});
		return;
	}

	const file = URI.file(result.path);
	// Open in the operating system's PDF viewer or word processor.
	await openerService.open(file, { openExternal: true });
	notificationService.prompt(
		result.warnings?.length ? Severity.Warning : Severity.Info,
		reportWrittenMessage(result),
		[
			{
				label: localize('report.open', "Open Report"),
				run: () => openerService.open(file, { openExternal: true }),
			},
			{
				label: localize('report.reveal', "Reveal in File Explorer"),
				run: () => commandService.executeCommand(REVEAL_IN_OS_COMMAND_ID, file),
			},
		],
	);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PRINT_REPORT_COMMAND_ID,
			title: localize2('saengine.printReport', "Print Design Report"),
			category,
			icon: Codicon.filePdf,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 1, when: projectOpen },
				{ id: MenuId.ViewTitle, group: '9_report', order: 1, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	override run(accessor: ServicesAccessor, args?: IReportCommandArgs): Promise<void> {
		return writeReport(accessor, 'pdf', args?.template);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: EXPORT_WORD_REPORT_COMMAND_ID,
			title: localize2('saengine.exportWordReport', "Export Design Report to Word"),
			category,
			icon: Codicon.fileText,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 2, when: projectOpen },
				{ id: MenuId.ViewTitle, group: '9_report', order: 2, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	override run(accessor: ServicesAccessor, args?: IReportCommandArgs): Promise<void> {
		return writeReport(accessor, 'docx', args?.template);
	}
});

interface ITemplatePick extends IQuickPickItem {
	readonly templateId?: string;
	readonly path?: string;
	readonly create?: boolean;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CONFIGURE_REPORT_COMMAND_ID,
			title: localize2('saengine.configureReport', "Configure Design Report..."),
			category,
			icon: Codicon.settingsGear,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.MenubarFileMenu, group: '4_save_print', order: 3, when: projectOpen },
				{ id: MenuId.ViewTitle, group: '9_report', order: 3, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	/**
	 * Lists the report templates (built-in and the project's): a project template opens in its
	 * editor; a built-in one, or "New Template", is copied into the project first.
	 */
	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const commandService = accessor.get(ICommandService);
		const quickInput = accessor.get(IQuickInputService);
		const notificationService = accessor.get(INotificationService);
		const editorService = accessor.get(IEditorService);
		if (!project) {
			return;
		}
		let listed: IReportTemplates | undefined;
		try {
			listed = await commandService.executeCommand<IReportTemplates>(REPORT_TEMPLATES_COMMAND_ID, { projectRoot: project.root.fsPath });
		} catch (error) {
			notificationService.error(localize('report.templatesFailed', "The report templates could not be listed: {0}", toErrorMessage(error)));
			return;
		}
		const templates = listed?.templates ?? [];
		const current = listed?.current ?? 'default';
		const items: (ITemplatePick | IQuickPickSeparator)[] = [
			{ type: 'separator', label: localize('report.projectTemplates', "Templates of this project") },
			...templates.filter(t => t.source === 'project').map(t => ({
				label: t.name,
				description: t.id === current ? localize('report.currentTemplate', "{0} (printed for this project)", t.id) : t.id,
				templateId: t.id,
				path: t.path,
			})),
			{ type: 'separator', label: localize('report.builtInTemplates', "Built-in (opens an editable copy)") },
			...templates.filter(t => t.source === 'builtIn').map(t => ({
				label: t.name,
				description: t.id === current ? localize('report.currentTemplate', "{0} (printed for this project)", t.id) : t.id,
				templateId: t.id,
			})),
			{ type: 'separator' },
			{ label: `$(add) ${localize('report.newTemplate', "New Template...")}`, create: true },
		];
		const pick = await quickInput.pick(items, { placeHolder: localize('report.pickTemplate', "Choose the report template to edit: sections, detail, cover, letterhead, members") }) as ITemplatePick | undefined;
		if (!pick) {
			return;
		}
		if (pick.path) {
			await editorService.openEditor({ resource: URI.file(pick.path), options: { pinned: true } });
			return;
		}
		const base = pick.create ? current : pick.templateId;
		const name = await quickInput.input({
			prompt: localize('report.templateName', "Name of the new report template (its id is made from it)"),
			value: pick.create ? '' : localize('report.copyName', "{0} (project)", pick.label),
			validateInput: async value => templateId(value) ? undefined : localize('report.templateNameEmpty', "Give the template a name with letters or digits."),
		});
		if (!name) {
			return;
		}
		const answer = await commandService.executeCommand<{ path?: string; problems?: string[] }>(CREATE_REPORT_TEMPLATE_COMMAND_ID, { projectRoot: project.root.fsPath, id: templateId(name), base, name });
		if (!answer?.path) {
			notificationService.error(localize('report.createFailed', "The report template was not written: {0}", (answer?.problems ?? []).join(' ')));
			return;
		}
		await editorService.openEditor({ resource: URI.file(answer.path), options: { pinned: true } });
	}
});

/** Makes a template the one the project prints: Project Settings → Design report → Template. */
registerAction2(class extends Action2 {
	constructor() {
		super({ id: USE_REPORT_TEMPLATE_COMMAND_ID, title: localize2('saengine.useReportTemplate', "Print This Report Template for the Project"), category, f1: false, precondition: projectOpen });
	}

	override async run(accessor: ServicesAccessor, args?: IReportCommandArgs): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const settings = partById('settings');
		const notificationService = accessor.get(INotificationService);
		const textModelService = accessor.get(ITextModelService);
		const textFileService = accessor.get(ITextFileService);
		if (!project || !settings?.mainFile || !args?.template) {
			return;
		}
		const resource = joinPath(project.root, settings.folder, settings.mainFile);
		const reference = await textModelService.createModelReference(resource);
		try {
			const model = reference.object.textEditorModel;
			const text = model.getValue();
			const edits = setProperty(text, ['report', 'template'], args.template, { tabSize: 1, insertSpaces: false, eol: model.getEOL() });
			model.pushEditOperations([], [{ range: model.getFullModelRange(), text: applyEdits(text, edits) }], () => null);
			await textFileService.save(resource);
			notificationService.info(localize('report.templateUsed', "The project now prints the report template \"{0}\" (Project Settings → Design report → Template).", args.template));
		} catch (error) {
			notificationService.error(localize('report.useFailed', "The project settings could not be changed: {0}", toErrorMessage(error)));
		} finally {
			reference.dispose();
		}
	}
});

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(ReportTemplateEditor, LibraryEditorInput.REPORT_TEMPLATE_EDITOR_ID, localize('reportTemplateEditorPane', "SAEngine Report Template Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

/** Opens the project's report templates (`11 Exports/report-templates/*.json`) in their form by default. */
class ReportTemplateEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.reportTemplateEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`**/${REPORT_TEMPLATES_FOLDER}/*.json`,
			{
				id: LibraryEditorInput.REPORT_TEMPLATE_EDITOR_ID,
				label: localize('reportTemplateEditorLabel', "Report Template Editor"),
				detail: localize('reportTemplateEditorDetail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isTemplate(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(LibraryEditorInput, resource, 'reportTemplate', undefined),
					options,
				}),
			}
		));
	}

	/** A file of the open project's `11 Exports/report-templates` folder. */
	private isTemplate(resource: URI): boolean {
		const project = this.projectService.project;
		const exportsPart = partById('exports');
		if (!project || !exportsPart) {
			return false;
		}
		const folder = joinPath(project.root, exportsPart.folder, REPORT_TEMPLATES_FOLDER);
		return extUriBiasedIgnorePathCase.isEqual(extUriBiasedIgnorePathCase.dirname(resource), folder);
	}
}

registerWorkbenchContribution2(ReportTemplateEditorResolverContribution.ID, ReportTemplateEditorResolverContribution, WorkbenchPhase.BlockStartup);

// ─────────────────────────────── calculation worksheets ───────────────────────────────

interface IKindPick extends IQuickPickItem {
	readonly kind: IWorksheetKind;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: NEW_WORKSHEET_COMMAND_ID,
			title: localize2('saengine.newWorksheet', "New Calculation Worksheet..."),
			category,
			icon: Codicon.symbolNumeric,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.ViewTitle, group: '9_report', order: 4, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	/** Picks a kind (beam, column, footing, development length, wind on a sign, ...), names it, writes it with the kind's defaults and opens it. */
	override async run(accessor: ServicesAccessor, args?: { readonly kind?: string }): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const commandService = accessor.get(ICommandService);
		const quickInput = accessor.get(IQuickInputService);
		const notificationService = accessor.get(INotificationService);
		const editorService = accessor.get(IEditorService);
		if (!project) {
			return;
		}
		let kinds: readonly IWorksheetKind[];
		try {
			kinds = await worksheetKinds(commandService);
		} catch (error) {
			notificationService.error(localize('worksheet.kindsFailed', "The worksheet kinds could not be listed: {0}", toErrorMessage(error)));
			return;
		}
		let kind = kinds.find(k => k.id === args?.kind);
		if (!kind) {
			const items: (IKindPick | IQuickPickSeparator)[] = [];
			for (const [group, list] of kindsByGroup(kinds)) {
				items.push({ type: 'separator', label: group });
				items.push(...list.map(k => ({ label: k.title, detail: k.summary, kind: k })));
			}
			const pick = await quickInput.pick(items, { placeHolder: localize('worksheet.pickKind', "Choose the calculation"), matchOnDetail: true }) as IKindPick | undefined;
			kind = pick?.kind;
		}
		if (!kind) {
			return;
		}
		const title = await quickInput.input({
			prompt: localize('worksheet.name', "Title of the worksheet, as the report prints it (its file name is made from it)"),
			value: kind.title,
			validateInput: async value => worksheetId(value) ? undefined : localize('worksheet.nameEmpty', "Give the worksheet a title with letters or digits."),
		});
		if (!title) {
			return;
		}
		const answer = await commandService.executeCommand<{ path?: string; existing?: boolean; problems?: string[] }>(WORKSHEETS_REQUEST_COMMAND_ID, 'worksheets/create', { projectRoot: project.root.fsPath, kind: kind.id, id: worksheetId(title), title });
		if (!answer?.path) {
			notificationService.error(localize('worksheet.createFailed', "The worksheet was not written: {0}", (answer?.problems ?? []).join(' ')));
			return;
		}
		if (answer.existing) {
			notificationService.info(localize('worksheet.existing', "A worksheet with this name exists already; it is opened."));
		}
		await editorService.openEditor({ resource: URI.file(answer.path), options: { pinned: true } });
	}
});

interface IWorksheetPick extends IQuickPickItem {
	readonly path?: string;
	readonly create?: boolean;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: OPEN_WORKSHEETS_COMMAND_ID,
			title: localize2('saengine.openWorksheets', "Calculation Worksheets..."),
			category,
			icon: Codicon.symbolNumeric,
			f1: true,
			precondition: projectOpen,
			menu: [
				{ id: MenuId.ViewTitle, group: '9_report', order: 5, when: ContextKeyExpr.and(projectOpen, ContextKeyExpr.equals('view', MODEL_EXPLORER_VIEW_ID)) },
			],
		});
	}

	/** Lists the project's worksheets with their result; one opens in its editor. */
	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const commandService = accessor.get(ICommandService);
		const quickInput = accessor.get(IQuickInputService);
		const notificationService = accessor.get(INotificationService);
		const editorService = accessor.get(IEditorService);
		if (!project) {
			return;
		}
		let listed: { worksheets?: IWorksheetInfo[]; problems?: string[] } | undefined;
		try {
			listed = await commandService.executeCommand(WORKSHEETS_REQUEST_COMMAND_ID, 'worksheets/list', { projectRoot: project.root.fsPath });
		} catch (error) {
			notificationService.error(localize('worksheet.listFailed', "The worksheets could not be listed: {0}", toErrorMessage(error)));
			return;
		}
		const verdict = (w: IWorksheetInfo) => w.problems.length
			? localize('worksheet.listProblem', "not calculated")
			: w.ok
				? localize('worksheet.listOk', "passes ({0})", w.utilisation === null ? '–' : w.utilisation.toFixed(2))
				: localize('worksheet.listFail', "fails");
		const items: (IWorksheetPick | IQuickPickSeparator)[] = [
			...(listed?.worksheets ?? []).map(w => ({
				label: w.title,
				description: w.print ? verdict(w) : localize('worksheet.listNotPrinted', "{0} · not printed", verdict(w)),
				detail: w.kind,
				path: w.path,
			})),
			{ type: 'separator' },
			{ label: `$(add) ${localize('worksheet.newItem', "New Calculation Worksheet...")}`, create: true },
		];
		for (const problem of listed?.problems ?? []) {
			notificationService.warn(problem);
		}
		const pick = await quickInput.pick(items, { placeHolder: localize('worksheet.pick', "The project's calculation worksheets (11 Exports/worksheets)") }) as IWorksheetPick | undefined;
		if (pick?.create) {
			await commandService.executeCommand(NEW_WORKSHEET_COMMAND_ID);
		} else if (pick?.path) {
			await editorService.openEditor({ resource: URI.file(pick.path), options: { pinned: true } });
		}
	}
});

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(WorksheetEditor, LibraryEditorInput.WORKSHEET_EDITOR_ID, localize('worksheetEditorPane', "SAEngine Calculation Worksheet Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

/** Opens the project's worksheets (`11 Exports/worksheets/*.json`) in the worksheet editor by default. */
class WorksheetEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.worksheetEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`**/${WORKSHEETS_FOLDER}/*.json`,
			{
				id: LibraryEditorInput.WORKSHEET_EDITOR_ID,
				label: localize('worksheetEditorLabel', "Calculation Worksheet Editor"),
				detail: localize('worksheetEditorDetail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isWorksheet(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(LibraryEditorInput, resource, 'worksheet', undefined),
					options,
				}),
			}
		));
	}

	/** A file of the open project's `11 Exports/worksheets` folder. */
	private isWorksheet(resource: URI): boolean {
		const project = this.projectService.project;
		const exportsPart = partById('exports');
		if (!project || !exportsPart) {
			return false;
		}
		const folder = joinPath(project.root, exportsPart.folder, WORKSHEETS_FOLDER);
		return extUriBiasedIgnorePathCase.isEqual(extUriBiasedIgnorePathCase.dirname(resource), folder);
	}
}

registerWorkbenchContribution2(WorksheetEditorResolverContribution.ID, WorksheetEditorResolverContribution, WorkbenchPhase.BlockStartup);
