/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { IAction } from '../../../../base/common/actions.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { DisposableStore, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { MenuId, MenuItemAction, SubmenuItemAction } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr, ContextKeyExpression, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { CATALOG_TABS, CATALOG_TAB_SCOPES, CatalogTabId, RibbonScope } from './ribbonCatalog.generated.js';

/** Context key active while a Floor Plan or CAD drawing editor is focused. */
export const SAENGINE_DRAFT_CONTEXT = 'saengineDraftActive';

export const DraftActiveContext = new RawContextKey<boolean>(
	SAENGINE_DRAFT_CONTEXT,
	false,
	localize('saengine.draftActive', "Whether a SAEngine Floor Plan or CAD drawing editor is active")
);

/** Context key identifying the engineering domain of an active SAEngine U3 data panel editor. */
export const SAENGINE_DATA_PANEL_PART_CONTEXT = 'saengineDataPanelPart';

export const DataPanelPartContext = new RawContextKey<string>(
	SAENGINE_DATA_PANEL_PART_CONTEXT,
	'',
	localize('saengine.dataPanelPart', "The engineering domain of the active SAEngine U3 data panel")
);

/** Context key identifying the active sub-view of an SAEngine editor. */
export const SAENGINE_SUB_VIEW_CONTEXT = 'saengineSubView';

export const SubViewContext = new RawContextKey<string>(
	SAENGINE_SUB_VIEW_CONTEXT,
	'',
	localize('saengine.subView', "The active sub-view of the active SAEngine editor")
);

/** SAEngine editor pane IDs used in contextual ribbon `when` rules (plain strings: no cross-contrib imports). */
export const SAENGINE_EDITOR_IDS = {
	soil: 'workbench.editor.saengine.soil',
	settings: 'workbench.editor.saengine.settings',
	codePacks: 'workbench.editor.saengine.codePacks',
	library: 'workbench.editor.saengine.library',
	sectionDesigner: 'workbench.editor.saengine.sectionDesigner',
	floorPlan: 'workbench.editor.saengine.floorPlan',
	grids: 'workbench.editor.saengine.grids',
	membersTable: 'workbench.editor.saengine.membersTable',
	structureModeler: 'workbench.editor.saengine.structureModeler',
	structure: 'workbench.editor.saengine.structure',
	cad: 'workbench.editor.saengine.cad',
	architecture: 'workbench.editor.saengine.architecture',
	building: 'workbench.editor.saengine.building',
	mep: 'workbench.editor.saengine.mep',
	femModel: 'workbench.editor.saengine.femModel',
	femResults: 'workbench.editor.saengine.femResults',
	femCfdWind: 'workbench.editor.saengine.femCfdWind',
	femDesignProposal: 'workbench.editor.saengine.femDesignProposal',
	femStrutAndTie: 'workbench.editor.saengine.femStrutAndTie',
	substructure: 'workbench.editor.saengine.substructure',
	boq: 'workbench.editor.saengine.boq',
	rates: 'workbench.editor.saengine.rates',
	exports: 'workbench.editor.saengine.exports',
	drawingPreview: 'workbench.editor.saengine.drawingPreview',
	reportTemplate: 'workbench.editor.saengine.reportTemplate',
	worksheet: 'workbench.editor.saengine.worksheet',
	officeTools: 'workbench.editor.saengine.officeTools',
	studies: 'workbench.editor.saengine.studies',
	graph: 'workbench.editor.saengine.graph',
	dataPanel: 'workbench.editor.saengine.dataPanel',
	overview: 'workbench.editor.saengine.overview',
} as const;

export type RibbonTabId =
	| 'home'
	| 'project'
	| 'soil'
	| 'soilTests'
	| 'soilBearing'
	| 'soilSeismic'
	| 'soilEarth'
	| 'soilSite'
	| 'settings'
	| 'settingsLoads'
	| 'settingsHazard'
	| 'settingsChecks'
	| 'settingsOverrides'
	| 'library'
	| 'librarySections'
	| 'libraryObjects'
	| 'libraryChecks'
	| 'plan'
	| 'architecture'
	| 'architectureRooms'
	| 'architectureExchange'
	| 'architectureEnvironment'
	| 'bim3d'
	| 'bimExchange'
	| 'bimFabrication'
	| 'bimStudies'
	| 'mepCoordination'
	| 'mepIssues'
	| 'mepPlumbing'
	| 'mepPlumbingDesign'
	| 'mepHvac'
	| 'mepHvacAnalysis'
	| 'mepElectrical'
	| 'mepPowerSystems'
	| 'mepFire'
	| 'mepFireSystems'
	| 'mepSystems'
	| 'analyze'
	| 'results'
	| 'design'
	| 'femLoads'
	| 'femSeismic'
	| 'femWind'
	| 'femNonlinear'
	| 'femServiceability'
	| 'foundations'
	| 'foundationsPiles'
	| 'foundationsPileAnalysis'
	| 'foundationsRetaining'
	| 'foundationsSpecial'
	| 'foundationsReport'
	| 'boq'
	| 'boqCosting'
	| 'boqSchedule'
	| 'boqTakeoff'
	| 'documents'
	| 'documentsDrawings'
	| 'documentsSheets'
	| 'documentsSchedules'
	| 'documentsReports'
	| 'studies'
	| 'studiesDesign'
	| 'studiesEnvironment'
	| 'studiesSite'
	| 'studiesVerification'
	| 'draft'
	| 'insert'
	| 'annotate'
	| 'parametric'
	| 'view'
	| 'manage'
	| 'output'
	| 'exportsExchange'
	| 'exportsFabrication'
	| 'exportsArchive'
	| CatalogTabId;

/**
 * MenuId per ribbon tab. Other contributions add buttons via `registerAction2` or
 * `MenuRegistry.appendMenuItem` using `group: '<order>_<GroupName>'`, e.g. `'3_Electrical'`.
 */
export const RibbonMenus = {
	Home: MenuId.for('SaengineRibbon.Home'),
	Project: MenuId.for('SaengineRibbon.Project'),
	Soil: MenuId.for('SaengineRibbon.Soil'),
	SoilTests: MenuId.for('SaengineRibbon.SoilTests'),
	SoilBearing: MenuId.for('SaengineRibbon.SoilBearing'),
	SoilSeismic: MenuId.for('SaengineRibbon.SoilSeismic'),
	SoilEarth: MenuId.for('SaengineRibbon.SoilEarth'),
	SoilSite: MenuId.for('SaengineRibbon.SoilSite'),
	Settings: MenuId.for('SaengineRibbon.Settings'),
	SettingsLoads: MenuId.for('SaengineRibbon.SettingsLoads'),
	SettingsHazard: MenuId.for('SaengineRibbon.SettingsHazard'),
	SettingsChecks: MenuId.for('SaengineRibbon.SettingsChecks'),
	SettingsOverrides: MenuId.for('SaengineRibbon.SettingsOverrides'),
	Library: MenuId.for('SaengineRibbon.Library'),
	LibrarySections: MenuId.for('SaengineRibbon.LibrarySections'),
	LibraryObjects: MenuId.for('SaengineRibbon.LibraryObjects'),
	LibraryChecks: MenuId.for('SaengineRibbon.LibraryChecks'),
	Plan: MenuId.for('SaengineRibbon.Plan'),
	Architecture: MenuId.for('SaengineRibbon.Architecture'),
	ArchitectureRooms: MenuId.for('SaengineRibbon.ArchitectureRooms'),
	ArchitectureExchange: MenuId.for('SaengineRibbon.ArchitectureExchange'),
	ArchitectureEnvironment: MenuId.for('SaengineRibbon.ArchitectureEnvironment'),
	Bim3D: MenuId.for('SaengineRibbon.Bim3D'),
	BimExchange: MenuId.for('SaengineRibbon.BimExchange'),
	BimFabrication: MenuId.for('SaengineRibbon.BimFabrication'),
	BimStudies: MenuId.for('SaengineRibbon.BimStudies'),
	MepCoordination: MenuId.for('SaengineRibbon.MepCoordination'),
	MepIssues: MenuId.for('SaengineRibbon.MepIssues'),
	MepPlumbing: MenuId.for('SaengineRibbon.MepPlumbing'),
	MepPlumbingDesign: MenuId.for('SaengineRibbon.MepPlumbingDesign'),
	MepHvac: MenuId.for('SaengineRibbon.MepHvac'),
	MepHvacAnalysis: MenuId.for('SaengineRibbon.MepHvacAnalysis'),
	MepElectrical: MenuId.for('SaengineRibbon.MepElectrical'),
	MepPowerSystems: MenuId.for('SaengineRibbon.MepPowerSystems'),
	MepFire: MenuId.for('SaengineRibbon.MepFire'),
	MepFireSystems: MenuId.for('SaengineRibbon.MepFireSystems'),
	MepSystems: MenuId.for('SaengineRibbon.MepSystems'),
	Analyze: MenuId.for('SaengineRibbon.Analyze'),
	Results: MenuId.for('SaengineRibbon.Results'),
	Design: MenuId.for('SaengineRibbon.Design'),
	FemLoads: MenuId.for('SaengineRibbon.FemLoads'),
	FemSeismic: MenuId.for('SaengineRibbon.FemSeismic'),
	FemWind: MenuId.for('SaengineRibbon.FemWind'),
	FemNonlinear: MenuId.for('SaengineRibbon.FemNonlinear'),
	FemServiceability: MenuId.for('SaengineRibbon.FemServiceability'),
	Foundations: MenuId.for('SaengineRibbon.Foundations'),
	FoundationsPiles: MenuId.for('SaengineRibbon.FoundationsPiles'),
	FoundationsPileAnalysis: MenuId.for('SaengineRibbon.FoundationsPileAnalysis'),
	FoundationsRetaining: MenuId.for('SaengineRibbon.FoundationsRetaining'),
	FoundationsSpecial: MenuId.for('SaengineRibbon.FoundationsSpecial'),
	FoundationsReport: MenuId.for('SaengineRibbon.FoundationsReport'),
	BOQ: MenuId.for('SaengineRibbon.BOQ'),
	BOQCosting: MenuId.for('SaengineRibbon.BOQCosting'),
	BOQSchedule: MenuId.for('SaengineRibbon.BOQSchedule'),
	BOQTakeoff: MenuId.for('SaengineRibbon.BOQTakeoff'),
	Documents: MenuId.for('SaengineRibbon.Documents'),
	DocumentsDrawings: MenuId.for('SaengineRibbon.DocumentsDrawings'),
	DocumentsSheets: MenuId.for('SaengineRibbon.DocumentsSheets'),
	DocumentsSchedules: MenuId.for('SaengineRibbon.DocumentsSchedules'),
	DocumentsReports: MenuId.for('SaengineRibbon.DocumentsReports'),
	Studies: MenuId.for('SaengineRibbon.Studies'),
	StudiesDesign: MenuId.for('SaengineRibbon.StudiesDesign'),
	StudiesEnvironment: MenuId.for('SaengineRibbon.StudiesEnvironment'),
	StudiesSite: MenuId.for('SaengineRibbon.StudiesSite'),
	StudiesVerification: MenuId.for('SaengineRibbon.StudiesVerification'),
	ExportsExchange: MenuId.for('SaengineRibbon.ExportsExchange'),
	ExportsFabrication: MenuId.for('SaengineRibbon.ExportsFabrication'),
	ExportsArchive: MenuId.for('SaengineRibbon.ExportsArchive'),
	Insert: MenuId.for('SaengineRibbon.Insert'),
	Draft: MenuId.for('SaengineRibbon.Draft'),
	Annotate: MenuId.for('SaengineRibbon.Annotate'),
	Parametric: MenuId.for('SaengineRibbon.Parametric'),
	View: MenuId.for('SaengineRibbon.View'),
	Manage: MenuId.for('SaengineRibbon.Manage'),
	Output: MenuId.for('SaengineRibbon.Output'),
} as const;

export interface IRibbonTabDescriptor {
	readonly id: RibbonTabId;
	readonly label: string;
	readonly menuId: MenuId;
	readonly contextual?: boolean;
	readonly contextualTag?: string;
	readonly when?: ContextKeyExpression;
}

function anyOf(exprs: readonly [ContextKeyExpression, ...ContextKeyExpression[]]): ContextKeyExpression {
	return ContextKeyExpr.or(...exprs) ?? exprs[0];
}

function allOf(exprs: readonly [ContextKeyExpression, ...ContextKeyExpression[]]): ContextKeyExpression {
	return ContextKeyExpr.and(...exprs) ?? exprs[0];
}

export function subViewWhen(...subViews: readonly [string, ...string[]]): ContextKeyExpression {
	return anyOf([SubViewContext.isEqualTo(subViews[0]), ...subViews.slice(1).map(subView => SubViewContext.isEqualTo(subView))]);
}

export function mepDisciplineWhen(discipline: 'coordination' | 'plumbing' | 'hvac' | 'electrical' | 'fire'): ContextKeyExpression {
	return subViewWhen(`mep.${discipline}`, `mep.${discipline}.data`, `mep.${discipline}.results`);
}

export function editorWhen(editorIds: readonly [string, ...string[]], dataPanelPart?: string): ContextKeyExpression {
	const checks: [ContextKeyExpression, ...ContextKeyExpression[]] = [
		ActiveEditorContext.isEqualTo(editorIds[0]),
		...editorIds.slice(1).map(id => ActiveEditorContext.isEqualTo(id)),
	];
	if (dataPanelPart) {
		const panelExpr = ContextKeyExpr.and(
			ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.dataPanel),
			DataPanelPartContext.isEqualTo(dataPanelPart),
		);
		if (panelExpr) {
			checks.push(panelExpr);
		}
	}
	return anyOf(checks);
}

const SPECIALIZED_EDITOR_IDS: readonly [string, ...string[]] = [
	SAENGINE_EDITOR_IDS.soil,
	SAENGINE_EDITOR_IDS.settings,
	SAENGINE_EDITOR_IDS.codePacks,
	SAENGINE_EDITOR_IDS.library,
	SAENGINE_EDITOR_IDS.sectionDesigner,
	SAENGINE_EDITOR_IDS.floorPlan,
	SAENGINE_EDITOR_IDS.grids,
	SAENGINE_EDITOR_IDS.membersTable,
	SAENGINE_EDITOR_IDS.structureModeler,
	SAENGINE_EDITOR_IDS.structure,
	SAENGINE_EDITOR_IDS.cad,
	SAENGINE_EDITOR_IDS.architecture,
	SAENGINE_EDITOR_IDS.building,
	SAENGINE_EDITOR_IDS.mep,
	SAENGINE_EDITOR_IDS.femModel,
	SAENGINE_EDITOR_IDS.femResults,
	SAENGINE_EDITOR_IDS.femCfdWind,
	SAENGINE_EDITOR_IDS.femDesignProposal,
	SAENGINE_EDITOR_IDS.femStrutAndTie,
	SAENGINE_EDITOR_IDS.substructure,
	SAENGINE_EDITOR_IDS.boq,
	SAENGINE_EDITOR_IDS.rates,
	SAENGINE_EDITOR_IDS.exports,
	SAENGINE_EDITOR_IDS.drawingPreview,
	SAENGINE_EDITOR_IDS.reportTemplate,
	SAENGINE_EDITOR_IDS.worksheet,
	SAENGINE_EDITOR_IDS.officeTools,
	SAENGINE_EDITOR_IDS.studies,
	SAENGINE_EDITOR_IDS.graph,
];

const SPECIALIZED_PANEL_PARTS: readonly [string, ...string[]] = [
	'soil',
	'settings',
	'library',
	'plan',
	'architecture',
	'bim3d',
	'mep',
	'fem',
	'foundations',
	'boq',
	'output',
	'documents',
	'studies',
];

const NOT_SPECIALIZED_PANEL = allOf([
	DataPanelPartContext.notEqualsTo(SPECIALIZED_PANEL_PARTS[0]),
	...SPECIALIZED_PANEL_PARTS.slice(1).map(part => DataPanelPartContext.notEqualsTo(part)),
]);

export const PROJECT_TAB_WHEN: ContextKeyExpression = allOf([
	ActiveEditorContext.notEqualsTo(SPECIALIZED_EDITOR_IDS[0]),
	...SPECIALIZED_EDITOR_IDS.slice(1).map(id => ActiveEditorContext.notEqualsTo(id)),
	anyOf([ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.dataPanel), NOT_SPECIALIZED_PANEL]),
]);

export const FLOOR_PLAN_WHEN = ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.floorPlan);
export const CAD_ONLY_WHEN = ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.cad);
export const DRAFT_WHEN = editorWhen([SAENGINE_EDITOR_IDS.floorPlan, SAENGINE_EDITOR_IDS.cad]);
export const SOIL_WHEN = editorWhen([SAENGINE_EDITOR_IDS.soil], 'soil');
export const SETTINGS_WHEN = editorWhen([SAENGINE_EDITOR_IDS.settings, SAENGINE_EDITOR_IDS.codePacks], 'settings');
export const LIBRARY_WHEN = editorWhen([SAENGINE_EDITOR_IDS.library, SAENGINE_EDITOR_IDS.sectionDesigner], 'library');
export const PLAN_SUB_WHEN = editorWhen([
	SAENGINE_EDITOR_IDS.floorPlan,
	SAENGINE_EDITOR_IDS.grids,
	SAENGINE_EDITOR_IDS.membersTable,
	SAENGINE_EDITOR_IDS.structureModeler,
	SAENGINE_EDITOR_IDS.structure,
], 'plan');
export const ARCHITECTURE_WHEN = editorWhen([SAENGINE_EDITOR_IDS.architecture], 'architecture');
export const BIM_WHEN = editorWhen([SAENGINE_EDITOR_IDS.building], 'bim3d');
const BIM_RIBBON_WHEN = allOf([
	BIM_WHEN,
	anyOf([subViewWhen('bim.3d', 'bim.additions', 'bim.summary'), ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.dataPanel)]),
]);
export const MEP_WHEN = editorWhen([SAENGINE_EDITOR_IDS.mep], 'mep');
const MEP_COORDINATION_WHEN = allOf([MEP_WHEN, mepDisciplineWhen('coordination')]);
const MEP_PLUMBING_WHEN = allOf([MEP_WHEN, mepDisciplineWhen('plumbing')]);
const MEP_HVAC_WHEN = allOf([MEP_WHEN, mepDisciplineWhen('hvac')]);
const MEP_ELECTRICAL_WHEN = allOf([MEP_WHEN, mepDisciplineWhen('electrical')]);
const MEP_FIRE_WHEN = allOf([MEP_WHEN, mepDisciplineWhen('fire')]);
const MEP_SYSTEMS_WHEN = allOf([MEP_WHEN, subViewWhen('mep.systems')]);
export const FEM_WHEN = editorWhen([
	SAENGINE_EDITOR_IDS.femModel,
	SAENGINE_EDITOR_IDS.femResults,
	SAENGINE_EDITOR_IDS.femCfdWind,
	SAENGINE_EDITOR_IDS.femDesignProposal,
	SAENGINE_EDITOR_IDS.femStrutAndTie,
], 'fem');
/** Each FEM sub-window shows only its own tabs (owner, 2026-11-23). */
const FEM_MODEL_TABS_WHEN = allOf([FEM_WHEN, subViewWhen('fem.model')]);
const FEM_PUSHOVER_TABS_WHEN = allOf([FEM_WHEN, subViewWhen('fem.pushover')]);
const FEM_CHARTS_TABS_WHEN = allOf([FEM_WHEN, subViewWhen('fem.charts')]);
const FEM_DESIGN_TABS_WHEN = allOf([FEM_WHEN, subViewWhen('fem.design')]);
export const FOUNDATIONS_WHEN = editorWhen([SAENGINE_EDITOR_IDS.substructure], 'foundations');
export const BOQ_WHEN = editorWhen([SAENGINE_EDITOR_IDS.boq, SAENGINE_EDITOR_IDS.rates], 'boq');
export const EXPORTS_WHEN = editorWhen([SAENGINE_EDITOR_IDS.exports], 'output');
export const DOCUMENTS_WHEN = editorWhen([
	SAENGINE_EDITOR_IDS.drawingPreview,
	SAENGINE_EDITOR_IDS.reportTemplate,
	SAENGINE_EDITOR_IDS.worksheet,
], 'documents');
export const STUDIES_WHEN = editorWhen([
	SAENGINE_EDITOR_IDS.officeTools,
	SAENGINE_EDITOR_IDS.studies,
	SAENGINE_EDITOR_IDS.graph,
], 'studies');

const BASE_TABS: readonly IRibbonTabDescriptor[] = [
	{ id: 'home', label: localize('ribbon.tab.home', "Home"), menuId: RibbonMenus.Home },
	{
		id: 'project',
		label: localize('ribbon.tab.project', "Project"),
		menuId: RibbonMenus.Project,
		when: PROJECT_TAB_WHEN,
	},
	{
		id: 'soil',
		label: localize('ribbon.tab.soil', "Investigation"),
		menuId: RibbonMenus.Soil,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'soilTests',
		label: localize('ribbon.tab.soilTests', "Lab Tests"),
		menuId: RibbonMenus.SoilTests,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'soilBearing',
		label: localize('ribbon.tab.soilBearing', "Bearing & Settlement"),
		menuId: RibbonMenus.SoilBearing,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'soilSeismic',
		label: localize('ribbon.tab.soilSeismic', "Seismic & Liquefaction"),
		menuId: RibbonMenus.SoilSeismic,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'soilEarth',
		label: localize('ribbon.tab.soilEarth', "Earth Pressure & Chemistry"),
		menuId: RibbonMenus.SoilEarth,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'soilSite',
		label: localize('ribbon.tab.soilSite', "Site & GIS"),
		menuId: RibbonMenus.SoilSite,
		contextual: true,
		when: SOIL_WHEN,
	},
	{
		id: 'settings',
		label: localize('ribbon.tab.settings', "Code & Packs"),
		menuId: RibbonMenus.Settings,
		contextual: true,
		when: SETTINGS_WHEN,
	},
	{
		id: 'settingsLoads',
		label: localize('ribbon.tab.settingsLoads', "Loads"),
		menuId: RibbonMenus.SettingsLoads,
		contextual: true,
		when: SETTINGS_WHEN,
	},
	{
		id: 'settingsHazard',
		label: localize('ribbon.tab.settingsHazard', "Seismic & Wind"),
		menuId: RibbonMenus.SettingsHazard,
		contextual: true,
		when: SETTINGS_WHEN,
	},
	{
		id: 'settingsChecks',
		label: localize('ribbon.tab.settingsChecks', "Checks"),
		menuId: RibbonMenus.SettingsChecks,
		contextual: true,
		when: SETTINGS_WHEN,
	},
	{
		id: 'settingsOverrides',
		label: localize('ribbon.tab.settingsOverrides', "Overrides"),
		menuId: RibbonMenus.SettingsOverrides,
		contextual: true,
		when: SETTINGS_WHEN,
	},
	{
		id: 'library',
		label: localize('ribbon.tab.library', "Materials"),
		menuId: RibbonMenus.Library,
		contextual: true,
		when: LIBRARY_WHEN,
	},
	{
		id: 'librarySections',
		label: localize('ribbon.tab.librarySections', "Sections"),
		menuId: RibbonMenus.LibrarySections,
		contextual: true,
		when: LIBRARY_WHEN,
	},
	{
		id: 'libraryObjects',
		label: localize('ribbon.tab.libraryObjects', "Object Types"),
		menuId: RibbonMenus.LibraryObjects,
		contextual: true,
		when: LIBRARY_WHEN,
	},
	{
		id: 'libraryChecks',
		label: localize('ribbon.tab.libraryChecks', "Modifiers & Checks"),
		menuId: RibbonMenus.LibraryChecks,
		contextual: true,
		when: LIBRARY_WHEN,
	},
	{
		id: 'plan',
		label: localize('ribbon.tab.plan', "Structure"),
		menuId: RibbonMenus.Plan,
		contextual: true,
		when: PLAN_SUB_WHEN,
	},
	{
		id: 'architecture',
		label: localize('ribbon.tab.architecture', "Architecture"),
		menuId: RibbonMenus.Architecture,
		contextual: true,
		when: ARCHITECTURE_WHEN,
	},
	{
		id: 'architectureRooms',
		label: localize('ribbon.tab.architectureRooms', "Rooms & Schedules"),
		menuId: RibbonMenus.ArchitectureRooms,
		contextual: true,
		when: ARCHITECTURE_WHEN,
	},
	{
		id: 'architectureExchange',
		label: localize('ribbon.tab.architectureExchange', "Import & Export"),
		menuId: RibbonMenus.ArchitectureExchange,
		contextual: true,
		when: ARCHITECTURE_WHEN,
	},
	{
		id: 'architectureEnvironment',
		label: localize('ribbon.tab.architectureEnvironment', "Environment"),
		menuId: RibbonMenus.ArchitectureEnvironment,
		contextual: true,
		when: ARCHITECTURE_WHEN,
	},
	{
		id: 'bim3d',
		label: localize('ribbon.tab.bim3d', "3D View"),
		menuId: RibbonMenus.Bim3D,
		contextual: true,
		when: BIM_RIBBON_WHEN,
	},
	{
		id: 'bimExchange',
		label: localize('ribbon.tab.bimExchange', "IFC & Exchange"),
		menuId: RibbonMenus.BimExchange,
		contextual: true,
		when: BIM_RIBBON_WHEN,
	},
	{
		id: 'bimFabrication',
		label: localize('ribbon.tab.bimFabrication', "Rebar & Fabrication"),
		menuId: RibbonMenus.BimFabrication,
		contextual: true,
		when: BIM_RIBBON_WHEN,
	},
	{
		id: 'bimStudies',
		label: localize('ribbon.tab.bimStudies', "Studies"),
		menuId: RibbonMenus.BimStudies,
		contextual: true,
		when: BIM_RIBBON_WHEN,
	},
	{
		id: 'mepCoordination',
		label: localize('ribbon.tab.mepCoordination', "Coordination"),
		menuId: RibbonMenus.MepCoordination,
		contextual: true,
		when: MEP_COORDINATION_WHEN,
	},
	{
		id: 'mepIssues',
		label: localize('ribbon.tab.mepIssues', "Issues"),
		menuId: RibbonMenus.MepIssues,
		contextual: true,
		when: MEP_COORDINATION_WHEN,
	},
	{
		id: 'mepPlumbing',
		label: localize('ribbon.tab.mepPlumbing', "Plumbing"),
		menuId: RibbonMenus.MepPlumbing,
		contextual: true,
		when: MEP_PLUMBING_WHEN,
	},
	{
		id: 'mepPlumbingDesign',
		label: localize('ribbon.tab.mepPlumbingDesign', "Plumbing Design"),
		menuId: RibbonMenus.MepPlumbingDesign,
		contextual: true,
		when: MEP_PLUMBING_WHEN,
	},
	{
		id: 'mepHvac',
		label: localize('ribbon.tab.mepHvac', "HVAC"),
		menuId: RibbonMenus.MepHvac,
		contextual: true,
		when: MEP_HVAC_WHEN,
	},
	{
		id: 'mepHvacAnalysis',
		label: localize('ribbon.tab.mepHvacAnalysis', "HVAC Analysis"),
		menuId: RibbonMenus.MepHvacAnalysis,
		contextual: true,
		when: MEP_HVAC_WHEN,
	},
	{
		id: 'mepElectrical',
		label: localize('ribbon.tab.mepElectrical', "Electrical"),
		menuId: RibbonMenus.MepElectrical,
		contextual: true,
		when: MEP_ELECTRICAL_WHEN,
	},
	{
		id: 'mepPowerSystems',
		label: localize('ribbon.tab.mepPowerSystems', "Power Systems"),
		menuId: RibbonMenus.MepPowerSystems,
		contextual: true,
		when: MEP_ELECTRICAL_WHEN,
	},
	{
		id: 'mepFire',
		label: localize('ribbon.tab.mepFire', "Fire"),
		menuId: RibbonMenus.MepFire,
		contextual: true,
		when: MEP_FIRE_WHEN,
	},
	{
		id: 'mepFireSystems',
		label: localize('ribbon.tab.mepFireSystems', "Fire Systems"),
		menuId: RibbonMenus.MepFireSystems,
		contextual: true,
		when: MEP_FIRE_WHEN,
	},
	{
		id: 'mepSystems',
		label: localize('ribbon.tab.mepSystems', "Systems"),
		menuId: RibbonMenus.MepSystems,
		contextual: true,
		when: MEP_SYSTEMS_WHEN,
	},
	{
		id: 'analyze',
		label: localize('ribbon.tab.analyze', "Analyze"),
		menuId: RibbonMenus.Analyze,
		contextual: true,
		when: FEM_MODEL_TABS_WHEN,
	},
	{
		id: 'results',
		label: localize('ribbon.tab.results', "Results"),
		menuId: RibbonMenus.Results,
		contextual: true,
		when: FEM_CHARTS_TABS_WHEN,
	},
	{
		id: 'design',
		label: localize('ribbon.tab.design', "Design"),
		menuId: RibbonMenus.Design,
		contextual: true,
		when: FEM_DESIGN_TABS_WHEN,
	},
	{
		id: 'femLoads',
		label: localize('ribbon.tab.femLoads', "Loads & Combinations"),
		menuId: RibbonMenus.FemLoads,
		contextual: true,
		when: FEM_MODEL_TABS_WHEN,
	},
	{
		id: 'femSeismic',
		label: localize('ribbon.tab.femSeismic', "Seismic"),
		menuId: RibbonMenus.FemSeismic,
		contextual: true,
		when: FEM_MODEL_TABS_WHEN,
	},
	{
		id: 'femWind',
		label: localize('ribbon.tab.femWind', "Wind"),
		menuId: RibbonMenus.FemWind,
		contextual: true,
		when: FEM_MODEL_TABS_WHEN,
	},
	{
		id: 'femNonlinear',
		label: localize('ribbon.tab.femNonlinear', "Nonlinear & Stability"),
		menuId: RibbonMenus.FemNonlinear,
		contextual: true,
		when: FEM_PUSHOVER_TABS_WHEN,
	},
	{
		id: 'femServiceability',
		label: localize('ribbon.tab.femServiceability', "Serviceability"),
		menuId: RibbonMenus.FemServiceability,
		contextual: true,
		when: FEM_CHARTS_TABS_WHEN,
	},
	{
		id: 'foundations',
		label: localize('ribbon.tab.foundations', "Shallow & Raft"),
		menuId: RibbonMenus.Foundations,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'foundationsPiles',
		label: localize('ribbon.tab.foundationsPiles', "Piles"),
		menuId: RibbonMenus.FoundationsPiles,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'foundationsPileAnalysis',
		label: localize('ribbon.tab.foundationsPileAnalysis', "Pile Analysis"),
		menuId: RibbonMenus.FoundationsPileAnalysis,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'foundationsRetaining',
		label: localize('ribbon.tab.foundationsRetaining', "Retaining & Excavation"),
		menuId: RibbonMenus.FoundationsRetaining,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'foundationsSpecial',
		label: localize('ribbon.tab.foundationsSpecial', "Slabs & Machine"),
		menuId: RibbonMenus.FoundationsSpecial,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'foundationsReport',
		label: localize('ribbon.tab.foundationsReport', "Detailing & Report"),
		menuId: RibbonMenus.FoundationsReport,
		contextual: true,
		when: FOUNDATIONS_WHEN,
	},
	{
		id: 'boq',
		label: localize('ribbon.tab.boq', "Quantities"),
		menuId: RibbonMenus.BOQ,
		contextual: true,
		when: BOQ_WHEN,
	},
	{
		id: 'boqCosting',
		label: localize('ribbon.tab.boqCosting', "Rates & Costing"),
		menuId: RibbonMenus.BOQCosting,
		contextual: true,
		when: BOQ_WHEN,
	},
	{
		id: 'boqSchedule',
		label: localize('ribbon.tab.boqSchedule', "Construction Schedule"),
		menuId: RibbonMenus.BOQSchedule,
		contextual: true,
		when: BOQ_WHEN,
	},
	{
		id: 'boqTakeoff',
		label: localize('ribbon.tab.boqTakeoff', "Takeoff"),
		menuId: RibbonMenus.BOQTakeoff,
		contextual: true,
		when: BOQ_WHEN,
	},
	{
		id: 'documents',
		label: localize('ribbon.tab.documents', "Documents"),
		menuId: RibbonMenus.Documents,
		contextual: true,
		when: DOCUMENTS_WHEN,
	},
	{
		id: 'documentsDrawings',
		label: localize('ribbon.tab.documentsDrawings', "Drawings"),
		menuId: RibbonMenus.DocumentsDrawings,
		contextual: true,
		when: DOCUMENTS_WHEN,
	},
	{
		id: 'documentsSheets',
		label: localize('ribbon.tab.documentsSheets', "Sheets & Issue"),
		menuId: RibbonMenus.DocumentsSheets,
		contextual: true,
		when: DOCUMENTS_WHEN,
	},
	{
		id: 'documentsSchedules',
		label: localize('ribbon.tab.documentsSchedules', "Schedules & Keynotes"),
		menuId: RibbonMenus.DocumentsSchedules,
		contextual: true,
		when: DOCUMENTS_WHEN,
	},
	{
		id: 'documentsReports',
		label: localize('ribbon.tab.documentsReports', "Reports & Worksheets"),
		menuId: RibbonMenus.DocumentsReports,
		contextual: true,
		when: DOCUMENTS_WHEN,
	},
	{
		id: 'studies',
		label: localize('ribbon.tab.studies', "Studies"),
		menuId: RibbonMenus.Studies,
		contextual: true,
		when: STUDIES_WHEN,
	},
	{
		id: 'studiesDesign',
		label: localize('ribbon.tab.studiesDesign', "Design Studies"),
		menuId: RibbonMenus.StudiesDesign,
		contextual: true,
		when: STUDIES_WHEN,
	},
	{
		id: 'studiesEnvironment',
		label: localize('ribbon.tab.studiesEnvironment', "Environment"),
		menuId: RibbonMenus.StudiesEnvironment,
		contextual: true,
		when: STUDIES_WHEN,
	},
	{
		id: 'studiesSite',
		label: localize('ribbon.tab.studiesSite', "Site & Terrain"),
		menuId: RibbonMenus.StudiesSite,
		contextual: true,
		when: STUDIES_WHEN,
	},
	{
		id: 'studiesVerification',
		label: localize('ribbon.tab.studiesVerification', "Verification"),
		menuId: RibbonMenus.StudiesVerification,
		contextual: true,
		when: STUDIES_WHEN,
	},
	{
		id: 'draft',
		label: localize('ribbon.tab.draft', "Draft"),
		menuId: RibbonMenus.Draft,
		contextual: true,
		contextualTag: localize('ribbon.tab.draftTag', "CAD"),
		when: DRAFT_WHEN,
	},
	{
		id: 'insert',
		label: localize('ribbon.tab.insert', "Insert"),
		menuId: RibbonMenus.Insert,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'annotate',
		label: localize('ribbon.tab.annotate', "Annotate"),
		menuId: RibbonMenus.Annotate,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'parametric',
		label: localize('ribbon.tab.parametric', "Parametric"),
		menuId: RibbonMenus.Parametric,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'view',
		label: localize('ribbon.tab.view', "View"),
		menuId: RibbonMenus.View,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'manage',
		label: localize('ribbon.tab.manage', "Manage"),
		menuId: RibbonMenus.Manage,
		contextual: true,
		when: DRAFT_WHEN,
	},
	{
		id: 'output',
		label: localize('ribbon.tab.output', "Output"),
		menuId: RibbonMenus.Output,
		contextual: true,
		when: anyOf([EXPORTS_WHEN, DRAFT_WHEN]),
	},
	{
		id: 'exportsExchange',
		label: localize('ribbon.tab.exportsExchange', "Exchange"),
		menuId: RibbonMenus.ExportsExchange,
		contextual: true,
		when: EXPORTS_WHEN,
	},
	{
		id: 'exportsFabrication',
		label: localize('ribbon.tab.exportsFabrication', "Fabrication"),
		menuId: RibbonMenus.ExportsFabrication,
		contextual: true,
		when: EXPORTS_WHEN,
	},
	{
		id: 'exportsArchive',
		label: localize('ribbon.tab.exportsArchive', "Archive & Validation"),
		menuId: RibbonMenus.ExportsArchive,
		contextual: true,
		when: EXPORTS_WHEN,
	},
];

/** The sub-view, or none (a data panel of the part, the structural modeller). */
function subViewOrNone(...subViews: readonly [string, ...string[]]): ContextKeyExpression {
	return anyOf([subViewWhen(...subViews), SubViewContext.isEqualTo('')]);
}

/**
 * Where a scope's tabs show: a window, or one sub-window of it (owner, 2026-11-23: every
 * sub-window shows only its own ribbon). The scopes come from scripts/ribbon/ribbon_catalog.json.
 */
export function scopeWhen(scope: RibbonScope): ContextKeyExpression {
	switch (scope) {
		case 'soil': return SOIL_WHEN;
		case 'settings': return SETTINGS_WHEN;
		// The settings editor reports its section (settingsEditor.ts SECTIONS), as the tree's entries group them.
		case 'settings.code': return allOf([SETTINGS_WHEN, subViewOrNone('settings.project', 'settings.occupancy', 'settings.construction', 'settings.site', 'settings.packages')]);
		case 'settings.loads': return allOf([SETTINGS_WHEN, subViewOrNone('settings.areaLoads', 'settings.cranes', 'settings.specialStructures', 'settings.combinations', 'settings.analysis')]);
		case 'settings.hazard': return allOf([SETTINGS_WHEN, subViewOrNone('settings.seismic', 'settings.wind')]);
		case 'settings.foundation': return allOf([SETTINGS_WHEN, subViewOrNone('settings.foundation')]);
		case 'settings.drawings': return allOf([SETTINGS_WHEN, subViewOrNone('settings.drawings', 'settings.detailing', 'settings.report')]);
		case 'settings.codeValues': return allOf([SETTINGS_WHEN, subViewOrNone('settings.codeOverrides')]);
		case 'materials': return allOf([LIBRARY_WHEN, subViewOrNone('library.materials')]);
		case 'objects': return allOf([LIBRARY_WHEN, subViewOrNone('library.objects')]);
		case 'plan.plan': return allOf([PLAN_SUB_WHEN, subViewOrNone('plan.plan')]);
		case 'plan.grids': return allOf([PLAN_SUB_WHEN, subViewWhen('plan.grids')]);
		case 'plan.members': return allOf([PLAN_SUB_WHEN, subViewWhen('plan.members')]);
		case 'architecture': return ARCHITECTURE_WHEN;
		case 'bim.3d': return allOf([BIM_WHEN, subViewOrNone('bim.3d')]);
		case 'bim.additions': return allOf([BIM_WHEN, subViewWhen('bim.additions')]);
		case 'bim.summary': return allOf([BIM_WHEN, subViewWhen('bim.summary')]);
		case 'mep.coordination': return MEP_COORDINATION_WHEN;
		case 'mep.plumbing': return MEP_PLUMBING_WHEN;
		case 'mep.hvac': return MEP_HVAC_WHEN;
		case 'mep.electrical': return MEP_ELECTRICAL_WHEN;
		case 'mep.fire': return MEP_FIRE_WHEN;
		case 'mep.systems': return MEP_SYSTEMS_WHEN;
		case 'fem.model': return FEM_MODEL_TABS_WHEN;
		case 'fem.charts': return FEM_CHARTS_TABS_WHEN;
		case 'fem.pushover': return FEM_PUSHOVER_TABS_WHEN;
		case 'fem.design': return FEM_DESIGN_TABS_WHEN;
		case 'fem.cfd': return allOf([FEM_WHEN, subViewWhen('fem.cfd')]);
		case 'fem.stm': return allOf([FEM_WHEN, subViewWhen('fem.stm')]);
		case 'foundations': return FOUNDATIONS_WHEN;
		case 'boq': return BOQ_WHEN;
		case 'documents.drawing': return allOf([DOCUMENTS_WHEN, subViewOrNone('documents.drawing')]);
		case 'documents.report': return allOf([DOCUMENTS_WHEN, subViewWhen('documents.report')]);
		case 'documents.worksheet': return allOf([DOCUMENTS_WHEN, subViewWhen('documents.worksheet')]);
		case 'studies': return STUDIES_WHEN;
		case 'exports': return EXPORTS_WHEN;
		case 'overview': return PROJECT_TAB_WHEN;
	}
}

/** The top window of a scope (`fem.model` -> `fem`), to place a window's catalog tabs after its own. */
function scopeWindow(scope: RibbonScope | undefined): string | undefined {
	return scope?.split('.')[0];
}

/** The menu of a catalog tab. */
export function catalogTabMenu(id: CatalogTabId): MenuId {
	return MenuId.for(`SaengineRibbon.Catalog.${id}`);
}

/**
 * The base tabs, each limited to its scope, with the catalog's tabs after the last tab of the
 * same window.
 */
function withCatalogTabs(base: readonly IRibbonTabDescriptor[]): readonly IRibbonTabDescriptor[] {
	const tabs = base.map(tab => {
		const scope = CATALOG_TAB_SCOPES[tab.id];
		return scope ? { ...tab, when: scopeWhen(scope) } : tab;
	});
	for (const catalogTab of CATALOG_TABS) {
		const descriptor: IRibbonTabDescriptor = {
			id: catalogTab.id,
			label: catalogTab.label,
			menuId: catalogTabMenu(catalogTab.id),
			// The Overview's tabs sit with Home and Project: the window has no contextual tab.
			contextual: catalogTab.scope !== 'overview',
			when: scopeWhen(catalogTab.scope),
		};
		const window = scopeWindow(catalogTab.scope);
		let at = -1;
		tabs.forEach((tab, index) => {
			if (scopeWindow(CATALOG_TAB_SCOPES[tab.id]) === window) {
				at = index;
			}
		});
		tabs.splice(at >= 0 ? at + 1 : tabs.length, 0, descriptor);
	}
	// A window's tabs for all its sub-windows (Project Settings: Checks, Units, Audit) come after
	// the tabs of the sub-window shown, so a section's own tab is the first one.
	const shared = tabs.filter(tab => {
		const scope = CATALOG_TAB_SCOPES[tab.id];
		return scope !== undefined && !scope.includes('.') && Object.values(CATALOG_TAB_SCOPES).some(other => other.startsWith(`${scope}.`));
	});
	for (const tab of shared) {
		tabs.splice(tabs.indexOf(tab), 1);
		const window = scopeWindow(CATALOG_TAB_SCOPES[tab.id]);
		let at = -1;
		tabs.forEach((other, index) => {
			if (scopeWindow(CATALOG_TAB_SCOPES[other.id]) === window) {
				at = index;
			}
		});
		tabs.splice(at + 1, 0, tab);
	}
	return tabs;
}

export const RIBBON_TABS: readonly IRibbonTabDescriptor[] = withCatalogTabs(BASE_TABS);

/** Maps a U3 data panel id and optional `part` descriptor property to a contextual ribbon domain key. */
export function resolveDataPanelPart(panelId: string | undefined, descriptorPart: string | undefined): string {
	if (!panelId) {
		return '';
	}
	if (panelId.startsWith('saengine.studies.')) {
		return 'studies';
	}
	if (panelId.startsWith('saengine.drawings.')) {
		return 'documents';
	}
	switch (descriptorPart) {
		case 'exports': return 'output';
		case 'substructure': return 'foundations';
		case 'bim': return 'bim3d';
		case 'floorPlan':
		case 'structure': return 'plan';
		case 'materials':
		case 'objects': return 'library';
		default: return descriptorPart ?? '';
	}
}

/** Maps a U3 data panel id to the MEP discipline sub-view so MEP panels keep their discipline tabs. */
export function resolveDataPanelSubView(panelId: string | undefined): string {
	if (!panelId?.startsWith('saengine.mep.')) {
		return '';
	}
	const segment = panelId.slice('saengine.mep.'.length).split('.')[0];
	switch (segment) {
		case 'coordination':
		case 'plumbing':
		case 'hvac':
		case 'electrical':
		case 'fire':
		case 'systems':
			return `mep.${segment}`;
		default:
			return '';
	}
}

/** Returns the ribbon tabs whose `when` rule matches the current context key state. */
export function getVisibleRibbonTabs(
	contextKeyService: Pick<IContextKeyService, 'contextMatchesRules'>,
	tabs: readonly IRibbonTabDescriptor[] = RIBBON_TABS,
): readonly IRibbonTabDescriptor[] {
	return tabs.filter(tab => !tab.when || contextKeyService.contextMatchesRules(tab.when));
}

/**
 * Picks the ribbon tab to show after switching editors: returns the remembered tab for
 * `editorKey` if still visible, otherwise the first contextual tab, falling back to the first visible tab.
 */
export function resolveActiveTabForEditor(
	editorKey: string,
	visibleTabs: readonly IRibbonTabDescriptor[],
	rememberedByEditor: ReadonlyMap<string, RibbonTabId>,
	subView = '',
): RibbonTabId {
	const remembered = rememberedByEditor.get(editorKey);
	if (remembered && visibleTabs.some(tab => tab.id === remembered)) {
		return remembered;
	}
	if (editorKey === SAENGINE_EDITOR_IDS.floorPlan) {
		return 'home';
	}
	if (subView === 'fem.charts' && visibleTabs.some(t => t.id === 'results')) {
		return 'results';
	}
	if (subView === 'fem.design' && visibleTabs.some(t => t.id === 'design')) {
		return 'design';
	}
	return visibleTabs.find(tab => tab.contextual)?.id ?? visibleTabs[0]?.id ?? 'home';
}

/**
 * Picks the ribbon tab where an active editor publishes its toolbar groups ("View", "<Editor name>", "Help"):
 * its first contextual tab, or the Project tab (avoiding Home unless on Floor Plan or no other tab is visible).
 */
export function resolveEditorToolbarTargetTab(
	visibleTabs: readonly IRibbonTabDescriptor[],
	editorKey = '',
	subView = '',
): RibbonTabId {
	if (editorKey === SAENGINE_EDITOR_IDS.floorPlan) {
		return 'home';
	}
	if (subView === 'fem.charts' && visibleTabs.some(t => t.id === 'results')) {
		return 'results';
	}
	if (subView === 'fem.design' && visibleTabs.some(t => t.id === 'design')) {
		return 'design';
	}
	return visibleTabs.find(tab => tab.contextual)?.id
		?? visibleTabs.find(tab => tab.id !== 'home')?.id
		?? visibleTabs[0]?.id
		?? 'home';
}

export type RibbonButtonSize = 'large' | 'small';

export interface IRibbonItemHint {
	readonly size?: RibbonButtonSize;
	readonly label?: string;
	readonly primaryCommandId?: string;
	readonly renderCustom?: (container: HTMLElement, instantiationService: IInstantiationService, action: MenuItemAction) => IDisposable;
}

export interface IRibbonCustomGroup {
	readonly tabId: RibbonTabId;
	readonly group: string;
	readonly label: string;
	readonly icon?: ThemeIcon;
	readonly collapsible?: boolean;
	readonly collapsePriority?: number;
	readonly getCollapsedActions?: (store: DisposableStore) => readonly IAction[];
	readonly render: (container: HTMLElement, instantiationService: IInstantiationService) => IDisposable;
}

const itemHints = new Map<string, IRibbonItemHint>();
const scopedItemHints = new Map<string, IRibbonItemHint>();
const groupLabels = new Map<string, string>();
const groupPriorities = new Map<string, number>();
const customGroups = new Map<RibbonTabId, IRibbonCustomGroup[]>();
const registryChangeEmitter = new Emitter<void>();

export const onDidChangeRibbonRegistry: Event<void> = registryChangeEmitter.event;

function scopedHintKey(menuId: MenuId, id: string): string {
	return `${menuId.id}\0${id}`;
}

/** Registers display hints (size, short label, split primary command) for a command or submenu id. */
export function registerRibbonItemHint(id: string, hint: IRibbonItemHint, menuId?: MenuId): IDisposable {
	const map = menuId ? scopedItemHints : itemHints;
	const key = menuId ? scopedHintKey(menuId, id) : id;
	const previous = map.get(key);
	map.set(key, hint);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (map.get(key) === hint) {
			if (previous !== undefined) {
				map.set(key, previous);
			} else {
				map.delete(key);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonItemHint(id: string, menuId?: MenuId): IRibbonItemHint | undefined {
	if (menuId) {
		const scoped = scopedItemHints.get(scopedHintKey(menuId, id));
		if (scoped) {
			return scoped;
		}
	}
	return itemHints.get(id);
}

/** Registers a localized group label for a group key (the suffix after `<order>_`). */
export function registerRibbonGroupLabel(groupKey: string, label: string): IDisposable {
	const previous = groupLabels.get(groupKey);
	groupLabels.set(groupKey, label);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (groupLabels.get(groupKey) === label) {
			if (previous !== undefined) {
				groupLabels.set(groupKey, previous);
			} else {
				groupLabels.delete(groupKey);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonGroupLabel(groupKey: string): string | undefined {
	return groupLabels.get(groupKey);
}

const groupWhens = new Map<string, ContextKeyExpression>();

function groupWhenKey(menuId: MenuId, rawGroup: string): string {
	return `${menuId.id}::${rawGroup}`;
}

/**
 * Shows a tab's group only while `when` holds (e.g. the MEP tab's Plumbing group only in the
 * Plumbing sub-window), so a sub-window's ribbon carries its own commands only.
 */
export function registerRibbonGroupWhen(menuId: MenuId, rawGroup: string, when: ContextKeyExpression): IDisposable {
	const key = groupWhenKey(menuId, rawGroup);
	groupWhens.set(key, when);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (groupWhens.get(key) === when) {
			groupWhens.delete(key);
			registryChangeEmitter.fire();
		}
	});
}

/** The visibility rule of a tab's group, if one was registered. */
export function getRibbonGroupWhen(menuId: MenuId, rawGroup: string): ContextKeyExpression | undefined {
	return groupWhens.get(groupWhenKey(menuId, rawGroup));
}

/** Registers a collapse priority for a group key (smaller values collapse first when space is tight). */
export function registerRibbonGroupPriority(groupKey: string, priority: number): IDisposable {
	const previous = groupPriorities.get(groupKey);
	groupPriorities.set(groupKey, priority);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		if (groupPriorities.get(groupKey) === priority) {
			if (previous !== undefined) {
				groupPriorities.set(groupKey, previous);
			} else {
				groupPriorities.delete(groupKey);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonGroupPriority(groupKey: string): number | undefined {
	return groupPriorities.get(groupKey);
}

/** Registers a custom-rendered ribbon group (such as Home's Workflow stepper). */
export function registerRibbonCustomGroup(group: IRibbonCustomGroup): IDisposable {
	let list = customGroups.get(group.tabId);
	if (!list) {
		list = [];
		customGroups.set(group.tabId, list);
	}
	list.push(group);
	registryChangeEmitter.fire();
	return toDisposable(() => {
		const entries = customGroups.get(group.tabId);
		if (!entries) {
			return;
		}
		const idx = entries.indexOf(group);
		if (idx >= 0) {
			entries.splice(idx, 1);
			if (!entries.length) {
				customGroups.delete(group.tabId);
			}
			registryChangeEmitter.fire();
		}
	});
}

export function getRibbonCustomGroups(tabId: RibbonTabId): readonly IRibbonCustomGroup[] {
	return customGroups.get(tabId) ?? [];
}

/** Maximum small buttons stacked vertically in one ribbon column. */
export const RIBBON_SMALL_STACK_MAX = 3;

export interface IParsedRibbonGroup {
	readonly raw: string;
	readonly order: number;
	readonly key: string;
	readonly label: string;
}

/** Parses `<order>_<GroupName>` menu group identifiers into sort order, key, and display label. */
export function parseRibbonGroup(rawGroup: string, labelLookup: (key: string) => string | undefined = getRibbonGroupLabel): IParsedRibbonGroup {
	if (rawGroup === 'navigation') {
		return { raw: rawGroup, order: -1, key: 'navigation', label: labelLookup('navigation') ?? localize('ribbon.group.general', "General") };
	}
	if (!rawGroup) {
		return { raw: rawGroup, order: Number.MAX_SAFE_INTEGER, key: '', label: labelLookup('') ?? localize('ribbon.group.more', "More") };
	}
	const match = /^(\d+)_(.+)$/.exec(rawGroup);
	if (match) {
		const order = Number(match[1]);
		const key = match[2];
		return { raw: rawGroup, order, key, label: labelLookup(key) ?? key };
	}
	return { raw: rawGroup, order: 100, key: rawGroup, label: labelLookup(rawGroup) ?? rawGroup };
}

export type RibbonColumn<T> =
	| { readonly kind: 'large'; readonly item: T }
	| { readonly kind: 'stack'; readonly items: readonly T[] };

/** Packs ribbon items into standalone large columns and vertical stacks of up to 3 small items. */
export function packRibbonColumns<T extends { readonly size: RibbonButtonSize }>(items: readonly T[]): readonly RibbonColumn<T>[] {
	const columns: RibbonColumn<T>[] = [];
	let stack: T[] = [];
	const flushStack = () => {
		if (stack.length) {
			columns.push({ kind: 'stack', items: stack });
			stack = [];
		}
	};
	for (const item of items) {
		if (item.size === 'large') {
			flushStack();
			columns.push({ kind: 'large', item });
		} else {
			stack.push(item);
			if (stack.length >= RIBBON_SMALL_STACK_MAX) {
				flushStack();
			}
		}
	}
	flushStack();
	return columns;
}

export interface IRibbonActionItem {
	readonly kind: 'action';
	readonly action: MenuItemAction;
	readonly size: RibbonButtonSize;
	readonly label: string;
	readonly renderCustom?: (container: HTMLElement, instantiationService: IInstantiationService, action: MenuItemAction) => IDisposable;
}

export interface IRibbonSubmenuItem {
	readonly kind: 'submenu';
	readonly action: SubmenuItemAction;
	readonly size: RibbonButtonSize;
	readonly label: string;
	readonly isSplit: boolean;
	readonly primaryAction: MenuItemAction | undefined;
}

export type RibbonItem = IRibbonActionItem | IRibbonSubmenuItem;

export interface IRibbonGroupModel {
	readonly raw: string;
	readonly key: string;
	readonly label: string;
	readonly order: number;
	readonly collapsePriority: number;
	readonly columns: readonly RibbonColumn<RibbonItem>[];
	readonly custom?: IRibbonCustomGroup;
}

export interface IRibbonGroupCollapseInput {
	readonly key: string;
	readonly order: number;
	readonly collapsePriority: number;
	readonly collapsible: boolean;
	readonly expandedWidth: number;
	readonly collapsedWidth: number;
}

/**
 * Selects the smallest-priority collapsible groups to collapse into dropdown buttons
 * so the ribbon fits within `availableWidth` without a horizontal scrollbar.
 */
export function computeCollapsedRibbonGroups(
	groups: readonly IRibbonGroupCollapseInput[],
	availableWidth: number,
	chromeWidth = 0,
): ReadonlySet<string> {
	const collapsed = new Set<string>();
	if (availableWidth <= 0) {
		return collapsed;
	}

	let totalWidth = chromeWidth;
	for (const group of groups) {
		totalWidth += group.expandedWidth;
	}
	if (totalWidth <= availableWidth) {
		return collapsed;
	}

	const candidates = groups
		.filter(group => group.collapsible && group.expandedWidth > group.collapsedWidth)
		.sort((a, b) => a.collapsePriority - b.collapsePriority || b.order - a.order);

	for (const candidate of candidates) {
		if (totalWidth <= availableWidth) {
			break;
		}
		collapsed.add(candidate.key);
		totalWidth -= candidate.expandedWidth - candidate.collapsedWidth;
	}

	return collapsed;
}

function resolvePrimaryAction(action: SubmenuItemAction, primaryCommandId: string | undefined): MenuItemAction | undefined {
	const items = action.actions.filter((candidate): candidate is MenuItemAction => candidate instanceof MenuItemAction);
	if (primaryCommandId) {
		const explicit = items.find(candidate => candidate.id === primaryCommandId);
		if (explicit) {
			return explicit;
		}
	}
	return items.find(candidate => candidate.enabled) ?? items[0];
}

/** Builds sorted ribbon group models from menu action groups and custom groups. */
export function buildRibbonGroups(
	menuGroups: readonly [string, readonly (MenuItemAction | SubmenuItemAction)[]][],
	tabCustomGroups: readonly IRibbonCustomGroup[],
	options?: {
		readonly menuId?: MenuId;
		readonly hintLookup?: (id: string, menuId?: MenuId) => IRibbonItemHint | undefined;
		readonly labelLookup?: (key: string) => string | undefined;
		readonly priorityLookup?: (key: string) => number | undefined;
	}
): readonly IRibbonGroupModel[] {
	const menuId = options?.menuId;
	const hintLookup = options?.hintLookup ?? getRibbonItemHint;
	const labelLookup = options?.labelLookup ?? getRibbonGroupLabel;
	const priorityLookup = options?.priorityLookup ?? getRibbonGroupPriority;
	const groups: IRibbonGroupModel[] = [];

	for (const [rawGroup, actions] of menuGroups) {
		if (!actions.length) {
			continue;
		}
		const parsed = parseRibbonGroup(rawGroup, labelLookup);
		const defaultSize: RibbonButtonSize = actions.length <= 2 ? 'large' : 'small';
		const items: RibbonItem[] = actions.map(action => {
			if (action instanceof SubmenuItemAction) {
				const hint = hintLookup(action.item.submenu.id, menuId);
				const isSplit = !!action.item.isSplitButton;
				return {
					kind: 'submenu',
					action,
					size: hint?.size ?? defaultSize,
					label: hint?.label ?? action.label,
					isSplit,
					primaryAction: isSplit ? resolvePrimaryAction(action, hint?.primaryCommandId) : undefined,
				};
			}
			const hint = hintLookup(action.id, menuId);
			return {
				kind: 'action',
				action,
				size: hint?.size ?? defaultSize,
				label: hint?.label ?? action.label,
				renderCustom: hint?.renderCustom,
			};
		});
		groups.push({
			raw: parsed.raw,
			key: parsed.key,
			label: parsed.label,
			order: parsed.order,
			collapsePriority: priorityLookup(parsed.key) ?? -parsed.order,
			columns: packRibbonColumns(items),
		});
	}

	for (const custom of tabCustomGroups) {
		const parsed = parseRibbonGroup(custom.group, labelLookup);
		groups.push({
			raw: parsed.raw,
			key: parsed.key,
			label: custom.label,
			order: parsed.order,
			collapsePriority: custom.collapsePriority ?? priorityLookup(parsed.key) ?? -parsed.order,
			columns: [],
			custom,
		});
	}

	groups.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
	return groups;
}
