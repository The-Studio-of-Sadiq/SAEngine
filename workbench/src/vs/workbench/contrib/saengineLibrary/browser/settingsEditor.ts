/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action } from '../../../../base/common/actions.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { BNBC, DEFAULT_SETTINGS, SETTINGS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, PROJECT_TYPES, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { humanize, JsonObject, JsonValue, SchemaForm, titleCase } from './schemaForm.js';

const SETTINGS_SCHEMA_ID = 'saengine.projectSettings/1';

function format(value: number): string {
	return `${Number(value.toFixed(3))}`;
}

/** One derived code value: what it is, its value, and where it comes from. */
interface ICodeValue {
	readonly label: string;
	readonly value: string;
	readonly source: string;
	readonly overridden?: boolean;
}

/**
 * The code values the settings imply, from the BNBC 2020 tables (the same tables and rules as
 * `saengine.library.settings.derived`).
 */
export function codeValues(settings: JsonObject): ICodeValue[] {
	const object = (key: string) => (isObject(settings[key]) ? settings[key] : {}) as JsonObject;
	const site = object('site');
	const occupancy = object('occupancy');
	const seismic = object('seismic');
	const wind = object('wind');
	const location = BNBC.locations[String(site.location)];
	const category = BNBC.categories[String(occupancy.category)];
	const system = BNBC.systems[String(seismic.system)];
	const override = (value: JsonValue | undefined) => typeof value === 'number' ? value : undefined;
	const values: ICodeValue[] = [];
	const push = (label: string, value: number | string | undefined, source: string, overridden = false) => {
		values.push({ label, value: value === undefined ? '—' : typeof value === 'number' ? format(value) : value, source, overridden });
	};
	const z = override(site.zoneCoefficient);
	push(localize('code.zone', "Seismic zone"), location ? String(location.zone) : undefined, localize('code.zoneSource', "Seismic zoning map"));
	push(localize('code.z', "Zone coefficient Z"), z ?? (location ? BNBC.zoneCoefficient[String(location.zone)] : undefined), localize('code.zSource', "Table 6.2.14"), z !== undefined);
	const v = override(site.windSpeed);
	push(localize('code.windSpeed', "Basic wind speed V (m/s)"), v ?? location?.windSpeed, localize('code.windSource', "Table 6.2.8"), v !== undefined);
	push(localize('code.seismicImportance', "Seismic importance factor I"), category?.seismicImportance, localize('code.seismicImportanceSource', "Table 6.2.17"));
	push(localize('code.windImportance', "Wind importance factor I"), category?.windImportance, localize('code.windImportanceSource', "Table 6.2.9"));
	for (const [key, label] of [['r', localize('code.r', "Response reduction factor R")], ['omega', localize('code.omega', "Overstrength factor Ω0")], ['cd', localize('code.cd', "Deflection amplification Cd")]] as const) {
		const own = override(seismic[key]);
		push(label, own ?? system?.[key], localize('code.systemSource', "Table 6.2.19"), own !== undefined);
	}
	push(localize('code.siteClass', "Site class"), BNBC.siteClasses[String(site.siteClass)], localize('code.siteClassSource', "Table 6.2.13"));
	push(localize('code.exposure', "Wind exposure"), BNBC.exposures[String(wind.exposure)], localize('code.exposureSource', "6.2.9.3"));
	return values;
}

/** A section of the settings: one page of the form, listed on the left. */
export interface ISettingsSection {
	readonly id: string;
	readonly title: string;
	/** The top-level settings the section edits, in schema order. */
	readonly keys: readonly string[];
}

/** Settings shown in another setting's section: the floor and roof loads pick an area load. */
const SECTION_OF: { readonly [key: string]: string } = {
	floorLoad: 'areaLoads',
	roofLoad: 'areaLoads',
};

/**
 * The sections of the settings form: one per top-level setting of the schema (an object, a
 * list), in schema order; plain values join the section named in {@link SECTION_OF}.
 */
export function settingsSections(schema: IJSONSchema): ISettingsSection[] {
	const sections: { id: string; title: string; keys: string[] }[] = [];
	for (const [key, property] of Object.entries(schema.properties ?? {})) {
		if (property.const !== undefined) {
			continue;
		}
		const owner = SECTION_OF[key];
		if (owner) {
			sections.find(s => s.id === owner)?.keys.push(key);
			continue;
		}
		const ref = property.$ref?.startsWith('#/$defs/') ? schema.$defs?.[property.$ref.slice('#/$defs/'.length)] : undefined;
		sections.push({ id: key, title: titleCase(property.title ?? ref?.title ?? humanize(key)), keys: [key] });
	}
	return sections;
}

const SECTIONS = settingsSections(SETTINGS_SCHEMA);

/**
 * The project settings (`02 Project Settings/project-settings.json`): codes, occupancy, site and
 * loads. Part 2 is upstream of the floor plan, the building model and the analysis, which read
 * these settings.
 *
 * In the shared editor frame: the project type in the toolbar, the sections listed on the left,
 * the selected section's form in the middle, and the code values the settings imply (BNBC
 * tables, refreshed as fields are typed) in the properties panel.
 */
export class SettingsEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.SETTINGS_EDITOR_ID;

	private nav!: HTMLElement;
	private page!: HTMLElement;
	private typeSelect: SelectBox | undefined;
	private typeSlot: HTMLElement | undefined;
	private typeHover: { update(content: string): void } | undefined;
	private sectionId = SECTIONS[0]?.id;
	private problemBox: HTMLElement | undefined;
	private readonly form: SchemaForm;

	private readonly navDisposables = this._register(new DisposableStore());
	private readonly valuesDisposables = this._register(new DisposableStore());
	private readonly resetAction = this._register(Object.assign(
		new Action('saengine.settings.resetCombinations', localize('settings.resetCombinationsEllipsis', "Reset Combinations to {0}...", BNBC.edition), undefined, true, () => this.resetCombinations()),
		{ tooltip: localize('settings.resetTitle', "Replace the load combinations with the {0} strength design combinations", BNBC.edition) },
	));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService commandService: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService private readonly project: ISaengineProjectService,
		@IDialogService private readonly dialogService: IDialogService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IHoverService private readonly hoverService: IHoverService,
		@IConfigurationService configurationService: IConfigurationService,
	) {
		super(SettingsEditor.ID, group, telemetryService, themeService, storageService, commandService, editorService, textModelService, project);
		this.trackDeveloperMode(configurationService);
		this.form = instantiationService.createInstance(SchemaForm, {
			root: SETTINGS_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			references: path => this.references(path),
			validate: (path, value) => this.validate(path, value),
			changed: (path, structural) => this.onChanged(path, structural),
			mode: () => undefined,
			newItem: (path, list) => this.newItem(path, list),
		});
		this._register({ dispose: () => this.form.dispose() });
	}

	protected override createDocumentFrame(parent: HTMLElement): EditorFrame {
		return this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: SettingsEditor.ID,
			ariaLabel: localize('settings.toolbar', "Project Settings"),
			properties: { title: localize('settings.codeValues', "Code Values"), defaultWidth: 320 },
		}));
	}

	protected createBody(body: HTMLElement): void {
		const frame = this.documentFrame!;
		frame.element.classList.add('saengine-settings-editor');
		frame.setTitle(localize('settings.title', "Project Settings"));
		frame.setHelp(localize('settings.intro', "Codes, occupancy, site and loads of the project. {0} is the governing code: its tables give the code values in the panel on the right, and every one can be overridden. The floor plan, the building model and the analysis read these settings.", BNBC.edition));
		this.createProjectType(frame);

		body.classList.add('sa-sections');
		this.nav = append(body, $('.sa-section-list', { role: 'listbox', tabIndex: 0, 'aria-label': localize('settings.sections', "Sections") }));
		this.page = append(body, $('.sa-form-page'));
		this._register(addDisposableListener(this.nav, EventType.KEY_DOWN, e => this.onNavKey(new StandardKeyboardEvent(e))));
	}

	/**
	 * What the project designs (Building / Special Structure), which decides how Part 5 models it;
	 * kept in the project manifest. A selector in the toolbar, its description in the hover.
	 */
	private createProjectType(frame: EditorFrame): void {
		const slot = this.typeSlot = append(frame.controlsSlot, $('.settings-project-type'));
		append(slot, $('span.sa-frame-label', undefined, localize('settings.projectType', "Project type")));
		const select = this.typeSelect = this._register(new SelectBox(PROJECT_TYPES.map(t => ({ text: t.label, description: t.description })), 0, this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: localize('settings.projectType', "Project type"),
		}));
		const box = append(slot, $('.settings-project-type-select'));
		select.render(box);
		this.typeHover = this._register(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), box, ''));
		this._register(select.onDidSelect(e => void this.changeProjectType(PROJECT_TYPES[e.index].type)));
	}

	protected override documentFrameActions(): IDocumentFrameActions {
		return {
			primary: this.document && this.documentFrame ? [this.documentFrame.togglePropertiesAction] : [],
			secondary: this.document ? [this.resetAction] : [],
		};
	}

	protected shapeError(value: JsonObject): IShapeError | undefined {
		if (value.schema === SETTINGS_SCHEMA_ID) {
			return undefined;
		}
		if (value.part === 'settings') {
			// The placeholder of projects created before Part 2 existed.
			return {
				message: localize('settings.empty', "This project has no settings yet."),
				fix: {
					label: localize('settings.create', "Create Project Settings"),
					run: () => this.replaceDocument({ ...clone(DEFAULT_SETTINGS as JsonObject), project: { name: this.project.project?.name ?? 'Project' } }),
				},
			};
		}
		return { message: localize('settings.unexpected', "This file is not SAEngine project settings ({0}).", SETTINGS_SCHEMA_ID) };
	}

	// ───────────────────────────── form rules ─────────────────────────────

	private get areaLoads(): JsonObject[] {
		const list = this.document?.areaLoads;
		return Array.isArray(list) ? list.filter(isObject) : [];
	}

	/** The floor and roof loads are picked from the area loads. */
	private references(path: string): readonly string[] | undefined {
		return path === 'floorLoad' || path === 'roofLoad' ? this.areaLoads.map(a => String(a.id)) : undefined;
	}

	private validate(path: string, value: string): string | undefined {
		const match = /^areaLoads\.(?<index>\d+)\.id$/.exec(path);
		if (match) {
			const own = this.areaLoads[Number(match.groups!.index)];
			if (this.areaLoads.some(a => a !== own && a.id === value)) {
				return localize('settings.duplicateLoad', "Another area load already uses the id {0}.", value);
			}
		}
		return undefined;
	}

	/** Choosing an area's use sets its live load to the code minimum for that use. */
	private onChanged(path: string, structural: boolean): void {
		const match = /^areaLoads\.(?<index>\d+)\.use$/.exec(path);
		const load = match ? this.areaLoads[Number(match.groups!.index)] : undefined;
		const use = load ? BNBC.areaUses[String(load.use)] : undefined;
		if (load && use) {
			load.live = use.live;
			this.changed(true);
			return;
		}
		this.changed(structural);
		if (!structural) {
			this.renderValues();
		}
	}

	private newItem(path: string, list: readonly JsonValue[]): JsonObject | undefined {
		if (path !== 'areaLoads') {
			return undefined;
		}
		const used = new Set(list.filter(isObject).map(a => String(a.id)));
		let n = 1;
		while (used.has(`AL${n}`)) {
			n++;
		}
		return { ...clone(TEMPLATES.AreaLoad as JsonObject), id: `AL${n}` };
	}

	/** Replaces every load combination with the code's, after asking (it can also be undone). */
	private async resetCombinations(): Promise<void> {
		if (!this.document) {
			return;
		}
		const current = Array.isArray(this.document.combinations) ? this.document.combinations.length : 0;
		const { confirmed } = await this.dialogService.confirm({
			message: localize('settings.resetConfirm', "Replace the load combinations with the {0} combinations?", BNBC.edition),
			detail: current === 1
				? localize('settings.resetDetailOne', "The 1 load combination of this project is replaced by the {0} strength design combinations. Edit > Undo brings it back.", BNBC.edition)
				: localize('settings.resetDetail', "All {0} load combinations of this project are replaced by the {1} strength design combinations. Edit > Undo brings them back.", current, BNBC.edition),
			primaryButton: localize('settings.resetButton', "&&Replace Combinations"),
		});
		const document = this.document;
		if (confirmed && document) {
			document.combinations = clone((DEFAULT_SETTINGS as JsonObject).combinations as JsonValue);
			this.sectionId = 'combinations';
			this.changed(true);
		}
	}

	private async changeProjectType(type: ProjectType): Promise<void> {
		if (this.project.project?.type === type) {
			return;
		}
		const label = PROJECT_TYPES.find(t => t.type === type)!.label;
		const { confirmed } = await this.dialogService.confirm({
			message: localize('settings.changeType', "Make this project a {0}?", label),
			detail: type === 'structure'
				? localize('settings.toStructure', "Part 5 becomes the Structural Model (05 Structural Model/structure.json), drawn in 3D. The Floor Plan folder stays with its files but is no longer used. Rebuild the Building Model from the Structural Model afterwards.")
				: localize('settings.toBuilding', "Part 5 becomes the Floor Plan (05 Floor Plan/floor-plan.json), story by story. The Structural Model folder stays with its files but is no longer used. Rebuild the Building Model from the Floor Plan afterwards."),
			primaryButton: localize('settings.changeTypeButton', "&&Change Project Type"),
		});
		if (confirmed) {
			await this.project.setProjectType(type);
		}
		this.renderProjectType();
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private get section(): ISettingsSection | undefined {
		return SECTIONS.find(s => s.id === this.sectionId) ?? SECTIONS[0];
	}

	protected render(): void {
		this.problemBox = undefined;
		this.renderProjectType();
		this.renderNav();
		this.renderPage();
		this.renderValues();
		this.renderStatus();
	}

	/** The toolbar's project type follows the manifest (shown only for a project). */
	private renderProjectType(): void {
		const current = this.project.project?.type;
		this.typeSlot?.classList.toggle('hidden', !current || !this.document);
		const index = PROJECT_TYPES.findIndex(t => t.type === current);
		if (index >= 0) {
			this.typeSelect?.select(index);
			this.typeHover?.update(PROJECT_TYPES[index].description);
		}
	}

	private renderNav(): void {
		this.navDisposables.clear();
		clearNode(this.nav);
		if (!this.document) {
			return;
		}
		const current = this.section;
		for (const section of SECTIONS) {
			const selected = section === current;
			const row = append(this.nav, $('.sa-section-item', { role: 'option', 'aria-selected': String(selected), id: `settings-section-${section.id}` }));
			row.classList.toggle('selected', selected);
			append(row, $('span.sa-section-title', undefined, section.title));
			const problems = this.problemsIn(section);
			if (problems.length) {
				const icon = append(row, $(`span.sa-section-warning${ThemeIcon.asCSSSelector(Codicon.warning)}`));
				this.navDisposables.add(this.hoverService.setupDelayedHover(icon, { content: problems.map(p => p.message).join('\n') }));
			}
			this.navDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.selectSection(section.id)));
		}
		if (current) {
			this.nav.setAttribute('aria-activedescendant', `settings-section-${current.id}`);
		}
	}

	private renderPage(): void {
		clearNode(this.page);
		const section = this.section;
		if (!this.document || !section) {
			return;
		}
		append(this.page, $('.sa-form-page-title', undefined, section.title));
		this.problemBox = append(this.page, $('.library-problems'));
		this.renderSectionProblems();
		const skip = Object.keys(SETTINGS_SCHEMA.properties ?? {}).filter(key => !section.keys.includes(key));
		this.form.render(append(this.page, $('.library-form')), SETTINGS_SCHEMA, this.document, skip, { flat: true });
	}

	private selectSection(id: string): void {
		if (id === this.sectionId && this.page.childElementCount) {
			return;
		}
		this.flush();
		this.sectionId = id;
		this.renderNav();
		this.renderPage();
		this.page.scrollTop = 0;
		this.nav.focus();
	}

	private onNavKey(e: StandardKeyboardEvent): void {
		const index = SECTIONS.indexOf(this.section!);
		const next = e.keyCode === KeyCode.DownArrow ? SECTIONS[index + 1] : e.keyCode === KeyCode.UpArrow ? SECTIONS[index - 1]
			: e.keyCode === KeyCode.Home ? SECTIONS[0] : e.keyCode === KeyCode.End ? SECTIONS[SECTIONS.length - 1] : undefined;
		if (next) {
			e.preventDefault();
			this.selectSection(next.id);
		}
	}

	/** Problems whose field lies in `section` (or, for the first section, the file's own). */
	private problemsIn(section: ISettingsSection) {
		return this.problems.filter(p => {
			const key = p.path.split('.')[0];
			return section.keys.includes(key) || (!key && section === SECTIONS[0]);
		});
	}

	/** Code values derived from the settings, in the properties panel; refreshed as fields are typed. */
	private renderValues(): void {
		const panel = this.documentFrame?.properties;
		if (!panel) {
			return;
		}
		this.valuesDisposables.clear();
		clearNode(panel);
		if (!this.document) {
			return;
		}
		const table = append(panel, $('.settings-values', { role: 'table', 'aria-label': localize('settings.codeValues', "Code Values") }));
		for (const value of codeValues(this.document)) {
			const row = append(table, $('.sa-props-row', { role: 'row' }));
			append(row, $('span.name', { role: 'cell' }, value.label));
			const cell = append(row, $('span.value', { role: 'cell' }, value.value));
			if (value.overridden) {
				row.classList.add('overridden');
			}
			// Where the value comes from, on hover: the table, or that it was overridden.
			const source = value.overridden ? localize('settings.overriddenSource', "Overridden in the settings ({0} gives it in {1}).", BNBC.edition, value.source) : localize('settings.source', "{0}, {1}", BNBC.edition, value.source);
			this.valuesDisposables.add(this.hoverService.setupDelayedHover(row, { content: source }));
			if (value.overridden) {
				append(cell, $('span.settings-overridden', { 'aria-label': localize('settings.overridden', "overridden") }, '*'));
			}
		}
		append(panel, $('.sa-props-note', undefined, localize('settings.valuesNote', "From the {0} tables for the site, occupancy and structural system. * overridden in the settings. Hover a value for its source.", BNBC.edition)));
	}

	protected renderProblems(): void {
		this.renderSectionProblems();
		this.renderNav();
		this.renderValues();
		this.renderStatus();
	}

	/** The selected section's problems, quietly above its form (without rebuilding it). */
	private renderSectionProblems(): void {
		const box = this.problemBox;
		const section = this.section;
		if (!box || !section) {
			return;
		}
		clearNode(box);
		const problems = this.problemsIn(section);
		box.classList.toggle('visible', problems.length > 0);
		for (const problem of problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			const field = problem.path ? `${problem.path.split('.').filter(p => !/^\d+$/.test(p)).map(humanize).join(' › ')}: ` : '';
			append(row, $('span', undefined, `${field}${problem.message}`));
		}
	}

	/** The status line: problems when there are any, otherwise what the settings are for. */
	private renderStatus(): void {
		const frame = this.documentFrame;
		if (!frame || !this.document) {
			return;
		}
		if (this.problems.length) {
			const first = this.problems[0];
			const section = SECTIONS.find(s => this.problemsIn(s).includes(first));
			frame.setStatus({
				severity: 'warning',
				text: this.problems.length === 1
					? localize('settings.oneProblem', "1 problem: {0}", first.message)
					: localize('settings.problems', "{0} problems. {1}", this.problems.length, first.message),
				link: section && section !== this.section ? { label: localize('settings.showProblem', "Show"), run: () => this.selectSection(section.id) } : undefined,
			});
			return;
		}
		frame.setStatus({ text: localize('settings.status', "{0} governs; every code value can be overridden. Read by the floor plan, the building model and the analysis.", BNBC.edition) });
	}
}
