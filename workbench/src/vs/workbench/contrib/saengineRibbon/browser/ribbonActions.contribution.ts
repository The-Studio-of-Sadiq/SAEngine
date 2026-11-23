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
	['Tests', localize('ribbon.grp.tests', "Tests & Bearing")],
	['Export', localize('ribbon.grp.export', "Export")],
	['Settings', localize('ribbon.grp.settings', "Settings")],
	// Settings
	['ProjectAndSite', localize('ribbon.grp.projectSite', "Project & Site")],
	['Loads', localize('ribbon.grp.loads', "Loads")],
	['Engineering', localize('ribbon.grp.engineering', "Engineering")],
	['Outputs', localize('ribbon.grp.outputs', "Outputs")],
	['Packages', localize('ribbon.grp.packages', "Packages")],
	// Library
	['Switch', localize('ribbon.grp.switch', "Library")],
	['AddMaterial', localize('ribbon.grp.addMaterial', "Materials")],
	['AddObject', localize('ribbon.grp.addObject', "Object Types")],
	['Sections', localize('ribbon.grp.sections', "Sections & Stiffness")],
	['Exchange', localize('ribbon.grp.exchange', "Exchange")],
	// Plan
	['Place', localize('ribbon.grp.place', "Place")],
	['Edit', localize('ribbon.grp.edit', "Edit")],
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
	['Display', localize('ribbon.grp.display', "Display")],
	['ChartsAndTables', localize('ribbon.grp.chartsTables', "Charts & Tables")],
	['Inspect3D', localize('ribbon.grp.inspect3d', "3D Inspect")],
	['Checks', localize('ribbon.grp.checks', "Checks")],
	['Detailing', localize('ribbon.grp.detailing', "Detailing")],
	['Standards', localize('ribbon.grp.standards', "Standards")],
	// Foundations
	['Shallow', localize('ribbon.grp.shallow', "Shallow Foundations")],
	['Piles', localize('ribbon.grp.piles', "Piles & Caps")],
	['GradeBeams', localize('ribbon.grp.gradeBeams', "Grade Beams & Tools")],
	['Design', localize('ribbon.grp.design', "Design")],
	// BOQ
	['RatesAndCarbon', localize('ribbon.grp.ratesCarbon', "Rates & Carbon")],
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
): void {
	MenuRegistry.appendMenuItem(parentMenuId, {
		group,
		order,
		submenu,
		title,
		icon,
	});
}

//#endregion

//#region Tab 1: Home (always visible)

addItem(RibbonMenus.Home, '1_Project', 1, 'saengine.project.new', localize('rib.home.new', "New"), Codicon.newFolder, 'large');
addSubmenu(RibbonMenus.Home, '1_Project', 2, RibbonSubmenus.HomeOpen, localize('rib.home.open', "Open"), Codicon.folderOpened, 'large', true, 'saengine.project.open');
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 1, 'saengine.project.open', localize('rib.home.openProject', "Open Project..."), Codicon.folderOpened);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 2, 'saengine.project.openArchive', localize('rib.home.openArchive', "Open Project Archive..."), Codicon.archive);
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
addNestedSubmenu(RibbonSubmenus.HomeManage, '1_standards', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package);
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

addSubmenu(RibbonMenus.Project, '4_Standards', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package, 'large', true, 'saengine.packages.show');
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 1, 'saengine.packages.show', localize('rib.manage.showPackages', "Packages..."), Codicon.package);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 2, 'saengine.codePacks.new', localize('rib.manage.newCodePack', "New Code Pack..."), Codicon.newFile);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 3, 'saengine.codePacks.install', localize('rib.manage.installPkg', "Install Package from File..."), Codicon.cloudDownload);
addItem(RibbonMenus.Project, '4_Standards', 2, 'saengine.showPlannedFeatures', localize('rib.manage.planned', "Planned Features"), Codicon.lightbulb, 'small');
addItem(RibbonMenus.Project, '4_Standards', 3, 'saengine.components.show', localize('rib.manage.components', "Installer Components"), Codicon.extensions, 'small');
addItem(RibbonMenus.Project, '4_Standards', 4, 'saengine.update.check', localize('rib.manage.updates', "Check Updates"), Codicon.refresh, 'small');
addItem(RibbonMenus.Project, '4_Standards', 5, 'saengine.manage.verificationManual', localize('rib.manage.verificationManual', "Verification Manual (PDF)"), Codicon.filePdf, 'small');

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

//#region Tab 3: Soil Report (cross-part settings link; domain commands registered in saengineSoil)


//#endregion

//#region Tab 4: Settings (Project Settings & Code Packs)

addItem(RibbonMenus.Settings, '4_Outputs', 3, 'saengine.settings.resetDefaults', localize('rib.set.reset', "Reset to Defaults"), Codicon.discard, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '5_Packages', 1, 'saengine.packages.show', localize('rib.set.packages', "Packages"), Codicon.package, 'large', { when: subViewWhen('settings.packages') });
addItem(RibbonMenus.Settings, '5_Packages', 3, 'saengine.codePacks.new', localize('rib.set.newCodePack', "New Code Pack"), Codicon.newFile, 'small', { when: subViewWhen('settings.packages') });
addItem(RibbonMenus.Settings, '5_Packages', 4, 'saengine.codePacks.install', localize('rib.set.installPkg', "Install Package"), Codicon.cloudDownload, 'small', { when: subViewWhen('settings.packages') });

//#endregion

//#region Tab 5: Library (Materials, Object Types, Section Designer; editor actions in saengineLibrary)

addItem(RibbonMenus.Library, '4_Sections', 1, 'saengine.section.new', localize('rib.lib.sectionDesigner', "Section Designer"), Codicon.symbolRuler, 'large', { precondition: projectOpen });

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


//#endregion

//#region Tab 15: Foundations (cross-part settings link; domain commands registered in saengineSubstructure)


//#endregion

//#region Tab 16: BOQ (cross-part links; domain commands registered in saengineBoq)

addItem(RibbonMenus.BOQ, '2_RatesAndCarbon', 1, 'saengine.boq.editRates', localize('rib.boq.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '2_RatesAndCarbon', 2, 'saengine.boq.editCarbon', localize('rib.boq.carbon', "Carbon Factors"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '4_Export', 1, 'saengine.boq.exportXlsx', localize('rib.boq.xlsx', "Export Excel"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '4_Export', 2, 'saengine.boq.exportCsv', localize('rib.boq.csv', "Export CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 17: Output

addItem(RibbonMenus.Output, '1_Exports', 2, 'saengine.exports.revealFolder', localize('rib.out.revealFolder', "Exports Folder"), Codicon.folderOpened, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '1_Exports', 3, 'saengine.exports.refresh', localize('rib.out.refresh', "Refresh"), Codicon.refresh, 'small', { precondition: projectOpen });

// The floor plan's Output tab shows only drawing exports; project-wide exports stay in the Exports window.
for (const outputGroup of ['1_Exports', '2_IFC', '4_Exchange', '5_BOQAndReports']) {
	registerRibbonGroupWhen(RibbonMenus.Output, outputGroup, EXPORTS_WHEN);
}

addItem(RibbonMenus.Output, '2_IFC', 1, 'saengine.bim.exportIfcOptions', localize('rib.out.ifcOptions', "Export IFC..."), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_IFC', 2, 'saengine.bim.compareIfc', localize('rib.out.ifcCompare', "Compare IFC Revisions..."), Codicon.diff, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_IFC', 3, 'saengine.bim.exportIfc', localize('rib.out.ifc', "Quick Export IFC"), Codicon.export, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '3_BIMAndCAD', 1, 'saengine.floorPlan.exportDxf', localize('rib.out.dxf', "DXF Floor Plans"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_BIMAndCAD', 2, 'saengine.revit.exportUi', localize('rib.out.revitExport', "Export for Revit"), Codicon.sync, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_BIMAndCAD', 3, 'saengine.revit.importUi', localize('rib.out.revitImport', "Import from Revit..."), Codicon.cloudDownload, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '4_Exchange', 1, 'saengine.export.e2kOptions', localize('rib.out.e2kOptions', "ETABS .e2k Options..."), Codicon.export, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 2, 'saengine.export.s2k', localize('rib.out.s2k', "SAP2000 .s2k"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 3, 'saengine.export.std', localize('rib.out.std', "STAAD .std"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 4, 'saengine.export.saf', localize('rib.out.saf', "SAF (.xlsx)"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 5, 'saengine.export.cis2', localize('rib.out.cis2', "CIS/2"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 6, 'saengine.export.sdnf', localize('rib.out.sdnf', "SDNF Steel"), Codicon.tools, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_Exchange', 7, 'saengine.export.detailingNote', localize('rib.out.detailingNote', "Steel Detailing Guide"), Codicon.info, 'small');

addItem(RibbonMenus.Output, '5_BOQAndReports', 1, 'saengine.boq.exportXlsx', localize('rib.out.boqXlsx', "BOQ Excel"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '5_BOQAndReports', 2, 'saengine.boq.exportCsv', localize('rib.out.boqCsv', "BOQ CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '5_BOQAndReports', 3, 'saengine.report.exportWord', localize('rib.out.wordReport', "Word Report"), Codicon.fileText, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '6_WebAndArchive', 1, 'saengine.export.webViewer', localize('rib.out.webViewer', "Web Viewer"), Codicon.browser, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Output, '6_WebAndArchive', 2, RibbonSubmenus.OutputArchive, localize('rib.out.archive', "Archive .civil"), Codicon.archive, 'large', true, 'saengine.project.exportArchive');
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 1, 'saengine.project.exportArchive', localize('rib.out.exportArchive', "Export Project (.civil)..."), Codicon.archive, { precondition: projectOpen });

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
