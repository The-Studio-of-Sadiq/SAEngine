/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveDocument } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr, ContextKeyExpression } from '../../../../platform/contextkey/common/contextkey.js';
import { ProjectStageBar } from '../../saengineProject/browser/projectStageBar.js';
import {
	registerRibbonCustomGroup,
	registerRibbonGroupLabel,
	registerRibbonGroupPriority,
	registerRibbonItemHint,
	RibbonButtonSize,
	RibbonMenus,
	subViewWhen,
	PROJECT_TAB_WHEN,
	registerRibbonGroupWhen,
	EXPORTS_WHEN,
	FLOOR_PLAN_WHEN,
	SETTINGS_WHEN,
} from './ribbonRegistry.js';

const projectOpen = ContextKeyExpr.has('saengineProjectOpen');
const runAllRunning = ContextKeyExpr.has('saengineRunAllRunning');
const developerMode = ContextKeyExpr.has('saengineDeveloperMode');
const aiRunning = ContextKeyExpr.has('saengineAiRunning');
const aiEditsAllowed = ContextKeyExpr.has('saengineAiEditsAllowed');
const liveCoEditing = ContextKeyExpr.has('saengineLiveCoEditing');
const relayHosted = ContextKeyExpr.has('saengineCoEditingRelayHosted');

const category = localize2('saengine.category', "SAEngine");

const RibbonSubmenus = {
	HomeOpen: MenuId.for('SaengineRibbon.Submenu.HomeOpen'),
	HomeSave: MenuId.for('SaengineRibbon.Submenu.HomeSave'),
	HomeParts: MenuId.for('SaengineRibbon.Submenu.HomeParts'),
	HomeRun: MenuId.for('SaengineRibbon.Submenu.HomeRun'),
	HomeCollaborate: MenuId.for('SaengineRibbon.Submenu.HomeCollaborate'),
	HomeManage: MenuId.for('SaengineRibbon.Submenu.HomeManage'),
	DocsReport: MenuId.for('SaengineRibbon.Submenu.DocsReport'),
	DocsWorksheets: MenuId.for('SaengineRibbon.Submenu.DocsWorksheets'),
	OutputArchive: MenuId.for('SaengineRibbon.Submenu.OutputArchive'),
	StudiesGraph: MenuId.for('SaengineRibbon.Submenu.StudiesGraph'),
	CollabLocks: MenuId.for('SaengineRibbon.Submenu.CollabLocks'),
	CollabLive: MenuId.for('SaengineRibbon.Submenu.CollabLive'),
	ManagePackages: MenuId.for('SaengineRibbon.Submenu.ManagePackages'),
	ManageAi: MenuId.for('SaengineRibbon.Submenu.ManageAi'),
	AnalyzeRun: MenuId.for('SaengineRibbon.Submenu.AnalyzeRun'),
	FemResultForces: MenuId.for('SaengineRibbon.Submenu.FemResultForces'),
} as const;

//#region Clipboard commands

function registerDomClipboardCommand(id: string, title: ReturnType<typeof localize2>, command: 'cut' | 'copy' | 'paste'): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, category, f1: false });
		}

		override run(): void {
			getActiveDocument().execCommand(command);
		}
	});
}

const CMD_CUT = 'saengine.ribbon.cut';
const CMD_COPY = 'saengine.ribbon.copy';
const CMD_PASTE = 'saengine.ribbon.paste';

registerDomClipboardCommand(CMD_CUT, localize2('ribbon.cut', "Cut"), 'cut');
registerDomClipboardCommand(CMD_COPY, localize2('ribbon.copy', "Copy"), 'copy');
registerDomClipboardCommand(CMD_PASTE, localize2('ribbon.paste', "Paste"), 'paste');

//#endregion

//#region Group labels, priorities, and Workflow custom group

const GROUP_LABELS: readonly [string, string][] = [
	['Project', localize('ribbon.grp.project', "Project")],
	['Parts', localize('ribbon.grp.parts', "Parts")],
	['Workflow', localize('ribbon.grp.workflow', "Workflow")],
	['Run', localize('ribbon.grp.run', "Run")],
	['Clipboard', localize('ribbon.grp.clipboard', "Clipboard")],
	['Workspace', localize('ribbon.grp.workspace', "Workspace")],
	// Soil Report
	['Boreholes', localize('ribbon.grp.boreholes', "Boreholes")],
	['Views', localize('ribbon.grp.views', "Views")],
	['InvestigationChecks', localize('ribbon.grp.invChecks', "Investigation Checks")],
	['Tests', localize('ribbon.grp.tests', "Tests & Samples")],
	['LabReports', localize('ribbon.grp.labReports', "Lab & SPT Reports")],
	['Bearing', localize('ribbon.grp.bearing', "Bearing Capacity")],
	['Settlement', localize('ribbon.grp.settlement', "Settlement & Sources")],
	['SeismicClassification', localize('ribbon.grp.seismicClass', "Site Classification")],
	['LiquefactionAndSoils', localize('ribbon.grp.liqSoils', "Liquefaction & Special Soils")],
	['EarthPressure', localize('ribbon.grp.earthPressure', "Lateral Earth Pressure")],
	['Chemistry', localize('ribbon.grp.chemistry', "Chemistry & Durability")],
	['SiteAndPlanning', localize('ribbon.grp.sitePlanning', "Site & Planning")],
	['GisExchange', localize('ribbon.grp.gisExchange', "GIS Exchange")],
	['Export', localize('ribbon.grp.export', "Export")],
	['Settings', localize('ribbon.grp.settings', "Settings")],
	// Settings
	['CodePack', localize('ribbon.grp.codePack', "Code Pack")],
	['PackAuthoring', localize('ribbon.grp.packAuthoring', "Authoring & Trust")],
	['Packages', localize('ribbon.grp.packages', "Packages")],
	['AreaAndChoices', localize('ribbon.grp.areaChoices', "Area Loads & Choices")],
	['Combinations', localize('ribbon.grp.combinations', "Load Combinations")],
	['HazardParameters', localize('ribbon.grp.hazardParams', "Hazard Parameters")],
	['OnlineHazard', localize('ribbon.grp.onlineHazard', "Online Hazard Lookup")],
	['Validation', localize('ribbon.grp.validation', "Project Validation")],
	['Conformance', localize('ribbon.grp.conformance', "Conformance & Limits")],
	['CodeTables', localize('ribbon.grp.codeTables', "Code Tables & Overrides")],
	['FallbacksAndTemplates', localize('ribbon.grp.fallbacksTemplates', "Fallbacks & Templates")],
	['ProjectAndSite', localize('ribbon.grp.projectSite', "Project & Site")],
	['Loads', localize('ribbon.grp.loads', "Loads")],
	['Engineering', localize('ribbon.grp.engineering', "Engineering")],
	['Outputs', localize('ribbon.grp.outputs', "Outputs")],
	// Library
	['Switch', localize('ribbon.grp.switch', "Library")],
	['AddMaterial', localize('ribbon.grp.addMaterial', "Materials")],
	['Edit', localize('ribbon.grp.edit', "Edit")],
	['Exchange', localize('ribbon.grp.exchange', "Exchange")],
	['Sections', localize('ribbon.grp.sections', "Designed Sections")],
	['Catalogues', localize('ribbon.grp.catalogues', "Standard Catalogues")],
	['AddObject', localize('ribbon.grp.addObject', "Object Types")],
	['Components', localize('ribbon.grp.components', "Architecture & Bars")],
	['Modifiers', localize('ribbon.grp.modifiers', "Stiffness Modifiers")],
	['Checks', localize('ribbon.grp.checks', "Checks")],
	// Plan
	['Place', localize('ribbon.grp.place', "Place")],
	['Underlay', localize('ribbon.grp.underlay', "Underlay")],
	['ModelData', localize('ribbon.grp.modelData', "Model & Data")],
	// Architecture
	['Build', localize('ribbon.grp.build', "Build")],
	['RoomsAndRoofs', localize('ribbon.grp.roomsRoofs', "Rooms & Roofs")],
	['ComponentsAndMass', localize('ribbon.grp.compMass', "Components & Mass")],
	['TypesAndImport', localize('ribbon.grp.typesImport', "Types & Import")],
	// 3D View
	['Section', localize('ribbon.grp.section', "Section")],
	['Measure', localize('ribbon.grp.measure', "Measure")],
	['Visibility', localize('ribbon.grp.visibility', "Hide / Isolate")],
	['RenderAndStudies', localize('ribbon.grp.renderStudies', "Render & Studies")],
	// MEP
	['Clashes', localize('ribbon.grp.clashes', "Clashes")],
	['Openings', localize('ribbon.grp.openings', "Openings & Loads")],
	['BCF', localize('ribbon.grp.bcf', "BCF")],
	['ModelChecks', localize('ribbon.grp.modelChecks', "Model Checks")],
	['Occupancies', localize('ribbon.grp.occupancies', "Occupancies")],
	['Branches', localize('ribbon.grp.branches', "Branches")],
	['HotAndGas', localize('ribbon.grp.hotAndGas', "Hot & Gas")],
	['DrainageAndRainwater', localize('ribbon.grp.drainageAndRainwater', "Drainage & Rainwater")],
	['SepticAndSoakWell', localize('ribbon.grp.septicAndSoakWell', "Septic & Soak Well")],
	['PumpsAndHydraulics', localize('ribbon.grp.pumpsAndHydraulics', "Pumps & Hydraulics")],
	['HvacSummary', localize('ribbon.grp.hvacSummary', "HVAC Report")],
	['DuctOpenings', localize('ribbon.grp.ductOpenings', "Duct Coordination")],
	['AirDistribution', localize('ribbon.grp.airDistribution', "Air Distribution")],
	['Envelope', localize('ribbon.grp.envelope', "Envelope")],
	['ElectricalUses', localize('ribbon.grp.electricalUses', "Load Densities")],
	['DemandAndRooms', localize('ribbon.grp.demandAndRooms', "Demand & Rooms")],
	['Distribution', localize('ribbon.grp.distribution', "Distribution")],
	['Lighting', localize('ribbon.grp.lighting', "Lighting")],
	['SupplyAndProtection', localize('ribbon.grp.supplyAndProtection', "Supply & Protection")],
	['FireHydraulics', localize('ribbon.grp.fireHydraulics', "Hydraulics & Supports")],
	['FireSleeves', localize('ribbon.grp.fireSleeves', "Fire Coordination")],
	['Suppression', localize('ribbon.grp.suppression', "Suppression")],
	['Detection', localize('ribbon.grp.detection', "Detection")],
	['WaterSupply', localize('ribbon.grp.waterSupply', "Water Supply")],
	['Requirements', localize('ribbon.grp.requirements', "Requirements")],
	['SystemBrowser', localize('ribbon.grp.systemBrowser', "System Browser")],
	['Fabrication', localize('ribbon.grp.fabrication', "Fabrication")],
	// Analyze / Results / Design
	['Solver', localize('ribbon.grp.solver', "Solver")],
	['Advanced', localize('ribbon.grp.advanced', "Advanced")],
	['MeshAndView', localize('ribbon.grp.meshView', "Mesh & View")],
	['Assign', localize('ribbon.grp.assign', "Assign")],
	['Display', localize('ribbon.grp.display', "Display")],
	['ChartsAndTables', localize('ribbon.grp.chartsTables', "Charts & Tables")],
	['Inspect3D', localize('ribbon.grp.inspect3d', "3D Inspect")],
	['Checks', localize('ribbon.grp.checks', "Checks")],
	['Detailing', localize('ribbon.grp.detailing', "Detailing")],
	['Standards', localize('ribbon.grp.standards', "Standards")],
	// The Project tab's packages, updates and manuals: the catalog's own Standards group sits beside it.
	['Manage', localize('ribbon.grp.manage', "Manage")],
	// Foundations
	['Shallow', localize('ribbon.grp.shallow', "Shallow Foundations")],
	['Sizing', localize('ribbon.grp.sizing', "Sizing")],
	['Geotechnical', localize('ribbon.grp.geotechnical', "Geotechnical")],
	['Piles', localize('ribbon.grp.piles', "Piles & Caps")],
	['GradeBeams', localize('ribbon.grp.gradeBeams', "Grade Beams")],
	['PileDetailing', localize('ribbon.grp.pileDetailing', "Detailing & Tests")],
	['AxialCapacity', localize('ribbon.grp.axialCapacity', "Axial Capacity")],
	['LateralAndSettlement', localize('ribbon.grp.lateralSettlement', "Lateral & Settlement")],
	['RetainingElements', localize('ribbon.grp.retainingElements', "Add Elements")],
	['RetainingAnalysis', localize('ribbon.grp.retainingAnalysis', "Wall & Excavation Analysis")],
	['SpecialElements', localize('ribbon.grp.specialElements', "Add Special Foundations")],
	['SpecialAnalysis', localize('ribbon.grp.specialAnalysis', "Slab & Dynamic Checks")],
	['Actions', localize('ribbon.grp.actions', "Actions")],
	['Design', localize('ribbon.grp.design', "Design")],
	// BOQ
	['Measure', localize('ribbon.grp.measure', "Measure")],
	['RatesAndCarbon', localize('ribbon.grp.ratesCarbon', "Rates & Carbon")],
	['CostAnalysis', localize('ribbon.grp.costAnalysis', "Cost & Value Analysis")],
	['Programme', localize('ribbon.grp.programme', "4D Programme")],
	['RatesAndScheduleExport', localize('ribbon.grp.schedExport', "Productivity & Export")],
	['SpecialTakeoff', localize('ribbon.grp.specialTakeoff', "Architectural & Precast")],
	['PdfTakeoff', localize('ribbon.grp.pdfTakeoff', "2D PDF Takeoff")],
	// Documents
	['Drawings', localize('ribbon.grp.drawings', "Drawings")],
	['Annotation', localize('ribbon.grp.annotation', "Annotation")],
	['Schedules', localize('ribbon.grp.schedules', "Schedules")],
	['Report', localize('ribbon.grp.report', "Report")],
	// Output
	['Exports', localize('ribbon.grp.exports', "Exports")],
	['IFC', localize('ribbon.grp.ifc', "IFC")],
	['BIMAndCAD', localize('ribbon.grp.bimCad', "BIM & CAD")],
	['BOQAndReports', localize('ribbon.grp.boqReports', "BOQ & Reports")],
	['WebAndArchive', localize('ribbon.grp.webArchive', "Web & Archive")],
	// Studies
	['ConstructionAndCost', localize('ribbon.grp.constructionCost', "Construction & Cost")],
	['Environmental', localize('ribbon.grp.environmental', "Environmental")],
	['Optioneering', localize('ribbon.grp.optioneering', "Optioneering")],
	// U6e
	['LoadPattern', localize('u6e.grp.loadPattern', "Gravity & Live Loads")],
	['SpecialtyLoads', localize('u6e.grp.specialtyLoads', "Specialty Loads")],
	['CombinationAudit', localize('u6e.grp.combinationAudit', "Combinations")],
	['SeismicHazard', localize('u6e.grp.seismicHazard', "Hazard & Design")],
	['GroundMotions', localize('u6e.grp.groundMotions', "Ground Motions")],
	['SeismicResponse', localize('u6e.grp.seismicResponse', "Response & Regularity")],
	['IsolationSystems', localize('u6e.grp.isolationSystems', "Isolation Systems")],
	['WindExposure', localize('u6e.grp.windExposure', "Wind Exposure")],
	['WindEffects', localize('u6e.grp.windEffects', "Wind Effects")],
	['PressureCoefficients', localize('u6e.grp.pressureCoefficients', "Pressure Coefficients")],
	['NonlinearAnalysis', localize('u6e.grp.nonlinearAnalysis', "Nonlinear Analysis")],
	['StabilityChecks', localize('u6e.grp.stabilityChecks', "Stability Checks")],
	['ConstructionStages', localize('u6e.grp.constructionStages', "Construction Stages")],
	['FoundationInteraction', localize('u6e.grp.foundationInteraction', "Soil Interaction")],
	['SwayAndSettlement', localize('u6e.grp.swaySettlement', "Sway & Settlement")],
	['VibrationChecks', localize('u6e.grp.vibrationChecks', "Vibration Checks")],
	['ConcreteDesign', localize('u6e.grp.concreteDesign', "Concrete Design")],
	['MemberDesign', localize('u6e.grp.memberDesign', "Member Design")],
	['CapacityDetailing', localize('u6e.grp.capacityDetailing', "Capacity & Detailing")],
	['FireAndConnections', localize('u6e.grp.fireConnections', "Fire & Connections")],
	['ModelExchange', localize('u6e.grp.modelExchange', "Model Exchange")],
	['IFCValidation', localize('u6e.grp.ifcValidation', "IFC Validation")],
	['RebarModel', localize('u6e.grp.rebarModel', "Rebar Model")],
	['FabricationSchedules', localize('u6e.grp.fabricationSchedules', "Fabrication Schedules")],
	['DaylightStudy', localize('u6e.grp.daylightStudy', "Daylight Study")],
	['SitePlanning', localize('u6e.grp.sitePlanning', "Site Planning")],
	['PhaseReview', localize('u6e.grp.phaseReview', "Phase Review")],
	['EnvironmentStudy', localize('u6e.grp.environmentStudy', "Environment Study")],
	['RoomChecks', localize('u6e.grp.roomChecks', "Room Checks")],
	['MassingReview', localize('u6e.grp.massingReview', "Massing & Floors")],
	['EnvelopeReview', localize('u6e.grp.envelopeReview', "Envelope Review")],
	['ScanData', localize('u6e.grp.scanData', "Scan Data")],
	['SolarExposure', localize('u6e.grp.solarExposure', "Solar Exposure")],
	['RoadNoise', localize('u6e.grp.roadNoise', "Road Noise")],
	['DrawingReview', localize('u6e.grp.drawingReview', "Drawing Review")],
	['DrawingInventory', localize('u6e.grp.drawingInventory', "Drawing Inventory")],
	['SheetIssue', localize('u6e.grp.sheetIssue', "Sheets & Issue")],
	['ProjectInformation', localize('u6e.grp.projectInformation', "Project Information")],
	['ClauseTraceability', localize('u6e.grp.clauseTraceability', "Clause Traceability")],
	['ScheduleCategories', localize('u6e.grp.scheduleCategories', "Schedule Categories")],
	['CalculationPackages', localize('u6e.grp.calculationPackages', "Calculation Packages")],
	['WorksheetInventory', localize('u6e.grp.worksheetInventory', "Worksheet Inventory")],
	['SpecialStructures', localize('u6e.grp.specialStructures', "Special Structures")],
	['BatchVerification', localize('u6e.grp.batchVerification', "Batch Verification")],
	['SolarAndDaylight', localize('u6e.grp.solarAndDaylight', "Solar & Daylight")],
	['TerrainReview', localize('u6e.grp.terrainReview', "Terrain Review")],
	['VerificationCases', localize('u6e.grp.verificationCases', "Verification Cases")],
	['AnalysisFormats', localize('u6e.grp.analysisFormats', "Analysis Formats")],
	['ExchangeFormats', localize('u6e.grp.exchangeFormats', "Exchange Formats")],
	['ExchangeGuides', localize('u6e.grp.exchangeGuides', "Exchange Guides")],
	['FabricationPreview', localize('u6e.grp.fabricationPreview', "Fabrication Preview")],
	['ArchiveReview', localize('u6e.grp.archiveReview', "Archive Review")],
	['StructuralValidation', localize('u6e.grp.structuralValidation', "Structural Validation")],
	['FormatValidation', localize('u6e.grp.formatValidation', "Format Validation")],
	// Project tab (Collaborate & Manage groups)
	['SyncAndWorksharing', localize('ribbon.grp.syncWorksharing', "Sync & Worksharing")],
	['LiveCoEditing', localize('ribbon.grp.liveCoEditing', "Live Co-Editing")],
	['OfficeServer', localize('ribbon.grp.officeServer', "Office Server")],
	['AIControl', localize('ribbon.grp.aiControl', "AI Control")],
	['Automation', localize('ribbon.grp.automation', "Automation")],
	['SettingsAndHelp', localize('ribbon.grp.settingsHelp', "Settings & Help")],
];

for (const [key, label] of GROUP_LABELS) {
	registerRibbonGroupLabel(key, label);
}

const GROUP_PRIORITIES: readonly [string, number][] = [
	['Project', 100],
	['Parts', 90],
	['Run', 80],
	['Clipboard', 50],
	['Workspace', 40],
	['SyncAndWorksharing', 70],
	['LiveCoEditing', 60],
	['Standards', 50],
	['Manage', 50],
	['OfficeServer', 40],
	['AIControl', 30],
	['Automation', 20],
	['SettingsAndHelp', 10],
];

for (const [key, priority] of GROUP_PRIORITIES) {
	registerRibbonGroupPriority(key, priority);
}

registerRibbonCustomGroup({
	tabId: 'home',
	group: '3_Workflow',
	label: localize('ribbon.grp.workflow', "Workflow"),
	render: (container, instantiationService) => {
		const stageBar = instantiationService.createInstance(ProjectStageBar);
		container.appendChild(stageBar.element);
		return stageBar;
	},
});

// Parts and Workflow open other windows, which the project tree already does: they show only on the
// Overview (no editor), so an editor's Home tab holds that window's own tools.
registerRibbonGroupWhen(RibbonMenus.Home, '2_Parts', PROJECT_TAB_WHEN);
registerRibbonGroupWhen(RibbonMenus.Home, '3_Workflow', PROJECT_TAB_WHEN);

//#endregion

//#region Registration helpers

interface IItemOptions {
	readonly precondition?: ContextKeyExpression;
	readonly when?: ContextKeyExpression;
	readonly tooltip?: string;
	readonly toggled?: ContextKeyExpression;
}

function addItem(
	menuId: MenuId,
	group: string,
	order: number,
	id: string,
	title: string,
	icon: ThemeIcon,
	size: RibbonButtonSize,
	options?: IItemOptions,
): void {
	MenuRegistry.appendMenuItem(menuId, {
		group,
		order,
		when: options?.when,
		command: {
			id,
			title,
			icon,
			precondition: options?.precondition,
			tooltip: options?.tooltip,
			toggled: options?.toggled,
		},
	});
	registerRibbonItemHint(id, { size, label: title }, menuId);
}

function addU6ePanelItem(menuId: MenuId, group: string, order: number, panel: string, title: string, icon: ThemeIcon, size: RibbonButtonSize = 'large'): void {
	addItem(menuId, group, order, `saengine.u6e.${panel}`, title, icon, size, { precondition: projectOpen });
}

function addSubItem(
	menuId: MenuId,
	group: string,
	order: number,
	id: string,
	title: string,
	icon: ThemeIcon,
	options?: IItemOptions,
): void {
	MenuRegistry.appendMenuItem(menuId, {
		group,
		order,
		when: options?.when,
		command: {
			id,
			title,
			icon,
			precondition: options?.precondition,
			tooltip: options?.tooltip,
			toggled: options?.toggled,
		},
	});
}

function addSubmenu(
	menuId: MenuId,
	group: string,
	order: number,
	submenu: MenuId,
	title: string,
	icon: ThemeIcon,
	size: RibbonButtonSize,
	isSplit: boolean,
	primaryCommandId?: string,
	when?: ContextKeyExpression,
): void {
	MenuRegistry.appendMenuItem(menuId, {
		group,
		order,
		submenu,
		title,
		icon,
		isSplitButton: isSplit,
		when,
	});
	registerRibbonItemHint(submenu.id, { size, label: title, primaryCommandId }, menuId);
}

function addNestedSubmenu(
	parentMenuId: MenuId,
	group: string,
	order: number,
	submenu: MenuId,
	title: string,
	icon: ThemeIcon,
	when?: ContextKeyExpression,
): void {
	MenuRegistry.appendMenuItem(parentMenuId, {
		group,
		order,
		submenu,
		title,
		icon,
		when,
	});
}

//#endregion

//#region Tab 1: Home (always visible)

addItem(RibbonMenus.Home, '1_Project', 1, 'saengine.project.new', localize('rib.home.new', "New"), Codicon.newFolder, 'large');
addSubmenu(RibbonMenus.Home, '1_Project', 2, RibbonSubmenus.HomeOpen, localize('rib.home.open', "Open"), Codicon.folderOpened, 'large', true, 'saengine.project.open');
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 1, 'saengine.project.open', localize('rib.home.openProject', "Open Project..."), Codicon.folderOpened);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 2, 'saengine.project.openArchive', localize('rib.home.openArchive', "Open Project Archive..."), Codicon.archive, { when: EXPORTS_WHEN.negate() });
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 3, 'saengine.project.openSample', localize('rib.home.openSample', "Open Sample Project..."), Codicon.project);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 5, 'saengine.project.showStart', localize('rib.home.showStart', "Show Start Window"), Codicon.home);

addSubmenu(RibbonMenus.Home, '1_Project', 3, RibbonSubmenus.HomeSave, localize('rib.home.save', "Save"), Codicon.save, 'large', true, 'saveAll');
addSubItem(RibbonSubmenus.HomeSave, '1_save', 1, 'saveAll', localize('rib.home.saveAll', "Save All"), Codicon.saveAll);
addSubItem(RibbonSubmenus.HomeSave, '1_save', 2, 'workbench.action.files.save', localize('rib.home.saveFile', "Save Active File"), Codicon.save);

addItem(RibbonMenus.Home, '1_Project', 5, 'saengine.project.showOverview', localize('rib.home.overview', "Overview"), Codicon.dashboard, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '1_Project', 6, 'saengine.project.revealInOS', localize('rib.home.reveal', "Open Folder"), Codicon.folder, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Home, '2_Parts', 2, 'saengine.showProperties', localize('rib.home.properties', "Properties"), Codicon.symbolProperty, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '2_Parts', 4, 'saengine.showTables', localize('rib.home.tables', "Tables"), Codicon.table, 'small', { precondition: projectOpen });

// 3_Workflow is rendered by ProjectStageBar via registerRibbonCustomGroup above.

addSubmenu(RibbonMenus.Home, '4_Run', 2, RibbonSubmenus.HomeRun, localize('rib.home.run', "Run"), Codicon.runAll, 'large', false);
addSubItem(RibbonSubmenus.HomeRun, '2_log', 2, 'saengine.showProgress', localize('rib.home.progress', "Progress"), Codicon.tasklist, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 3, 'saengine.restartEngine', localize('rib.home.restartEngine', "Restart Engine"), Codicon.debugRestart);

addItem(RibbonMenus.Home, '5_Clipboard', 1, 'undo', localize('rib.home.undo', "Undo"), Codicon.discard, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 2, 'redo', localize('rib.home.redo', "Redo"), Codicon.redo, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 3, CMD_CUT, localize('rib.home.cut', "Cut"), Codicon.clippy, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 4, CMD_COPY, localize('rib.home.copy', "Copy"), Codicon.copy, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 5, CMD_PASTE, localize('rib.home.paste', "Paste"), Codicon.insert, 'small');

// Home's Collaborate and Manage menus hide where the Project tab (Overview) holds the same commands.
const HOME_MENUS_WHEN = PROJECT_TAB_WHEN.negate();
addSubmenu(RibbonMenus.Home, '6_Workspace', 1, RibbonSubmenus.HomeCollaborate, localize('rib.home.collaborate', "Collaborate"), Codicon.organization, 'small', false, undefined, HOME_MENUS_WHEN);
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 1, 'saengine.share.shareProject', localize('rib.collab.share', "Share Project"), Codicon.organization, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 2, 'saengine.share.syncNow', localize('rib.collab.sync', "Sync"), Codicon.sync, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 3, 'saengine.share.openShared', localize('rib.collab.openShared', "Open Shared"), Codicon.folderOpened);
addNestedSubmenu(RibbonSubmenus.HomeCollaborate, '2_locks', 1, RibbonSubmenus.CollabLocks, localize('rib.collab.lockPart', "Lock Part"), Codicon.lock);
addNestedSubmenu(RibbonSubmenus.HomeCollaborate, '2_locks', 2, RibbonSubmenus.CollabLive, localize('rib.collab.live', "Live Co-Editing"), Codicon.broadcast);
addSubItem(RibbonSubmenus.HomeCollaborate, '3_versions', 1, 'saengine.project.showVersions', localize('rib.collab.versions', "Versions"), Codicon.history, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '3_versions', 2, 'saengine.project.saveVersion', localize('rib.collab.saveVersion', "Save Version"), Codicon.gitCommit, { precondition: projectOpen });

addSubmenu(RibbonMenus.Home, '6_Workspace', 2, RibbonSubmenus.HomeManage, localize('rib.home.manage', "Manage"), Codicon.settingsGear, 'small', false, undefined, HOME_MENUS_WHEN);
addNestedSubmenu(RibbonSubmenus.HomeManage, '1_standards', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package, SETTINGS_WHEN.negate());
addNestedSubmenu(RibbonSubmenus.HomeManage, '1_standards', 2, RibbonSubmenus.ManageAi, localize('rib.manage.aiControl', "AI Control"), Codicon.robot);
addSubItem(RibbonSubmenus.HomeManage, '2_server', 2, 'saengine.officeServer.check', localize('rib.manage.checkServer', "Check Server"), Codicon.pass);
addSubItem(RibbonSubmenus.HomeManage, '2_server', 3, 'saengine.officeServer.setToken', localize('rib.manage.setToken', "Set Server Token"), Codicon.key);
addSubItem(RibbonSubmenus.HomeManage, '2_server', 4, 'saengine.officeServer.clearToken', localize('rib.manage.clearToken', "Forget Token"), Codicon.trash);
addSubItem(RibbonSubmenus.HomeManage, '3_ai', 1, 'saengine.ai.manageModels', localize('rib.manage.aiModels', "AI Models & Providers"), Codicon.settingsGear);
addSubItem(RibbonSubmenus.HomeManage, '3_ai', 2, 'saengine.ai.useAnthropicKey', localize('rib.manage.anthropicKey', "Anthropic API Key"), Codicon.key);
addSubItem(RibbonSubmenus.HomeManage, '3_ai', 3, 'saengine.ai.useEndpoint', localize('rib.manage.endpoint', "Self-Hosted Endpoint"), Codicon.globe);
addSubItem(RibbonSubmenus.HomeManage, '4_auto', 1, 'saengine.actions.runFromFile', localize('rib.manage.runActions', "Run Actions File..."), Codicon.play);
addSubItem(RibbonSubmenus.HomeManage, '4_auto', 2, 'saengine.actions.showCatalogue', localize('rib.manage.actionCatalogue', "Action Catalogue"), Codicon.book);
addSubItem(RibbonSubmenus.HomeManage, '4_auto', 3, 'saengine.checkPythonRuntime', localize('rib.manage.pythonRuntime', "Check Python Runtime"), Codicon.terminal);
addSubItem(RibbonSubmenus.HomeManage, '4_auto', 4, 'saengine.manage.verificationManual', localize('rib.manage.verificationManual', "Verification Manual (PDF)"), Codicon.filePdf);
addSubItem(RibbonSubmenus.HomeManage, '5_app', 1, 'saengine.openSettings', localize('rib.manage.settings', "Settings"), Codicon.settingsGear);
addSubItem(RibbonSubmenus.HomeManage, '5_app', 2, 'saengine.toggleDeveloperMode', localize('rib.manage.devMode', "Developer Mode"), Codicon.code, { toggled: developerMode });
addSubItem(RibbonSubmenus.HomeManage, '5_app', 3, 'saengine.showPlannedFeatures', localize('rib.manage.planned', "Planned Features"), Codicon.lightbulb);
addSubItem(RibbonSubmenus.HomeManage, '5_app', 4, 'saengine.components.show', localize('rib.manage.components', "Installer Components"), Codicon.extensions);
addSubItem(RibbonSubmenus.HomeManage, '5_app', 5, 'saengine.update.check', localize('rib.manage.updates', "Check Updates"), Codicon.refresh);
addSubItem(RibbonSubmenus.HomeManage, '6_help', 1, 'saengine.help.userManual', localize('rib.manage.userManual', "User Manual"), Codicon.book);
addSubItem(RibbonSubmenus.HomeManage, '6_help', 2, 'saengine.help.tutorial', localize('rib.manage.tutorial', "Sample Tutorial"), Codicon.mortarBoard);
addSubItem(RibbonSubmenus.HomeManage, '6_help', 3, 'saengine.feedback.reportBug', localize('rib.manage.reportBug', "Report a Bug"), Codicon.bug);
addSubItem(RibbonSubmenus.HomeManage, '6_help', 4, 'saengine.feedback.send', localize('rib.manage.sendFeedback', "Send Feedback"), Codicon.commentDiscussion);
addSubItem(RibbonSubmenus.HomeManage, '6_help', 5, 'saengine.diagnostics.create', localize('rib.manage.diagnostics', "Diagnostics Bundle"), Codicon.shield);

addItem(RibbonMenus.Home, '6_Workspace', 3, 'saengine.ai.openChat', localize('rib.home.aiChat', "AI Assistant"), Codicon.sparkle, 'small');

//#endregion

//#region Tab 2: Project (Overview / non-specialized editor)


addItem(RibbonMenus.Project, '2_SyncAndWorksharing', 1, 'saengine.share.shareProject', localize('rib.collab.share', "Share Project"), Codicon.organization, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Project, '2_SyncAndWorksharing', 2, 'saengine.share.syncNow', localize('rib.collab.sync', "Sync"), Codicon.sync, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Project, '2_SyncAndWorksharing', 3, RibbonSubmenus.CollabLocks, localize('rib.collab.lockPart', "Lock Part"), Codicon.lock, 'large', true, 'saengine.share.lockPart');
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 1, 'saengine.share.lockPart', localize('rib.collab.lock', "Lock Part for Editing..."), Codicon.lock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 2, 'saengine.share.unlockPart', localize('rib.collab.unlock', "Release Part Lock..."), Codicon.unlock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '2_stop', 1, 'saengine.share.stopSharing', localize('rib.collab.stopSharing', "Stop Sharing..."), Codicon.debugStop, { precondition: projectOpen });

addSubmenu(RibbonMenus.Project, '3_LiveCoEditing', 1, RibbonSubmenus.CollabLive, localize('rib.collab.live', "Live Co-Editing"), Codicon.broadcast, 'large', true, 'saengine.share.liveCoEditing');
addSubItem(RibbonSubmenus.CollabLive, '1_live', 1, 'saengine.share.liveCoEditing', localize('rib.collab.liveSetup', "Live Co-Editing..."), Codicon.broadcast, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLive, '1_live', 2, 'saengine.collaboration.start', localize('rib.collab.liveStart', "Start Live Co-Editing"), Codicon.play, { precondition: ContextKeyExpr.and(projectOpen, liveCoEditing.negate()) });
addSubItem(RibbonSubmenus.CollabLive, '1_live', 3, 'saengine.collaboration.stop', localize('rib.collab.liveStop', "Stop Live Co-Editing"), Codicon.debugStop, { precondition: liveCoEditing });
addSubItem(RibbonSubmenus.CollabLive, '2_relay', 1, 'saengine.collaboration.hostRelay', localize('rib.collab.hostRelay', "Host Co-Editing Relay"), Codicon.server, { precondition: relayHosted.negate() });
addSubItem(RibbonSubmenus.CollabLive, '2_relay', 2, 'saengine.collaboration.stopRelay', localize('rib.collab.stopRelay', "Stop Hosting Relay"), Codicon.debugStop, { precondition: relayHosted });

addSubmenu(RibbonMenus.Project, '4_Manage', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package, 'large', true, 'saengine.packages.show');
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 1, 'saengine.packages.show', localize('rib.manage.showPackages', "Packages..."), Codicon.package);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 2, 'saengine.codePacks.new', localize('rib.manage.newCodePack', "New Code Pack..."), Codicon.newFile);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 3, 'saengine.codePacks.install', localize('rib.manage.installPkg', "Install Package from File..."), Codicon.cloudDownload);
addItem(RibbonMenus.Project, '4_Manage', 2, 'saengine.showPlannedFeatures', localize('rib.manage.planned', "Planned Features"), Codicon.lightbulb, 'small');
addItem(RibbonMenus.Project, '4_Manage', 3, 'saengine.components.show', localize('rib.manage.components', "Installer Components"), Codicon.extensions, 'small');
addItem(RibbonMenus.Project, '4_Manage', 4, 'saengine.update.check', localize('rib.manage.updates', "Check Updates"), Codicon.refresh, 'small');
addItem(RibbonMenus.Project, '4_Manage', 5, 'saengine.manage.verificationManual', localize('rib.manage.verificationManual', "Verification Manual (PDF)"), Codicon.filePdf, 'small');

addItem(RibbonMenus.Project, '5_OfficeServer', 1, 'saengine.officeServer.run', localize('rib.manage.runServer', "Run on Server"), Codicon.server, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Project, '5_OfficeServer', 2, 'saengine.officeServer.check', localize('rib.manage.checkServer', "Check Server"), Codicon.pass, 'small');
addItem(RibbonMenus.Project, '5_OfficeServer', 3, 'saengine.officeServer.setToken', localize('rib.manage.setToken', "Set Server Token"), Codicon.key, 'small');
addItem(RibbonMenus.Project, '5_OfficeServer', 4, 'saengine.officeServer.clearToken', localize('rib.manage.clearToken', "Forget Token"), Codicon.trash, 'small');

addSubmenu(RibbonMenus.Project, '6_AIControl', 2, RibbonSubmenus.ManageAi, localize('rib.manage.aiControl', "AI Control"), Codicon.robot, 'large', true, 'saengine.ai.allowControl');
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 1, 'saengine.ai.allowControl', localize('rib.manage.aiAllow', "Allow AI Window Control"), Codicon.robot);
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 2, 'saengine.ai.stop', localize('rib.manage.aiStop', "Stop AI Access"), Codicon.debugStop, { precondition: aiRunning });
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 3, 'saengine.ai.showConnection', localize('rib.manage.aiDetails', "Show AI Connection Details"), Codicon.info, { precondition: aiRunning });
addSubItem(RibbonSubmenus.ManageAi, '2_edits', 1, 'saengine.ai.allowEdits', localize('rib.manage.aiAllowEdits', "Allow AI Edits for Session"), Codicon.edit, { precondition: ContextKeyExpr.and(aiRunning, aiEditsAllowed.negate()) });
addSubItem(RibbonSubmenus.ManageAi, '2_edits', 2, 'saengine.ai.disallowEdits', localize('rib.manage.aiDisallowEdits', "Stop AI Edits"), Codicon.lock, { precondition: aiEditsAllowed });
addSubItem(RibbonSubmenus.ManageAi, '3_privacy', 1, 'saengine.ai.manageProjectConsent', localize('rib.manage.aiConsent', "AI Data Sharing for Project..."), Codicon.shield);
addSubItem(RibbonSubmenus.ManageAi, '3_privacy', 2, 'saengine.ai.showActivity', localize('rib.manage.aiActivity', "Show AI Activity"), Codicon.output);
addItem(RibbonMenus.Project, '6_AIControl', 3, 'saengine.ai.manageModels', localize('rib.manage.aiModels', "AI Models & Providers"), Codicon.settingsGear, 'small');
addItem(RibbonMenus.Project, '6_AIControl', 4, 'saengine.ai.useAnthropicKey', localize('rib.manage.anthropicKey', "Anthropic API Key"), Codicon.key, 'small');
addItem(RibbonMenus.Project, '6_AIControl', 5, 'saengine.ai.useEndpoint', localize('rib.manage.endpoint', "Self-Hosted Endpoint"), Codicon.globe, 'small');

addItem(RibbonMenus.Project, '7_Automation', 1, 'saengine.actions.runFromFile', localize('rib.manage.runActions', "Run Actions File..."), Codicon.play, 'small');
addItem(RibbonMenus.Project, '7_Automation', 2, 'saengine.actions.showCatalogue', localize('rib.manage.actionCatalogue', "Action Catalogue"), Codicon.book, 'small');
addItem(RibbonMenus.Project, '7_Automation', 3, 'saengine.checkPythonRuntime', localize('rib.manage.pythonRuntime', "Check Python Runtime"), Codicon.terminal, 'small');

addItem(RibbonMenus.Project, '8_SettingsAndHelp', 1, 'saengine.openSettings', localize('rib.manage.settings', "Settings"), Codicon.settingsGear, 'large');
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 2, 'saengine.toggleDeveloperMode', localize('rib.manage.devMode', "Developer Mode"), Codicon.code, 'small', { toggled: developerMode });
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 3, 'saengine.help.userManual', localize('rib.manage.userManual', "User Manual"), Codicon.book, 'small');
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 4, 'saengine.help.tutorial', localize('rib.manage.tutorial', "Sample Tutorial"), Codicon.mortarBoard, 'small');
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 5, 'saengine.feedback.reportBug', localize('rib.manage.reportBug', "Report a Bug"), Codicon.bug, 'small');
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 6, 'saengine.feedback.send', localize('rib.manage.sendFeedback', "Send Feedback"), Codicon.commentDiscussion, 'small');
addItem(RibbonMenus.Project, '8_SettingsAndHelp', 7, 'saengine.diagnostics.create', localize('rib.manage.diagnostics', "Diagnostics Bundle"), Codicon.shield, 'small');

//#endregion

//#region Tab 3: Soil Report (6 contextual tabs)

// Investigation
addItem(RibbonMenus.Soil, '1_Boreholes', 1, 'saengine.soil.addBorehole', localize('soil.rib.add', "Add Borehole"), Codicon.add, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 2, 'saengine.soil.importFile', localize('soil.rib.import', "Import"), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 3, 'saengine.soil.saveTemplate', localize('soil.rib.template', "Template"), Codicon.notebookTemplate, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 4, 'saengine.soil.editBorehole', localize('soil.rib.edit', "Edit Borehole"), Codicon.edit, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 5, 'saengine.soil.duplicateBorehole', localize('soil.rib.duplicate', "Duplicate"), Codicon.copy, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 6, 'saengine.soil.deleteBorehole', localize('soil.rib.delete', "Delete"), Codicon.trash, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '1_Boreholes', 7, 'saengine.soil.toggleExcludeBearing', localize('soil.rib.exclude', "Exclude Bearing"), Codicon.circleSlash, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Soil, '2_Views', 5, 'saengine.soil.viewStrata3d', localize('soil.rib.strata3d', "3D Strata"), Codicon.symbolNamespace, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '2_Views', 6, 'saengine.soil.toggleFence', localize('soil.rib.fence', "All Boreholes"), Codicon.splitHorizontal, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Soil, '3_InvestigationChecks', 1, 'saengine.soil.investigationCheck', localize('soil.rib.invCheck', "Investigation Check"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Soil, '3_InvestigationChecks', 2, 'saengine.soil.stratigraphySummary', localize('soil.rib.strat3d', "3D Stratigraphy"), Codicon.layers, 'large', { precondition: projectOpen });

// Lab Tests
addItem(RibbonMenus.SoilTests, '1_Tests', 1, 'saengine.soil.editSpt', localize('soil.rib.spt', "SPT & Samples"), Codicon.listFlat, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilTests, '1_Tests', 2, 'saengine.soil.editLabTests', localize('soil.rib.lab', "Lab Tests"), Codicon.beaker, 'small', { precondition: projectOpen });
addItem(RibbonMenus.SoilTests, '1_Tests', 3, 'saengine.soil.recompute', localize('soil.rib.recompute', "Recompute"), Codicon.refresh, 'small', { precondition: projectOpen });

addItem(RibbonMenus.SoilTests, '2_LabReports', 1, 'saengine.soil.sptProfile', localize('soil.rib.sptProf', "SPT Profile"), Codicon.listFlat, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilTests, '2_LabReports', 2, 'saengine.soil.labSummary', localize('soil.rib.labSum', "USCS & Lab Summary"), Codicon.beaker, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilTests, '2_LabReports', 3, 'saengine.soil.pileParams', localize('soil.rib.pilePar', "Pile Parameters"), Codicon.arrowDown, 'small', { precondition: projectOpen });

addItem(RibbonMenus.SoilTests, '3_Exchange', 1, 'saengine.soil.exportAgs4', localize('soil.rib.ags', "Export AGS4"), Codicon.cloudUpload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilTests, '3_Exchange', 2, 'saengine.soil.exportDiggs', localize('soil.rib.diggs', "Export DIGGS"), Codicon.fileCode, 'small', { precondition: projectOpen });

// Bearing & Settlement
addItem(RibbonMenus.SoilBearing, '1_Bearing', 1, 'saengine.soil.bearingCalc', localize('soil.rib.bearingCalc', "Bearing Calculator"), Codicon.dashboard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilBearing, '1_Bearing', 2, 'saengine.soil.bearingTable', localize('soil.rib.bearingTab', "Bearing Table"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilBearing, '1_Bearing', 3, 'saengine.soil.bearingOverride', localize('soil.rib.bearing', "Bearing Override"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });

addItem(RibbonMenus.SoilBearing, '2_Settlement', 1, 'saengine.soil.settlementCalc', localize('soil.rib.settCalc', "Settlement Calculator"), Codicon.graphLine, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilBearing, '2_Settlement', 2, 'saengine.soil.characteristicBearing', localize('soil.rib.charBearing', "Characteristic Bearing"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.SoilBearing, '2_Settlement', 3, 'saengine.soil.sources', localize('soil.rib.sources', "Active Sources"), Codicon.info, 'small', { precondition: projectOpen });

// Seismic & Liquefaction
addItem(RibbonMenus.SoilSeismic, '1_SeismicClassification', 1, 'saengine.soil.siteClass', localize('soil.rib.siteClass', "Site Class Report"), Codicon.pulse, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilSeismic, '1_SeismicClassification', 2, 'saengine.soil.siteResponse', localize('soil.rib.siteResp', "1D Site Response"), Codicon.lightbulb, 'small');

addItem(RibbonMenus.SoilSeismic, '2_LiquefactionAndSoils', 1, 'saengine.soil.liquefaction', localize('soil.rib.liq', "Liquefaction Screening"), Codicon.warning, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilSeismic, '2_LiquefactionAndSoils', 2, 'saengine.soil.specialSoils', localize('soil.rib.special', "Problem & Special Soils"), Codicon.shield, 'large', { precondition: projectOpen });

// Earth Pressure & Chemistry
addItem(RibbonMenus.SoilEarth, '1_EarthPressure', 1, 'saengine.soil.earthPressure', localize('soil.rib.earth', "Earth Pressure Profile"), Codicon.arrowBoth, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilEarth, '2_Chemistry', 1, 'saengine.soil.chemistry', localize('soil.rib.chem', "Chemistry & Durability"), Codicon.beaker, 'large', { precondition: projectOpen });

// Site & GIS
addItem(RibbonMenus.SoilSite, '1_SiteAndPlanning', 1, 'saengine.soil.locationSummary', localize('soil.rib.loc', "Site & Nearest Town"), Codicon.location, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilSite, '1_SiteAndPlanning', 2, 'saengine.soil.plotCompliance', localize('soil.rib.plot', "Plot & Planning Check"), Codicon.layout, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilSite, '1_SiteAndPlanning', 3, 'saengine.soil.terrainProfile', localize('soil.rib.terrain', "Cut & Fill Terrain"), Codicon.compass, 'small', { precondition: projectOpen });

addItem(RibbonMenus.SoilSite, '2_GisExchange', 1, 'saengine.soil.importGis', localize('soil.rib.impGis', "Import GIS"), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SoilSite, '2_GisExchange', 2, 'saengine.soil.exportGeoJson', localize('soil.rib.geojson', "GeoJSON"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.SoilSite, '2_GisExchange', 3, 'saengine.soil.exportGeoPackage', localize('soil.rib.gpkg', "GeoPackage"), Codicon.package, 'small', { precondition: projectOpen });
addItem(RibbonMenus.SoilSite, '2_GisExchange', 4, 'saengine.soil.openInQgis', localize('soil.rib.qgis', "Open in QGIS"), Codicon.linkExternal, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 4: Settings (Project Settings & Code Packs — 5 contextual tabs)

// Code & Packs
addItem(RibbonMenus.Settings, '1_CodePack', 1, 'saengine.settings.codePackInfo', localize('set.rib.packInfo', "Active Pack Info"), Codicon.book, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '1_CodePack', 2, 'saengine.settings.installedPacks', localize('set.rib.installed', "Installed Packages"), Codicon.package, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '1_CodePack', 3, 'saengine.settings.packTemplates', localize('set.rib.templates', "Pack Templates"), Codicon.files, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '2_PackAuthoring', 1, 'saengine.settings.diffPacks', localize('set.rib.diff', "Compare Packs"), Codicon.diff, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_PackAuthoring', 2, 'saengine.settings.validatePack', localize('set.rib.validatePack', "Validate Pack"), Codicon.checklist, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_PackAuthoring', 3, 'saengine.settings.checkTemplate', localize('set.rib.checkTpl', "Check .civil Archive"), Codicon.archive, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_PackAuthoring', 4, 'saengine.settings.trustAudit', localize('set.rib.trust', "Hooks & Trust"), Codicon.shield, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '3_Packages', 1, 'saengine.packages.show', localize('rib.set.packages', "Packages"), Codicon.package, 'large', { when: subViewWhen('settings.packages') });
addItem(RibbonMenus.Settings, '3_Packages', 2, 'saengine.codePacks.new', localize('rib.set.newCodePack', "New Code Pack"), Codicon.newFile, 'small', { when: subViewWhen('settings.packages') });
addItem(RibbonMenus.Settings, '3_Packages', 3, 'saengine.codePacks.install', localize('rib.set.installPkg', "Install Package"), Codicon.cloudDownload, 'small', { when: subViewWhen('settings.packages') });

// Loads
addItem(RibbonMenus.SettingsLoads, '1_AreaAndChoices', 1, 'saengine.settings.areaLoads', localize('set.rib.areaLoads', "Area Loads Audit"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsLoads, '1_AreaAndChoices', 2, 'saengine.settings.packChoices', localize('set.rib.choices', "Occupancies & Systems"), Codicon.listFlat, 'large', { precondition: projectOpen });

addItem(RibbonMenus.SettingsLoads, '2_Combinations', 1, 'saengine.settings.combinationsPreview', localize('set.rib.combos', "Load Combinations"), Codicon.symbolOperator, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsLoads, '2_Combinations', 2, 'saengine.settings.resetDefaults', localize('rib.set.reset', "Reset to Defaults"), Codicon.discard, 'small', { precondition: projectOpen });

// Seismic & Wind
addItem(RibbonMenus.SettingsHazard, '1_HazardParameters', 1, 'saengine.settings.hazardSummary', localize('set.rib.hazard', "Derived Seismic & Wind"), Codicon.pulse, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsHazard, '1_HazardParameters', 2, 'saengine.settings.townCatalogue', localize('set.rib.towns', "Town Hazard Table"), Codicon.globe, 'large', { precondition: projectOpen });

addItem(RibbonMenus.SettingsHazard, '2_OnlineHazard', 1, 'saengine.settings.hazardOffers', localize('set.rib.offers', "Hazard Providers"), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsHazard, '2_OnlineHazard', 2, 'saengine.settings.hazardLookup', localize('set.rib.lookup', "Fetch Hazard Values"), Codicon.globe, 'large', { precondition: projectOpen });

// Checks
addItem(RibbonMenus.SettingsChecks, '1_Validation', 1, 'saengine.settings.validateAll', localize('set.rib.valAll', "Validate All Parts"), Codicon.checkAll, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsChecks, '1_Validation', 2, 'saengine.settings.checkSettings', localize('set.rib.chkSet', "Check Settings"), Codicon.pass, 'large', { precondition: projectOpen });

addItem(RibbonMenus.SettingsChecks, '2_Conformance', 1, 'saengine.settings.conformance', localize('set.rib.conf', "Pack Conformance"), Codicon.verified, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsChecks, '2_Conformance', 2, 'saengine.settings.guardrails', localize('set.rib.guard', "Guardrail Limits"), Codicon.law, 'large', { precondition: projectOpen });

// Overrides
addItem(RibbonMenus.SettingsOverrides, '1_CodeTables', 1, 'saengine.settings.codeValues', localize('set.rib.codeVals', "Browse Code Tables"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsOverrides, '1_CodeTables', 2, 'saengine.settings.activeOverrides', localize('set.rib.over', "Overrides Audit"), Codicon.edit, 'large', { precondition: projectOpen });

addItem(RibbonMenus.SettingsOverrides, '2_FallbacksAndTemplates', 1, 'saengine.settings.packFallbacks', localize('set.rib.fall', "Practice Fallbacks"), Codicon.info, 'large', { precondition: projectOpen });
addItem(RibbonMenus.SettingsOverrides, '2_FallbacksAndTemplates', 2, 'saengine.settings.codedGeometry', localize('set.rib.coded', "Coded Templates"), Codicon.symbolStructure, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 5: Library (Materials, Sections, Object Types, Modifiers & Checks — 4 contextual tabs)

// Materials (LibraryAddMaterialSubmenu registered in saengineLibrary under 1_AddMaterial)
addItem(RibbonMenus.Library, '1_AddMaterial', 2, 'saengine.library.materialSummary', localize('lib.rib.matSum', "Materials Summary"), Codicon.beaker, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Library, '1_AddMaterial', 3, 'saengine.library.concreteCalc', localize('lib.rib.concCalc', "Concrete & Mix Calc"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Library, '2_Edit', 1, 'saengine.library.cmd.duplicate', localize('rib.lib.duplicate', "Duplicate"), Codicon.copy, 'small');
addItem(RibbonMenus.Library, '2_Edit', 2, 'saengine.library.cmd.delete', localize('rib.lib.delete', "Delete"), Codicon.trash, 'small');

addItem(RibbonMenus.Library, '3_Exchange', 1, 'saengine.library.cmd.import', localize('rib.lib.import', "Import JSON..."), Codicon.cloudDownload, 'small');
addItem(RibbonMenus.Library, '3_Exchange', 2, 'saengine.library.cmd.export', localize('rib.lib.export', "Export JSON..."), Codicon.export, 'small');

// Sections
addItem(RibbonMenus.LibrarySections, '1_Sections', 1, 'saengine.section.new', localize('rib.lib.sectionDesigner', "Section Designer"), Codicon.symbolRuler, 'large', { precondition: projectOpen });
addItem(RibbonMenus.LibrarySections, '1_Sections', 2, 'saengine.library.designedSections', localize('lib.rib.desSec', "Designed Sections"), Codicon.symbolRuler, 'large', { precondition: projectOpen });
addItem(RibbonMenus.LibrarySections, '1_Sections', 3, 'saengine.library.sectionCapacity', localize('lib.rib.secCap', "P-M & M-κ Analysis"), Codicon.graphLine, 'small', { precondition: projectOpen });

addItem(RibbonMenus.LibrarySections, '2_Catalogues', 1, 'saengine.library.steelCatalogue', localize('lib.rib.steel', "Steel Catalogue"), Codicon.library, 'large');
addItem(RibbonMenus.LibrarySections, '2_Catalogues', 2, 'saengine.library.sheetPiles', localize('lib.rib.sheetPiles', "Sheet Pile Catalogue"), Codicon.layoutPanel, 'small');
addItem(RibbonMenus.LibrarySections, '2_Catalogues', 3, 'saengine.library.profileProperties', localize('lib.rib.profProps', "Profile Properties"), Codicon.symbolField, 'small', { precondition: projectOpen });

// Object Types (LibraryAddObjectSubmenu registered in saengineLibrary under 1_AddObject)
addItem(RibbonMenus.LibraryObjects, '1_AddObject', 2, 'saengine.library.objectSchedule', localize('lib.rib.objSched', "Object Types Summary"), Codicon.symbolClass, 'large', { precondition: projectOpen });

addItem(RibbonMenus.LibraryObjects, '2_Components', 1, 'saengine.library.archTypes', localize('lib.rib.archTypes', "Architectural Types"), Codicon.typeHierarchy, 'large', { precondition: projectOpen });
addItem(RibbonMenus.LibraryObjects, '2_Components', 2, 'saengine.library.components', localize('lib.rib.comp', "Parametric Components"), Codicon.extensions, 'small', { precondition: projectOpen });
addItem(RibbonMenus.LibraryObjects, '2_Components', 3, 'saengine.library.barSizes', localize('lib.rib.bars', "Code Rebar Sizes"), Codicon.listOrdered, 'small', { precondition: projectOpen });

// Modifiers & Checks
addItem(RibbonMenus.LibraryChecks, '1_Modifiers', 1, 'saengine.library.cmd.stiffnessModifiers', localize('rib.lib.stiffness', "Stiffness Modifiers"), Codicon.settings, 'large');
addItem(RibbonMenus.LibraryChecks, '1_Modifiers', 2, 'saengine.library.modifiersAudit', localize('lib.rib.modsAudit', "Modifiers Audit"), Codicon.settings, 'large', { precondition: projectOpen });

addItem(RibbonMenus.LibraryChecks, '2_Checks', 1, 'saengine.library.checkAll', localize('lib.rib.checkAll', "Validate Libraries"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.LibraryChecks, '2_Checks', 2, 'saengine.library.limits', localize('lib.rib.limits', "Guardrail Limits"), Codicon.law, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 6: Plan (cross-part links; Floor Plan tools registered in saengineCad)


//#endregion

//#region Tab 11: MEP (discipline-scoped tabs)

// Coordination
addItem(RibbonMenus.MepCoordination, '1_Clashes', 1, 'saengine.mep.editor.importIfc', localize('rib.mep.importIfc', "Import MEP IFC"), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepCoordination, '1_Clashes', 2, 'saengine.mep.editor.suggestSleeves', localize('rib.mep.suggestSleeves', "Suggest Sleeves"), Codicon.wand, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepCoordination, '1_Clashes', 3, 'saengine.mep.editor.runClashTests', localize('rib.mep.runClashTests', "Run Clash Tests"), Codicon.runAll, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepCoordination, '1_Clashes', 4, 'saengine.mep.editor.recompute', localize('rib.mep.checkAgain', "Check Again"), Codicon.refresh, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepCoordination, '2_Openings', 1, 'saengine.mep.coordination.openings', localize('rib.mep.openingChecks', "Opening Checks"), Codicon.circleLargeOutline, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepCoordination, '2_Openings', 2, 'saengine.mep.editor.addExternalModel', localize('rib.mep.addExternalModel', "Add External IFC"), Codicon.add, 'small', { precondition: projectOpen });

// Issues
addItem(RibbonMenus.MepIssues, '1_BCF', 1, 'saengine.mep.editor.exportBcf', localize('rib.mep.exportBcf', "Export BCF..."), Codicon.export, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepIssues, '1_BCF', 2, 'saengine.mep.editor.importBcf', localize('rib.mep.importBcf', "Import BCF..."), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepIssues, '2_ModelChecks', 1, 'saengine.mep.coordination.checkIds', localize('rib.mep.checkIds', "Check IDS"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepIssues, '2_ModelChecks', 2, 'saengine.mep.editor.addIdsFile', localize('rib.mep.addIdsFile', "Add IDS File..."), Codicon.newFile, 'small', { precondition: projectOpen });

// Plumbing
addItem(RibbonMenus.MepPlumbing, '1_Occupancies', 1, 'saengine.mep.plumbing.occupancies', localize('rib.mep.plumbingOccupancies', "Water Occupancies"), Codicon.book, 'large');
addItem(RibbonMenus.MepPlumbing, '2_Branches', 1, 'saengine.mep.plumbing.branches', localize('rib.mep.plumbingBranches', "Wet-Room Branches"), Codicon.gitBranch, 'large', { precondition: projectOpen });

// Plumbing Design
addItem(RibbonMenus.MepPlumbingDesign, '1_HotAndGas', 1, 'saengine.mep.plumbing.hotWater', localize('rib.mep.hotWater', "Hot Water"), Codicon.beaker, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPlumbingDesign, '1_HotAndGas', 2, 'saengine.mep.plumbing.gas', localize('rib.mep.gas', "Gas & Medical Gas"), Codicon.flame, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPlumbingDesign, '2_DrainageAndRainwater', 1, 'saengine.mep.plumbing.drainage', localize('rib.mep.drainage', "Sanitary Drainage"), Codicon.arrowDown, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPlumbingDesign, '2_DrainageAndRainwater', 2, 'saengine.mep.plumbing.rainwater', localize('rib.mep.rainwater', "Rainwater & Harvesting"), Codicon.cloudDownload, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPlumbingDesign, '3_SepticAndSoakWell', 1, 'saengine.mep.plumbing.septic', localize('rib.mep.septic', "Septic & Soak Well"), Codicon.database, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPlumbingDesign, '4_PumpsAndHydraulics', 1, 'saengine.mep.plumbing.hydraulics', localize('rib.mep.hydraulics', "Pumps & Hydraulics"), Codicon.pulse, 'large', { precondition: projectOpen });

// HVAC
addItem(RibbonMenus.MepHvac, '1_HvacSummary', 1, 'saengine.mep.hvac.summary', localize('rib.mep.hvacSummary', "HVAC Summary"), Codicon.output, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepHvac, '1_HvacSummary', 2, 'saengine.mep.editor.cancelHvacLoads', localize('rib.mep.cancelHvacLoads', "Cancel Load Run"), Codicon.debugStop, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepHvac, '2_DuctOpenings', 1, 'saengine.mep.hvac.openingsCheck', localize('rib.mep.ductOpeningsCheck', "Duct Openings Audit"), Codicon.circleLargeOutline, 'large', { precondition: projectOpen });

// HVAC Analysis
addItem(RibbonMenus.MepHvacAnalysis, '1_Loads', 1, 'saengine.mep.hvac.roomLoads', localize('rib.mep.roomLoads', "Room Loads"), Codicon.dashboard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepHvacAnalysis, '1_Loads', 2, 'saengine.mep.hvac.heatingLoads', localize('rib.mep.heatingLoads', "Heating Loads"), Codicon.flame, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepHvacAnalysis, '2_AirDistribution', 1, 'saengine.mep.hvac.ductPressure', localize('rib.mep.ductPressure', "Duct Pressure"), Codicon.compass, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepHvacAnalysis, '2_AirDistribution', 2, 'saengine.mep.hvac.routeDucts', localize('rib.mep.routeDucts', "Route Ducts"), Codicon.wand, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepHvacAnalysis, '3_Envelope', 1, 'saengine.mep.hvac.constructions', localize('rib.mep.hvacConstructions', "Constructions"), Codicon.layers, 'large');
addItem(RibbonMenus.MepHvacAnalysis, '3_Envelope', 2, 'saengine.mep.hvac.tables', localize('rib.mep.hvacTables', "Design Tables"), Codicon.table, 'large');

// Electrical
addItem(RibbonMenus.MepElectrical, '1_ElectricalUses', 1, 'saengine.mep.electrical.uses', localize('rib.mep.electricalUses', "Electrical Uses"), Codicon.book, 'large');
addItem(RibbonMenus.MepElectrical, '2_DemandAndRooms', 1, 'saengine.mep.electrical.demand', localize('rib.mep.electricalDemand', "Demand Schedule"), Codicon.graph, 'large', { precondition: projectOpen });

// Power Systems
addItem(RibbonMenus.MepPowerSystems, '1_Distribution', 1, 'saengine.mep.electrical.boards', localize('rib.mep.boards', "Boards & Circuits"), Codicon.circuitBoard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '1_Distribution', 2, 'saengine.mep.electrical.cables', localize('rib.mep.cables', "Cable Sizing"), Codicon.plug, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '1_Distribution', 3, 'saengine.mep.electrical.voltageDrop', localize('rib.mep.voltageDrop', "Voltage Drop"), Codicon.pulse, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '1_Distribution', 4, 'saengine.mep.electrical.shortCircuit', localize('rib.mep.shortCircuit', "Short Circuit"), Codicon.symbolEvent, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '2_Lighting', 1, 'saengine.mep.electrical.lighting', localize('rib.mep.lighting', "Lighting Design"), Codicon.lightbulb, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '3_SupplyAndProtection', 1, 'saengine.mep.electrical.supply', localize('rib.mep.electricalSupply', "Substation & Generator"), Codicon.zap, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '3_SupplyAndProtection', 2, 'saengine.mep.electrical.lightning', localize('rib.mep.electricalLightning', "Lightning Protection"), Codicon.shield, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepPowerSystems, '3_SupplyAndProtection', 3, 'saengine.mep.electrical.risers', localize('rib.mep.electricalRisers', "Risers & Trays"), Codicon.arrowUp, 'small', { precondition: projectOpen });

// Fire
addItem(RibbonMenus.MepFire, '1_FireHydraulics', 1, 'saengine.mep.fire.hydraulics', localize('rib.mep.fireHydraulics', "Fire Hydraulics"), Codicon.pulse, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepFire, '2_FireSleeves', 1, 'saengine.mep.fire.openingsCheck', localize('rib.mep.fireSleevesAudit', "Fire Sleeves Audit"), Codicon.circleLargeOutline, 'large', { precondition: projectOpen });

// Fire Systems
addItem(RibbonMenus.MepFireSystems, '1_Suppression', 1, 'saengine.mep.fire.sprinklers', localize('rib.mep.sprinklers', "Place Sprinklers"), Codicon.flame, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepFireSystems, '2_Detection', 1, 'saengine.mep.fire.alarm', localize('rib.mep.alarm', "Fire Alarm"), Codicon.warning, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepFireSystems, '3_WaterSupply', 1, 'saengine.mep.fire.proposals', localize('rib.mep.fireProposals', "Water Supply Proposals"), Codicon.database, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepFireSystems, '4_Requirements', 1, 'saengine.mep.fire.requirements', localize('rib.mep.fireRequirements', "Code Requirements"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepFireSystems, '4_Requirements', 2, 'saengine.mep.fire.chapter', localize('rib.mep.fireChapter', "Fire Report Chapter"), Codicon.fileText, 'small');

// Systems
addItem(RibbonMenus.MepSystems, '1_SystemBrowser', 1, 'saengine.mep.systems.summary', localize('rib.mep.systemsSummary', "Systems Summary"), Codicon.typeHierarchy, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MepSystems, '1_SystemBrowser', 2, 'saengine.mep.editor.recomputeSystems', localize('rib.mep.recomputeSystems', "Check Systems"), Codicon.refresh, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepSystems, '1_SystemBrowser', 3, 'saengine.mep.editor.exportSystemBcf', localize('rib.mep.exportSystemBcf', "Export Warnings to BCF..."), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MepSystems, '2_Fabrication', 1, 'saengine.office.fabrication', localize('rib.mep.fabrication', "MEP Fabrication"), Codicon.tools, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 12: Analyze

addItem(RibbonMenus.Analyze, '1_Solver', 1, 'saengine.runAll', localize('rib.analyze.runAll', "Run All"), Codicon.play, 'large', { precondition: projectOpen, when: runAllRunning.negate() });
addItem(RibbonMenus.Analyze, '1_Solver', 1, 'saengine.runAll.cancel', localize('rib.analyze.stopRunAll', "Stop"), Codicon.debugStop, 'large', { precondition: runAllRunning, when: runAllRunning });
addSubmenu(RibbonMenus.Analyze, '1_Solver', 2, RibbonSubmenus.AnalyzeRun, localize('rib.analyze.run', "Run"), Codicon.runAll, 'large', true, 'saengine.fem.runAnalysis');
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 1, 'saengine.fem.runAnalysis', localize('rib.analyze.runAnalysis', "Run Analysis"), Codicon.runAll, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 2, 'saengine.analyze.runDerive', localize('rib.analyze.deriveOnly', "Derive Only"), Codicon.symbolStructure, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 3, 'saengine.analyze.runAnalyse', localize('rib.analyze.analyseOnly', "Analyse Only"), Codicon.runAll, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 4, 'saengine.analyze.runDesign', localize('rib.analyze.designOnly', "Design Only"), Codicon.symbolRuler, { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 3, 'saengine.fem.runSelectedCases', localize('rib.analyze.selectedCases', "Selected Cases"), Codicon.checklist, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 4, 'saengine.fem.deriveModel', localize('rib.analyze.deriveModel', "Derive Model"), Codicon.symbolStructure, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '2_Advanced', 2, 'saengine.fem.cfdWind', localize('rib.analyze.cfdWind', "CFD Wind Tunnel"), Codicon.symbolEvent, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '3_MeshAndView', 1, 'saengine.fem.toggleMeshNodes', localize('rib.analyze.meshNodes', "Mesh Nodes"), Codicon.circleSmallFilled, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 2, 'saengine.fem.fitView', localize('rib.analyze.fitView', "Zoom to Fit"), Codicon.screenFull, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 3, 'saengine.fem.showLog', localize('rib.analyze.log', "Analysis Log"), Codicon.output, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 4, 'saengine.runAll.showSteps', localize('rib.analyze.steps', "Run All Steps"), Codicon.listFlat, 'small', { precondition: projectOpen });

// #303: the picked member's end releases and the picked joint's point spring (Properties panel).
addItem(RibbonMenus.Analyze, '4_Assign', 1, 'saengine.fem.endReleases', localize('rib.analyze.endReleases', "End Releases…"), Codicon.debugDisconnect, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '4_Assign', 2, 'saengine.fem.pointSpring', localize('rib.analyze.pointSpring', "Point Spring…"), Codicon.pinned, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 13: Results

addItem(RibbonMenus.Results, '1_Display', 1, 'saengine.fem.display.deformed', localize('rib.res.deformed', "Deflected Shape"), Codicon.pulse, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Results, '1_Display', 2, RibbonSubmenus.FemResultForces, localize('rib.res.forces', "Forces & Shells"), Codicon.graphLine, 'large', false);
addSubItem(RibbonSubmenus.FemResultForces, '1_general', 1, 'saengine.fem.display.none', localize('rib.res.modelOnly', "Model Only"), Codicon.symbolStructure, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '1_general', 2, 'saengine.fem.display.reactions', localize('rib.res.reactions', "Support Reactions"), Codicon.arrowUp, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 1, 'saengine.fem.display.N', localize('rib.res.axial', "Axial Force N"), Codicon.arrowBoth, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 2, 'saengine.fem.display.Vy', localize('rib.res.shearY', "Shear Force V2"), Codicon.arrowDown, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 3, 'saengine.fem.display.Vz', localize('rib.res.shearZ', "Shear Force V3"), Codicon.arrowDown, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 4, 'saengine.fem.display.T', localize('rib.res.torsion', "Torsion T"), Codicon.sync, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 5, 'saengine.fem.display.My', localize('rib.res.momentY', "Moment M2"), Codicon.graphLine, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '2_frame', 6, 'saengine.fem.display.Mz', localize('rib.res.momentZ', "Moment M3"), Codicon.graphLine, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '3_shell', 1, 'saengine.fem.display.M11', localize('rib.res.m11', "Shell Moment M11"), Codicon.layout, { precondition: projectOpen });
addSubItem(RibbonSubmenus.FemResultForces, '3_shell', 2, 'saengine.fem.display.M22', localize('rib.res.m22', "Shell Moment M22"), Codicon.layout, { precondition: projectOpen });
addItem(RibbonMenus.Results, '1_Display', 3, 'saengine.fem.exportAnimation', localize('rib.res.animation', "Export Animation"), Codicon.deviceCameraVideo, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Results, '2_ChartsAndTables', 2, 'saengine.fem.toggleTables', localize('rib.res.tables', "Result Tables"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 3, 'saengine.fem.exportResultTables', localize('rib.res.exportTables', "Export Tables"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 4, 'saengine.fem.showBridgeResults', localize('rib.res.bridge', "Bridge Results"), Codicon.compass, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Results, '3_Inspect3D', 1, 'saengine.fem.sectionBox', localize('rib.res.sectionBox', "Section Box"), Codicon.symbolMisc, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '3_Inspect3D', 2, 'saengine.fem.measure', localize('rib.res.measure', "Measure"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '3_Inspect3D', 3, 'saengine.fem.revealHidden', localize('rib.res.revealHidden', "Reveal Hidden"), Codicon.lightbulb, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 14: Design

addItem(RibbonMenus.Design, '1_Checks', 1, 'saengine.fem.toggleDesignUtilisation', localize('rib.design.utilisation', "Utilisation"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Checks', 2, 'saengine.analyze.checkProject', localize('rib.design.checkProject', "Check Project"), Codicon.pass, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Checks', 3, 'saengine.analyze.validateProject', localize('rib.design.validate', "Validate"), Codicon.shield, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Design, '2_Detailing', 2, 'saengine.fem.pickMember', localize('rib.design.memberDetails', "Member Details"), Codicon.search, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Detailing', 3, 'saengine.fem.strutAndTie', localize('rib.design.strutAndTie', "Strut-and-Tie"), Codicon.symbolStructure, 'large', { precondition: projectOpen });

addU6ePanelItem(RibbonMenus.Design, '3_ConcreteDesign', 1, 'fem.punchingShear', localize('u6e.rib.fem.punchingShear', "Punching Shear"), Codicon.circleLargeFilled);
addU6ePanelItem(RibbonMenus.Design, '3_ConcreteDesign', 2, 'fem.deflectionCheck', localize('u6e.rib.fem.deflectionCheck', "Deflection Check"), Codicon.graphLine);
addU6ePanelItem(RibbonMenus.Design, '3_ConcreteDesign', 3, 'fem.crackControl', localize('u6e.rib.fem.crackControl', "Crack Control"), Codicon.warning, 'small');
addU6ePanelItem(RibbonMenus.Design, '3_ConcreteDesign', 4, 'fem.torsionDesign', localize('u6e.rib.fem.torsionDesign', "Torsion Design"), Codicon.sync, 'small');
addU6ePanelItem(RibbonMenus.Design, '4_CapacityDetailing', 1, 'fem.capacitySeismicDetailing', localize('u6e.rib.fem.capacitySeismicDetailing', "Capacity & Seismic Detailing"), Codicon.shield);
addU6ePanelItem(RibbonMenus.Design, '4_CapacityDetailing', 2, 'fem.fireSteelConnections', localize('u6e.rib.fem.fireSteelConnections', "Fire, Steel & Connections"), Codicon.tools);

//#endregion

//#region U6e: FEM advanced analysis tabs

addU6ePanelItem(RibbonMenus.FemLoads, '1_LoadPattern', 1, 'fem.notionalLoads', localize('u6e.rib.fem.notionalLoads', "Notional Loads"), Codicon.arrowBoth);
addU6ePanelItem(RibbonMenus.FemLoads, '1_LoadPattern', 2, 'fem.patternLive', localize('u6e.rib.fem.patternLive', "Pattern Live Loads"), Codicon.symbolNumeric);
addU6ePanelItem(RibbonMenus.FemLoads, '1_LoadPattern', 3, 'fem.snowRainLoads', localize('u6e.rib.fem.snowRainLoads', "Snow & Rain Loads"), Codicon.cloud);
addU6ePanelItem(RibbonMenus.FemLoads, '2_SpecialtyLoads', 1, 'fem.thermalLoads', localize('u6e.rib.fem.thermalLoads', "Thermal Loads"), Codicon.flame);
addU6ePanelItem(RibbonMenus.FemLoads, '2_SpecialtyLoads', 2, 'fem.floodLoads', localize('u6e.rib.fem.floodLoads', "Flood Loads"), Codicon.globe);
addU6ePanelItem(RibbonMenus.FemLoads, '2_SpecialtyLoads', 3, 'fem.stairCraneLoads', localize('u6e.rib.fem.stairCraneLoads', "Stair & Crane Loads"), Codicon.tools);
addU6ePanelItem(RibbonMenus.FemLoads, '3_CombinationAudit', 1, 'fem.loadCombinations', localize('u6e.rib.fem.loadCombinations', "Load Combinations Audit"), Codicon.listOrdered);

addU6ePanelItem(RibbonMenus.FemSeismic, '1_SeismicHazard', 1, 'fem.spectralHazard', localize('u6e.rib.fem.spectralHazard', "Spectral Hazard"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.FemSeismic, '1_SeismicHazard', 2, 'fem.seismicSummary', localize('u6e.rib.fem.seismicSummary', "Seismic Summary"), Codicon.graphLine);
addU6ePanelItem(RibbonMenus.FemSeismic, '2_GroundMotions', 1, 'fem.groundMotions', localize('u6e.rib.fem.groundMotions', "Ground Motions"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.FemSeismic, '2_GroundMotions', 2, 'fem.linearTimeHistory', localize('u6e.rib.fem.linearTimeHistory', "Linear Time History"), Codicon.debug);
addU6ePanelItem(RibbonMenus.FemSeismic, '3_SeismicResponse', 1, 'fem.irregularities', localize('u6e.rib.fem.irregularities', "Seismic Irregularities"), Codicon.warning);
addU6ePanelItem(RibbonMenus.FemSeismic, '3_SeismicResponse', 2, 'fem.torsionalEffects', localize('u6e.rib.fem.torsionalEffects', "Torsional Effects"), Codicon.sync);
addU6ePanelItem(RibbonMenus.FemSeismic, '3_SeismicResponse', 3, 'fem.twoLevelSeismic', localize('u6e.rib.fem.twoLevelSeismic', "Two-Level Seismic"), Codicon.layers);
addU6ePanelItem(RibbonMenus.FemSeismic, '3_SeismicResponse', 4, 'fem.floorSpectra', localize('u6e.rib.fem.floorSpectra', "Floor Spectra"), Codicon.graph);
addU6ePanelItem(RibbonMenus.FemSeismic, '4_IsolationSystems', 1, 'fem.isolationDampers', localize('u6e.rib.fem.isolationDampers', "Isolation & Dampers"), Codicon.shield);

addU6ePanelItem(RibbonMenus.FemWind, '1_WindExposure', 1, 'fem.windSpeedFactors', localize('u6e.rib.fem.windSpeedFactors', "Wind Speed Factors"), Codicon.globe);
addU6ePanelItem(RibbonMenus.FemWind, '1_WindExposure', 2, 'fem.peakVelocityPressure', localize('u6e.rib.fem.peakVelocityPressure', "Peak Velocity Pressure"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.FemWind, '2_WindEffects', 1, 'fem.gustResponse', localize('u6e.rib.fem.gustResponse', "Gust Response"), Codicon.graphLine);
addU6ePanelItem(RibbonMenus.FemWind, '2_WindEffects', 2, 'fem.windComfort', localize('u6e.rib.fem.windComfort', "Wind Comfort"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.FemWind, '3_PressureCoefficients', 1, 'fem.localPressures', localize('u6e.rib.fem.localPressures', "Local Pressures"), Codicon.arrowBoth);
addU6ePanelItem(RibbonMenus.FemWind, '3_PressureCoefficients', 2, 'fem.openStructures', localize('u6e.rib.fem.openStructures', "Open Structures"), Codicon.symbolStructure);

addU6ePanelItem(RibbonMenus.FemNonlinear, '1_NonlinearAnalysis', 1, 'fem.pushoverAnalysis', localize('u6e.rib.fem.pushoverAnalysis', "Pushover Analysis"), Codicon.graphLine);
addU6ePanelItem(RibbonMenus.FemNonlinear, '1_NonlinearAnalysis', 2, 'fem.nonlinearHistory', localize('u6e.rib.fem.nonlinearHistory', "Nonlinear History"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.FemNonlinear, '2_StabilityChecks', 1, 'fem.pDeltaBuckling', localize('u6e.rib.fem.pDeltaBuckling', "P-Delta & Buckling"), Codicon.warning);
addU6ePanelItem(RibbonMenus.FemNonlinear, '2_StabilityChecks', 2, 'fem.swayDrift', localize('u6e.rib.fem.swayDrift', "Sway & Drift"), Codicon.arrowBoth);
addU6ePanelItem(RibbonMenus.FemNonlinear, '3_ConstructionStages', 1, 'fem.stagedConstruction', localize('u6e.rib.fem.stagedConstruction', "Staged Construction"), Codicon.layers);
addU6ePanelItem(RibbonMenus.FemNonlinear, '3_ConstructionStages', 2, 'fem.creepShrinkage', localize('u6e.rib.fem.creepShrinkage', "Creep & Shrinkage"), Codicon.graph);
addU6ePanelItem(RibbonMenus.FemNonlinear, '4_FoundationInteraction', 1, 'fem.ssiSprings', localize('u6e.rib.fem.ssiSprings', "Soil-Structure Interaction"), Codicon.symbolStructure);

addU6ePanelItem(RibbonMenus.FemServiceability, '1_SwayAndSettlement', 1, 'fem.differentialSettlement', localize('u6e.rib.fem.differentialSettlement', "Differential Settlement"), Codicon.arrowDown);
addU6ePanelItem(RibbonMenus.FemServiceability, '2_VibrationChecks', 1, 'fem.floorVibration', localize('u6e.rib.fem.floorVibration', "Floor Vibration"), Codicon.pulse);

//#endregion

//#region U6e: BIM, Architecture, Documents, Studies and Exports

addU6ePanelItem(RibbonMenus.BimExchange, '1_ModelExchange', 1, 'bim.syncStamps', localize('u6e.rib.bim.syncStamps', "Model Sync Status"), Codicon.sync);
addU6ePanelItem(RibbonMenus.BimExchange, '2_IFCValidation', 1, 'bim.ifcCheck', localize('u6e.rib.bim.ifcCheck', "Structural IFC Check"), Codicon.checklist);
addU6ePanelItem(RibbonMenus.BimExchange, '3_ModelReview', 1, 'bim.detailingModel', localize('u6e.rib.bim.detailingModel', "Detailing Model Audit"), Codicon.layers);

addU6ePanelItem(RibbonMenus.BimFabrication, '1_RebarModel', 1, 'bim.rebarCages', localize('u6e.rib.bim.rebarCages', "Rebar Cages"), Codicon.symbolStructure);
addU6ePanelItem(RibbonMenus.BimFabrication, '2_FabricationSchedules', 1, 'bim.barBendingSchedule', localize('u6e.rib.bim.barBendingSchedule', "Bar Bending Schedule"), Codicon.listOrdered);

addU6ePanelItem(RibbonMenus.BimStudies, '1_DaylightStudy', 1, 'bim.studyDaylight', localize('u6e.rib.bim.studyDaylight', "Daylight & Solar Study"), Codicon.lightbulb);
addU6ePanelItem(RibbonMenus.BimStudies, '2_EnvironmentStudy', 1, 'bim.studyNoise', localize('u6e.rib.bim.studyNoise', "Noise Study"), Codicon.pulse);
addU6ePanelItem(RibbonMenus.BimStudies, '3_PhaseReview', 1, 'bim.studyPhasing', localize('u6e.rib.bim.studyPhasing', "Phasing Summary"), Codicon.layers);
addU6ePanelItem(RibbonMenus.BimStudies, '4_SitePlanning', 1, 'bim.studySite', localize('u6e.rib.bim.studySite', "Plot Planning"), Codicon.compass);

addU6ePanelItem(RibbonMenus.ArchitectureRooms, '1_RoomChecks', 1, 'architecture.roomsCheck', localize('u6e.rib.arch.roomsCheck', "Rooms Check"), Codicon.checklist);
addU6ePanelItem(RibbonMenus.ArchitectureRooms, '2_MassingReview', 1, 'architecture.massingFloors', localize('u6e.rib.arch.massingFloors', "Massing & Floors"), Codicon.home);
addU6ePanelItem(RibbonMenus.ArchitectureRooms, '3_EnvelopeReview', 1, 'architecture.roofCeilingCurtain', localize('u6e.rib.arch.roofCeilingCurtain', "Roof, Ceiling & Curtain Wall"), Codicon.layers);

addU6ePanelItem(RibbonMenus.ArchitectureExchange, '1_IFCValidation', 1, 'architecture.ifcCheck', localize('u6e.rib.arch.ifcCheck', "Structural IFC Check"), Codicon.checklist);
addU6ePanelItem(RibbonMenus.ArchitectureExchange, '2_ScanData', 1, 'architecture.pointCloudStatus', localize('u6e.rib.arch.pointCloudStatus', "Point Cloud Status"), Codicon.symbolFile);

addU6ePanelItem(RibbonMenus.ArchitectureEnvironment, '1_DaylightStudy', 1, 'architecture.daylight', localize('u6e.rib.arch.daylight', "Daylight Study"), Codicon.lightbulb);
addU6ePanelItem(RibbonMenus.ArchitectureEnvironment, '2_SolarExposure', 1, 'architecture.sun', localize('u6e.rib.arch.sun', "Solar Exposure"), Codicon.lightbulb);
addU6ePanelItem(RibbonMenus.ArchitectureEnvironment, '3_RoadNoise', 1, 'architecture.noise', localize('u6e.rib.arch.noise', "Road Noise Study"), Codicon.pulse);

addU6ePanelItem(RibbonMenus.DocumentsDrawings, '1_DrawingReview', 1, 'documents.drawingAutomation', localize('u6e.rib.docs.drawingAutomation', "Drawing Automation Review"), Codicon.wand);
addU6ePanelItem(RibbonMenus.DocumentsDrawings, '2_DrawingInventory', 1, 'documents.drawingList', localize('u6e.rib.docs.drawingList', "Drawing Inventory"), Codicon.files);

addU6ePanelItem(RibbonMenus.DocumentsSheets, '1_SheetIssue', 1, 'documents.sheetInventory', localize('u6e.rib.docs.sheetInventory', "Sheet Inventory"), Codicon.layout);
addU6ePanelItem(RibbonMenus.DocumentsSheets, '2_ProjectInformation', 1, 'documents.projectMetadata', localize('u6e.rib.docs.projectMetadata', "Project Metadata"), Codicon.info);

addU6ePanelItem(RibbonMenus.DocumentsSchedules, '1_ClauseTraceability', 1, 'documents.clauseTraceability', localize('u6e.rib.docs.clauseTraceability', "Clause Traceability"), Codicon.book);
addU6ePanelItem(RibbonMenus.DocumentsSchedules, '2_ScheduleCategories', 1, 'documents.scheduleCategories', localize('u6e.rib.docs.scheduleCategories', "Schedule Categories"), Codicon.listOrdered);

addU6ePanelItem(RibbonMenus.DocumentsReports, '1_CalculationPackages', 1, 'documents.calculationPackage', localize('u6e.rib.docs.calculationPackage', "Calculation Package"), Codicon.report);
addU6ePanelItem(RibbonMenus.DocumentsReports, '2_WorksheetInventory', 1, 'documents.worksheetInventory', localize('u6e.rib.docs.worksheetInventory', "Worksheet Inventory"), Codicon.symbolNumeric);

addU6ePanelItem(RibbonMenus.StudiesDesign, '1_SpecialStructures', 1, 'studies.specialStructures', localize('u6e.rib.studies.specialStructures', "Special Structures"), Codicon.symbolStructure);
addU6ePanelItem(RibbonMenus.StudiesDesign, '2_PhaseReview', 1, 'studies.phasingSummary', localize('u6e.rib.studies.phasingSummary', "Phasing Summary"), Codicon.layers);

addU6ePanelItem(RibbonMenus.StudiesEnvironment, '1_SolarAndDaylight', 1, 'studies.daylightSolar', localize('u6e.rib.studies.daylightSolar', "Daylight & Solar Study"), Codicon.lightbulb);
addU6ePanelItem(RibbonMenus.StudiesEnvironment, '2_EnvironmentStudy', 1, 'studies.noiseStudy', localize('u6e.rib.studies.noiseStudy', "Noise Study"), Codicon.pulse);

addU6ePanelItem(RibbonMenus.StudiesSite, '1_SitePlanning', 1, 'studies.plotPlanning', localize('u6e.rib.studies.plotPlanning', "Plot Planning"), Codicon.compass);
addU6ePanelItem(RibbonMenus.StudiesSite, '2_TerrainReview', 1, 'studies.terrain', localize('u6e.rib.studies.terrain', "Terrain Mesh"), Codicon.globe);

addU6ePanelItem(RibbonMenus.StudiesVerification, '1_BatchVerification', 1, 'studies.batchCheck', localize('u6e.rib.studies.batchCheck', "Batch Check"), Codicon.checkAll);
addU6ePanelItem(RibbonMenus.StudiesVerification, '2_VerificationCases', 1, 'studies.verificationCases', localize('u6e.rib.studies.verificationCases', "Verification Cases"), Codicon.listFlat);
addU6ePanelItem(RibbonMenus.StudiesVerification, '3_VerificationStatus', 1, 'studies.verificationStatus', localize('u6e.rib.studies.verificationStatus', "Verification Status"), Codicon.verified);
addU6ePanelItem(RibbonMenus.StudiesVerification, '4_VerificationRun', 1, 'studies.verificationRun', localize('u6e.rib.studies.verificationRun', "Run Verification"), Codicon.play);

addU6ePanelItem(RibbonMenus.ExportsFabrication, '1_FabricationPreview', 1, 'exports.fabricationPreview', localize('u6e.rib.exports.fabricationPreview', "Fabrication Preview"), Codicon.tools);
addU6ePanelItem(RibbonMenus.ExportsFabrication, '2_FabricationSchedules', 1, 'exports.bbsReconciliation', localize('u6e.rib.exports.bbsReconciliation', "Bar Schedule Reconciliation"), Codicon.listOrdered);

addU6ePanelItem(RibbonMenus.ExportsArchive, '1_ArchiveReview', 1, 'exports.archiveInspection', localize('u6e.rib.exports.archiveInspection', "Archive Inspection"), Codicon.archive);
addU6ePanelItem(RibbonMenus.ExportsArchive, '2_StructuralValidation', 1, 'exports.structuralIfcCheck', localize('u6e.rib.exports.structuralIfcCheck', "Structural IFC Check"), Codicon.checklist);
addU6ePanelItem(RibbonMenus.ExportsArchive, '3_FormatValidation', 1, 'exports.formatMatrix', localize('u6e.rib.exports.formatMatrix', "Export Format Matrix"), Codicon.export);
addSubmenu(RibbonMenus.ExportsArchive, '1_ArchiveReview', 2, RibbonSubmenus.OutputArchive, localize('rib.out.archive', "Archive .civil"), Codicon.archive, 'large', true, 'saengine.project.exportArchive');
addItem(RibbonMenus.ExportsArchive, '3_FormatValidation', 2, 'saengine.settings.validateAll', localize('set.rib.valAll', "Validate All Parts"), Codicon.checkAll, 'small', { precondition: projectOpen });

// Rehome the existing exchange actions without changing their command IDs.
addItem(RibbonMenus.ExportsExchange, '1_AnalysisFormats', 1, 'saengine.export.e2kOptions', localize('rib.out.e2kOptions', "ETABS .e2k Options..."), Codicon.export, 'large', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '1_AnalysisFormats', 2, 'saengine.export.s2k', localize('rib.out.s2k', "SAP2000 .s2k"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '1_AnalysisFormats', 3, 'saengine.export.std', localize('rib.out.std', "STAAD .std"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '2_ExchangeFormats', 1, 'saengine.export.saf', localize('rib.out.saf', "SAF (.xlsx)"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '2_ExchangeFormats', 2, 'saengine.export.cis2', localize('rib.out.cis2', "CIS/2"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '2_ExchangeFormats', 3, 'saengine.export.sdnf', localize('rib.out.sdnf', "SDNF Steel"), Codicon.tools, 'small', { precondition: projectOpen });
addItem(RibbonMenus.ExportsExchange, '3_ExchangeGuides', 1, 'saengine.export.detailingNote', localize('rib.out.detailingNote', "Steel Detailing Guide"), Codicon.info, 'small');

//#endregion
//#region Tab 15: Foundations (Substructure — 6 contextual tabs)

// Shallow & Raft
addItem(RibbonMenus.Foundations, '1_Shallow', 1, 'saengine.substructure.addFooting', localize('fdn.rib.addFooting', "Add Footing"), Codicon.add, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '1_Shallow', 2, 'saengine.substructure.addRaft', localize('fdn.rib.addRaft', "Add Raft"), Codicon.primitiveSquare, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '1_Shallow', 3, 'saengine.substructure.addStrip', localize('fdn.rib.addStrip', "Strip Footing"), Codicon.layoutPanel, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '1_Shallow', 4, 'saengine.substructure.addTieBeam', localize('fdn.rib.addTie', "Add Tie Beam"), Codicon.dash, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '1_Shallow', 5, 'saengine.substructure.selectUncovered', localize('fdn.rib.uncovered', "Uncovered Columns"), Codicon.selection, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Foundations, '2_Sizing', 1, 'saengine.substructure.sizeAll', localize('fdn.rib.sizeAll', "Size Footings"), Codicon.wand, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '2_Sizing', 2, 'saengine.substructure.importFootings', localize('fdn.rib.import', "Import Footings"), Codicon.cloudDownload, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '2_Sizing', 3, 'saengine.substructure.recompute', localize('fdn.rib.recompute', "Check Again"), Codicon.refresh, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Foundations, '3_Geotechnical', 1, 'saengine.substructure.sizeSummary', localize('fdn.rib.sizeSum', "Sizing Summary"), Codicon.symbolRuler, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Foundations, '3_Geotechnical', 2, 'saengine.substructure.piledRaft', localize('fdn.rib.piledRaft', "Piled Raft"), Codicon.lightbulb, 'small');

// Piles
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 1, 'saengine.substructure.addPileCap', localize('fdn.rib.addCap', "Add Pile Cap"), Codicon.circleLargeOutline, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 2, 'saengine.substructure.placePiles', localize('fdn.rib.placePiles', "Place Piles"), Codicon.circleFilled, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 3, 'saengine.substructure.pileGrid', localize('fdn.rib.pileGrid', "Pile Grid"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 4, 'saengine.substructure.pileGroup', localize('fdn.rib.pileGroup', "Pile Group"), Codicon.location, 'small', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 5, 'saengine.substructure.makeCap', localize('fdn.rib.makeCap', "Make Cap"), Codicon.package, 'small', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '1_Piles', 6, 'saengine.substructure.addPileType', localize('fdn.rib.addPileType', "Add Pile Type"), Codicon.newFile, 'small', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsPiles, '2_GradeBeams', 1, 'saengine.substructure.gradeBeam', localize('fdn.rib.gradeBeam', "Draw Grade Beam"), Codicon.arrowBoth, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '2_GradeBeams', 2, 'saengine.substructure.connectBeams', localize('fdn.rib.connect', "Connect Beams"), Codicon.gitMerge, 'small', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsPiles, '3_PileDetailing', 1, 'saengine.substructure.pileDetailing', localize('fdn.rib.pileDet', "Pile Detailing & Mix"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPiles, '3_PileDetailing', 2, 'saengine.substructure.pileLoadTests', localize('fdn.rib.loadTests', "Pile Load Tests"), Codicon.beaker, 'large', { precondition: projectOpen });

// Pile Analysis
addItem(RibbonMenus.FoundationsPileAnalysis, '1_AxialCapacity', 1, 'saengine.substructure.pileCapacity', localize('fdn.rib.pcap', "Single-Pile Capacity"), Codicon.arrowDown, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPileAnalysis, '1_AxialCapacity', 2, 'saengine.substructure.downdrag', localize('fdn.rib.downdrag', "Downdrag & Uplift"), Codicon.triangleDown, 'large', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsPileAnalysis, '2_LateralAndSettlement', 1, 'saengine.substructure.pileLateral', localize('fdn.rib.plat', "Lateral & Broms Hu"), Codicon.arrowRight, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPileAnalysis, '2_LateralAndSettlement', 2, 'saengine.substructure.pileSettlement', localize('fdn.rib.psett', "Group Settlement"), Codicon.graphLine, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsPileAnalysis, '2_LateralAndSettlement', 3, 'saengine.substructure.pileGroupInteraction', localize('fdn.rib.grpInt', "Group Interaction"), Codicon.lightbulb, 'small');

// Retaining & Excavation
addItem(RibbonMenus.FoundationsRetaining, '1_RetainingElements', 1, 'saengine.substructure.addRetainingWall', localize('fdn.rib.addRetWall', "Add Retaining Wall"), Codicon.layoutSidebarLeft, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsRetaining, '1_RetainingElements', 2, 'saengine.substructure.addExcavation', localize('fdn.rib.addExc', "Add Excavation"), Codicon.debugPause, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsRetaining, '1_RetainingElements', 3, 'saengine.substructure.addSlope', localize('fdn.rib.addSlope', "Add Slope"), Codicon.graph, 'small', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsRetaining, '2_RetainingAnalysis', 1, 'saengine.substructure.embeddedWall', localize('fdn.rib.embWall', "Embedded Wall Check"), Codicon.shield, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsRetaining, '2_RetainingAnalysis', 2, 'saengine.substructure.basementLoads', localize('fdn.rib.baseLoads', "Basement Loads (H)"), Codicon.layers, 'small', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsRetaining, '2_RetainingAnalysis', 3, 'saengine.substructure.excavationReport', localize('fdn.rib.excRep', "Retaining & Exc. Audit"), Codicon.checklist, 'small', { precondition: projectOpen });

// Slabs & Machine
addItem(RibbonMenus.FoundationsSpecial, '1_SpecialElements', 1, 'saengine.substructure.addGroundSlab', localize('fdn.rib.addGSlab', "Add Slab on Grade"), Codicon.browser, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsSpecial, '1_SpecialElements', 2, 'saengine.substructure.addMachine', localize('fdn.rib.addMachine', "Add Machine Block"), Codicon.settingsGear, 'large', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsSpecial, '2_SpecialAnalysis', 1, 'saengine.substructure.groundSlabCalc', localize('fdn.rib.gslabCalc', "Slab on Grade Calc"), Codicon.symbolNumeric, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsSpecial, '2_SpecialAnalysis', 2, 'saengine.substructure.machineReport', localize('fdn.rib.machRep', "Machine & Slab Checks"), Codicon.pulse, 'large', { precondition: projectOpen });

// Detailing & Report

addItem(RibbonMenus.FoundationsReport, '2_Actions', 1, 'saengine.substructure.saveAndCheck', localize('fdn.rib.saveCheck', "Save & Check"), Codicon.checkAll, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsReport, '2_Actions', 2, 'saengine.substructure.delete', localize('fdn.rib.delete', "Delete Selected"), Codicon.trash, 'small', { precondition: projectOpen });

addItem(RibbonMenus.FoundationsReport, '3_Report', 1, 'saengine.substructure.designSummary', localize('fdn.rib.repSum', "Substructure Report"), Codicon.report, 'large', { precondition: projectOpen });
addItem(RibbonMenus.FoundationsReport, '3_Report', 2, 'saengine.substructure.limitState', localize('fdn.rib.limState', "Limit State Factors"), Codicon.law, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 16: BOQ (Bill of Quantities & Schedule of Rates — 4 contextual tabs)

// Quantities
addItem(RibbonMenus.BOQ, '1_Measure', 1, 'saengine.boq.measure', localize('boq.rib.measure', "Measure / Update"), Codicon.refresh, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '1_Measure', 2, 'saengine.boq.summary', localize('boq.rib.summary', "BOQ Summary"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '1_Measure', 3, 'saengine.boq.rebarSchedule', localize('boq.rib.bbs', "Rebar Schedule"), Codicon.listOrdered, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '1_Measure', 4, 'saengine.boq.conventions', localize('boq.rib.conv', "Estimating Rules"), Codicon.book, 'small', { precondition: projectOpen });

addItem(RibbonMenus.BOQ, '2_Views', 1, 'saengine.boq.toggleImperial', localize('boq.rib.imperial', "Feet Units"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '2_Views', 2, 'saengine.boq.expandAll', localize('boq.rib.expand', "Expand All"), Codicon.expandAll, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '2_Views', 3, 'saengine.boq.collapseAll', localize('boq.rib.collapse', "Collapse All"), Codicon.collapseAll, 'small', { precondition: projectOpen });

addItem(RibbonMenus.BOQ, '3_Export', 1, 'saengine.boq.exportXlsx', localize('rib.boq.xlsx', "Export Excel"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '3_Export', 2, 'saengine.boq.exportCsv', localize('rib.boq.csv', "Export CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });

// Rates & Costing
addItem(RibbonMenus.BOQCosting, '1_RatesAndCarbon', 1, 'saengine.boq.editRates', localize('rib.boq.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQCosting, '1_RatesAndCarbon', 2, 'saengine.boq.editCarbon', localize('rib.boq.carbon', "Carbon Factors"), Codicon.globe, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQCosting, '1_RatesAndCarbon', 3, 'saengine.boq.rateTemplates', localize('boq.rib.rateTpl', "Sample Rates"), Codicon.library, 'small');

addItem(RibbonMenus.BOQCosting, '2_CostAnalysis', 1, 'saengine.boq.costReport', localize('boq.rib.costRep', "Cost & Carbon Report"), Codicon.pieChart, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQCosting, '2_CostAnalysis', 2, 'saengine.boq.phaseBill', localize('boq.rib.phaseBill', "Phased BOQ"), Codicon.splitHorizontal, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQCosting, '2_CostAnalysis', 3, 'saengine.boq.costOptimise', localize('boq.rib.optimise', "Cost Optimisation"), Codicon.sparkle, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQCosting, '2_CostAnalysis', 4, 'saengine.boq.compareOptions', localize('boq.rib.compare', "Compare Versions"), Codicon.diff, 'small', { precondition: projectOpen });

// Construction Schedule
addItem(RibbonMenus.BOQSchedule, '1_Programme', 1, 'saengine.boq.generateSchedule', localize('boq.rib.genSched', "Generate 4D Programme"), Codicon.calendar, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQSchedule, '1_Programme', 2, 'saengine.boq.scheduleSummary', localize('boq.rib.schedSum', "Critical Path Audit"), Codicon.checklist, 'large', { precondition: projectOpen });

addItem(RibbonMenus.BOQSchedule, '2_RatesAndScheduleExport', 1, 'saengine.boq.productivityRates', localize('boq.rib.prod', "Crew Productivity"), Codicon.dashboard, 'large');
addItem(RibbonMenus.BOQSchedule, '2_RatesAndScheduleExport', 2, 'saengine.boq.exportSchedule', localize('boq.rib.expSched', "Export Schedule"), Codicon.export, 'large', { precondition: projectOpen });

// Takeoff
addItem(RibbonMenus.BOQTakeoff, '1_SpecialTakeoff', 1, 'saengine.boq.archTakeoff', localize('boq.rib.arch', "Architectural Takeoff"), Codicon.home, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQTakeoff, '1_SpecialTakeoff', 2, 'saengine.boq.precastSchedule', localize('boq.rib.precast', "Precast Piece Schedule"), Codicon.symbolStructure, 'large', { precondition: projectOpen });

addItem(RibbonMenus.BOQTakeoff, '2_PdfTakeoff', 1, 'saengine.boq.takeoffSummary', localize('boq.rib.takeoffSum', "2D PDF Takeoff"), Codicon.filePdf, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQTakeoff, '2_PdfTakeoff', 2, 'saengine.boq.pdfCalibrate', localize('boq.rib.calibrate', "Calibrate PDF Scale"), Codicon.compass, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 17: Output

addItem(RibbonMenus.Output, '1_Exports', 2, 'saengine.exports.revealFolder', localize('rib.out.revealFolder', "Exports Folder"), Codicon.folderOpened, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '1_Exports', 3, 'saengine.exports.refresh', localize('rib.out.refresh', "Refresh"), Codicon.refresh, 'small', { precondition: projectOpen });

// The floor plan's Output tab shows only drawing exports; project-wide exports stay in the Exports window.
for (const outputGroup of ['1_Exports', '2_IFC', '5_BOQAndReports']) {
	registerRibbonGroupWhen(RibbonMenus.Output, outputGroup, EXPORTS_WHEN);
}

addItem(RibbonMenus.Output, '2_IFC', 1, 'saengine.bim.exportIfcOptions', localize('rib.out.ifcOptions', "Export IFC..."), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_IFC', 2, 'saengine.bim.compareIfc', localize('rib.out.ifcCompare', "Compare IFC Revisions..."), Codicon.diff, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_IFC', 3, 'saengine.bim.exportIfc', localize('rib.out.ifc', "Quick Export IFC"), Codicon.export, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '3_BIMAndCAD', 1, 'saengine.floorPlan.exportDxf', localize('rib.out.dxf', "DXF Floor Plans"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_BIMAndCAD', 2, 'saengine.revit.exportUi', localize('rib.out.revitExport', "Export for Revit"), Codicon.sync, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_BIMAndCAD', 3, 'saengine.revit.importUi', localize('rib.out.revitImport', "Import from Revit..."), Codicon.cloudDownload, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '5_BOQAndReports', 1, 'saengine.boq.exportXlsx', localize('rib.out.boqXlsx', "BOQ Excel"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '5_BOQAndReports', 2, 'saengine.boq.exportCsv', localize('rib.out.boqCsv', "BOQ CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '5_BOQAndReports', 3, 'saengine.report.exportWord', localize('rib.out.wordReport', "Word Report"), Codicon.fileText, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '6_WebAndArchive', 1, 'saengine.export.webViewer', localize('rib.out.webViewer', "Web Viewer"), Codicon.browser, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Output, '6_WebAndArchive', 2, RibbonSubmenus.OutputArchive, localize('rib.out.archive', "Archive .civil"), Codicon.archive, 'large', true, 'saengine.project.exportArchive', FLOOR_PLAN_WHEN);
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 1, 'saengine.project.exportArchive', localize('rib.out.exportArchive', "Export Project (.civil)..."), Codicon.archive, { precondition: projectOpen });
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 2, 'saengine.project.openArchive', localize('rib.out.openArchive', "Inspect / Open Archive..."), Codicon.folderOpened, { when: EXPORTS_WHEN });

//#endregion

//#region Tab 18: Documents

addItem(RibbonMenus.Documents, '1_Drawings', 3, 'saengine.cad.openDxf', localize('rib.docs.openCad', "Open DXF in CAD"), Codicon.linkExternal, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '1_Drawings', 4, 'saengine.office.takeoff', localize('rib.docs.takeoff', "PDF Takeoff"), Codicon.preview, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Documents, '2_Views', 1, 'saengine.drawings.scopeBoxes', localize('rib.docs.scopeBoxes', "Scope Boxes"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Views', 2, 'saengine.drawings.callouts', localize('rib.docs.callouts', "Callouts"), Codicon.search, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Views', 3, 'saengine.drawings.keynotes', localize('rib.docs.keynotes', "Keynotes"), Codicon.tag, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Views', 4, 'saengine.drawings.legend', localize('rib.docs.legend', "Legend"), Codicon.bookmark, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Documents, '3_Annotation', 1, 'saengine.drawings.autoDimension', localize('rib.docs.autoDim', "Auto-Dimension"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_Annotation', 2, 'saengine.drawings.autoTag', localize('rib.docs.autoTag', "Auto-Tag"), Codicon.symbolKey, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_Annotation', 3, 'saengine.drawings.autoArrange', localize('rib.docs.autoArrange', "Arrange Labels"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_Annotation', 4, 'saengine.drawings.undoAutomation', localize('rib.docs.undoAuto', "Undo Automation"), Codicon.discard, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Documents, '4_Schedules', 1, 'saengine.drawings.scheduleBuilder', localize('rib.docs.scheduleBuilder', "Schedule Builder"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '4_Schedules', 3, 'saengine.boq.editRates', localize('rib.docs.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '4_Schedules', 4, 'saengine.boq.editCarbon', localize('rib.docs.carbon', "Carbon Factors"), Codicon.globe, 'small', { precondition: projectOpen });

addSubmenu(RibbonMenus.Documents, '5_Report', 1, RibbonSubmenus.DocsReport, localize('rib.docs.report', "Design Report"), Codicon.filePdf, 'large', true, 'saengine.report.print');
addSubItem(RibbonSubmenus.DocsReport, '1_report', 1, 'saengine.report.print', localize('rib.docs.printReport', "Print Design Report"), Codicon.filePdf, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '1_report', 2, 'saengine.report.exportWord', localize('rib.docs.wordReport', "Export Report to Word"), Codicon.fileText, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '2_config', 1, 'saengine.report.configure', localize('rib.docs.configureReport', "Configure Design Report..."), Codicon.settingsGear, { precondition: projectOpen });

addSubmenu(RibbonMenus.Documents, '5_Report', 2, RibbonSubmenus.DocsWorksheets, localize('rib.docs.worksheets', "Worksheets"), Codicon.symbolNumeric, 'large', true, 'saengine.worksheets.open');
addSubItem(RibbonSubmenus.DocsWorksheets, '1_ws', 1, 'saengine.worksheets.open', localize('rib.docs.openWorksheets', "Calculation Worksheets..."), Codicon.symbolNumeric, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsWorksheets, '1_ws', 2, 'saengine.worksheets.new', localize('rib.docs.newWorksheet', "New Calculation Worksheet..."), Codicon.add, { precondition: projectOpen });

//#endregion

//#region Tab 19: Studies

addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 1, 'saengine.office.schedule', localize('rib.studies.4d', "4D Programme"), Codicon.calendar, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 2, 'saengine.office.cost', localize('rib.studies.cost', "Cost Optimisation"), Codicon.graph, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 3, 'saengine.bim.play4d', localize('rib.studies.play4d', "Play 4D in BIM"), Codicon.play, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 4, 'saengine.office.takeoff', localize('rib.studies.takeoff', "2D PDF Takeoff"), Codicon.preview, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 5, 'saengine.office.fabrication', localize('rib.studies.fabrication', "MEP Fabrication"), Codicon.tools, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Studies, '2_Environmental', 1, 'saengine.office.site', localize('rib.studies.site', "Terrain, Sun & Noise"), Codicon.compass, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '2_Environmental', 2, 'saengine.studies.annualEnergy', localize('rib.studies.annualEnergy', "Annual Energy"), Codicon.pulse, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '2_Environmental', 3, 'saengine.studies.envelopeCompliance', localize('rib.studies.envelopeCompliance', "Envelope Compliance"), Codicon.pass, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Studies, '3_Optioneering', 1, 'saengine.office.phasing', localize('rib.studies.phasing', "Phases & Options"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '3_Optioneering', 2, 'saengine.studies.open', localize('rib.studies.designStudies', "Design Studies"), Codicon.beaker, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Studies, '3_Optioneering', 3, RibbonSubmenus.StudiesGraph, localize('rib.studies.visualProgram', "Visual Program"), Codicon.circuitBoard, 'large', true, 'saengine.graph.open');
addSubItem(RibbonSubmenus.StudiesGraph, '1_graph', 1, 'saengine.graph.open', localize('rib.studies.openGraph', "Open Visual Program..."), Codicon.circuitBoard, { precondition: projectOpen });
addSubItem(RibbonSubmenus.StudiesGraph, '1_graph', 2, 'saengine.graph.new', localize('rib.studies.newGraph', "New Visual Program..."), Codicon.add, { precondition: projectOpen });

//#endregion
