/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { BNBC, DEFAULT_SETTINGS, SETTINGS_SCHEMA, TEMPLATES } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, PROJECT_TYPES, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { clone, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { JsonObject, JsonValue, SchemaForm } from './schemaForm.js';

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

/**
 * The project settings (`02 Project Settings/project-settings.json`): codes, occupancy, site and
 * loads. Part 2 is upstream of the floor plan, the building model and the analysis, which read
 * these settings. The form edits the file; the panel above it shows the code values they imply.
 */
export class SettingsEditor extends JsonDocumentEditor {

	static readonly ID = LibraryEditorInput.SETTINGS_EDITOR_ID;

	private container!: HTMLElement;
	private problemBox: HTMLElement | undefined;
	private values: HTMLElement | undefined;
	private readonly form: SchemaForm;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@ICommandService commandService: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService textModelService: ITextModelService,
		@ISaengineProjectService private readonly project: ISaengineProjectService,
		@IDialogService private readonly dialogService: IDialogService,
	) {
		super(SettingsEditor.ID, group, telemetryService, themeService, storageService, commandService, editorService, textModelService, project);
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

	protected createBody(body: HTMLElement): void {
		this.container = append(body, $('.building-editor.settings-editor'));
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

	private resetCombinations(): void {
		const document = this.document;
		if (document) {
			document.combinations = clone((DEFAULT_SETTINGS as JsonObject).combinations as JsonValue);
			this.changed(true);
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	protected render(): void {
		this.viewDisposables.clear();
		clearNode(this.container);
		this.problemBox = undefined;
		this.values = undefined;
		if (!this.document) {
			return;
		}
		append(this.container, $('h2', undefined, localize('settings.title', "Project Settings")));
		append(this.container, $('p.building-intro', undefined, localize('settings.intro', "Codes, occupancy, site and loads of the project. {0} is the governing code: its tables give the values below, and every one can be overridden. The floor plan, the building model and the analysis read these settings.", BNBC.edition)));
		this.problemBox = append(this.container, $('.library-problems'));
		this.renderProblems();

		this.renderProjectType();

		append(this.container, $('h3', undefined, localize('settings.codeValues', "Code Values")));
		this.values = append(this.container, $('.building-table.settings-values'));
		this.renderValues();

		const actions = append(this.container, $('.building-actions'));
		const reset = this.viewDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true, title: localize('settings.resetTitle', "Replace the load combinations with the {0} strength design combinations", BNBC.edition) }));
		reset.label = `$(${Codicon.discard.id}) ${localize('settings.resetCombinations', "Reset Combinations to {0}", BNBC.edition)}`;
		this.viewDisposables.add(reset.onDidClick(() => this.resetCombinations()));

		this.form.render(append(this.container, $('.library-form')), SETTINGS_SCHEMA, this.document);
	}

	/** What the project designs, which decides how Part 5 models it; kept in the project manifest. */
	private renderProjectType(): void {
		const current = this.project.project?.type;
		if (!current) {
			return;
		}
		append(this.container, $('h3', undefined, localize('settings.projectType', "Project Type")));
		const row = append(this.container, $('.building-actions.project-type'));
		for (const option of PROJECT_TYPES) {
			const selected = option.type === current;
			const button = this.viewDisposables.add(new Button(row, { ...defaultButtonStyles, secondary: !selected, supportIcons: true, title: option.description }));
			button.label = selected ? `$(${Codicon.check.id}) ${option.label}` : option.label;
			button.element.setAttribute('aria-pressed', String(selected));
			this.viewDisposables.add(button.onDidClick(() => this.changeProjectType(option.type)));
		}
		append(this.container, $('p.building-intro', undefined, PROJECT_TYPES.find(t => t.type === current)?.description ?? ''));
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
			this.render();
		}
	}

	/** Code values derived from the settings, refreshed as fields are typed. */
	private renderValues(): void {
		const table = this.values;
		if (!table || !this.document) {
			return;
		}
		clearNode(table);
		for (const header of [localize('settings.quantity', "Quantity"), localize('settings.value', "Value"), localize('settings.source', "Source ({0})", BNBC.edition)]) {
			append(table, $('span.header', undefined, header));
		}
		for (const value of codeValues(this.document)) {
			append(table, $('span', undefined, value.label));
			append(table, $('span.number', undefined, value.value));
			append(table, $('span', undefined, value.overridden ? localize('settings.overridden', "overridden") : value.source));
		}
	}

	protected renderProblems(): void {
		const box = this.problemBox;
		if (!box) {
			return;
		}
		clearNode(box);
		box.classList.toggle('visible', this.problems.length > 0);
		for (const problem of this.problems) {
			const row = append(box, $('.library-problem'));
			append(row, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(row, $('span', undefined, problem.message));
		}
	}
}
