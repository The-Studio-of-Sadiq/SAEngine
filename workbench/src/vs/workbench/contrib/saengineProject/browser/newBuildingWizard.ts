/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/newBuilding.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLButtonElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { toErrorMessage } from '../../../../base/common/errorMessage.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { isWindows } from '../../../../base/common/platform.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IProgressService } from '../../../../platform/progress/common/progress.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { EditorInputCapabilities, IEditorOpenContext, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { gridLabel } from '../../../services/saengineProject/common/gridLabels.js';
import { DEFAULT_CODE_TABLES, DEFAULT_MATERIALS, SETTINGS_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProject, ISaengineProjectService, partById, PROJECT_TYPES, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';
import {
	BLANK_FORM, buildSpec, centralBay, fitSpacings, folderError, FOOTING_CHOICES, FormField, formatLengths, formatSummary, formFromSpec, formInUnits, GENERATE_BUILDING_COMMAND, IGenerateOutcome, IGenerateSummary, INewBuildingForm, IPendingBuilding, IWizardPlot, lengthUnit, OccupancyCategory,
	parseSpacings, PENDING_BUILDING_STORAGE_KEY, plotFitWarning, readGenerateResult, readPendingBuilding, SiteClass, storyHeights, summarize, SYSTEM_CHOICES,
} from './newBuildingModel.js';
import { ISoilLocationRequest, ISoilLocationResult, SOIL_LOCATION_COMMAND } from '../../saengineSoil/browser/soilDocument.js';
import { SHOW_MODEL_VIEW_COMMAND } from './modelView.js';
import { ProjectOverviewInput } from './projectOverviewInput.js';
import { ProjectOpener, projectFolderName } from './projectOpener.js';
import { INewFromTemplateArgs } from './projectArchiveFlows.js';

import { plannedCodePacks } from '../../saengineLibrary/common/plannedCodePacks.js';
import { CODES_CHOICES_COMMAND, CODES_LIST_COMMAND, ICodePackInfo, readCodePacks, readPackLists } from '../../saengineLibrary/browser/codePacksModel.js';
import { CODES_TEMPLATES_COMMAND, DEFAULT_BUILDING_TEMPLATE, IBuildingTemplate, NEW_FROM_TEMPLATE_COMMAND, readBuildingTemplates } from '../../saengineLibrary/common/packageTemplates.js';
import { sameFolder } from './structuralImportModel.js';
import { lookUpHazardValues } from '../../saengineLibrary/browser/hazardLookup.js';
import { DEFAULT_CODE_PACK_ID, defaultCodeName } from '../../../services/saengineProject/common/activeCodePack.js';

const SVG = 'http://www.w3.org/2000/svg';

/** Application storage: the folder the last building was created in, offered next time. */
const LAST_FOLDER_STORAGE_KEY = 'saengine.newBuilding.lastFolder';

const wizardIcon = registerIcon('saengine-new-building-icon', Codicon.symbolStructure, localize('newBuildingIcon', "Icon of the New Project wizard."));

/** What a command asks the wizard to start from: the grid or the first full template. */
export type NewProjectStart = 'grid' | 'template';

/** The New Project wizard (start page, ≡ File, the sidebar's ≡ menu, the command palette). */
export class NewBuildingWizardInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.newBuilding';
	static readonly EDITOR_ID = 'workbench.editor.saengine.newBuilding';

	private static _instance: NewBuildingWizardInput | undefined;
	static get instance(): NewBuildingWizardInput {
		if (!NewBuildingWizardInput._instance || NewBuildingWizardInput._instance.isDisposed()) {
			NewBuildingWizardInput._instance = new NewBuildingWizardInput();
		}
		return NewBuildingWizardInput._instance;
	}

	readonly resource = URI.from({ scheme: 'saengine-new-building', path: 'default' });

	override get typeId(): string {
		return NewBuildingWizardInput.ID;
	}

	override get editorId(): string {
		return NewBuildingWizardInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('newProject.tab', "New Project");
	}

	override getIcon(): ThemeIcon {
		return wizardIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof NewBuildingWizardInput;
	}

	/**
	 * A building specification to fill the form with when the wizard shows next (the AI
	 * assistant's propose_building): applied over the starting template, then cleared. The
	 * engineer still reviews it and clicks Generate.
	 */
	prefill: { readonly [key: string]: unknown } | undefined;

	/** What to start from when the wizard shows next (the former New Project from Template...), then cleared. */
	startFrom: NewProjectStart | undefined;
}

/** The pages of the wizard: the project, its site and use, the building's grid and storeys. */
type WizardStep = 'project' | 'site' | 'building';

/**
 * What the new project starts from: the grid (a building specification fills the form, the
 * default one first), a full template (a whole project of an installed package), or an empty
 * project of a type (a building drawn by hand, a special structure).
 */
type StartFrom =
	| { readonly kind: 'spec'; readonly template?: IBuildingTemplate }
	| { readonly kind: 'archive'; readonly template: IBuildingTemplate }
	| { readonly kind: 'empty'; readonly type: ProjectType };

interface IStartOption {
	readonly text: string;
	readonly description?: string;
	readonly start: StartFrom;
}

/** Tells the starts apart (the option of "Start from" that is chosen). */
function startKey(start: StartFrom): string {
	return start.kind === 'empty' ? `empty:${start.type}` : `${start.kind}:${start.template?.package ?? ''}:${start.template?.file ?? ''}:${start.template?.path ?? ''}`;
}

/** A template's name, with its package's where they differ. */
function templateLabel(t: IBuildingTemplate): string {
	return t.packageName === t.name || !t.packageName ? t.name : localize('newBuilding.templateIn', "{0} ({1})", t.name, t.packageName);
}

/** Lets a page's fields enable or disable Next and Create as they change. */
interface IPageActions {
	refresh(): void;
}

interface IChoice<T extends string> {
	readonly value: T;
	readonly label: string;
	/** Shown but not choosable (a planned option). */
	readonly disabled?: boolean;
}

/**
 * The design code: BNBC 2020, the other design-code packs installed here (the built-in
 * Eurocodes loads pack, user packs), and the code packs planned after it, shown disabled and
 * marked "Planned" (their pages are on the Packages page and under the chips below the selector).
 */
function designCodeChoices(packs: readonly ICodePackInfo[]): IChoice<string>[] {
	const installed = packs.filter(p => p.kind === 'designCode' && p.effective && p.id !== DEFAULT_CODE_PACK_ID && p.usable !== false);
	// W4A-26 / W4B-22: a planned entry whose built-in pack is installed is not listed again.
	const ids = new Set(installed.map(p => p.id));
	return [
		{ value: DEFAULT_CODE_PACK_ID, label: defaultCodeName() },
		...installed.map(pack => ({ value: pack.id, label: pack.name })),
		...plannedCodePacks().filter(pack => !pack.coveredBy || !ids.has(pack.coveredBy.packId))
			.map(pack => ({ value: pack.feature, label: localize('newBuilding.codePlanned', "{0} (Planned)", pack.name), disabled: true })),
	];
}

/** Materials of a category from the default materials (`03 Materials`), as choices. */
function materialChoices(category: string): IChoice<string>[] {
	const materials = (DEFAULT_MATERIALS as { readonly materials?: readonly { readonly id: string; readonly name: string; readonly category: string }[] }).materials ?? [];
	return materials.filter(m => m.category === category).map(m => ({ value: m.id, label: m.name }));
}

/** The BNBC district towns of the project settings (Site > Location), without "Custom". */
function locationChoices(): IChoice<string>[] {
	return Object.entries(DEFAULT_CODE_TABLES.locations).map(([id, location]) => ({ value: id, label: localize('location.choice', "{0} (zone {1}, {2} m/s)", location.name, location.zone, location.windSpeed) }));
}

type SchemaEnum = { readonly enum?: readonly string[]; readonly enumDescriptions?: readonly string[] };

/** An enum of the project settings schema's `$defs`, as choices. */
function settingsEnum(def: string, property: string): IChoice<string>[] {
	const defs = (SETTINGS_SCHEMA as { readonly $defs?: { readonly [name: string]: { readonly properties?: { readonly [name: string]: SchemaEnum } } } }).$defs;
	const schema = defs?.[def]?.properties?.[property];
	return (schema?.enum ?? []).map((value, i) => ({ value, label: schema?.enumDescriptions?.[i] ?? value }));
}

/**
 * The New Project wizard, the one way to start a project: page 1 the name, folder, what it
 * starts from (the grid, a building specification or full template of a package, an empty
 * building or special structure), the design code and units; page 2 the site and use; page 3
 * (from the grid) the grids as spacings with a live plan and elevation, the storeys, the
 * structural system, the materials and the footings. A full template skips pages 2 and 3, an
 * empty project page 3. Create asks the generator (`saengine.library.generateBuilding`) for the
 * project and its floor plan, shows its notes and opens it; an empty project is created and
 * opened; a full template goes through the template check and the archive path (`saengine.project.newFromTemplate` with its path).
 */

export class NewBuildingWizard extends EditorPane {

	static readonly ID = NewBuildingWizardInput.EDITOR_ID;

	private container!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private readonly opener: ProjectOpener;
	private readonly pageDisposables = this._register(new DisposableStore());
	private form: { -readonly [key in keyof INewBuildingForm]: INewBuildingForm[key] } = { ...BLANK_FORM };
	private folder = '';
	private focusTarget: { focus(): void } | undefined;
	private busy = false;
	/** The plot of the open project's soil report, in the grid's frame; undefined without one. */
	private plot: IWizardPlot | undefined;
	/** The building templates installed (Packages page): specifications and full projects. */
	private templates: IBuildingTemplate[] = [];
	/** The design-code packs installed (empty without the backend). */
	private codePacks: ICodePackInfo[] = [];
	/** The exposures (terrain categories) of the chosen pack other than the default. */
	private packExposures: { id: string; label: string }[] = [];
	/** W4A-27: the exposure a new project under the chosen pack starts in ('' for none given). */
	private defaultExposure = '';
	/** C7: the towns and site classes of the chosen pack other than the default (empty: none). */
	private packTowns: { id: string; label: string }[] = [];
	private packSiteClasses: { id: string; label: string }[] = [];
	/** C1: the chosen pack's design spectrum method (`mappedSpectral`: the site's SDS, SD1 instead of Z). */
	private packSpectrum = '';
	/** Walk 4: the clause that classes the site in the chosen pack (its own; '' for none). */
	private packSiteClassClause = '';
	/** Walk 4 (W4A-6): the chosen pack's own bar grades (empty: the default materials'). */
	private packRebars: { id: string; label: string }[] = [];
	/** C22: the site's coordinates typed for the hazard lookup (without an open project's site point). */
	private hazardLatitude = '';
	private hazardLongitude = '';
	/** What the project starts from ("Start from" on page 1); the grid until the templates are read. */
	private start: StartFrom = { kind: 'spec' };
	/** Whether the starting values (a specification's) were applied once. */
	private started = false;
	/** B10-3: the grids, storeys or system were edited after a specification filled them. */
	private templateCustom = false;
	/** The page shown. */
	private step: WizardStep = 'project';

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService private readonly wizardStorage: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly workspaceService: IWorkspaceContextService,
		@IDialogService private readonly wizardDialogs: IDialogService,
		@IConfigurationService private readonly wizardConfiguration: IConfigurationService,
		@IProgressService private readonly wizardProgress: IProgressService,
	) {
		super(NewBuildingWizard.ID, group, telemetryService, themeService, wizardStorage);
		this.opener = instantiationService.createInstance(ProjectOpener);
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = $('.saengine-new-building');
		this.scrollable = this._register(new DomScrollableElement(this.container, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(parent, this.scrollable.getDomNode());
	}

	override async setInput(input: NewBuildingWizardInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		if (!this.folder) {
			this.folder = await this.initialFolder();
		}
		// The starting values are a building template's (saengine-default-building, built in).
		// B10-2: the engine may still be starting; say so instead of a blank page meanwhile.
		if (!this.templates.length) {
			const page = this.resetPage();
			append(page, $('h1', undefined, localize('newProject.title', "New Project")));
			append(page, $('p.hint', { role: 'status' }, localize('newBuilding.loading', "Reading the building templates (the engine starts the first time, a few seconds)...")));
		}
		await this.loadTemplates();
		await this.loadCodePacks();
		if (!this.started) {
			// The grid: the default specification (the first option of "Start from").
			this.chooseStart(this.startOptions()[0].start);
			this.started = true;
		}
		// Opened again: from the first page, with what was typed before kept.
		this.step = 'project';
		const startFrom = input.startFrom;
		if (startFrom) {
			input.startFrom = undefined;
			this.applyStartRequest(startFrom);
		}
		const prefill = input.prefill;
		if (prefill) {
			// The AI assistant's building: the grid, filled with it.
			input.prefill = undefined;
			this.chooseStart(this.startOptions()[0].start);
			this.form = { ...formFromSpec(prefill, this.form), ...(typeof prefill.name === 'string' && prefill.name.trim() ? { name: prefill.name.trim() } : {}) };
			this.templateCustom = true;
		}
		this.renderPage();
		// The plot needs the backend (a second or two): the form shows at once, then again with it.
		const plot = await this.loadPlot();
		if (plot && this.input === input && !token.isCancellationRequested) {
			this.plot = plot;
			if (this.showsGrid()) {
				this.renderPage(); // the plot is drawn on the grid's page only
			}
		}
	}

	override clearInput(): void {
		this.pageDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
		this.scrollable.scanDomNode();
	}

	override focus(): void {
		super.focus();
		this.focusTarget?.focus();
	}

	/**
	 * Where the building goes unless the engineer picks another folder: beside the open project,
	 * else in the open folder (not a project), else where the last building went, else the
	 * default projects folder. Never a relative path; a Windows drive in capitals ("C:\").
	 */
	private async initialFolder(): Promise<string> {
		const open = this.projectService.project?.root;
		if (open?.scheme === 'file') {
			return driveInCapitals(dirname(open).fsPath);
		}
		const folder = this.workspaceService.getWorkspace().folders[0]?.uri;
		if (folder?.scheme === 'file') {
			return driveInCapitals(folder.fsPath);
		}
		const last = this.wizardStorage.get(LAST_FOLDER_STORAGE_KEY, StorageScope.APPLICATION);
		if (last && !folderError(last, isWindows)) {
			return driveInCapitals(last);
		}
		return driveInCapitals((await this.opener.defaultLocation()).fsPath);
	}

	/**
	 * The plot of the open project (01 Soil Report's site) in the frame the new building's grid
	 * takes: turned along the road side, its origin inside the buildable envelope
	 * (saengine.gis.plot). Undefined without a project, a plot or the backend.
	 */
	private async loadPlot(): Promise<IWizardPlot | undefined> {
		const project = this.projectService.project;
		const part = partById('soil');
		if (!project || !part?.mainFile || !CommandsRegistry.getCommand(SOIL_LOCATION_COMMAND)) {
			return undefined;
		}
		try {
			const soilText = (await this.fileService.readFile(joinPath(project.root, part.folder, part.mainFile))).value.toString();
			const site = (JSON.parse(soilText) as { readonly site?: object }).site;
			if (!site) {
				return undefined;
			}
			const location = await this.commandService.executeCommand<ISoilLocationResult>(SOIL_LOCATION_COMMAND, { soilText } satisfies ISoilLocationRequest);
			const fit = location?.plot?.fit;
			return fit && fit.width > 0 && fit.depth > 0
				? { project: project.name, width: fit.width, depth: fit.depth, plot: fit.plot, envelope: fit.envelope, site }
				: undefined;
		} catch {
			return undefined; // no soil report, or not one that reads: no plot
		}
	}

	/** The design-code packs installed (empty without the backend: the default pack only). */
	private async loadCodePacks(): Promise<void> {
		if (!CommandsRegistry.getCommand(CODES_LIST_COMMAND)) {
			return;
		}
		try {
			this.codePacks = readCodePacks(await this.commandService.executeCommand<unknown>(CODES_LIST_COMMAND, { root: this.projectService.project?.root.fsPath }));
		} catch {
			this.codePacks = [];
		}
	}

	/** The exposures of the pack ``id`` (its wind table), for a pack other than the default. */
	private async loadPackExposures(id: string): Promise<void> {
		this.packExposures = [];
		this.defaultExposure = '';
		this.packTowns = [];
		this.packSiteClasses = [];
		this.packSpectrum = '';
		this.packSiteClassClause = '';
		const hadRebars = this.packRebars.length > 0;
		this.packRebars = [];
		let units: 'SI' | 'USCustomary' = 'SI';
		if (id === DEFAULT_CODE_PACK_ID || !CommandsRegistry.getCommand(CODES_CHOICES_COMMAND)) {
			this.form.packTowns = false;
			this.useUnitsAndRebars(units, hadRebars);
			return;
		}
		try {
			const lists = readPackLists(await this.commandService.executeCommand<unknown>(CODES_CHOICES_COMMAND, { id, root: this.projectService.project?.root.fsPath }));
			this.packExposures = lists?.exposures ?? [];
			this.defaultExposure = lists?.defaultExposure?.[0]?.id ?? '';
			this.packTowns = (lists?.locations ?? []).filter(l => l.id !== 'custom');
			this.packSiteClasses = lists?.siteClasses ?? [];
			this.packSpectrum = lists?.designSpectrum?.[0]?.id ?? '';
			this.packSiteClassClause = lists?.siteClassClause?.[0]?.label ?? '';
			// W4A-6: the pack's suggested units and its own bar grades.
			units = lists?.units?.[0]?.id === 'USCustomary' ? 'USCustomary' : 'SI';
			this.packRebars = lists?.rebarGrades ?? [];
		} catch {
			this.packExposures = [];
		}
		this.useUnitsAndRebars(units, hadRebars);
		// W4A-27: the exposure shown is the one sent: the pack's start (the generator's rule).
		if (!this.packExposures.some(e => e.id === this.form.exposure)) {
			const start = this.defaultExposure;
			this.form.exposure = this.packExposures.some(e => e.id === start) ? start : (this.packExposures[0]?.id ?? '');
		}
		// C7: a pack with towns of its own is chosen from them; its site class from its classes.
		this.form.packTowns = this.packTowns.length > 0;
		if (this.packTowns.length && !this.packTowns.some(t => t.id === this.form.location)) {
			this.form.location = this.packTowns[0].id;
		}
		if (this.packSiteClasses.length && !this.packSiteClasses.some(c => c.id === this.form.siteClass)) {
			this.form.siteClass = this.packSiteClasses[0].id;
		}
	}

	/**
	 * W4A-6: the chosen pack's units (the form's lengths and wind speed written again in them) and
	 * bar grades (the first where the form's grade is not one of them; back to the default
	 * materials' first when the pack before had grades of its own and this one has none).
	 */
	private useUnitsAndRebars(units: 'SI' | 'USCustomary', hadRebars: boolean): void {
		this.form = formInUnits(this.form, units);
		if (this.packRebars.length && !this.packRebars.some(r => r.id === this.form.rebar)) {
			this.form.rebar = this.packRebars[0].id;
		} else if (!this.packRebars.length && hadRebars) {
			this.form.rebar = materialChoices('rebar')[0]?.value ?? this.form.rebar;
		}
	}

	/**
	 * A start asked for by a command: `template` the first full template installed (or, with none,
	 * a note that leads to the Packages page; the grid stays), `grid` the grid.
	 */
	private applyStartRequest(request: NewProjectStart): void {
		const options = this.startOptions();
		const wanted = request === 'template' ? options.find(o => o.start.kind === 'archive') : options[0];
		this.step = 'project';
		if (wanted) {
			this.chooseStart(wanted.start);
			return;
		}
		this.notificationService.prompt(Severity.Info,
			localize('template.none', "No full building templates are installed. A full template is a whole project (floor plan, model, settings) to start from; building specifications are offered under Start from in New Project."),
			[{ label: localize('template.getMore', "Get Building Templates..."), run: () => this.commandService.executeCommand('saengine.packages.show', { tab: 'browse', kind: 'buildingTemplate' }) }]);
	}

	/** The building templates of the installed packages (empty without the backend). */
	private async loadTemplates(): Promise<void> {
		if (!CommandsRegistry.getCommand(CODES_TEMPLATES_COMMAND)) {
			return;
		}
		try {
			this.templates = readBuildingTemplates(await this.commandService.executeCommand<unknown>(CODES_TEMPLATES_COMMAND, { kind: 'buildingTemplate', root: this.projectService.project?.root.fsPath }));
		} catch {
			this.templates = [];
		}
	}

	/** The choices of "Start from" (page 1), the current one marked; Custom once a specification was edited. */
	private startOptions(): IStartOption[] {
		const specs = this.templates.filter(t => t.type === 'spec');
		const archives = this.templates.filter(t => t.type === 'archive');
		const label = templateLabel;
		// The default specification is "the grid": its values are the form's starting values.
		const grid = specs.find(t => t.package === DEFAULT_BUILDING_TEMPLATE) ?? specs[0];
		const typeDescription = (type: ProjectType) => PROJECT_TYPES.find(t => t.type === type)?.description;
		return [
			{ text: localize('newProject.startGrid', "Grid and storeys (the whole building, defined next)"), description: grid?.description, start: { kind: 'spec', template: grid } },
			...specs.filter(t => t !== grid).map((t): IStartOption => ({ text: localize('newProject.startSpec', "{0}: grid and storeys to adjust", label(t)), description: t.description, start: { kind: 'spec', template: t } })),
			...archives.map((t): IStartOption => ({ text: localize('newProject.startArchive', "{0}: full project with its own model", label(t)), description: t.description, start: { kind: 'archive', template: t } })),
			{ text: localize('newProject.startEmpty', "Empty building (draw the grids and members yourself)"), description: typeDescription('building'), start: { kind: 'empty', type: 'building' } },
			{ text: localize('newProject.startStructure', "Special structure (a 3D model, no grid)"), description: typeDescription('structure'), start: { kind: 'empty', type: 'structure' } },
		];
	}

	/** "Start from": the grid (a building specification fills the form), a full template, or an empty project. */
	private renderStartFrom(form: HTMLElement): void {
		const control = this.row(form, localize('newBuilding.template', "Start from"));
		const options = this.startOptions();
		const index = Math.max(0, options.findIndex(o => startKey(o.start) === startKey(this.start)));
		const from = this.start.kind === 'spec' ? this.start.template : undefined;
		// B10-3: edited after a specification filled it, the form is no longer that specification.
		const custom = this.templateCustom && from
			? [{ text: index === 0 ? localize('newProject.startGridEdited', "Grid and storeys (edited)") : localize('newBuilding.templateCustom', "Custom (started from {0})", templateLabel(from)), description: undefined }] : [];
		const items = [...options.map(o => ({ text: o.text, description: o.description })), ...custom];
		const box = this.pageDisposables.add(new SelectBox(items, custom.length ? options.length : index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('newBuilding.template', "Start from") }));
		box.render(control);
		const hint = append(form, $('p.hint.indented.plot-hint'));
		hint.textContent = this.startHint();
		// Building templates are installed on the Packages page; the wizard only links to it.
		const more = append(form, $('p.hint.indented'));
		const link = append(more, $('a.packages-link', { href: '#', role: 'button' }, localize('newBuilding.moreTemplates', "Get more building templates...")));
		this.pageDisposables.add(addDisposableListener(link, EventType.CLICK, e => {
			e.preventDefault();
			void this.commandService.executeCommand('saengine.packages.show', { tab: 'browse', kind: 'buildingTemplate' });
		}));
		this.pageDisposables.add(box.onDidSelect(({ index: picked }) => {
			const option = options[picked];
			if (!option) {
				return; // the custom entry: nothing to apply
			}
			this.chooseStart(option.start);
			this.renderPage();
		}));
	}

	/** What the chosen start makes, under "Start from". */
	private startHint(): string {
		switch (this.start.kind) {
			case 'spec':
				return localize('newBuilding.subtitle', "Columns, beams, walls, slabs and footings on every storey in one step, with preliminary sizes. Edit them afterwards in the floor plan.");
			case 'archive':
				return localize('newProject.archiveHint', "A whole project (floor plan, model, settings) from an installed template. It keeps its own design code and settings: change them in 02 Project Settings once it opens.");
			case 'empty':
				return this.start.type === 'building'
					? localize('newProject.emptyHint', "A project with no grids or members yet: draw them in 05 Floor Plan, or generate members from the grid there.")
					: localize('newProject.structureHint', "A project modelled in 3D (roofs, stadiums, towers, bridges): no floor grid is asked.");
		}
	}

	/** The start chosen in "Start from": a specification fills the form with its values. */
	private chooseStart(start: StartFrom): void {
		this.start = start;
		this.templateCustom = false;
		if (start.kind === 'spec' && start.template?.spec) {
			this.form = { ...formFromSpec(start.template.spec, this.form) };
		}
	}

	/** The pages of the chosen start: the grid's three, an empty project's two, a full template's one. */
	private steps(): readonly WizardStep[] {
		switch (this.start.kind) {
			case 'spec': return ['project', 'site', 'building'];
			case 'empty': return ['project', 'site'];
			case 'archive': return ['project'];
		}
	}

	private stepTitle(step: WizardStep): string {
		switch (step) {
			case 'project': return localize('newProject.stepProject', "Project");
			case 'site': return localize('newBuilding.site', "Site and Use");
			case 'building': return localize('newProject.stepBuilding', "Grid and Storeys");
		}
	}

	/** Why the name cannot be used, or undefined (an empty project's folder name is made from any name). */
	private nameError(text: string): string | undefined {
		return this.start.kind === 'empty' ? this.opener.validateDisplayName(text) : this.opener.validateName(text);
	}

	/** The folder the project will be in, or undefined while the name or the folder is not valid. */
	private targetFolder(): URI | undefined {
		if (folderError(this.folder, isWindows) || !this.form.name.trim() || this.nameError(this.form.name)) {
			return undefined;
		}
		const folder = this.start.kind === 'empty' ? projectFolderName(this.form.name) : this.form.name.trim();
		return joinPath(URI.file(this.folder.trim()), folder);
	}

	/** Whether the grid's page is shown (the engineer may have gone on while the plot was read). */
	private showsGrid(): boolean {
		return this.step === 'building';
	}

	/** Whether the page `step` is complete (its fields read). */
	private stepValid(step: WizardStep): boolean {
		switch (step) {
			case 'project': return !!this.targetFolder();
			case 'site': return true;
			case 'building': return buildSpec(this.form, value => this.opener.validateName(value)).ok;
		}
	}

	/** Whether this build can create the chosen start (the generator, the template check). */
	private get available(): boolean {
		switch (this.start.kind) {
			case 'spec': return !!CommandsRegistry.getCommand(GENERATE_BUILDING_COMMAND);
			default: return true; // a full template's check and an empty project need no generator
		}
	}

	private resetPage(): HTMLElement {
		this.pageDisposables.clear();
		clearNode(this.container);
		this.scrollable.setScrollPosition({ scrollTop: 0 });
		return append(this.container, $('.page'));
	}

	/** To page `step`: forward only past complete pages (the first incomplete one shows instead). */
	private goTo(step: WizardStep): void {
		const steps = this.steps();
		const target = steps.indexOf(step);
		if (target < 0) {
			return;
		}
		for (let i = steps.indexOf(this.step); i >= 0 && i < target; i++) {
			if (!this.stepValid(steps[i])) {
				this.step = steps[i];
				this.renderPage(true);
				return;
			}
		}
		this.step = step;
		this.renderPage();
	}

	// ───────────────────────────── the pages ─────────────────────────────

	/**
	 * The page of {@link step}: the steps above it, its fields, and Back, Next (or Create on the
	 * last page) and Cancel. `showErrors`: the page's fields say what is wrong at once.
	 */
	private renderPage(showErrors = false): void {
		const steps = this.steps();
		if (!steps.includes(this.step)) {
			this.step = steps[0];
		}
		const page = this.resetPage();
		const header = append(page, $('header.header'));
		append(header, $('h1', undefined, localize('newProject.title', "New Project")));
		const current = steps.indexOf(this.step);
		if (steps.length > 1) {
			const list = append(header, $('ol.steps', { 'aria-label': localize('newProject.stepsAria', "Steps") }));
			for (const [i, step] of steps.entries()) {
				const item = append(list, $('li'));
				const button = append(item, $('button.step', { type: 'button' }, localize('newProject.stepLabel', "{0}. {1}", i + 1, this.stepTitle(step))));
				button.classList.toggle('current', i === current);
				button.classList.toggle('done', i < current);
				if (i === current) {
					button.setAttribute('aria-current', 'step');
				}
				this.pageDisposables.add(addDisposableListener(button, EventType.CLICK, () => this.goTo(step)));
			}
		}
		if (!this.available) {
			const note = append(page, $('.unavailable', { role: 'status' }));
			append(note, $(`span${ThemeIcon.asCSSSelector(Codicon.info)}`));
			append(note, $('span', undefined, localize('newBuilding.unavailable', "Generating a building is not available in this build yet. You can fill in the form; Create is enabled once the generator is installed.")));
		}

		const body = append(page, $('.body'));
		const form = append(body, $('.form'));
		const last = current === steps.length - 1;
		const actions: IPageActions = { refresh: () => { } };
		switch (this.step) {
			case 'project': this.renderProjectStep(form, actions, showErrors); break;
			case 'site': this.renderSiteStep(form); break;
			case 'building': this.renderBuildingStep(form, append(body, $('aside.preview', { 'aria-label': localize('newBuilding.previewAria', "Preview") })), actions, showErrors); break;
		}
		body.classList.toggle('single', this.step !== 'building');

		// ── actions ──
		const row = append(form, $('.form-actions'));
		if (current > 0) {
			const back = this.pageDisposables.add(new Button(row, { ...defaultButtonStyles, secondary: true }));
			back.label = localize('newProject.back', "Back");
			this.pageDisposables.add(back.onDidClick(() => this.goTo(steps[current - 1])));
		}
		const primary = this.pageDisposables.add(new Button(row, defaultButtonStyles));
		primary.label = last ? localize('newProject.create', "Create Project") : localize('newProject.next', "Next");
		const cancel = this.pageDisposables.add(new Button(row, { ...defaultButtonStyles, secondary: true }));
		cancel.label = localize('newBuilding.cancel', "Cancel");
		this.pageDisposables.add(cancel.onDidClick(() => this.close()));
		const status = append(row, $('span.status', { 'aria-live': 'polite' }));
		// W4A-1: a failure stays on the form (the notification may be closed or time out) until the next try.
		const failure = append(form, $('p.error.create-failure', { role: 'alert' }));
		// Create stays off while a page is not complete; Next shows what is missing instead.
		const update = () => {
			primary.enabled = !this.busy && (!last || (this.available && steps.every(step => this.stepValid(step))));
		};
		actions.refresh = update;
		const next = () => {
			if (!primary.enabled) {
				return;
			}
			if (!last) {
				this.goTo(steps[current + 1]);
			} else if (!steps.every(step => this.stepValid(step))) {
				this.goTo(steps[steps.length - 1]); // to the first incomplete page
			} else {
				void this.createProject(failure, status, update);
			}
		};
		this.pageDisposables.add(primary.onDidClick(next));
		this.pageDisposables.add(addDisposableListener(form, EventType.KEY_DOWN, e => {
			// Enter in a field goes on (Next, or Create on the last page) when the button could.
			if (e.key === 'Enter' && !isHTMLButtonElement(e.target)) {
				next();
			} else if (e.key === 'Escape') {
				this.close();
			}
		}));
		update();
		this.scrollable.scanDomNode();
		this.focusTarget?.focus();
	}

	/** Page 1: the name and folder, what the project starts from, its design code and units. */
	private renderProjectStep(form: HTMLElement, actions: IPageActions, showErrors: boolean): void {
		const name = this.textInput(form, localize('newBuilding.name', "Name"), this.form.name, value => this.form.name = value, localize('newBuilding.namePlaceholder', "e.g. Office Building"), text => this.nameError(text));
		const folderRow = this.row(form, localize('newBuilding.folder', "Folder"));
		const location = this.pageDisposables.add(new InputBox(folderRow, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: localize('newBuilding.folder', "Folder") }));
		location.value = this.folder;
		this.pageDisposables.add(location.onDidChange(value => this.folder = value));
		const browse = this.pageDisposables.add(new Button(folderRow, { ...defaultButtonStyles, secondary: true }));
		browse.label = localize('newBuilding.browse', "Browse...");
		this.pageDisposables.add(browse.onDidClick(async () => {
			const picked = await this.opener.browseForLocation(URI.file(location.value), localize('newProject.folderTitle', "Choose Where to Create the Project"));
			if (picked) {
				location.value = picked.fsPath;
			}
		}));
		const folderMessage = append(form, $('p.error', { 'aria-live': 'polite' }));
		const target = append(form, $('p.target'));
		const project = this.projectService.project;
		if (project) {
			append(form, $('p.hint.indented', undefined, localize('newProject.separate', "The new project is separate: {0}, open now, is not changed.", project.name)));
		}
		const updateTarget = () => {
			const error = folderError(this.folder, isWindows);
			folderMessage.textContent = error ?? '';
			const folder = this.targetFolder();
			target.textContent = folder ? localize('newBuilding.target', "Will be created in {0}", folder.fsPath) : '';
			actions.refresh();
		};
		this.pageDisposables.add(name.onDidChange(() => {
			name.validate();
			updateTarget();
		}));
		this.pageDisposables.add(location.onDidChange(updateTarget));

		this.renderStartFrom(form);

		if (this.start.kind === 'archive') {
			// The template keeps its own design code and units: nothing more is asked.
		} else {
			// The installed design-code packs, then the planned ones as disabled options of the list
			// (B10-4: no second set of chips).
			this.select(form, localize('newBuilding.designCode', "Design code"), designCodeChoices(this.codePacks), this.form.designCode || DEFAULT_CODE_PACK_ID, value => {
				if (value === this.form.designCode) {
					return;
				}
				this.form.designCode = value;
				this.form.hazard = undefined; // C22: another code's values are not this one's
				void this.loadPackExposures(value).then(() => this.renderPage());
			});
			if (this.start.kind === 'spec') {
				// W4A-6: the units the project shows (the pack's suggestion: US customary for the US pack);
				// the grid, the storeys and the wind speed are typed in them.
				const unitChoices: IChoice<string>[] = [
					{ value: 'SI', label: localize('newBuilding.unitsSi', "SI (mm, m, kN, MPa)") },
					{ value: 'USCustomary', label: localize('newBuilding.unitsUs', "US customary (ft, in, kip, ksi, psf)") },
				];
				this.select(form, localize('newBuilding.units', "Units"), unitChoices, this.form.units ?? 'SI', value => {
					const units = value === 'USCustomary' ? 'USCustomary' : 'SI';
					if (units !== (this.form.units ?? 'SI')) {
						this.form = formInUnits(this.form, units);
						this.renderPage();
					}
				});
			} else {
				append(form, $('p.hint.indented', undefined, localize('newProject.unitsLater', "The project's units follow the design code; change them in 02 Project Settings.")));
			}
		}
		updateTarget();
		if (showErrors) {
			name.validate();
		}
		this.focusTarget = showErrors && !this.nameError(this.form.name) ? location : name;
	}

	/**
	 * Page 2: where the building stands and what it is for. An empty project takes the location
	 * and the use (the rest is set in Project Settings > Site); a building from the grid all of it.
	 */
	private renderSiteStep(form: HTMLElement): void {
		const full = this.start.kind === 'spec';
		const inFeet = lengthUnit(this.form) === 'ft';
		const isDefault = (this.form.designCode || DEFAULT_CODE_PACK_ID) === DEFAULT_CODE_PACK_ID;
		let first: { focus(): void } | undefined;
		if (isDefault) {
			// W4C-34: the default pack is the one chosen here, whatever pack the open project uses.
			append(form, $('p.hint', undefined, localize('newBuilding.siteHint', "{0}: the location sets the seismic zone and basic wind speed; the occupancy category the importance factors (Table 6.1.1).", defaultCodeName())));
			first = this.select(form, localize('newBuilding.location', "Location"), locationChoices(), this.form.location, value => this.form.location = value);
		} else if (this.packTowns.length) {
			// C7: a pack with towns of its own (Indian Standards): the town sets the zone and wind speed.
			append(form, $('p.hint', undefined, localize('newBuilding.packTownsHint', "The location sets the seismic zone and basic wind speed of this design code. Check them, and the exposure, in Project Settings.")));
			first = this.select(form, localize('newBuilding.location', "Location"), this.packTowns.map(t => ({ value: t.id, label: t.label })), this.form.location, value => this.form.location = value);
			if (full && this.packExposures.length) {
				const exposures = this.packExposures.map(e => ({ value: e.id, label: e.label }));
				this.select(form, localize('newBuilding.exposure', "Exposure"), exposures, this.form.exposure, value => this.form.exposure = value);
			}
		} else if (full) {
			// C4: a pack without the default pack's towns (the Eurocodes: the National Annex maps).
			append(form, $('p.hint', undefined, localize('newBuilding.otherPackHint', "This design code has no towns of its own: enter the site's peak ground acceleration and basic wind speed from the national maps (the project's Location is Custom). Check them, and the exposure, in Project Settings.")));
			if (this.packSpectrum === 'mappedSpectral') {
				// C1: a pack whose design spectrum comes from the site's mapped values (ASCE 7-22).
				append(form, $('p.hint', undefined, localize('newBuilding.mappedHint', "This design code takes the seismic hazard from the site's mapped values (for ASCE 7-22, the ASCE Hazard Tool): SDS and SD1, with S1 and the long-period transition TL. They can be changed later in Project Settings > Site.")));
				first = this.textInput(form, localize('newBuilding.sds', "SDS (g)"), this.form.sds, value => this.form.sds = value, localize('newBuilding.sdsPlaceholder', "e.g. 1.0"));
				this.textInput(form, localize('newBuilding.sd1', "SD1 (g)"), this.form.sd1, value => this.form.sd1 = value, localize('newBuilding.sd1Placeholder', "e.g. 0.6"));
				this.textInput(form, localize('newBuilding.s1', "S1 (g)"), this.form.s1, value => this.form.s1 = value, localize('newBuilding.s1Placeholder', "optional"));
				this.textInput(form, localize('newBuilding.tl', "TL (s)"), this.form.tl, value => this.form.tl = value, localize('newBuilding.tlPlaceholder', "optional, e.g. 8"));
				this.renderHazardLookup(form);
			} else {
				first = this.textInput(form, localize('newBuilding.zoneCoefficient', "Peak ground acceleration (g)"), this.form.zoneCoefficient, value => this.form.zoneCoefficient = value, localize('newBuilding.zonePlaceholder', "e.g. 0.16 (agR)"));
			}
			if (inFeet) {
				this.textInput(form, localize('newBuilding.windSpeedMph', "Basic wind speed (mph)"), this.form.windSpeed, value => this.form.windSpeed = value, localize('newBuilding.windPlaceholderMph', "e.g. 105 (V)"));
			} else {
				this.textInput(form, localize('newBuilding.windSpeed', "Basic wind speed (m/s)"), this.form.windSpeed, value => this.form.windSpeed = value, localize('newBuilding.windPlaceholder', "e.g. 27 (vb,0)"));
			}
			if (this.packExposures.length) {
				const exposures = this.packExposures.map(e => ({ value: e.id, label: e.label }));
				this.select(form, localize('newBuilding.exposure', "Exposure"), exposures, this.form.exposure, value => this.form.exposure = value);
			}
		}
		if (full) {
			const siteClasses = this.packSiteClasses.length ? this.packSiteClasses.map(c => ({ value: c.id, label: c.label })) : settingsEnum('Site', 'siteClass');
			this.select(form, localize('newBuilding.siteClass', "Site class"), siteClasses, this.form.siteClass, value => this.form.siteClass = value as SiteClass);
			// Walk 4: the clause of the chosen pack (its own), never the default pack's under another code.
			const siteClassHint = isDefault
				? localize('newBuilding.siteClassHint', "Assumed until a soil report gives it ({0} Part 6, Table 6.2.13): add boreholes in 01 Soil Report and their class replaces it.", defaultCodeName())
				: this.packSiteClassClause
					? localize('newBuilding.siteClassHintPack', "Assumed until a soil report gives it ({0}): add boreholes in 01 Soil Report and their class replaces it.", this.packSiteClassClause)
					: localize('newBuilding.siteClassHintNone', "Assumed until a soil report gives it: add boreholes in 01 Soil Report and their class replaces it.");
			append(form, $('p.hint.indented', undefined, siteClassHint));
		}
		const use = this.select(form, localize('newBuilding.use', "Building use"), settingsEnum('Occupancy', 'use'), this.form.use, value => this.form.use = value);
		if (full) {
			this.select(form, localize('newBuilding.category', "Occupancy category"), settingsEnum('Occupancy', 'category'), this.form.category, value => this.form.category = value as OccupancyCategory);
		} else {
			append(form, $('p.hint.indented', undefined, localize('newProject.siteLater', "The site class, the occupancy category and the hazard values are set in 02 Project Settings > Site once the project opens.")));
		}
		this.focusTarget = first ?? use;
	}

	/** Page 3 (from the grid): the grids, the storeys and the structure, with a live plan and elevation. */
	private renderBuildingStep(form: HTMLElement, side: HTMLElement, actions: IPageActions, showErrors: boolean): void {
		const planHost = append(side, $('.preview-plan'));
		const elevationHost = append(side, $('.preview-elevation'));
		const summary = append(side, $('p.summary'));
		const systemHint = append(side, $('p.hint'));
		const inputs = new Map<FormField, InputBox>();
		const errors = new Map<FormField, HTMLElement>();
		const plotWarning: { element?: HTMLElement } = {};
		// B10-3: once the grids, storeys or system are edited, "Start from" says Custom.
		let ready = false;
		const updatePreview = () => {
			if (ready) {
				this.templateCustom = true;
			}
			const x = parseSpacings(this.form.gridX, lengthUnit(this.form));
			const y = parseSpacings(this.form.gridY, lengthUnit(this.form));
			const heights = storyHeights(this.form);
			clearNode(planHost);
			clearNode(elevationHost);
			if (x.ok && y.ok) {
				this.renderPlan(planHost, x.values, y.values);
			}
			if (x.ok && heights.ok) {
				this.renderElevation(elevationHost, x.values, heights.values);
			}
			summary.textContent = x.ok && y.ok && heights.ok ? formatSummary(summarize(x.values, y.values, heights.values), this.form.units) : localize('newBuilding.previewWaiting', "The preview shows once the grids and storeys read correctly.");
			systemHint.textContent = SYSTEM_CHOICES.find(s => s.value === this.form.system)?.description ?? '';
			if (plotWarning.element) {
				plotWarning.element.textContent = this.plot && x.ok && y.ok ? plotFitWarning(x.values, y.values, this.plot) ?? '' : '';
			}
			for (const [field, message] of [['gridX', x], ['gridY', y], ['stories', heights]] as const) {
				const element = errors.get(field);
				if (element) {
					element.textContent = message.ok || (!ready && !showErrors) ? '' : message.error;
				}
			}
			this.scrollable.scanDomNode();
			actions.refresh();
		};

		// ── grids ──
		const inFeet = lengthUnit(this.form) === 'ft';
		this.section(form, localize('newBuilding.grids', "Grids"), inFeet
			? localize('newBuilding.gridsHintFt', "Spacings in ft, left to right and bottom to top: \"3×20, 15\" is three 20 ft bays and one of 15 ft. mm and m work too (6000mm, 6m).")
			: localize('newBuilding.gridsHint', "Spacings in mm, left to right and bottom to top: \"3×6000, 4500\" is three 6 m bays and one of 4.5 m. m and ft work too (6m, 20ft)."));
		for (const [field, label] of [['gridX', localize('newBuilding.gridX', "X (A, B, C ...)")], ['gridY', localize('newBuilding.gridY', "Y (1, 2, 3 ...)")]] as const) {
			const box = this.textInput(form, label, this.form[field], value => {
				this.form[field] = value;
				updatePreview();
			});
			inputs.set(field, box);
			errors.set(field, append(form, $('p.error', { 'aria-live': 'polite' })));
		}
		const plot = this.plot;
		if (plot) {
			append(form, $('p.hint.indented.plot-hint', undefined, localize('newBuilding.plot', "The plot of {0} (01 Soil Report) is in the preview: the grid can take {1} × {2} m inside its setbacks, with the columns' faces inside. The new project takes the site, with the grid turned along the road side.", plot.project, (plot.width / 1000).toFixed(2), (plot.depth / 1000).toFixed(2))));
			const fitRow = append(form, $('.form-actions.indented'));
			const fit = this.pageDisposables.add(new Button(fitRow, { ...defaultButtonStyles, secondary: true }));
			fit.label = localize('newBuilding.fit', "Fit to the Buildable Area");
			fit.setTitle(localize('newBuilding.fitTitle', "Bay spacings that fill the buildable area (to 50 mm), keeping the number of bays and their proportions"));
			const fitStatus = append(fitRow, $('span.status', { 'aria-live': 'polite' }));
			this.pageDisposables.add(fit.onDidClick(() => {
				const x = parseSpacings(this.form.gridX, lengthUnit(this.form));
				const y = parseSpacings(this.form.gridY, lengthUnit(this.form));
				const fx = x.ok ? fitSpacings(x.values, plot.width) : undefined;
				const fy = y.ok ? fitSpacings(y.values, plot.depth) : undefined;
				if (!fx || !fy) {
					fitStatus.textContent = localize('newBuilding.fitFailed', "The buildable area is too small for this many bays (at least 1 m each): use fewer bays.");
					return;
				}
				fitStatus.textContent = '';
				for (const [field, values] of [['gridX', fx], ['gridY', fy]] as const) {
					// The fitted bays are exact millimetres: in US customary units they say so ("6050mm").
					const text = formatLengths(values);
					this.form[field] = lengthUnit(this.form) === 'ft' ? text.split(', ').map(part => `${part}mm`).join(', ') : text;
					inputs.get(field)!.value = this.form[field];
				}
				updatePreview();
			}));
			plotWarning.element = append(form, $('p.error', { 'aria-live': 'polite' }));
		} else if (this.projectService.project) {
			append(form, $('p.hint.indented.plot-hint', undefined, localize('newBuilding.noPlot', "To fit the grid to the plot, draw the plot in the map of 01 Soil Report first.")));
		}

		// ── storeys ──
		this.section(form, localize('newBuilding.storeys', "Storeys"));
		const storeyRow = this.row(form, localize('newBuilding.storeyCount', "Number"));
		storeyRow.classList.add('triple');
		const small = (label: string, field: 'storyCount' | 'groundHeight' | 'typicalHeight', aria: string) => {
			const cell = append(storeyRow, $('.cell'));
			const box = this.pageDisposables.add(new InputBox(cell, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: aria }));
			box.value = this.form[field];
			this.pageDisposables.add(box.onDidChange(value => {
				this.form[field] = value;
				updatePreview();
			}));
			if (label) {
				append(cell, $('span.unit', undefined, label));
			}
		};
		small('', 'storyCount', localize('newBuilding.storeyCountAria', "Number of storeys"));
		if (inFeet) {
			small(localize('newBuilding.groundUnitFt', "ground, ft"), 'groundHeight', localize('newBuilding.groundAriaFt', "Ground storey height in ft"));
			small(localize('newBuilding.typicalUnitFt', "typical, ft"), 'typicalHeight', localize('newBuilding.typicalAriaFt', "Typical storey height in ft"));
		} else {
			small(localize('newBuilding.groundUnit', "ground, mm"), 'groundHeight', localize('newBuilding.groundAria', "Ground storey height in mm"));
			small(localize('newBuilding.typicalUnit', "typical, mm"), 'typicalHeight', localize('newBuilding.typicalAria', "Typical storey height in mm"));
		}
		const heights = this.textInput(form, localize('newBuilding.heights', "Or every storey"), this.form.heights, value => {
			this.form.heights = value;
			updatePreview();
		}, inFeet
			? localize('newBuilding.heightsPlaceholderFt', "e.g. 13, 9×10.5 (overrides the number)")
			: localize('newBuilding.heightsPlaceholder', "e.g. 4000, 9×3200 (overrides the number)"));
		inputs.set('stories', heights);
		errors.set('stories', append(form, $('p.error', { 'aria-live': 'polite' })));

		// ── structure ──
		this.section(form, localize('newBuilding.structure', "Structure"));
		this.choices(form, localize('newBuilding.system', "System"), SYSTEM_CHOICES, this.form.system, value => {
			this.form.system = value;
			updatePreview();
		});
		this.select(form, localize('newBuilding.concrete', "Concrete"), materialChoices('concrete'), this.form.concrete, value => this.form.concrete = value);
		// W4A-6: the chosen pack's bar grades (ASTM A615 Grade 60) where it has its own.
		const rebars = this.packRebars.length ? this.packRebars.map(r => ({ value: r.id, label: r.label })) : materialChoices('rebar');
		this.select(form, localize('newBuilding.rebar', "Reinforcement"), rebars, this.form.rebar, value => this.form.rebar = value);
		this.select(form, localize('newBuilding.footing', "Footings"), FOOTING_CHOICES, this.form.footing, value => this.form.footing = value);

		updatePreview();
		ready = true;
		const result = buildSpec(this.form, value => this.opener.validateName(value));
		const wrong = result.ok ? undefined : (['gridX', 'gridY', 'stories'] as const).find(f => result.errors[f]);
		this.focusTarget = (wrong && inputs.get(wrong)) ?? inputs.get('gridX');
	}

	/** Create on the last page: generates the building, creates the empty project or opens the template. */
	private async createProject(failure: HTMLElement, status: HTMLElement, update: () => void): Promise<void> {
		if (this.busy || !this.available) {
			return;
		}
		const parent = this.folder.trim();
		const name = this.form.name.trim();
		this.busy = true;
		update();
		failure.textContent = '';
		status.textContent = this.start.kind === 'spec' ? localize('newBuilding.creating', "Creating the building...") : localize('newProject.creating', "Creating the project...");
		try {
			const missing = await this.prepareFolder(parent);
			if (missing) {
				throw new Error(missing);
			}
			switch (this.start.kind) {
				case 'spec': {
					const result = buildSpec(this.form, value => this.opener.validateName(value));
					if (!result.ok) {
						return;
					}
					const outcome = readGenerateResult(await this.commandService.executeCommand(GENERATE_BUILDING_COMMAND, { spec: result.spec, destParent: parent, name: result.spec.name, ...this.siteArgument() }));
					if (outcome.error || !outcome.root) {
						throw new Error(outcome.error ?? '');
					}
					this.wizardStorage.store(LAST_FOLDER_STORAGE_KEY, parent, StorageScope.APPLICATION, StorageTarget.MACHINE);
					this.busy = false;
					this.renderResult(result.spec.name, outcome.root, outcome.notes, outcome.summary, parent);
					return;
				}
				case 'empty': {
					// The location where the chosen code has towns (the default pack's, or its own).
					const towns = (this.form.designCode || DEFAULT_CODE_PACK_ID) === DEFAULT_CODE_PACK_ID || this.packTowns.length > 0;
					this.wizardStorage.store(LAST_FOLDER_STORAGE_KEY, parent, StorageScope.APPLICATION, StorageTarget.MACHINE);
					await this.opener.createAndOpen(URI.file(parent), name, this.start.type, { codePack: this.form.designCode || DEFAULT_CODE_PACK_ID, location: towns ? this.form.location || undefined : undefined, use: this.form.use || undefined });
					break;
				}
				case 'archive': {
					const template = this.start.template;
					const root = await this.commandService.executeCommand<URI | undefined>(NEW_FROM_TEMPLATE_COMMAND, { path: template.path, author: template.author, name, destParent: parent } satisfies INewFromTemplateArgs);
					if (root) {
						this.wizardStorage.store(LAST_FOLDER_STORAGE_KEY, parent, StorageScope.APPLICATION, StorageTarget.MACHINE);
						this.close();
					}
					break;
				}
			}
		} catch (error) {
			// Nothing was created: the form says so.
			const message = this.start.kind === 'spec'
				? localize('newBuilding.failed', "The building could not be created: {0}", toErrorMessage(error))
				: localize('newProject.failed', "The project could not be created: {0}", toErrorMessage(error));
			failure.textContent = message;
			this.notificationService.notify({ severity: Severity.Error, message, sticky: true });
		} finally {
			if (this.busy) {
				this.busy = false;
				status.textContent = '';
				update();
			}
		}
	}

	/**
	 * Why the project cannot go in `folder`, or undefined. A missing folder is created as long as
	 * the folder above it exists (a mistyped drive or path is not created silently).
	 */
	private async prepareFolder(folder: string): Promise<string | undefined> {
		const resource = URI.file(folder);
		if (await this.fileService.exists(resource)) {
			const stat = await this.fileService.stat(resource);
			return stat.isDirectory ? undefined : localize('newBuilding.notFolder', "{0} is a file, not a folder.", folder);
		}
		if (!await this.fileService.exists(dirname(resource))) {
			return localize('newBuilding.noFolder', "{0} does not exist. Choose an existing folder with Browse.", folder);
		}
		await this.fileService.createFolder(resource);
		return undefined;
	}

	private section(parent: HTMLElement, title: string, hint?: string): void {
		append(parent, $('h2', undefined, title));
		if (hint) {
			append(parent, $('p.hint', undefined, hint));
		}
	}

	/**
	 * C22: Look Up Hazard Values... under the mapped values: by the open project's site point (its
	 * soil report's plot), else by the latitude and longitude typed here (the new project keeps them as its site point).
	 * The values fill the fields above, stay editable, and the project keeps the source.
	 */
	private renderHazardLookup(form: HTMLElement): void {
		const site = (this.plot?.site ?? {}) as { readonly lat?: unknown; readonly lon?: unknown };
		const plotAt = typeof site.lat === 'number' && typeof site.lon === 'number' ? { latitude: site.lat, longitude: site.lon } : undefined;
		if (!plotAt) {
			this.textInput(form, localize('newBuilding.latitude', "Site latitude (°)"), this.hazardLatitude, value => this.hazardLatitude = value, localize('newBuilding.latitudePlaceholder', "the site point, e.g. 34.0522"));
			this.textInput(form, localize('newBuilding.longitude', "Site longitude (°)"), this.hazardLongitude, value => this.hazardLongitude = value, localize('newBuilding.longitudePlaceholder', "the site point, e.g. -118.2437"));
		}
		const control = this.row(form, '');
		const button = this.pageDisposables.add(new Button(control, { ...defaultButtonStyles, secondary: true }));
		button.label = localize('newBuilding.hazardLookUp', "Look Up Hazard Values...");
		button.setTitle(localize('newBuilding.hazardLookUpHint', "Asks the code's hazard service for the site's values by its coordinates (where the code pack names one, and the setting Allow online hazard lookups is on). Asks first; only the coordinates and the code parameters are sent."));
		this.pageDisposables.add(button.onDidClick(() => void this.lookUpHazard(plotAt)));
		const source = this.form.hazard?.source;
		if (source) {
			append(form, $('p.hint.indented', undefined, localize('newBuilding.hazardFrom', "From {0}, looked up {1}. The project keeps the source; the report names it.", String(source.service ?? ''), String(source.date ?? ''))));
		}
	}

	/**
	 * The site the new project starts with: the open project's plot (its soil report's site), else
	 * the latitude and longitude typed above (R4AC-2: kept as 01 Soil Report's site point, where
	 * sun, daylight and the map read it), else none.
	 */
	private siteArgument(): { readonly site?: object } {
		if (this.plot) {
			return { site: this.plot.site };
		}
		const typed = (text: string) => {
			const value = Number(text.trim().replace(',', '.'));
			return text.trim() && Number.isFinite(value) ? value : undefined;
		};
		const lat = typed(this.hazardLatitude);
		const lon = typed(this.hazardLongitude);
		return lat !== undefined && lon !== undefined && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { site: { lat, lon } } : {};
	}

	/** C22: the lookup, then its values into the form (SDS, SD1, S1, TL; the rest kept for the project). */
	private async lookUpHazard(plotAt: { readonly latitude: number; readonly longitude: number } | undefined): Promise<void> {
		const typed = (text: string) => {
			const value = Number(text.trim().replace(',', '.'));
			return text.trim() && Number.isFinite(value) ? value : undefined;
		};
		const at = plotAt ?? { latitude: typed(this.hazardLatitude), longitude: typed(this.hazardLongitude) };
		if (at.latitude === undefined || at.longitude === undefined || Math.abs(at.latitude) > 90 || Math.abs(at.longitude) > 180) {
			await this.wizardDialogs.info(localize('newBuilding.hazardNoSite', "Enter the site's latitude and longitude"), localize('newBuilding.hazardNoSiteDetail', "The lookup asks for the site's values by its coordinates (decimal degrees, south and west negative)."));
			return;
		}
		const settings = {
			codePack: this.form.designCode || DEFAULT_CODE_PACK_ID,
			occupancy: { category: this.form.category },
			site: { location: 'custom', siteClass: this.form.siteClass, siteClassSource: 'entered' },
		};
		const applied = await lookUpHazardValues(
			{ commands: this.commandService, dialogs: this.wizardDialogs, configuration: this.wizardConfiguration, progress: this.wizardProgress },
			{ settingsText: JSON.stringify(settings), latitude: at.latitude, longitude: at.longitude },
		);
		if (!applied) {
			return;
		}
		const spectral: { [key: string]: number | readonly (readonly number[])[] } = {};
		for (const value of applied.values) {
			const key = value.target.startsWith('site.spectral.') ? value.target.slice('site.spectral.'.length) : undefined;
			if (key) {
				spectral[key] = value.value;
			}
			if (value.target === 'site.windSpeed' && typeof value.value === 'number') {
				this.form.windSpeed = String(value.value);
			}
		}
		for (const key of ['sds', 'sd1', 's1', 'tl'] as const) {
			const value = spectral[key];
			if (typeof value === 'number') {
				this.form[key] = String(value);
			}
		}
		this.form.hazard = { spectral, source: applied.source };
		this.renderPage();
	}

	private row(parent: HTMLElement, label: string): HTMLElement {
		const row = append(parent, $('.row'));
		append(row, $('label', undefined, label));
		return append(row, $('.control'));
	}

	private textInput(parent: HTMLElement, label: string, value: string, onChange: (value: string) => void, placeholder?: string, validate?: (text: string) => string | undefined): InputBox {
		const control = this.row(parent, label);
		const box = this.pageDisposables.add(new InputBox(control, this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			ariaLabel: label,
			placeholder,
			validationOptions: validate ? {
				validation: text => {
					const error = validate(text);
					return error ? { content: error, type: MessageType.ERROR } : null;
				},
			} : undefined,
		}));
		box.value = value;
		this.pageDisposables.add(box.onDidChange(onChange));
		return box;
	}

	private select<T extends string>(parent: HTMLElement, label: string, options: readonly IChoice<T>[], initial: T, onChange: (value: T) => void): SelectBox {
		const control = this.row(parent, label);
		const index = Math.max(0, options.findIndex(o => o.value === initial));
		const box = this.pageDisposables.add(new SelectBox(options.map(o => ({ text: o.label, isDisabled: o.disabled })), index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
		box.render(control);
		if (options[index] && options[index].value !== initial) {
			onChange(options[index].value);
		}
		this.pageDisposables.add(box.onDidSelect(({ index: picked }) => onChange(options[picked].value)));
		return box;
	}

	/** Mutually exclusive choices as a segmented row of radio buttons (as on the start page). */
	private choices<T extends string>(parent: HTMLElement, label: string, options: readonly IChoice<T>[], initial: T, onChange: (value: T) => void): void {
		const control = this.row(parent, label);
		const group = append(control, $('.choices', { role: 'radiogroup', 'aria-label': label }));
		const buttons = options.map(option => {
			const button = append(group, $('button.choice', { type: 'button', role: 'radio' }, option.label));
			this.pageDisposables.add(addDisposableListener(button, EventType.CLICK, () => select(option.value)));
			return { button, value: option.value };
		});
		const select = (value: T) => {
			for (const option of buttons) {
				option.button.classList.toggle('selected', option.value === value);
				option.button.setAttribute('aria-checked', String(option.value === value));
			}
			onChange(value);
		};
		select(initial);
	}

	// ───────────────────────────── the preview ─────────────────────────────

	private svg(parent: HTMLElement, width: number, height: number, label: string): SVGSVGElement {
		const svg = parent.appendChild(parent.ownerDocument.createElementNS(SVG, 'svg'));
		svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
		svg.setAttribute('role', 'img');
		svg.setAttribute('aria-label', label);
		return svg;
	}

	private add(into: Element, name: string, attributes: { readonly [name: string]: string | number }, text?: string): Element {
		const element = into.appendChild(into.ownerDocument.createElementNS(SVG, name));
		for (const [key, value] of Object.entries(attributes)) {
			element.setAttribute(key, String(value));
		}
		if (text !== undefined) {
			element.textContent = text;
		}
		return element;
	}

	/** The plan: the plot and its buildable envelope (when there is one), grid lines with bubbles, columns at the intersections, beams, core walls. */
	private renderPlan(parent: HTMLElement, x: readonly number[], y: readonly number[]): void {
		const [width, height, margin] = [360, 280, 26];
		const xs = [0, ...x.map((_, i) => x.slice(0, i + 1).reduce((a, b) => a + b, 0))];
		const ys = [0, ...y.map((_, i) => y.slice(0, i + 1).reduce((a, b) => a + b, 0))];
		const [lx, ly] = [xs[xs.length - 1], ys[ys.length - 1]];
		const plot = this.plot?.plot ?? [];
		const [minX, maxX] = [Math.min(0, ...plot.map(p => p[0])), Math.max(lx, ...plot.map(p => p[0]))];
		const [minY, maxY] = [Math.min(0, ...plot.map(p => p[1])), Math.max(ly, ...plot.map(p => p[1]))];
		const scale = Math.min((width - 2 * margin) / (maxX - minX), (height - 2 * margin) / (maxY - minY));
		const ox = (width - (maxX - minX) * scale) / 2 - minX * scale;
		const oy = (height + (maxY - minY) * scale) / 2 + minY * scale;
		const px = (v: number) => ox + v * scale;
		const py = (v: number) => oy - v * scale;
		const svg = this.svg(parent, width, height, this.plot ? localize('newBuilding.planPlotAria', "Plan of the grids on the plot") : localize('newBuilding.planAria', "Plan of the grids"));
		if (this.plot) {
			const points = (ring: readonly (readonly number[])[]) => ring.map(p => `${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join(' ');
			this.add(svg, 'polygon', { class: 'plot', points: points(this.plot.plot) });
			this.add(svg, 'polygon', { class: 'envelope', points: points(this.plot.envelope) });
		}
		const system = this.form.system;
		if (system === 'flatSlab') {
			this.add(svg, 'rect', { class: 'slab', x: px(0), y: py(ly), width: lx * scale, height: ly * scale });
		}
		for (const [i, v] of xs.entries()) {
			this.add(svg, 'line', { class: 'grid', x1: px(v), y1: py(0) + 10, x2: px(v), y2: py(ly) - 10 });
			this.add(svg, 'circle', { class: 'bubble', cx: px(v), cy: py(ly) - 18, r: 8 });
			this.add(svg, 'text', { class: 'label', x: px(v), y: py(ly) - 18 }, gridLabel('x', i));
		}
		for (const [i, v] of ys.entries()) {
			this.add(svg, 'line', { class: 'grid', x1: px(0) - 10, y1: py(v), x2: px(lx) + 10, y2: py(v) });
			this.add(svg, 'circle', { class: 'bubble', cx: px(0) - 18, cy: py(v), r: 8 });
			this.add(svg, 'text', { class: 'label', x: px(0) - 18, y: py(v) }, gridLabel('y', i));
		}
		if (system !== 'flatSlab') {
			// Load-bearing masonry: walls on every grid line in place of the beams.
			const line = system === 'masonry' ? 'masonry-wall' : 'beam';
			for (const v of ys) {
				this.add(svg, 'line', { class: line, x1: px(0), y1: py(v), x2: px(lx), y2: py(v) });
			}
			for (const v of xs) {
				this.add(svg, 'line', { class: line, x1: px(v), y1: py(0), x2: px(v), y2: py(ly) });
			}
		}
		if (system === 'rcFrameCore') {
			const [bx, by] = [centralBay(x), centralBay(y)];
			this.add(svg, 'rect', { class: 'core', x: px(xs[bx]), y: py(ys[by + 1]), width: x[bx] * scale, height: y[by] * scale });
		}
		if (system === 'masonry') {
			return; // no columns
		}
		const size = 6;
		for (const vx of xs) {
			for (const vy of ys) {
				this.add(svg, 'rect', { class: 'column', x: px(vx) - size / 2, y: py(vy) - size / 2, width: size, height: size });
			}
		}
	}

	/** The elevation along X: the columns and a floor line at every level. */
	private renderElevation(parent: HTMLElement, x: readonly number[], heights: readonly number[]): void {
		const [width, height, margin] = [360, 150, 12];
		const xs = [0, ...x.map((_, i) => x.slice(0, i + 1).reduce((a, b) => a + b, 0))];
		const levels = [0, ...heights.map((_, i) => heights.slice(0, i + 1).reduce((a, b) => a + b, 0))];
		const [lx, lz] = [xs[xs.length - 1], levels[levels.length - 1]];
		const scale = Math.min((width - 2 * margin - 40) / lx, (height - 2 * margin) / lz);
		const ox = (width - lx * scale) / 2;
		const oy = height - margin;
		const svg = this.svg(parent, width, height, localize('newBuilding.elevationAria', "Elevation of the storeys"));
		this.add(svg, 'line', { class: 'ground', x1: ox - 12, y1: oy, x2: ox + lx * scale + 12, y2: oy });
		for (const v of xs) {
			this.add(svg, 'line', { class: 'beam', x1: ox + v * scale, y1: oy, x2: ox + v * scale, y2: oy - lz * scale });
		}
		for (const level of levels.slice(1)) {
			this.add(svg, 'line', { class: 'floor', x1: ox, y1: oy - level * scale, x2: ox + lx * scale, y2: oy - level * scale });
		}
		this.add(svg, 'text', { class: 'dimension', x: ox + lx * scale + 8, y: oy - lz * scale, 'text-anchor': 'start' }, `${(lz / 1000).toFixed(1)} m`);
	}

	// ───────────────────────────── the result ─────────────────────────────

	/** What was made, the actions first, then the sizes; how they were chosen folds out below. */
	private renderResult(name: string, root: string, notes: readonly string[], summary: IGenerateSummary | undefined, parent: string): void {
		const page = this.resetPage();
		const header = append(page, $('header.header'));
		append(header, $('h1', undefined, localize('newBuilding.created', "{0} Is Ready", name)));
		append(header, $('p.subtitle', undefined, localize('newBuilding.createdIn', "Created in {0}. The member sizes are preliminary: check them before the analysis.", root)));
		const result = append(page, $('.result'));
		// What needs the engineer's attention first: drift not met, overlapping footings.
		if (summary?.warnings.length) {
			const box = append(result, $('.warning-box', { role: 'alert' }));
			append(box, $('h2', undefined, localize('newBuilding.warnings', "Check Before the Analysis")));
			const list = append(box, $('ul'));
			for (const warning of summary.warnings) {
				append(list, $('li', undefined, warning));
			}
			if (summary.suggestCoreWalls && this.form.system !== 'rcFrameCore') {
				const coreWalls = this.pageDisposables.add(new Button(box, { ...defaultButtonStyles, secondary: true }));
				coreWalls.label = localize('newBuilding.addCoreWalls', "Add Core Walls and Size Again");
				coreWalls.setTitle(localize('newBuilding.addCoreWallsTitle', "Regenerates this building as a frame with a core in the central bay, in the same folder (the generated part files are replaced)."));
				this.pageDisposables.add(coreWalls.onDidClick(() => void this.regenerateWithCore(name, parent, coreWalls)));
			}
		}
		const actions = append(result, $('.form-actions'));
		if (summary && (summary.counts.length || summary.sizes.length)) {
			append(result, $('h2', undefined, localize('newBuilding.sizes', "Preliminary Sizes")));
			if (summary.counts.length) {
				const counts = summary.counts.map(([label, count]) => `${count} ${label.toLowerCase()}`).join(' · ');
				append(result, $('p.counts', undefined, summary.sdc ? localize('newBuilding.countsSdc', "{0} · seismic design category {1}", counts, summary.sdc) : counts));
			}
			const table = append(result, $('table.sizes'));
			for (const size of summary.sizes) {
				const row = append(table, $('tr'));
				append(row, $('th', { scope: 'row' }, size.what));
				append(row, $('td', undefined, size.size));
				append(row, $('td.why', undefined, size.why ?? ''));
			}
		}
		const details = append(result, $('details.notes'));
		append(details, $('summary', undefined, localize('newBuilding.notes', "How the sizes were chosen ({0} notes)", notes.length)));
		const list = append(details, $('ul.notes'));
		for (const note of notes.length ? notes : [localize('newBuilding.noNotes', "The generator left no notes.")]) {
			append(list, $('li', undefined, note));
		}
		const open = this.pageDisposables.add(new Button(actions, defaultButtonStyles));
		open.label = localize('newBuilding.open', "Open Building");
		this.pageDisposables.add(open.onDidClick(() => this.openBuilding(root, notes)));
		const another = this.pageDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
		another.label = localize('newBuilding.another', "Create Another");
		this.pageDisposables.add(another.onDidClick(() => {
			this.form = { ...this.form, name: '' };
			this.step = 'project';
			this.renderPage();
		}));
		this.focusTarget = open;
		open.focus();
		this.scrollable.scanDomNode();
	}

	/** The building generated again as a frame with a core, over the files of the first one. */
	private async regenerateWithCore(name: string, parent: string, button: Button): Promise<void> {
		const form = { ...this.form, system: 'rcFrameCore' as const };
		const spec = buildSpec(form, value => this.opener.validateName(value));
		if (!spec.ok) {
			return;
		}
		button.enabled = false;
		button.label = localize('newBuilding.addingCoreWalls', "Sizing again with core walls...");
		let outcome: IGenerateOutcome;
		try {
			outcome = readGenerateResult(await this.commandService.executeCommand(GENERATE_BUILDING_COMMAND, { spec: spec.spec, destParent: parent, name, overwrite: true, ...this.siteArgument() }));
		} catch (error) {
			outcome = { notes: [], error: toErrorMessage(error) };
		}
		if (outcome.error || !outcome.root) {
			button.enabled = true;
			button.label = localize('newBuilding.addCoreWalls', "Add Core Walls and Size Again");
			this.notificationService.error(localize('newBuilding.failed', "The building could not be created: {0}", outcome.error ?? ''));
			return;
		}
		this.form = form;
		this.renderResult(name, outcome.root, outcome.notes, outcome.summary, parent);
	}

	/** Opens the new project in this window; its floor plan opens there (see {@link NewBuildingOpener}). */
	private async openBuilding(root: string, notes: readonly string[]): Promise<void> {
		const pending: IPendingBuilding = { root, notes, time: Date.now() };
		this.wizardStorage.store(PENDING_BUILDING_STORAGE_KEY, JSON.stringify(pending), StorageScope.APPLICATION, StorageTarget.MACHINE);
		try {
			await this.opener.open(URI.file(root));
		} catch (error) {
			this.notificationService.error(error);
		}
	}

	private close(): void {
		const input = this.input;
		if (input) {
			void this.editorService.closeEditor({ editor: input, groupId: this.group.id });
		}
	}
}

/** "c:\Users" -> "C:\Users": URIs keep the drive in lower case, the engineer types it in capitals. */
export function driveInCapitals(path: string): string {
	return path.replace(/^([a-z]):/, (_, drive: string) => `${drive.toUpperCase()}:`);
}

/**
 * In the window of a building just generated: opens its floor plan and offers the generator's
 * notes once, then forgets them.
 */
export class NewBuildingOpener extends Disposable {

	constructor(
		@ISaengineProjectService projectService: ISaengineProjectService,
		@IStorageService private readonly storageService: IStorageService,
		@IEditorService private readonly editorService: IEditorService,
		@INotificationService private readonly notificationService: INotificationService,
		@IDialogService private readonly dialogService: IDialogService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super();
		void this.check(projectService.project);
		this._register(projectService.onDidChangeProject(project => this.check(project)));
	}

	private async check(project: ISaengineProject | undefined): Promise<void> {
		const pending = readPendingBuilding(this.storageService.get(PENDING_BUILDING_STORAGE_KEY, StorageScope.APPLICATION));
		if (!project || !pending || !sameFolder(pending.root, project.root.fsPath)) {
			return;
		}
		this.storageService.remove(PENDING_BUILDING_STORAGE_KEY, StorageScope.APPLICATION);
		// U3: the new building opens on its model view, the Overview (N-N1: the parts, their
		// status, what to do next) a tab behind it; the Properties panel shows the next step too.
		await this.editorService.openEditor(ProjectOverviewInput.instance, { pinned: true, inactive: true, preserveFocus: true });
		if (!await this.commandService.executeCommand<boolean>(SHOW_MODEL_VIEW_COMMAND, 'plan')) {
			await this.editorService.openEditor(ProjectOverviewInput.instance, { pinned: true });
		}
		if (pending.notes.length) {
			this.notificationService.prompt(Severity.Info,
				localize('newBuilding.openedNotes', "{0} was generated from the grid with preliminary member sizes ({1} notes).", project.name, pending.notes.length),
				[{ label: localize('newBuilding.showNotes', "Show Notes"), run: () => void this.dialogService.info(localize('newBuilding.notesTitle', "Generator Notes"), pending.notes.join('\n')) }]);
		}
	}
}
