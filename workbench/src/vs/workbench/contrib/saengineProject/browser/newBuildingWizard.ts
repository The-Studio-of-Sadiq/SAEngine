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
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
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
import { BNBC, DEFAULT_MATERIALS, SETTINGS_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import {
	BLANK_FORM, buildSpec, centralBay, fitSpacings, folderError, FOOTING_CHOICES, FormField, formatLengths, formatSummary, formFromSpec, GENERATE_BUILDING_COMMAND, IGenerateOutcome, IGenerateSummary, INewBuildingForm, IPendingBuilding, IWizardPlot, OccupancyCategory,
	parseSpacings, PENDING_BUILDING_STORAGE_KEY, plotFitWarning, readGenerateResult, readPendingBuilding, SiteClass, storyHeights, summarize, SYSTEM_CHOICES,
} from './newBuildingModel.js';
import { ISoilLocationRequest, ISoilLocationResult, SOIL_LOCATION_COMMAND } from '../../saengineSoil/browser/soilDocument.js';
import { ProjectOverviewInput } from './projectOverviewInput.js';
import { ProjectOpener } from './projectOpener.js';
import { plannedCodePacks } from '../../saengineLibrary/common/plannedCodePacks.js';
import { appendPlannedFeatureChip } from './plannedFeatureEditor.js';
import { CODES_TEMPLATES_COMMAND, DEFAULT_BUILDING_TEMPLATE, IBuildingTemplate, NEW_FROM_TEMPLATE_COMMAND, readBuildingTemplates } from '../../saengineLibrary/common/packageTemplates.js';
import { sameFolder } from './structuralImportModel.js';

const SVG = 'http://www.w3.org/2000/svg';

/** Application storage: the folder the last building was created in, offered next time. */
const LAST_FOLDER_STORAGE_KEY = 'saengine.newBuilding.lastFolder';

const wizardIcon = registerIcon('saengine-new-building-icon', Codicon.symbolStructure, localize('newBuildingIcon', "Icon of the New Building wizard."));

/** The New Building wizard: one page, opened from the start page and ≡ File. */
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
		return localize('newBuilding.tab', "New Building");
	}

	override getIcon(): ThemeIcon {
		return wizardIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof NewBuildingWizardInput;
	}
}

interface IChoice<T extends string> {
	readonly value: T;
	readonly label: string;
	/** Shown but not choosable (a planned option). */
	readonly disabled?: boolean;
}

/**
 * The design code: BNBC 2020, and the code packs planned after it, shown disabled and marked
 * "Planned" (their pages are on the Packages page and under the chips below the selector).
 */
function designCodeChoices(): IChoice<string>[] {
	return [
		{ value: 'bnbc', label: localize('newBuilding.codeBnbc', "BNBC 2020") },
		...plannedCodePacks().map(pack => ({ value: pack.feature, label: localize('newBuilding.codePlanned', "{0} (Planned)", pack.name), disabled: true })),
	];
}

/** Materials of a category from the default materials (`03 Materials`), as choices. */
function materialChoices(category: string): IChoice<string>[] {
	const materials = (DEFAULT_MATERIALS as { readonly materials?: readonly { readonly id: string; readonly name: string; readonly category: string }[] }).materials ?? [];
	return materials.filter(m => m.category === category).map(m => ({ value: m.id, label: m.name }));
}

/** The BNBC district towns of the project settings (Site > Location), without "Custom". */
function locationChoices(): IChoice<string>[] {
	return Object.entries(BNBC.locations).map(([id, location]) => ({ value: id, label: localize('location.choice', "{0} (zone {1}, {2} m/s)", location.name, location.zone, location.windSpeed) }));
}

type SchemaEnum = { readonly enum?: readonly string[]; readonly enumDescriptions?: readonly string[] };

/** An enum of the project settings schema's `$defs`, as choices. */
function settingsEnum(def: string, property: string): IChoice<string>[] {
	const defs = (SETTINGS_SCHEMA as { readonly $defs?: { readonly [name: string]: { readonly properties?: { readonly [name: string]: SchemaEnum } } } }).$defs;
	const schema = defs?.[def]?.properties?.[property];
	return (schema?.enum ?? []).map((value, i) => ({ value, label: schema?.enumDescriptions?.[i] ?? value }));
}

/**
 * The New Building wizard (one page): the project's name and folder, the grids as spacings with
 * a live plan and elevation, the storeys, the structural system, the materials, the footings,
 * the location and the occupancy. Create asks the generator (`saengine.library.generateBuilding`)
 * for the project and its floor plan, shows its notes and opens it.
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
	/** The package of the specification that filled the form last; undefined before any. */
	private templateApplied: string | undefined;

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
		await this.loadTemplates();
		if (!this.templateApplied) {
			const start = this.templates.find(t => t.type === 'spec' && t.package === DEFAULT_BUILDING_TEMPLATE) ?? this.templates.find(t => t.type === 'spec');
			if (start?.spec) {
				this.form = { ...formFromSpec(start.spec, this.form) };
				this.templateApplied = start.package;
			}
		}
		this.renderForm();
		// The plot needs the backend (a second or two): the form shows at once, then again with it.
		const plot = await this.loadPlot();
		if (plot && this.input === input && !token.isCancellationRequested) {
			this.plot = plot;
			this.renderForm();
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

	/** "Start from": the specifications fill the form; a full template opens as a new project. */
	private renderTemplates(form: HTMLElement): void {
		const control = this.row(form, localize('newBuilding.template', "Start from"));
		const specs = this.templates.filter(t => t.type === 'spec');
		const archives = this.templates.filter(t => t.type === 'archive');
		const label = (t: IBuildingTemplate) => t.packageName === t.name || !t.packageName ? t.name : localize('newBuilding.templateIn', "{0} ({1})", t.name, t.packageName);
		const options = [
			...specs.map(t => ({ text: label(t), description: t.description })),
			...archives.map(t => ({ text: localize('newBuilding.templateFull', "{0}: full project...", label(t)), description: t.description })),
		];
		if (!options.length) {
			append(control, $('span.hint', undefined, localize('newBuilding.noTemplates', "No building templates installed.")));
			return;
		}
		const index = Math.max(0, specs.findIndex(t => t.package === this.templateApplied));
		const box = this.pageDisposables.add(new SelectBox(options, index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('newBuilding.template', "Start from") }));
		box.render(control);
		this.pageDisposables.add(box.onDidSelect(({ index: picked }) => {
			const spec = specs[picked];
			if (spec?.spec) {
				this.form = { ...formFromSpec(spec.spec, this.form) };
				this.templateApplied = spec.package;
				this.renderForm();
				return;
			}
			const archive = archives[picked - specs.length];
			if (archive?.path) {
				box.select(index);
				void this.commandService.executeCommand(NEW_FROM_TEMPLATE_COMMAND, { path: archive.path, author: archive.author, name: this.form.name.trim() || undefined });
			}
		}));
	}

	/** Whether the backend can generate a building in this build. */
	private get available(): boolean {
		return !!CommandsRegistry.getCommand(GENERATE_BUILDING_COMMAND);
	}

	private resetPage(): HTMLElement {
		this.pageDisposables.clear();
		clearNode(this.container);
		this.scrollable.setScrollPosition({ scrollTop: 0 });
		return append(this.container, $('.page'));
	}

	// ───────────────────────────── the form ─────────────────────────────

	private renderForm(): void {
		const page = this.resetPage();
		const header = append(page, $('header.header'));
		append(header, $('h1', undefined, localize('newBuilding.title', "New Building from Grid")));
		append(header, $('p.subtitle', undefined, localize('newBuilding.subtitle', "Columns, beams, walls, slabs and footings on every storey in one step, with preliminary sizes. Edit them afterwards in the floor plan.")));
		// Building templates are installed on the Packages page; the wizard only links to it.
		const more = append(header, $('a.packages-link', { href: '#', role: 'button' }, localize('newBuilding.moreTemplates', "Get more building templates...")));
		this.pageDisposables.add(addDisposableListener(more, EventType.CLICK, e => {
			e.preventDefault();
			void this.commandService.executeCommand('saengine.packages.show', { tab: 'browse', kind: 'buildingTemplate' });
		}));
		if (!this.available) {
			const note = append(page, $('.unavailable', { role: 'status' }));
			append(note, $(`span${ThemeIcon.asCSSSelector(Codicon.info)}`));
			append(note, $('span', undefined, localize('newBuilding.unavailable', "Generating a building is not available in this build yet. You can fill in the form; Create is enabled once the generator is installed.")));
		}

		const body = append(page, $('.body'));
		const form = append(body, $('.form'));
		const side = append(body, $('aside.preview', { 'aria-label': localize('newBuilding.previewAria', "Preview") }));
		const planHost = append(side, $('.preview-plan'));
		const elevationHost = append(side, $('.preview-elevation'));
		const summary = append(side, $('p.summary'));
		const systemHint = append(side, $('p.hint'));

		// Create stays off while the form or the folder is not valid.
		const created: { button?: Button } = {};
		const updateCreate = () => {
			if (created.button) {
				created.button.enabled = this.available && !this.busy && buildSpec(this.form, value => this.opener.validateName(value)).ok && !folderError(this.folder, isWindows);
			}
		};
		const inputs = new Map<FormField, InputBox>();
		const errors = new Map<FormField, HTMLElement>();
		const plotWarning: { element?: HTMLElement } = {};
		const updatePreview = () => {
			const x = parseSpacings(this.form.gridX);
			const y = parseSpacings(this.form.gridY);
			const heights = storyHeights(this.form);
			clearNode(planHost);
			clearNode(elevationHost);
			if (x.ok && y.ok) {
				this.renderPlan(planHost, x.values, y.values);
			}
			if (x.ok && heights.ok) {
				this.renderElevation(elevationHost, x.values, heights.values);
			}
			summary.textContent = x.ok && y.ok && heights.ok ? formatSummary(summarize(x.values, y.values, heights.values)) : localize('newBuilding.previewWaiting', "The preview shows once the grids and storeys read correctly.");
			systemHint.textContent = SYSTEM_CHOICES.find(s => s.value === this.form.system)?.description ?? '';
			if (plotWarning.element) {
				plotWarning.element.textContent = this.plot && x.ok && y.ok ? plotFitWarning(x.values, y.values, this.plot) ?? '' : '';
			}
			for (const [field, message] of [['gridX', x], ['gridY', y], ['stories', heights]] as const) {
				const element = errors.get(field);
				if (element) {
					element.textContent = message.ok ? '' : message.error;
				}
			}
			this.scrollable.scanDomNode();
			updateCreate();
		};

		// ── project ──
		this.section(form, localize('newBuilding.project', "Project"));
		this.renderTemplates(form);
		const name = this.textInput(form, localize('newBuilding.name', "Name"), this.form.name, value => this.form.name = value, localize('newBuilding.namePlaceholder', "e.g. Office Building"), text => this.opener.validateName(text));
		inputs.set('name', name);
		this.pageDisposables.add(name.onDidChange(() => name.validate()));
		const folderRow = this.row(form, localize('newBuilding.folder', "Folder"));
		const location = this.pageDisposables.add(new InputBox(folderRow, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: localize('newBuilding.folder', "Folder") }));
		location.value = this.folder;
		this.pageDisposables.add(location.onDidChange(value => this.folder = value));
		const browse = this.pageDisposables.add(new Button(folderRow, { ...defaultButtonStyles, secondary: true }));
		browse.label = localize('newBuilding.browse', "Browse...");
		this.pageDisposables.add(browse.onDidClick(async () => {
			const picked = await this.opener.browseForLocation(URI.file(location.value), localize('newBuilding.folderTitle', "Choose Where to Create the Building"));
			if (picked) {
				location.value = picked.fsPath;
			}
		}));
		const folderMessage = append(form, $('p.error', { 'aria-live': 'polite' }));
		const target = append(form, $('p.target'));
		const project = this.projectService.project;
		if (project) {
			append(form, $('p.hint.indented', undefined, localize('newBuilding.separate', "The building is a new project: {0}, open now, is not changed.", project.name)));
		}
		const updateTarget = () => {
			const error = folderError(this.folder, isWindows);
			folderMessage.textContent = error ?? '';
			target.textContent = !error && this.form.name.trim() && !this.opener.validateName(this.form.name)
				? localize('newBuilding.target', "Created in {0}", joinPath(URI.file(this.folder.trim()), this.form.name.trim()).fsPath) : '';
			updateCreate();
		};
		this.pageDisposables.add(name.onDidChange(updateTarget));
		this.pageDisposables.add(location.onDidChange(updateTarget));

		// ── grids ──
		this.section(form, localize('newBuilding.grids', "Grids"), localize('newBuilding.gridsHint', "Spacings in mm, left to right and bottom to top: \"3×6000, 4500\" is three 6 m bays and one of 4.5 m. m and ft work too (6m, 20ft)."));
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
				const x = parseSpacings(this.form.gridX);
				const y = parseSpacings(this.form.gridY);
				const fx = x.ok ? fitSpacings(x.values, plot.width) : undefined;
				const fy = y.ok ? fitSpacings(y.values, plot.depth) : undefined;
				if (!fx || !fy) {
					fitStatus.textContent = localize('newBuilding.fitFailed', "The buildable area is too small for this many bays (at least 1 m each): use fewer bays.");
					return;
				}
				fitStatus.textContent = '';
				for (const [field, values] of [['gridX', fx], ['gridY', fy]] as const) {
					this.form[field] = formatLengths(values);
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
		small(localize('newBuilding.groundUnit', "ground, mm"), 'groundHeight', localize('newBuilding.groundAria', "Ground storey height in mm"));
		small(localize('newBuilding.typicalUnit', "typical, mm"), 'typicalHeight', localize('newBuilding.typicalAria', "Typical storey height in mm"));
		const heights = this.textInput(form, localize('newBuilding.heights', "Or every storey"), this.form.heights, value => {
			this.form.heights = value;
			updatePreview();
		}, localize('newBuilding.heightsPlaceholder', "e.g. 4000, 9×3200 (overrides the number)"));
		inputs.set('stories', heights);
		errors.set('stories', append(form, $('p.error', { 'aria-live': 'polite' })));

		// ── structure ──
		this.section(form, localize('newBuilding.structure', "Structure"));
		this.choices(form, localize('newBuilding.system', "System"), SYSTEM_CHOICES, this.form.system, value => {
			this.form.system = value;
			updatePreview();
		});
		this.select(form, localize('newBuilding.concrete', "Concrete"), materialChoices('concrete'), this.form.concrete, value => this.form.concrete = value);
		this.select(form, localize('newBuilding.rebar', "Reinforcement"), materialChoices('rebar'), this.form.rebar, value => this.form.rebar = value);
		this.select(form, localize('newBuilding.footing', "Footings"), FOOTING_CHOICES, this.form.footing, value => this.form.footing = value);

		// ── site and use ──
		this.section(form, localize('newBuilding.site', "Site and Use"), localize('newBuilding.siteHint', "BNBC 2020: the location sets the seismic zone and basic wind speed; the occupancy category the importance factors (Table 6.1.1)."));
		// Only BNBC 2020 in this MVP; the other code packs show as planned.
		this.select(form, localize('newBuilding.designCode', "Design code"), designCodeChoices(), 'bnbc', () => { /* BNBC 2020 is the only choice */ });
		const plannedCodes = append(form, $('p.hint.indented.planned-codes'));
		for (const pack of plannedCodePacks()) {
			this.pageDisposables.add(appendPlannedFeatureChip(plannedCodes, pack.feature, this.commandService));
		}
		this.select(form, localize('newBuilding.location', "Location"), locationChoices(), this.form.location, value => this.form.location = value);
		this.select(form, localize('newBuilding.siteClass', "Site class"), settingsEnum('Site', 'siteClass'), this.form.siteClass, value => this.form.siteClass = value as SiteClass);
		append(form, $('p.hint.indented', undefined, localize('newBuilding.siteClassHint', "Assumed until a soil report gives it (BNBC 2020 Part 6, Table 6.2.13): add boreholes in 01 Soil Report and their class replaces it.")));
		this.select(form, localize('newBuilding.use', "Building use"), settingsEnum('Occupancy', 'use'), this.form.use, value => this.form.use = value);
		this.select(form, localize('newBuilding.category', "Occupancy category"), settingsEnum('Occupancy', 'category'), this.form.category, value => this.form.category = value as OccupancyCategory);

		// ── actions ──
		const actions = append(form, $('.form-actions'));
		const create = created.button = this.pageDisposables.add(new Button(actions, defaultButtonStyles));
		create.label = localize('newBuilding.create', "Create Building");
		const cancel = this.pageDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true }));
		cancel.label = localize('newBuilding.cancel', "Cancel");
		this.pageDisposables.add(cancel.onDidClick(() => this.close()));
		const status = append(actions, $('span.status', { 'aria-live': 'polite' }));

		const submit = async () => {
			if (this.busy || !this.available) {
				return;
			}
			const result = buildSpec(this.form, value => this.opener.validateName(value));
			if (!result.ok) {
				name.validate();
				const first = (['name', 'gridX', 'gridY', 'stories'] as const).find(f => result.errors[f]);
				if (first) {
					inputs.get(first)?.focus();
				}
				return;
			}
			if (folderError(this.folder, isWindows)) {
				updateTarget();
				location.focus();
				return;
			}
			this.busy = true;
			updateCreate();
			status.textContent = localize('newBuilding.creating', "Creating the building...");
			let outcome: IGenerateOutcome;
			const parent = this.folder.trim();
			try {
				const missing = await this.prepareFolder(parent);
				outcome = missing
					? { notes: [], error: missing }
					: readGenerateResult(await this.commandService.executeCommand(GENERATE_BUILDING_COMMAND, { spec: result.spec, destParent: parent, name: result.spec.name, ...(this.plot ? { site: this.plot.site } : {}) }));
			} catch (error) {
				outcome = { notes: [], error: toErrorMessage(error) };
			} finally {
				this.busy = false;
			}
			if (outcome.error || !outcome.root) {
				updateCreate();
				status.textContent = '';
				this.notificationService.error(localize('newBuilding.failed', "The building could not be created: {0}", outcome.error ?? ''));
				return;
			}
			this.wizardStorage.store(LAST_FOLDER_STORAGE_KEY, parent, StorageScope.APPLICATION, StorageTarget.MACHINE);
			this.renderResult(result.spec.name, outcome.root, outcome.notes, outcome.summary, parent);
		};
		this.pageDisposables.add(create.onDidClick(() => void submit()));
		this.pageDisposables.add(addDisposableListener(form, EventType.KEY_DOWN, e => {
			// Enter in a field creates the building only when Create could (the form is valid).
			if (e.key === 'Enter' && !isHTMLButtonElement(e.target) && create.enabled) {
				void submit();
			} else if (e.key === 'Escape') {
				this.close();
			}
		}));

		updatePreview();
		updateTarget();
		this.focusTarget = name;
		name.focus();
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

	private select<T extends string>(parent: HTMLElement, label: string, options: readonly IChoice<T>[], initial: T, onChange: (value: T) => void): void {
		const control = this.row(parent, label);
		const index = Math.max(0, options.findIndex(o => o.value === initial));
		const box = this.pageDisposables.add(new SelectBox(options.map(o => ({ text: o.label, isDisabled: o.disabled })), index, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: label }));
		box.render(control);
		if (options[index] && options[index].value !== initial) {
			onChange(options[index].value);
		}
		this.pageDisposables.add(box.onDidSelect(({ index: picked }) => onChange(options[picked].value)));
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
			this.renderForm();
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
			outcome = readGenerateResult(await this.commandService.executeCommand(GENERATE_BUILDING_COMMAND, { spec: spec.spec, destParent: parent, name, overwrite: true, ...(this.plot ? { site: this.plot.site } : {}) }));
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
		// N-N1: the new building opens on its Overview (the parts, their status, what to do next).
		await this.editorService.openEditor(ProjectOverviewInput.instance, { pinned: true });
		if (pending.notes.length) {
			this.notificationService.prompt(Severity.Info,
				localize('newBuilding.openedNotes', "{0} was generated from the grid with preliminary member sizes ({1} notes).", project.name, pending.notes.length),
				[{ label: localize('newBuilding.showNotes', "Show Notes"), run: () => void this.dialogService.info(localize('newBuilding.notesTitle', "Generator Notes"), pending.notes.join('\n')) }]);
		}
	}
}
