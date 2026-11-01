/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Action } from '../../../../base/common/actions.js';
import { Emitter } from '../../../../base/common/event.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { DisposableStore, IReference, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { language as displayLanguage } from '../../../../base/common/platform.js';
import { IJSONSchema } from '../../../../base/common/jsonSchema.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { ISoilSources } from '../../../../platform/saengine/common/femSolver.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { ILocaleService } from '../../../services/localization/common/locale.js';
import { BNBC, DEFAULT_SETTINGS, REDUCED_LIVE, SETTINGS_SCHEMA, SETTLEMENT_COMBINATIONS, TEMPLATES, THERMAL_COMBINATIONS } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { IPartSectionPane, sectionOption } from '../../../services/saengineProject/common/partSections.js';
import { IPartCheckItem, ISaenginePartStatusService } from '../../../services/saengineProject/common/partStatus.js';
import { ISaengineProjectService, partById, PROJECT_TYPES, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';
import { appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import './media/codePacks.css';
import { changePackWarning, chosenPackId, CODES_LIST_COMMAND, coverageLabel, DEFAULT_CODE_PACK, ICodePackInfo, ICodePackOption, packOptionBlock, packOptions, readCodePacks } from './codePacksModel.js';
import { clone, IDocumentFrameActions, IShapeError, isObject, JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditorInput } from './libraryEditorInput.js';
import { humanize, JsonObject, JsonValue, SchemaForm, titleCase } from './schemaForm.js';

const SETTINGS_SCHEMA_ID = 'saengine.projectSettings/1';

/** Desktop command telling where the site class and qa come from (`saengine.soil.sources`). */
const SOIL_SOURCES_COMMAND = 'saengine.soil.sources';

/** The schema title of a settings field (`Site`, `siteClassSource`), as the form labels it. */
function fieldTitle(defName: string, key: string): string | undefined {
	return SETTINGS_SCHEMA.$defs?.[defName]?.properties?.[key]?.title;
}

function format(value: number): string {
	return `${Number(value.toFixed(3))}`;
}

/**
 * Whether the code pack's reduced live load factor applies to `settings`: chosen (Analysis model,
 * Reduced live load factor) and every area load within the pack's conditions.
 */
export function reducedLiveApplies(settings: JsonObject): boolean {
	const analysis = isObject(settings.analysis) ? settings.analysis : undefined;
	const rule = REDUCED_LIVE as JsonObject;
	if (analysis?.reducedLiveFactor !== true || !Array.isArray(rule.combinations)) {
		return false;
	}
	const liveMax = typeof rule.liveMax === 'number' ? rule.liveMax : Infinity;
	const excluded = Array.isArray(rule.excludedUses) ? rule.excludedUses : [];
	const loads = Array.isArray(settings.areaLoads) ? settings.areaLoads.filter(isObject) : [];
	return loads.every(a => (typeof a.live !== 'number' || a.live <= liveMax + 1e-9) && !excluded.includes(a.use as JsonValue));
}

/**
 * The code's strength combinations for `settings`: with the temperature case on (Analysis model →
 * Temperature), combination 2 also with ±T right after it; with the reduced live load factor
 * where the code pack permits it.
 */
export function codeCombinations(settings: JsonObject): JsonValue[] {
	const source = reducedLiveApplies(settings) ? (REDUCED_LIVE as JsonObject).combinations : (DEFAULT_SETTINGS as JsonObject).combinations;
	const combinations = clone(source as JsonValue) as JsonValue[];
	const analysis = isObject(settings.analysis) ? settings.analysis : undefined;
	const thermal = analysis && isObject(analysis.thermal) ? analysis.thermal : undefined;
	const settlement = analysis && isObject(analysis.settlement) ? analysis.settlement : undefined;
	const withT = thermal?.enabled === true;
	const withSt = settlement?.enabled === true;
	if (!withT && !withSt) {
		return combinations;
	}
	const at = combinations.findIndex(c => isObject(c) && c.name === '1.2D + 1.6L + 0.5Lr');
	const added: JsonValue[] = withT ? clone(THERMAL_COMBINATIONS as JsonValue) as JsonValue[] : [];
	if (withSt) {
		// Settlement is a self-straining effect T (BNBC 2020 Part 6 Sec 2.7): 1.2ST alone, and
		// beside ±T when the temperature case is on too.
		added.push(...clone(SETTLEMENT_COMBINATIONS as JsonValue) as JsonValue[]);
		if (withT) {
			for (const t of THERMAL_COMBINATIONS as readonly JsonObject[]) {
				const name = String(t.name).replace(' + 1.6L', ' + 1.2ST + 1.6L');
				added.push({ ...(clone(t as JsonValue) as JsonObject), name, ST: 1.2 });
			}
		}
	}
	combinations.splice(at < 0 ? combinations.length : at + 1, 0, ...added);
	return combinations;
}

/** One derived code value: what it is, its value, and where it comes from. */
export interface ICodeValue {
	readonly label: string;
	readonly value: string;
	readonly source: string;
	readonly overridden?: boolean;
	/** What the short value stands for ("SD": its description), shown on hover. */
	readonly detail?: string;
	/** The value breaks a rule of the code (a system not permitted in the category). */
	readonly problem?: string;
}

/** Seismic detailing levels, lowest first (BNBC 2020 Part 6 Sec 8.3.2). */
const DETAILING = ['ordinary', 'intermediate', 'special'];

/** The seismic zone of a zone coefficient Z: the zone whose Z is nearest (Table 6.2.14). */
export function zoneOf(z: number): number {
	const zones = Object.entries(BNBC.zoneCoefficient);
	return Number(zones.reduce((best, zone) => Math.abs(zone[1] - z) < Math.abs(best[1] - z) ? zone : best)[0]);
}

/** The Seismic Design Category of the site and what it asks of the structural system. */
export interface IDesignCategory {
	readonly sdc: string;
	readonly zone: number;
	readonly siteClass: string;
	/** False when the system is NP (not permitted) in the category (Table 6.2.19). */
	readonly permitted: boolean;
	/** The system's frame detailing and the least the category needs (Sec 8.3.2). */
	readonly detailing: string | null;
	readonly required: string | undefined;
	/** The system's frame detailing is below what the category needs. */
	readonly tooLittleDetailing: boolean;
	/** The permitted system of the same material to switch to (a special moment frame). */
	readonly alternative: string | undefined;
}

/**
 * BNBC 2020 Part 6 Sec 2.5.5.2, Table 6.2.18 (p. 617): the Seismic Design Category from the
 * zone (the location's, or the one nearest an entered Z), the site class the analysis uses and
 * the occupancy category; and Table 6.2.19 (pp. 619-624), Sec 8.3.2 (pp. 1088-1089): whether
 * the structural system is permitted and detailed enough in it. The same rules as
 * `saengine.library.settings.design_category`. Undefined without a zone.
 */
export function designCategory(settings: JsonObject, siteClass: string): IDesignCategory | undefined {
	const object = (key: string) => (isObject(settings[key]) ? settings[key] : {}) as JsonObject;
	const site = object('site');
	const z = typeof site.zoneCoefficient === 'number' ? site.zoneCoefficient : undefined;
	const zone = z !== undefined ? zoneOf(z) : BNBC.locations[String(site.location)]?.zone;
	if (zone === undefined) {
		return undefined;
	}
	const table = BNBC.designCategories;
	const rows = table.bySiteClass;
	const row = rows[table.aliases[siteClass] ?? siteClass] ?? Object.values(rows)[Object.keys(rows).length - 1];
	const group = table.occupancyGroups[String(object('occupancy').category)] ?? Object.keys(row)[0];
	const sdc = row[group][zone - 1];
	const systemId = String(object('seismic').system);
	const system = BNBC.systems[systemId];
	const limit = system?.heightLimits[sdc];
	const permitted = !(limit !== null && limit !== undefined && limit <= 0);
	const required = BNBC.requiredDetailing[sdc];
	const detailing = system?.frame ?? null;
	const tooLittleDetailing = !!detailing && !!required && DETAILING.indexOf(detailing) < DETAILING.indexOf(required);
	const alternative = !permitted || tooLittleDetailing ? (systemId.startsWith('steel') ? 'steelSmf' : 'rcSmf') : undefined;
	return { sdc, zone, siteClass, permitted, detailing, required, tooLittleDetailing, alternative: alternative !== systemId ? alternative : undefined };
}

/**
 * The code values the settings imply, from the BNBC 2020 tables (the same tables and rules as
 * `saengine.library.settings.derived`). `soilSiteClass` is the site class the soil report gives
 * (with its label, "SD (N̄ = 12 over 30 m, BH-2)"): the settings use it unless their site class
 * source is Entered.
 */
export function codeValues(settings: JsonObject, soilSiteClass?: { readonly class: string; readonly label: string }): ICodeValue[] {
	const object = (key: string) => (isObject(settings[key]) ? settings[key] : {}) as JsonObject;
	const site = object('site');
	const occupancy = object('occupancy');
	const seismic = object('seismic');
	const wind = object('wind');
	const location = BNBC.locations[String(site.location)];
	const category = BNBC.categories[String(occupancy.category)];
	const systemId = String(seismic.system);
	const system = BNBC.systems[systemId];
	const override = (value: JsonValue | undefined) => typeof value === 'number' ? value : undefined;
	const values: ICodeValue[] = [];
	const push = (label: string, value: number | string | undefined, source: string, extra: { overridden?: boolean; detail?: string; problem?: string } = {}) => {
		values.push({ label, value: value === undefined ? '—' : typeof value === 'number' ? format(value) : value, source, ...extra });
	};
	const z = override(site.zoneCoefficient);
	if (z !== undefined && !location) {
		push(localize('code.zone', "Seismic zone"), zoneOf(z), localize('code.zoneOfZ', "Table 6.2.14: the zone whose Z is nearest the entered {0}", format(z)));
	} else {
		push(localize('code.zone', "Seismic zone"), location ? String(location.zone) : undefined, localize('code.zoneSource', "Seismic zoning map"));
	}
	push(localize('code.z', "Zone coefficient Z"), z ?? (location ? BNBC.zoneCoefficient[String(location.zone)] : undefined), localize('code.zSource', "Table 6.2.14"), { overridden: z !== undefined });
	const v = override(site.windSpeed);
	push(localize('code.windSpeed', "Basic wind speed V (m/s)"), v ?? location?.windSpeed, localize('code.windSource', "Table 6.2.8"), { overridden: v !== undefined });
	push(localize('code.seismicImportance', "Seismic importance factor I"), category?.seismicImportance, localize('code.seismicImportanceSource', "Table 6.2.17"));
	push(localize('code.windImportance', "Wind importance factor I"), category?.windImportance, localize('code.windImportanceSource', "Table 6.2.9"));
	const fromSoil = !!soilSiteClass && site.siteClassSource !== 'entered';
	const siteClass = fromSoil ? soilSiteClass!.class : String(site.siteClass);
	// The class itself ("SD"); its description on hover keeps the narrow panel from overflowing.
	push(localize('code.siteClass', "Site class"), siteClass, fromSoil
		? localize('code.siteClassFromSoil', "Table 6.2.13, from 1 Soil Report: {0}", soilSiteClass!.label)
		: localize('code.siteClassSource', "Table 6.2.13"), { detail: BNBC.siteClasses[siteClass] });
	const sdc = designCategory(settings, siteClass);
	push(localize('code.sdc', "Seismic Design Category"), sdc?.sdc, sdc
		? localize('code.sdcSource', "Table 6.2.18 (p. 617): zone {0}, site class {1}, occupancy category {2}", sdc.zone, sdc.siteClass, String(occupancy.category))
		: localize('code.sdcNone', "Table 6.2.18: needs the zone (a location, or Z)"));
	const row = system?.row ? localize('code.systemRow', "Table 6.2.19 row {0}", system.row) : localize('code.systemSource', "Table 6.2.19");
	for (const [key, label] of [['r', localize('code.r', "Response reduction factor R")], ['omega', localize('code.omega', "Overstrength factor Ω0")], ['cd', localize('code.cd', "Deflection amplification Cd")]] as const) {
		const own = override(seismic[key]);
		push(label, own ?? system?.[key], row, { overridden: own !== undefined });
	}
	// One system gives R, Ω0, Cd and the members' seismic detailing.
	const problem = sdc && !sdc.permitted
		? localize('code.systemNotPermitted', "{0} is not permitted in Seismic Design Category {1} ({2}). Category {1} needs {3} seismic detailing (Sec 8.3.2).", system?.name ?? systemId, sdc.sdc, row, sdc.required ?? '')
		: sdc?.tooLittleDetailing
			? localize('code.systemDetailing', "{0} has {1} detailing; Seismic Design Category {2} needs {3} detailing (Sec 8.3.2).", system?.name ?? systemId, sdc.detailing ?? '', sdc.sdc, sdc.required ?? '')
			: undefined;
	push(localize('code.detailing', "Seismic detailing"), system ? (system.frame ?? localize('code.detailingWalls', "per the system")) : undefined,
		localize('code.detailingSource', "Sec 8.3.2 (pp. 1088-1089), from the structural system {0}", system?.name ?? systemId), { problem });
	push(localize('code.exposure', "Wind exposure"), String(wind.exposure), localize('code.exposureSource', "6.2.9.3"), { detail: BNBC.exposures[String(wind.exposure)] });
	const kd = override(wind.directionality);
	push(localize('code.kd', "Directionality factor Kd"), kd ?? BNBC.wind.directionality, localize('code.kdSource', "Table 6.2.12"), { overridden: kd !== undefined });
	const kzt = override(wind.topographic);
	push(localize('code.kzt', "Topographic factor Kzt"), kzt ?? BNBC.wind.topographic, localize('code.kztSource', "Sec 2.4.7, flat terrain"), { overridden: kzt !== undefined });
	const gust = override(wind.gust);
	push(localize('code.gust', "Gust effect factor G"), gust ?? BNBC.wind.gust, localize('code.gustSource', "Sec 2.4.8.1, rigid building; a flexible building (natural frequency below 1 Hz) needs Gf of Sec 2.4.8.2 entered in Wind"), { overridden: gust !== undefined });
	return values;
}

/** The floors' area use (Table 6.2.3) for each building use, offered when the building use changes. */
const FLOOR_USE: { readonly [use: string]: string } = {
	residential: 'residential',
	office: 'office',
	educational: 'classroom',
	healthcare: 'hospitalWard',
	assembly: 'assemblyMovable',
	retail: 'retailUpper',
	industrial: 'storageLight',
	storage: 'storageLight',
	parking: 'parking',
};

/** The Code Values panel starts closed below this editor width, so the forms keep their tables. */
const NARROW_WIDTH = 1500;

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

/** Settings edited in the toolbar rather than in a section: the design code (code pack). */
const TOOLBAR_KEYS: ReadonlySet<string> = new Set(['codePack']);

/**
 * The sections of the settings form: one per top-level setting of the schema (an object, a
 * list), in schema order; plain values join the section named in {@link SECTION_OF}. Deprecated
 * settings (the old `codes`, replaced by the code pack) have none.
 */
export function settingsSections(schema: IJSONSchema): ISettingsSection[] {
	const sections: { id: string; title: string; keys: string[] }[] = [];
	for (const [key, property] of Object.entries(schema.properties ?? {})) {
		if (property.const !== undefined || property.deprecated || TOOLBAR_KEYS.has(key)) {
			continue;
		}
		const owner = SECTION_OF[key];
		if (owner) {
			sections.find(s => s.id === owner)?.keys.push(key);
			continue;
		}
		const ref = property.$ref?.startsWith('#/$defs/') ? schema.$defs?.[property.$ref.slice('#/$defs/'.length)] : undefined;
		sections.push({ id: key, title: titleCase(property.title ?? ref?.title ?? humanize(key)), keys: [key] });
		if (key === 'drawings') {
			// How the bars are detailed is an engineering choice, not part of the title block.
			sections.push({ id: DETAILING_SECTION, title: localize('settings.detailingSection', "Detailing"), keys: [key] });
		}
	}
	return sections;
}

/** The section of the drawings' detailing choices (development length, bar cut-off). */
const DETAILING_SECTION = 'detailing';
const DETAILING_FIELDS: ReadonlySet<string> = new Set(['developmentLength', 'curtail']);

/** The title block fields of Drawings whose home is Project: [drawings field, project field]. */
const PROJECT_FIELDS: readonly (readonly [string, string])[] = [['projectNumber', 'number'], ['engineer', 'engineer']];

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
export class SettingsEditor extends JsonDocumentEditor implements IPartSectionPane {

	static readonly ID = LibraryEditorInput.SETTINGS_EDITOR_ID;

	private nav!: HTMLElement;
	private page!: HTMLElement;
	private typeSelect: SelectBox | undefined;
	private typeSlot: HTMLElement | undefined;
	private typeHover: { update(content: string): void } | undefined;
	/** The design code (code pack) the project uses, in the toolbar after the project type. */
	private packSelect: SelectBox | undefined;
	private packSlot: HTMLElement | undefined;
	private packHover: { update(content: string): void } | undefined;
	/** The packs installed (from `saengine.codes.list`); undefined until the backend answers. */
	private packs: ICodePackInfo[] | undefined;
	private packChoices: ICodePackOption[] = [];
	private packsVersion = 0;
	private sectionId = SECTIONS[0]?.id;
	private readonly _onDidChangePartSection = this._register(new Emitter<void>());
	readonly onDidChangePartSection = this._onDidChangePartSection.event;
	private problemBox: HTMLElement | undefined;
	private readonly form: SchemaForm;
	/** The Code Values panel was closed for a narrow editor (and opens again when it is wide). */
	private autoCollapsed = false;

	private readonly navDisposables = this._register(new DisposableStore());
	private readonly pageDisposables = this._register(new DisposableStore());
	private readonly valuesDisposables = this._register(new DisposableStore());

	/** The soil report (unsaved edits included): where the site class and qa come from. */
	private readonly soilReference = this._register(new MutableDisposable<IReference<IResolvedTextEditorModel>>());
	private readonly soilListener = this._register(new MutableDisposable());
	private readonly sourcesScheduler = this._register(new RunOnceScheduler(() => void this.refreshSources(), 400));
	private sources: ISoilSources | undefined;
	private sourcesVersion = 0;
	/** The read-only rows of the Site and Foundation sections telling where the values come from. */
	private siteSourceCell: HTMLElement | undefined;
	private bearingSourceCell: HTMLElement | undefined;
	/** The Seismic section's read-only design category row (see renderSeismicSummary). */
	private seismicCell: HTMLElement | undefined;
	private readonly seismicDisposables = this._register(new DisposableStore());
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
		@ICommandService private readonly commands: ICommandService,
		@IEditorService editorService: IEditorService,
		@ITextModelService private readonly textModels: ITextModelService,
		@ISaengineProjectService private readonly project: ISaengineProjectService,
		@IDialogService private readonly dialogService: IDialogService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IHoverService private readonly hoverService: IHoverService,
		@IConfigurationService configurationService: IConfigurationService,
		@ITextFileService private readonly textFiles: ITextFileService,
		@ISaenginePartStatusService private readonly partStatus: ISaenginePartStatusService,
		@ILocaleService private readonly localeService: ILocaleService,
	) {
		super(SettingsEditor.ID, group, telemetryService, themeService, storageService, commands, editorService, textModels, project);
		this.trackDeveloperMode(configurationService);
		this.form = instantiationService.createInstance(SchemaForm, {
			root: SETTINGS_SCHEMA,
			template: defName => clone((TEMPLATES[defName] ?? {}) as JsonObject),
			references: path => this.references(path),
			validate: (path, value) => this.validate(path, value),
			changed: (path, structural) => this.onChanged(path, structural),
			mode: path => this.fieldMode(path),
			newItem: (path, list) => this.newItem(path, list),
			placeholder: path => this.placeholder(path),
			note: path => this.note(path),
			referenceLabel: (path, id) => this.referenceLabel(path, id),
			editing: active => this.fieldEditing(active),
		});
		this._register({ dispose: () => this.form.dispose() });
		// Unsaved settings show a Save link in the status line.
		this._register(this.textFiles.files.onDidChangeDirty(model => {
			if (this.resource && model.resource.toString() === this.resource.toString()) {
				this.renderStatus();
			}
		}));
		// The backend's commands are registered by the desktop contributions, possibly after this editor.
		this._register(CommandsRegistry.onDidRegisterCommand(id => {
			if (id === SOIL_SOURCES_COMMAND) {
				this.sourcesScheduler.schedule(0);
			}
			if (id === CODES_LIST_COMMAND) {
				void this.refreshPacks();
			}
		}));
	}

	// ───────────────────────────── values from the soil report ─────────────────────────────

	/** Integration glue: packs made or installed on the Code Packs page meanwhile are offered when the settings are shown again. */
	protected override setEditorVisible(visible: boolean): void {
		super.setEditorVisible(visible);
		if (visible && this.input) {
			void this.refreshPacks();
		}
	}

	/** The section shown, for the sidebar's entries under Project Settings. */
	get partSection(): string | undefined {
		return this.sectionId;
	}

	/** `section` (from the sidebar) shows that section. */
	protected override applyOptions(options: IEditorOptions | undefined): void {
		const section = sectionOption(options);
		if (section && SECTIONS.some(s => s.id === section)) {
			this.selectSection(section);
		}
	}

	/** Old files' deprecated `codes` (the design code is the code pack) is dropped when they are saved. */
	protected override commit(): void {
		if (this.document) {
			delete this.document.codes;
		}
		super.commit();
	}

	protected override onWillLoadInput(): void {
		this.sources = undefined;
		void this.trackSoil();
		void this.refreshPacks();
	}

	// ───────────────────────────── the design code (code pack) ─────────────────────────────

	/** Asks the backend which code packs are installed (built-in, the user's, the project's). */
	private async refreshPacks(): Promise<void> {
		if (!CommandsRegistry.getCommand(CODES_LIST_COMMAND)) {
			return; // until the backend offers code packs, the built-in BNBC 2020 alone is shown
		}
		const version = ++this.packsVersion;
		let packs: ICodePackInfo[] | undefined;
		try {
			packs = readCodePacks(await this.commands.executeCommand<unknown>(CODES_LIST_COMMAND, { root: this.project.project?.root.fsPath }));
		} catch {
			packs = undefined;
		}
		if (version === this.packsVersion) {
			this.packs = packs;
			this.renderCodePack();
			this.renderValues();
			this.renderStatus();
		}
	}

	/** The chosen pack as installed here (undefined when the settings name one not installed). */
	private get chosenPack(): ICodePackInfo | undefined {
		const id = chosenPackId(this.document);
		const scopes = ['project', 'user', 'builtin'];
		return [...(this.packs ?? [])].sort((a, b) => scopes.indexOf(a.scope) - scopes.indexOf(b.scope)).find(p => p.id === id);
	}

	/** The governing code's name ("BNBC 2020"), for the help, the status and the values panel. */
	private get codeName(): string {
		const id = chosenPackId(this.document);
		return id === DEFAULT_CODE_PACK ? (this.chosenPack?.name ?? BNBC.edition) : (this.chosenPack?.name ?? id);
	}

	private createCodePack(frame: EditorFrame): void {
		const slot = this.packSlot = append(frame.controlsSlot, $('.settings-code-pack'));
		append(slot, $('span.sa-frame-label', undefined, localize('settings.designCode', "Design code")));
		const select = this.packSelect = this._register(new SelectBox([], 0, this.contextViewService, defaultSelectBoxStyles, {
			ariaLabel: localize('settings.designCode', "Design code"),
		}));
		const box = append(slot, $('.settings-code-pack-select'));
		select.render(box);
		this.packHover = this._register(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), box, ''));
		this._register(select.onDidSelect(e => {
			const option = this.packChoices[e.index];
			if (option) {
				void this.changeCodePack(option);
				return;
			}
			// The entries after the packs: get more, manage or install packs on the Packages page.
			this.renderCodePack();
			const extra = e.index - this.packChoices.length;
			void (extra === 0
				? this.commands.executeCommand('saengine.packages.show', { tab: 'browse', kind: 'designCode' })
				: extra === 1 ? this.commands.executeCommand('saengine.packages.show', { tab: 'installed', kind: 'designCode' }) : this.commands.executeCommand('saengine.codePacks.install'));
		}));
	}

	/** The selector follows the settings' `codePack` and the packs installed. */
	private renderCodePack(): void {
		const select = this.packSelect;
		if (!select) {
			return;
		}
		this.packSlot?.classList.toggle('hidden', !this.document);
		const chosen = chosenPackId(this.document);
		this.packChoices = packOptions(this.packs ?? [], chosen);
		const index = Math.max(0, this.packChoices.findIndex(o => o.id === chosen));
		// A pack with errors cannot be loaded by analysis or design, so it cannot be chosen.
		select.setOptions([
			...this.packChoices.map(o => ({ text: o.label, description: o.description, isDisabled: o.unusable && o.id !== chosen })),
			{ text: localize('settings.getMorePacks', "Get More Design Codes..."), description: localize('settings.getMorePacksDescription', "Browses the design codes published for SAEngine (Packages page).") },
			{ text: localize('settings.managePacks', "Manage Packages..."), description: localize('settings.managePacksDescription', "Lists the design codes installed and makes new ones (Packages page).") },
			{ text: localize('settings.installPack', "Install from File..."), description: localize('settings.installPackDescription', "Installs a design code from a folder or .zip.") },
		], index);
		const option = this.packChoices[index];
		this.packHover?.update(this.packs === undefined
			? localize('settings.designCodeStandIn', "{0}. Other code packs become available when SAEngine offers them (Manage Packages... in this list).", option?.label ?? BNBC.edition)
			: option?.description || option?.label || '');
	}

	/** Switches the project to another pack after warning that the design results change. */
	private async changeCodePack(option: ICodePackOption | undefined): Promise<void> {
		const document = this.document;
		const from = chosenPackId(document);
		if (!document || !option || option.id === from) {
			return;
		}
		const block = packOptionBlock(option);
		if (block) {
			await this.dialogService.error(block.message, block.detail);
			this.renderCodePack();
			return;
		}
		const fromLabel = this.packChoices.find(o => o.id === from)?.label ?? from;
		const { confirmed } = await this.dialogService.confirm({ type: 'warning', ...changePackWarning(fromLabel, option), primaryButton: localize('settings.changeCodeButton', "&&Change Design Code") });
		if (confirmed && this.document === document) {
			document.codePack = option.id;
			this.changed(true);
		} else {
			this.renderCodePack();
		}
	}

	/** Follows the soil report (Part 1), whose boreholes give the site class and qa. */
	private async trackSoil(): Promise<void> {
		this.soilListener.clear();
		this.soilReference.clear();
		const root = this.project.project?.root;
		const part = partById('soil');
		if (root && part?.mainFile) {
			try {
				const reference = await this.textModels.createModelReference(joinPath(root, part.folder, part.mainFile));
				this.soilReference.value = reference;
				this.soilListener.value = reference.object.textEditorModel.onDidChangeContent(() => this.sourcesScheduler.schedule());
			} catch {
				// No soil report: the entered site class and the override qa apply.
			}
		}
		this.sourcesScheduler.schedule(0);
	}

	/** Asks the backend where the site class and qa come from (after edits to either file). */
	private async refreshSources(): Promise<void> {
		if (!this.document || !CommandsRegistry.getCommand(SOIL_SOURCES_COMMAND)) {
			return;
		}
		const version = ++this.sourcesVersion;
		let sources: ISoilSources | undefined;
		try {
			sources = await this.commands.executeCommand<ISoilSources>(SOIL_SOURCES_COMMAND, {
				soilText: this.soilReference.value?.object.textEditorModel.getValue(),
				settingsText: JSON.stringify(this.document),
			});
		} catch {
			sources = undefined; // no Python backend: the settings' own values are shown
		}
		if (version !== this.sourcesVersion || !this.document) {
			return;
		}
		const hidden = this.siteClassFromSoil;
		this.sources = sources;
		if (hidden !== this.siteClassFromSoil && this.section?.id === 'site') {
			this.renderPage(); // the entered site class field shows or hides
		} else {
			this.renderSources();
		}
		this.renderValues();
	}

	/** The site class comes from the soil report: the source is not Entered and the boreholes give one. */
	private get siteClassFromSoil(): boolean {
		const site = isObject(this.document?.site) ? this.document.site : {};
		return site.siteClassSource !== 'entered' && !!this.sources?.soil.class;
	}

	/**
	 * Adds a read-only row after the field titled `after` (or at the top of the form): what the
	 * analysis uses and where it comes from. Returns its value cell.
	 */
	private sourceRow(form: HTMLElement, after: string | undefined, label: string): HTMLElement {
		// A flat section's fields are the form's own rows: label cell first, its label first in it.
		const anchor = Array.from(form.children).find(row => row.classList.contains('form-field') && row.firstElementChild?.firstElementChild?.textContent === after);
		const row = $('.form-field.settings-source-field');
		append(append(row, $('.form-label-cell')), $('span.form-label', undefined, label));
		const cell = append(row, $('.form-control', { 'aria-live': 'polite' }));
		if (anchor) {
			anchor.after(row);
		} else {
			form.prepend(row);
		}
		return cell;
	}

	/** Fills the read-only source rows of the Site and Foundation sections. */
	private renderSources(): void {
		const soil = this.sources?.soil;
		const site = this.siteSourceCell;
		if (site) {
			clearNode(site);
			const entered = isObject(this.document?.site) && this.document.site.siteClassSource === 'entered';
			const row = site.parentElement!;
			let text: string | undefined;
			if (this.siteClassFromSoil && soil) {
				text = localize('settings.siteFromSoil', "from 1 Soil Report: {0}", soil.label);
			} else if (!entered && this.sources) {
				text = soil?.note
					? localize('settings.siteNoSoilClass', "the entered class below: 1 Soil Report gives none yet ({0})", soil.note.replace(/\.$/, ''))
					: localize('settings.siteEnteredFallback', "the entered class below");
			} else if (entered && soil?.class) {
				text = localize('settings.siteEntered', "the entered class below; 1 Soil Report gives {0}", soil.label);
			}
			row.classList.toggle('hidden', text === undefined);
			if (text !== undefined) {
				append(site, $('span.settings-source-value', undefined, text));
			}
			// S1 and S2 (soft clays, liquefiable soils) need a site-specific study.
			const flags = ((soil as { readonly flags?: readonly string[] } | undefined)?.flags ?? []).filter(f => f === 'S1' || f === 'S2');
			if (flags.length) {
				row.classList.remove('hidden');
				const warning = append(site, $('span.settings-source-warning'));
				append(warning, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
				append(warning, $('span', undefined, localize('settings.siteSpecific', "1 Soil Report flags site class {0} (Table 6.2.13): {1} Sec 2.5.3.1 asks for a site-specific study. The analysis meanwhile uses the class shown above.", flags.join(', '), BNBC.edition)));
			}
		}
		const bearing = this.bearingSourceCell;
		if (bearing) {
			clearNode(bearing);
			const foundation = isObject(this.document?.foundation) ? this.document.foundation : {};
			const override = typeof foundation.allowableBearing === 'number' ? foundation.allowableBearing : undefined;
			const boreholes = soil?.boreholes ?? 0;
			let text: string;
			if (override !== undefined) {
				text = boreholes
					? localize('settings.qaOverrideSoil', "the override, {0} kPa, for every footing; clear it to take qa per footing from 1 Soil Report ({1} boreholes)", override, boreholes)
					: localize('settings.qaOverride', "the override, {0} kPa, for every footing", override);
			} else if (boreholes) {
				text = localize('settings.qaFromSoil', "per footing from 1 Soil Report ({0} boreholes), at each footing's position, founding level and size", boreholes);
				const levels = this.sources?.bearing.levels;
				if (levels) {
					text = localize('settings.qaFromSoilLevels', "{0}. {1}", text, levels);
				}
			} else if (this.sources) {
				text = localize('settings.qaNone', "none: 1 Soil Report has no boreholes and no override is given, so the footings are designed without the bearing check");
			} else {
				text = override === undefined
					? localize('settings.qaUnknown', "from 1 Soil Report when it has boreholes, else the override")
					: localize('settings.qaOverride', "the override, {0} kPa, for every footing", override);
			}
			append(bearing, $('span.settings-source-value', undefined, text));
		}
		this.renderSeismicSummary();
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
		frame.setHelp(localize('settings.intro', "Codes, occupancy, site and loads of the project. The design code (a code pack, {0} by default) is chosen in the toolbar: its tables give the code values in the panel on the right, and every one can be overridden. The floor plan, the building model and the analysis read these settings. Get More Design Codes... and Manage Packages... at the end of the design code list open the Packages page.", BNBC.edition));
		this.createProjectType(frame);
		this.createCodePack(frame);

		body.classList.add('sa-sections');
		this.nav = append(body, $('.sa-section-list', { role: 'listbox', tabIndex: 0, 'aria-label': localize('settings.sections', "Sections") }));
		this.page = append(body, $('.sa-form-page'));
		this._register(addDisposableListener(this.nav, EventType.KEY_DOWN, e => this.onNavKey(new StandardKeyboardEvent(e))));
		// A field's help does not linger over other fields while the page scrolls.
		this._register(addDisposableListener(this.page, EventType.SCROLL, () => this.hoverService.hideHover(true)));
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

	override layout(dimension: Parameters<JsonDocumentEditor['layout']>[0]): void {
		super.layout(dimension);
		const frame = this.documentFrame;
		if (!frame) {
			return;
		}
		// Below about 1500 px the panel would squeeze the combination and area load tables into
		// stacked cards: it starts closed there (the toolbar button opens it) and opens again wider.
		if (dimension.width < NARROW_WIDTH && frame.isPropertiesVisible && !this.autoCollapsed) {
			this.autoCollapsed = true;
			frame.setPropertiesVisible(false);
		} else if (dimension.width >= NARROW_WIDTH && this.autoCollapsed) {
			this.autoCollapsed = false;
			if (!frame.isPropertiesVisible) {
				frame.setPropertiesVisible(true);
			}
		}
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

	/** The floor and roof selectors name each area load with its loads: "FL: Floors (L 2, finish 1.2, partitions 1 kN/m²)". */
	private referenceLabel(path: string, id: string): string | undefined {
		if (path !== 'floorLoad' && path !== 'roofLoad') {
			return undefined;
		}
		const load = this.areaLoads.find(a => a.id === id);
		if (!load) {
			return undefined;
		}
		const number = (value: JsonValue | undefined) => typeof value === 'number' ? format(value) : '0';
		return localize('settings.loadOption', "{0}: {1} (L {2}, finish {3}, partitions {4} kN/m²)", id, String(load.name ?? ''), number(load.live), number(load.finish), number(load.partitions));
	}

	private get location() {
		const site = isObject(this.document?.site) ? this.document.site : {};
		return BNBC.locations[String(site.location)];
	}

	private get system() {
		const seismic = isObject(this.document?.seismic) ? this.document.seismic : {};
		return BNBC.systems[String(seismic.system)];
	}

	/**
	 * Fields the section or the data leave out: the entered site class while the soil report gives
	 * one; the detailing choices on the Detailing page only (and the rest of Drawings off it); the
	 * drawings' own project number and engineer, whose home is Project, unless an old file holds
	 * one that differs from Project's (shown so that it can be cleared).
	 */
	private fieldMode(path: string): 'hidden' | undefined {
		if (path === 'site.siteClass' && this.siteClassFromSoil) {
			return 'hidden';
		}
		const [group, field] = path.split('.');
		if (group !== 'drawings' || field === undefined || path.split('.').length !== 2) {
			return undefined;
		}
		if ((this.section?.id === DETAILING_SECTION) !== DETAILING_FIELDS.has(field)) {
			return 'hidden';
		}
		const own = PROJECT_FIELDS.find(([drawing]) => drawing === field);
		return own && this.titleBlockOverride(own[0], own[1]) === undefined ? 'hidden' : undefined;
	}

	/** A drawings field (`projectNumber`) that holds a value other than Project's (`number`). */
	private titleBlockOverride(drawingField: string, projectField: string): string | undefined {
		const drawings = isObject(this.document?.drawings) ? this.document.drawings : {};
		const project = isObject(this.document?.project) ? this.document.project : {};
		const value = drawings[drawingField];
		return typeof value === 'string' && value !== '' && value !== project[projectField] ? value : undefined;
	}

	/** A quiet line under an entered override: the code value it replaces (clear the field to use it). */
	private note(path: string): string | undefined {
		const document = this.document;
		const object = (key: string) => (isObject(document?.[key]) ? document![key] : {}) as JsonObject;
		const site = object('site');
		const location = this.location;
		const system = this.system;
		switch (path) {
			case 'site.zoneCoefficient':
				return typeof site.zoneCoefficient === 'number' && location
					? localize('settings.zOverrideNote', "Override: {0} Table 6.2.14 gives {1} for {2} (zone {3}). Clear the field to use it.", BNBC.edition, format(BNBC.zoneCoefficient[String(location.zone)]), location.name, location.zone)
					: typeof site.zoneCoefficient === 'number'
						? localize('settings.zCustomNote', "Seismic zone {0} (Table 6.2.14: the zone whose Z is nearest).", zoneOf(site.zoneCoefficient))
						: undefined;
			case 'site.windSpeed':
				return typeof site.windSpeed === 'number' && location
					? localize('settings.vOverrideNote', "Override: {0} Table 6.2.8 gives {1} m/s for {2}. Clear the field to use it.", BNBC.edition, format(location.windSpeed), location.name)
					: undefined;
			case 'seismic.r':
			case 'seismic.omega':
			case 'seismic.cd': {
				const key = path.slice('seismic.'.length) as 'r' | 'omega' | 'cd';
				return typeof object('seismic')[key] === 'number' && system
					? localize('settings.factorOverrideNote', "Override: {0} Table 6.2.19 row {1} gives {2} for {3}.", BNBC.edition, system.row, format(system[key]), system.name)
					: undefined;
			}
		}
		const own = PROJECT_FIELDS.find(([drawing]) => path === `drawings.${drawing}`);
		if (own) {
			const project = object('project')[own[1]];
			return this.titleBlockOverride(own[0], own[1]) !== undefined
				? typeof project === 'string' && project
					? localize('settings.titleBlockDiffers', "Differs from Project's \"{0}\". Clear it so that the drawings print Project's.", project)
					: localize('settings.titleBlockMove', "Project has none: enter it in Project and clear it here, so that it is kept in one place.")
				: undefined;
		}
		return undefined;
	}

	/** An empty override shows the value it would replace, with its table. */
	private placeholder(path: string): string | undefined {
		const location = this.location;
		const system = this.system;
		const row = system?.row ? localize('settings.rowShort', "Table 6.2.19 row {0}", system.row) : localize('settings.tableSystems', "Table 6.2.19");
		switch (path) {
			case 'site.zoneCoefficient': return location ? localize('settings.zPlaceholder', "{0} ({1}, Table 6.2.14)", format(BNBC.zoneCoefficient[String(location.zone)]), location.name) : localize('settings.zRequired', "required for a custom location");
			case 'site.windSpeed': return location ? localize('settings.vPlaceholder', "{0} ({1}, Table 6.2.8)", format(location.windSpeed), location.name) : localize('settings.vRequired', "required for a custom location");
			case 'seismic.r': return system ? `${format(system.r)} (${row})` : undefined;
			case 'seismic.omega': return system ? `${format(system.omega)} (${row})` : undefined;
			case 'seismic.cd': return system ? `${format(system.cd)} (${row})` : undefined;
			case 'wind.directionality': return localize('settings.kdPlaceholder', "{0} (Table 6.2.12)", format(BNBC.wind.directionality));
			case 'wind.topographic': return localize('settings.kztPlaceholder', "{0} (flat terrain)", format(BNBC.wind.topographic));
			case 'wind.gust': return localize('settings.gustPlaceholder', "{0} (rigid, Sec 2.4.8.1)", format(BNBC.wind.gust));
			case 'foundation.allowableBearing': return localize('settings.qaPlaceholder', "from 1 Soil Report");
			case 'analysis.seismicLiveFactor': {
				const live = this.earthquakeLiveFactor();
				return live !== undefined
					? localize('settings.seismicLivePlaceholder', "{0} (the 1.2D + 1.0E combination's; Sec 2.7.3.1)", format(live))
					: localize('settings.seismicLiveNone', "the earthquake combination's (Sec 2.7.3.1)");
			}
			case 'analysis.massSource.liveShare': return localize('settings.liveSharePlaceholder', "0.25; 0.5 above 3 kN/m² (Sec 2.5.7.3)");
			case 'analysis.slenderness.driftFactor': return localize('settings.driftFactorPlaceholder', "automatic: 1.0 on cracked sections");
			case 'analysis.ssiShearModulusRatio': return localize('settings.gRatioPlaceholder', "from (2/3)·Z·S (ASCE 7-05 Table 19.2-1)");
		}
		if (/^combinations\.\d+\.F$/.test(path)) {
			return localize('settings.fPlaceholder', "as D");
		}
		return undefined;
	}

	/** L's factor in the project's 1.2D + 1.0E + L combination (the first with E and D 1.2). */
	private earthquakeLiveFactor(): number | undefined {
		const combinations = Array.isArray(this.document?.combinations) ? this.document.combinations.filter(isObject) : [];
		const quake = combinations.find(c => c.D === 1.2 && (typeof c.EX === 'number' && c.EX !== 0 || typeof c.EY === 'number' && c.EY !== 0));
		return typeof quake?.L === 'number' ? quake.L : undefined;
	}

	private validate(path: string, value: string): string | undefined {
		const number = value === '' ? undefined : Number(value);
		if (number !== undefined && isFinite(number)) {
			const system = this.system;
			const symbol = { 'seismic.r': 'R', 'seismic.omega': 'Ω0', 'seismic.cd': 'Cd' }[path];
			if (symbol && number <= 0) {
				return system
					? localize('settings.factorPositive', "{0} must be above 0. {1} Table 6.2.19 gives {2} for {3}; clear the field to use it.", symbol, BNBC.edition, format(system[path === 'seismic.r' ? 'r' : path === 'seismic.omega' ? 'omega' : 'cd']), system.name)
					: localize('settings.factorPositiveNoSystem', "{0} must be above 0.", symbol);
			}
			if (path === 'site.zoneCoefficient' && (number <= 0 || number >= 1)) {
				return localize('settings.zRange', "Z is a fraction of g between 0 and 1: {0} Table 6.2.14 gives 0.12, 0.20, 0.28 or 0.36 by zone.", BNBC.edition);
			}
			if (path === 'site.windSpeed' && number <= 0) {
				return localize('settings.vRange', "Enter the basic wind speed in m/s (3-second gust at 10 m, {0} Table 6.2.8).", BNBC.edition);
			}
			return undefined;
		}
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
		this.sourcesScheduler.schedule();
		if (path === 'site.siteClassSource') {
			this.changed(true); // the entered site class field shows or hides
			return;
		}
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
			this.form.refreshPlaceholders();
			this.renderValues();
			this.renderSources();
		}
		if (path === 'occupancy.use') {
			void this.offerFloorUse();
		}
		if (path === 'site.location') {
			const from = this.shownLocation;
			this.shownLocation = this.siteLocation;
			if (from === 'custom' && this.shownLocation !== 'custom') {
				void this.offerCodeSiteValues();
			}
		}
	}

	/** The location the form showed last, to tell when the site leaves Custom. */
	private shownLocation: string | undefined;

	private get siteLocation(): string | undefined {
		const site = isObject(this.document?.site) ? this.document.site : undefined;
		return site ? String(site.location ?? 'dhaka') : undefined;
	}

	/**
	 * Leaving Custom for a town: the Z and V entered for the custom site would silently override
	 * the town's code values, so the engineer is asked (the code values are the default answer).
	 */
	private async offerCodeSiteValues(): Promise<void> {
		const document = this.document;
		const site = isObject(document?.site) ? document.site : undefined;
		const location = this.location;
		const entered = (['zoneCoefficient', 'windSpeed'] as const).filter(k => typeof site?.[k] === 'number');
		if (!document || !site || !location || !entered.length) {
			return;
		}
		const z = BNBC.zoneCoefficient[String(location.zone)];
		const values = [
			typeof site.zoneCoefficient === 'number' ? localize('settings.siteZ', "Z {0} (the code gives {1})", format(site.zoneCoefficient), format(z)) : undefined,
			typeof site.windSpeed === 'number' ? localize('settings.siteV', "V {0} m/s (the code gives {1})", format(site.windSpeed), format(location.windSpeed)) : undefined,
		].filter(Boolean).join(', ');
		const useCode = await this.dialogService.prompt<boolean>({
			type: 'question',
			message: localize('settings.leaveCustomConfirm', "Use the code values of {0}?", location.name),
			detail: localize('settings.leaveCustomDetail', "The custom site had {0}. Kept, they override {1}'s values from {2} Tables 6.2.14 and 6.2.8.", values, location.name, BNBC.edition),
			buttons: [
				{ label: localize('settings.useCodeValues', "&&Use the Code Values"), run: () => true },
				{ label: localize('settings.keepOverrides', "&&Keep as Overrides"), run: () => false },
			],
			cancelButton: { label: localize('settings.keepOverridesCancel', "Keep as Overrides"), run: () => false },
		});
		if (useCode.result && this.document === document) {
			for (const key of entered) {
				delete site[key];
			}
			this.changed(true);
		}
	}

	/** After the building use changes: offers the floors' area load the code gives for that use. */
	private async offerFloorUse(): Promise<void> {
		const document = this.document;
		const occupancy = isObject(document?.occupancy) ? document.occupancy : {};
		const useId = FLOOR_USE[String(occupancy.use)];
		const use = useId ? BNBC.areaUses[useId] : undefined;
		const floor = this.areaLoads.find(a => a.id === document?.floorLoad);
		if (!document || !use || !floor || floor.use === useId) {
			return;
		}
		const { confirmed } = await this.dialogService.confirm({
			message: localize('settings.floorUseConfirm', "Update the floor load {0} to {1}?", String(floor.id), use.name),
			detail: localize('settings.floorUseDetail', "The floors ({0}) are loaded as {1} at {2} kN/m². {3} Table 6.2.3 gives {4} kN/m² for {5}.", String(floor.name ?? floor.id), String(BNBC.areaUses[String(floor.use)]?.name ?? floor.use), format(Number(floor.live)), BNBC.edition, format(use.live), use.name),
			primaryButton: localize('settings.floorUseButton', "&&Update Floor Load"),
			cancelButton: localize('settings.floorUseKeep', "Keep"),
		});
		if (confirmed && this.document === document && this.areaLoads.includes(floor)) {
			floor.use = useId;
			floor.live = use.live;
			this.changed(true);
		}
	}

	/** Switches the structural system to one the Seismic Design Category permits (after asking). */
	private async switchSystem(target: string): Promise<void> {
		const document = this.document;
		const system = BNBC.systems[target];
		if (!document || !system) {
			return;
		}
		const seismic = isObject(document.seismic) ? document.seismic : (document.seismic = {});
		const overrides = ['r', 'omega', 'cd'].filter(k => seismic[k] !== undefined);
		const { confirmed } = await this.dialogService.confirm({
			message: localize('settings.switchSystemConfirm', "Switch the structural system to {0}?", system.name),
			detail: [
				localize('settings.switchSystemDetail', "R, Ω0 and Cd become {0}, {1} and {2} ({3} Table 6.2.19 row {4}), and the members are designed and detailed as {5} (Sec 8.3).", format(system.r), format(system.omega), format(system.cd), BNBC.edition, system.row, system.name),
				...(overrides.length ? [localize('settings.switchSystemOverrides', "The overrides of R, Ω0 and Cd, which belonged to the old system, are cleared.")] : []),
				localize('settings.switchSystemUndo', "Edit > Undo brings the old system back."),
			].join(' '),
			primaryButton: localize('settings.switchSystemButton', "&&Switch System"),
		});
		if (confirmed && this.document === document) {
			seismic.system = target;
			for (const key of overrides) {
				delete seismic[key];
			}
			this.changed(true);
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
			document.combinations = codeCombinations(document);
			this.sectionId = 'combinations';
			this._onDidChangePartSection.fire();
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
		this.shownLocation = this.siteLocation;
		this.renderProjectType();
		this.renderCodePack();
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
		this.pageDisposables.clear();
		this.seismicCell = undefined;
		clearNode(this.page);
		const section = this.section;
		if (!this.document || !section) {
			return;
		}
		const title = append(this.page, $('.sa-form-page-title', undefined, section.title));
		if (section.id === 'combinations') {
			// The code's combinations, one click from the section (also in the ... menu).
			const button = this.pageDisposables.add(new Button(append(title, $('span.settings-generate')), { ...defaultButtonStyles, secondary: true, supportIcons: true, title: this.resetAction.tooltip }));
			button.label = `$(${Codicon.sync.id}) ${localize('settings.generateCombinations', "Generate from {0}", BNBC.edition)}`;
			this.pageDisposables.add(button.onDidClick(() => void this.resetCombinations()));
			append(this.page, $('.sa-props-note.settings-section-note', undefined, localize('settings.combinationsNote', "Factors on the load cases. D includes the superimposed dead load SD (finish, partitions). T applies to the temperature case (Analysis model › Temperature) and is 0 elsewhere; F, on the fluid loads of 07 MEP, follows D when empty. Hover a column heading for its meaning.")));
		}
		this.problemBox = append(this.page, $('.library-problems'));
		this.renderSectionProblems();
		const skip = Object.keys(SETTINGS_SCHEMA.properties ?? {}).filter(key => !section.keys.includes(key));
		const form = append(this.page, $('.library-form'));
		this.form.render(form, SETTINGS_SCHEMA, this.document, skip, { flat: true });
		// Where the site class and qa come from: read-only rows below their own fields.
		this.siteSourceCell = section.keys.includes('site')
			? this.sourceRow(form, fieldTitle('Site', 'siteClassSource'), this.siteClassFromSoil ? localize('settings.siteClass', "Site class") : localize('settings.siteClassUsed', "Site class used"))
			: undefined;
		this.bearingSourceCell = section.keys.includes('foundation')
			? this.sourceRow(form, fieldTitle('Foundation', 'allowableBearing'), localize('settings.qaUsed', "Allowable bearing qa used"))
			: undefined;
		// The category the site, occupancy and system give, also when the Code Values panel is closed.
		this.seismicCell = section.keys.includes('seismic')
			? this.sourceRow(form, undefined, localize('settings.designCategoryRow', "Design category"))
			: undefined;
		if (section.id === 'project') {
			this.renderDisplayLanguage(this.sourceRow(form, fieldTitle('ProjectInfo', 'language'), localize('settings.displayLanguageRow', "SAEngine screens")));
		}
		if (section.id === 'drawings') {
			this.renderTitleBlockSource(this.sourceRow(form, undefined, localize('settings.titleBlockRow', "Project number and engineer")));
		}
		this.renderSources();
	}

	/**
	 * The project language picks the reports' and drawings' language (Python side); the screens
	 * follow Code-OSS's display language (argv.json `locale`, the built-in Bangla language pack).
	 * Shown under Language with a button that switches the display language to match (restarts).
	 */
	private renderDisplayLanguage(cell: HTMLElement): void {
		const project = isObject(this.document?.project) ? this.document.project : {};
		const wanted = project.language === 'bn' ? 'bn' : 'en';
		const shown = displayLanguage.toLowerCase().startsWith('bn') ? 'bn' : 'en';
		const names: Record<string, string> = { en: 'English', bn: 'বাংলা' };
		append(cell, $('span.settings-source-value', undefined, wanted === shown
			? localize('settings.displayLanguageSame', "{0}, like the reports and drawings.", names[shown])
			: localize('settings.displayLanguageDiffers', "{0}. The reports and drawings are in {1}.", names[shown], names[wanted])));
		if (wanted === shown) {
			return;
		}
		const button = this.pageDisposables.add(new Button(append(cell, $('span.settings-source-action')), { ...defaultButtonStyles, secondary: true }));
		button.label = localize('settings.useDisplayLanguage', "Show Screens in {0}", names[wanted]);
		button.setTitle(localize('settings.useDisplayLanguageHint', "Sets SAEngine's display language and restarts it. Every window of SAEngine uses it; strings not yet translated stay in English."));
		this.pageDisposables.add(button.onDidClick(() => void this.localeService.setLocale({ id: wanted, label: names[wanted] })));
	}

	/** Drawings: the title block's project number and engineer come from Project (one home). */
	private renderTitleBlockSource(cell: HTMLElement): void {
		const project = isObject(this.document?.project) ? this.document.project : {};
		const text = (value: JsonValue | undefined) => typeof value === 'string' && value ? value : localize('settings.notEntered', "not entered");
		append(cell, $('span.settings-source-value', undefined, localize('settings.titleBlockFromProject', "from Project: {0}, {1}. Edit them in Project; every sheet prints them.", text(project.number), text(project.engineer))));
		const button = this.pageDisposables.add(new Button(append(cell, $('span.settings-source-action')), { ...defaultButtonStyles, secondary: true }));
		button.label = localize('settings.showProject', "Show Project");
		this.pageDisposables.add(button.onDidClick(() => this.selectSection('project')));
	}

	/**
	 * The Seismic section's read-only summary: "SDC D (zone 2, Z 0.20, SD, occupancy II), I = 1,
	 * special detailing", and when the system is not permitted, why and a switch to one that is.
	 */
	private renderSeismicSummary(): void {
		const cell = this.seismicCell;
		const document = this.document;
		if (!cell || !document) {
			return;
		}
		this.seismicDisposables.clear();
		clearNode(cell);
		const soil = this.sources?.soil;
		const site = isObject(document.site) ? document.site : {};
		const siteClass = soil?.class && site.siteClassSource !== 'entered' ? soil.class : String(site.siteClass);
		const values = codeValues(document, soil?.class ? { class: soil.class, label: soil.label } : undefined);
		const value = (label: string) => values.find(v => v.label === label);
		const category = designCategory(document, siteClass);
		const occupancy = isObject(document.occupancy) ? document.occupancy : {};
		const detailing = value(localize('code.detailing', "Seismic detailing"));
		append(cell, $('span.settings-source-value', undefined, category
			? localize('settings.designCategorySummary', "SDC {0} (zone {1}, Z {2}, site class {3}, occupancy category {4}), I = {5}; {6} detailing",
				category.sdc, category.zone, value(localize('code.z', "Zone coefficient Z"))?.value ?? '—', siteClass, String(occupancy.category),
				value(localize('code.seismicImportance', "Seismic importance factor I"))?.value ?? '—', detailing?.value ?? '—')
			: localize('settings.designCategoryNone', "needs the zone: choose a location, or enter Z for a custom site")));
		if (detailing?.problem) {
			const warning = append(cell, $('span.settings-source-warning'));
			append(warning, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(warning, $('span', undefined, detailing.problem));
		}
		if (category?.alternative) {
			const target = BNBC.systems[category.alternative];
			const button = this.seismicDisposables.add(new Button(append(cell, $('span.settings-source-action')), { ...defaultButtonStyles, supportIcons: true }));
			button.label = localize('settings.useSystem', "Use {0}", target?.name ?? category.alternative);
			this.seismicDisposables.add(button.onDidClick(() => void this.switchSystem(category.alternative!)));
		}
	}

	private selectSection(id: string): void {
		if (id === this.sectionId && this.page.childElementCount) {
			return;
		}
		this.flush();
		this.sectionId = id;
		this._onDidChangePartSection.fire();
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
		// The design code first: which pack, its edition and what it provides itself.
		const pack = this.chosenPack;
		appendPropertyRow(panel, localize('settings.designCode', "Design code"), this.packChoices.find(o => o.id === chosenPackId(this.document))?.label ?? this.codeName);
		if (pack?.edition && pack.edition !== pack.name) {
			appendPropertyRow(panel, localize('settings.edition', "Edition"), pack.edition);
		}
		if (pack?.covers.length) {
			// What the pack provides; each opens the pack on the Packages page, where its tables are.
			const chips = append(panel, $('.settings-code-pack-chips', { 'aria-label': localize('settings.packProvides', "Provides") }));
			for (const label of new Set(pack.covers.map(coverageLabel))) {
				const chip = append(chips, $<HTMLButtonElement>('button.settings-code-pack-chip', { type: 'button' }, label));
				this.valuesDisposables.add(this.hoverService.setupDelayedHover(chip, { content: localize('settings.chipHover', "{0} of {1}: show the pack's tables on the Packages page", label, pack.name) }));
				this.valuesDisposables.add(addDisposableListener(chip, EventType.CLICK, () => void this.commands.executeCommand('saengine.codePacks.show')));
			}
		}
		const table = append(panel, $('.settings-values', { role: 'table', 'aria-label': localize('settings.codeValues', "Code Values") }));
		const soil = this.sources?.soil;
		const problems: string[] = [];
		for (const value of codeValues(this.document, soil?.class ? { class: soil.class, label: soil.label } : undefined)) {
			const row = append(table, $('.sa-props-row', { role: 'row' }));
			append(row, $('span.name', { role: 'cell' }, value.label));
			const cell = append(row, $('span.value', { role: 'cell' }));
			if (value.problem) {
				row.classList.add('problem');
				append(cell, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
				problems.push(value.problem);
			}
			append(cell, $('span', undefined, value.value));
			if (value.overridden) {
				row.classList.add('overridden');
			}
			// Where the value comes from, on hover: what it stands for, the table, or that it was overridden.
			const source = value.overridden ? localize('settings.overriddenSource', "Overridden in the settings ({0} gives it in {1}).", BNBC.edition, value.source) : localize('settings.source', "{0}, {1}", BNBC.edition, value.source);
			const content = [value.detail ? `${value.value}: ${value.detail}` : undefined, source, value.problem].filter(Boolean).join('\n');
			this.valuesDisposables.add(this.hoverService.setupDelayedHover(row, { content }));
			if (value.overridden) {
				append(cell, $('span.settings-overridden', { 'aria-label': localize('settings.overridden', "overridden") }, '*'));
			}
		}
		// A system the Seismic Design Category does not permit: say so and offer the switch.
		const site = isObject(this.document.site) ? this.document.site : {};
		const category = designCategory(this.document, soil?.class && site.siteClassSource !== 'entered' ? soil.class : String(site.siteClass));
		if (problems.length) {
			append(panel, $('.sa-props-note.settings-values-problem', { role: 'alert' }, problems.join(' ')));
		}
		if (category?.alternative) {
			const target = BNBC.systems[category.alternative];
			const button = this.valuesDisposables.add(new Button(append(panel, $('.settings-values-action')), { ...defaultButtonStyles, supportIcons: true }));
			button.label = localize('settings.switchSystem', "Switch to {0}", target?.name ?? category.alternative);
			this.valuesDisposables.add(button.onDidClick(() => void this.switchSystem(category.alternative!)));
		}
		append(panel, $('.sa-props-note', undefined, localize('settings.valuesNote', "From the {0} tables for the site, occupancy and structural system. * overridden in the settings. Hover a value for its source.", BNBC.edition)));
		if (chosenPackId(this.document) !== DEFAULT_CODE_PACK) {
			append(panel, $('.sa-props-note', undefined, localize('settings.valuesOtherPack', "These preview values come from the {0} tables built into this editor; the tables of {1} apply when the project is analysed and designed.", BNBC.edition, this.codeName)));
		}
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

	private readonly checksScheduler = this._register(new RunOnceScheduler(() => void this.reportChecks(), 500));

	/**
	 * The settings' problems for the part list (`02 Project Settings/checks.json`): the checks of
	 * the saved file and a structural system the Seismic Design Category does not permit, so the
	 * part is not "done" while any is open. Unsaved edits are not reported (the counts must match
	 * the saved file the stamps are taken from).
	 */
	private async reportChecks(): Promise<void> {
		const document = this.document;
		const resource = this.resource;
		if (!document || !resource || this.textFiles.isDirty(resource)) {
			return;
		}
		const items: IPartCheckItem[] = this.problems.map(p => ({ severity: 'error', message: p.message, ...(p.path ? { where: p.path } : {}) }));
		const soil = this.sources?.soil;
		const system = codeValues(document, soil?.class ? { class: soil.class, label: soil.label } : undefined).find(v => v.problem);
		if (system?.problem && !this.problems.some(p => p.path.startsWith('seismic'))) {
			items.push({ severity: 'error', message: system.problem, where: 'seismic.system' });
		}
		await this.partStatus.reportChecks('settings', { problems: items.length, items }, ['settings', 'soil']);
	}

	/** The status line: problems when there are any, otherwise what the settings are for. */
	private renderStatus(): void {
		const frame = this.documentFrame;
		if (!frame || !this.document) {
			return;
		}
		this.checksScheduler.schedule();
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
		const resource = this.resource;
		if (resource && this.textFiles.isDirty(resource)) {
			// Run All and the other parts read the saved file: make the unsaved edits hard to miss.
			frame.setStatus({
				severity: 'warning',
				text: localize('settings.unsaved', "Unsaved changes: the analysis and the other parts read the saved settings."),
				link: { label: localize('settings.save', "Save"), run: () => void this.textFiles.save(resource) },
			});
			return;
		}
		frame.setStatus({ text: localize('settings.status', "{0} governs; every code value can be overridden. Read by the floor plan, the building model and the analysis.", this.codeName) });
	}
}
