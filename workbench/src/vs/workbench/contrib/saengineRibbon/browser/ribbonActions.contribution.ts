/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr, ContextKeyExpression } from '../../../../platform/contextkey/common/contextkey.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { ActiveEditorContext } from '../../../common/contextkeys.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { openPart, openPartSection, partSections } from '../../saengineProject/browser/projectParts.js';
import { ProjectStageBar } from '../../saengineProject/browser/projectStageBar.js';
import { registerRibbonCustomGroup, registerRibbonGroupLabel, registerRibbonItemHint, RibbonButtonSize, RibbonMenus } from './ribbonRegistry.js';

const projectOpen = ContextKeyExpr.has('saengineProjectOpen');
const runAllRunning = ContextKeyExpr.has('saengineRunAllRunning');
const developerMode = ContextKeyExpr.has('saengineDeveloperMode');
const aiRunning = ContextKeyExpr.has('saengineAiRunning');
const aiEditsAllowed = ContextKeyExpr.has('saengineAiEditsAllowed');
const liveCoEditing = ContextKeyExpr.has('saengineLiveCoEditing');
const relayHosted = ContextKeyExpr.has('saengineCoEditingRelayHosted');
const floorPlanActive = ActiveEditorContext.isEqualTo('workbench.editor.saengine.floorPlan');

const category = localize2('saengine.category', "SAEngine");

const RibbonSubmenus = {
	HomeOpen: MenuId.for('SaengineRibbon.Submenu.HomeOpen'),
	HomeSave: MenuId.for('SaengineRibbon.Submenu.HomeSave'),
	HomeVersions: MenuId.for('SaengineRibbon.Submenu.HomeVersions'),
	HomeRun: MenuId.for('SaengineRibbon.Submenu.HomeRun'),
	DefineCode: MenuId.for('SaengineRibbon.Submenu.DefineCode'),
	DocsReport: MenuId.for('SaengineRibbon.Submenu.DocsReport'),
	DocsWorksheets: MenuId.for('SaengineRibbon.Submenu.DocsWorksheets'),
	OutputArchive: MenuId.for('SaengineRibbon.Submenu.OutputArchive'),
	StudiesGraph: MenuId.for('SaengineRibbon.Submenu.StudiesGraph'),
	CollabLocks: MenuId.for('SaengineRibbon.Submenu.CollabLocks'),
	CollabLive: MenuId.for('SaengineRibbon.Submenu.CollabLive'),
	ManagePackages: MenuId.for('SaengineRibbon.Submenu.ManagePackages'),
	ManageAi: MenuId.for('SaengineRibbon.Submenu.ManageAi'),
} as const;

//#region Part and section opener commands (reuse projectParts.ts)

function registerPartOpener(id: string, title: ReturnType<typeof localize2>, partId: string): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, category, f1: false, precondition: projectOpen });
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const project = accessor.get(ISaengineProjectService).project;
			if (!project) {
				return;
			}
			const resolvedId = partId === 'floorPlan' && project.type === 'structure' ? 'structure' : partId;
			const part = partById(resolvedId);
			if (!part) {
				return;
			}
			await openPart(project, part, {
				editorService: accessor.get(IEditorService),
				fileService: accessor.get(IFileService),
				openerService: accessor.get(IOpenerService),
				commandService: accessor.get(ICommandService),
			});
		}
	});
}

function registerSectionOpener(id: string, title: ReturnType<typeof localize2>, partId: string, sectionId: string, explicitSections?: readonly string[]): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, category, f1: false, precondition: projectOpen });
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const project = accessor.get(ISaengineProjectService).project;
			const part = partById(partId);
			if (!project || !part) {
				return;
			}
			const entry = explicitSections
				? { id: sectionId, label: title.value, sections: explicitSections }
				: partSections(partId).find(s => s.id === sectionId) ?? { id: sectionId, label: title.value, sections: [sectionId] };
			await openPartSection(project, part, entry, {
				editorService: accessor.get(IEditorService),
				commandService: accessor.get(ICommandService),
			});
		}
	});
}

const CMD_OPEN_SOIL = 'saengine.ribbon.openPart.soil';
const CMD_OPEN_MATERIALS = 'saengine.ribbon.openPart.materials';
const CMD_OPEN_OBJECTS = 'saengine.ribbon.openPart.objects';
const CMD_OPEN_FLOOR_PLAN = 'saengine.ribbon.openPart.floorPlan';
const CMD_OPEN_FEM = 'saengine.ribbon.openPart.fem';
const CMD_OPEN_SUBSTRUCTURE = 'saengine.ribbon.openPart.substructure';
const CMD_OPEN_BOQ = 'saengine.ribbon.openPart.boq';

registerPartOpener(CMD_OPEN_SOIL, localize2('ribbon.openSoil', "Soil Report"), 'soil');
registerPartOpener(CMD_OPEN_MATERIALS, localize2('ribbon.openMaterials', "Materials"), 'materials');
registerPartOpener(CMD_OPEN_OBJECTS, localize2('ribbon.openObjects', "Object Types"), 'objects');
registerPartOpener(CMD_OPEN_FLOOR_PLAN, localize2('ribbon.openFloorPlan', "Floor Plan / Structural Model"), 'floorPlan');
registerPartOpener(CMD_OPEN_FEM, localize2('ribbon.openFem', "Analysis Model (FEM)"), 'fem');
registerPartOpener(CMD_OPEN_SUBSTRUCTURE, localize2('ribbon.openSubstructure', "Substructure & Foundations"), 'substructure');
registerPartOpener(CMD_OPEN_BOQ, localize2('ribbon.openBoq', "Bill of Quantities"), 'boq');

const CMD_SEC_SETTINGS_CODE = 'saengine.ribbon.openSection.settings.code';
const CMD_SEC_SETTINGS_AREA_LOADS = 'saengine.ribbon.openSection.settings.areaLoads';
const CMD_SEC_SETTINGS_CRANES = 'saengine.ribbon.openSection.settings.cranes';
const CMD_SEC_SETTINGS_SPECIAL = 'saengine.ribbon.openSection.settings.special';
const CMD_SEC_SETTINGS_SEISMIC = 'saengine.ribbon.openSection.settings.seismic';
const CMD_SEC_SETTINGS_WIND = 'saengine.ribbon.openSection.settings.wind';
const CMD_SEC_SETTINGS_COMBINATIONS = 'saengine.ribbon.openSection.settings.combinations';
const CMD_SEC_SETTINGS_ANALYSIS = 'saengine.ribbon.openSection.settings.analysis';
const CMD_SEC_SETTINGS_FOUNDATION = 'saengine.ribbon.openSection.settings.foundation';
const CMD_SEC_SETTINGS_DRAWINGS = 'saengine.ribbon.openSection.settings.drawings';
const CMD_SEC_SETTINGS_REPORT = 'saengine.ribbon.openSection.settings.report';
const CMD_SEC_SETTINGS_CODE_VALUES = 'saengine.ribbon.openSection.settings.codeValues';

registerSectionOpener(CMD_SEC_SETTINGS_CODE, localize2('ribbon.sec.code', "Design Code, Occupancy & Site"), 'settings', 'code', ['project', 'occupancy', 'construction', 'site']);
registerSectionOpener(CMD_SEC_SETTINGS_AREA_LOADS, localize2('ribbon.sec.areaLoads', "Area & Floor Loads"), 'settings', 'areaLoads', ['areaLoads']);
registerSectionOpener(CMD_SEC_SETTINGS_CRANES, localize2('ribbon.sec.cranes', "Crane Runways"), 'settings', 'cranes', ['cranes']);
registerSectionOpener(CMD_SEC_SETTINGS_SPECIAL, localize2('ribbon.sec.special', "Bridges & Special Structures"), 'settings', 'special', ['specialStructures']);
registerSectionOpener(CMD_SEC_SETTINGS_SEISMIC, localize2('ribbon.sec.seismic', "Seismic Loads"), 'settings', 'seismic', ['seismic']);
registerSectionOpener(CMD_SEC_SETTINGS_WIND, localize2('ribbon.sec.wind', "Wind Loads"), 'settings', 'wind', ['wind']);
registerSectionOpener(CMD_SEC_SETTINGS_COMBINATIONS, localize2('ribbon.sec.combinations', "Load Combinations"), 'settings', 'combinations', ['combinations']);
registerSectionOpener(CMD_SEC_SETTINGS_ANALYSIS, localize2('ribbon.sec.analysis', "Analysis Model Settings"), 'settings', 'analysis', ['analysis']);
registerSectionOpener(CMD_SEC_SETTINGS_FOUNDATION, localize2('ribbon.sec.foundation', "Foundation Settings"), 'settings', 'foundation', ['foundation']);
registerSectionOpener(CMD_SEC_SETTINGS_DRAWINGS, localize2('ribbon.sec.drawings', "Drawings & Detailing Settings"), 'settings', 'drawings', ['drawings', 'detailing']);
registerSectionOpener(CMD_SEC_SETTINGS_REPORT, localize2('ribbon.sec.report', "Design Report Settings"), 'settings', 'report', ['report']);
registerSectionOpener(CMD_SEC_SETTINGS_CODE_VALUES, localize2('ribbon.sec.codeValues', "Code Values"), 'settings', 'codeValues', ['codeOverrides']);

const CMD_SEC_GRIDS = 'saengine.ribbon.openSection.floorPlan.grids';
const CMD_SEC_BIM_3D = 'saengine.ribbon.openSection.bim.3d';
const CMD_SEC_BIM_ADDITIONS = 'saengine.ribbon.openSection.bim.additions';
const CMD_SEC_BIM_SUMMARY = 'saengine.ribbon.openSection.bim.summary';

registerSectionOpener(CMD_SEC_GRIDS, localize2('ribbon.sec.grids', "Grids & Stories"), 'floorPlan', 'grids');
registerSectionOpener(CMD_SEC_BIM_3D, localize2('ribbon.sec.bim3d', "3D Building Model"), 'bim', '3d');
registerSectionOpener(CMD_SEC_BIM_ADDITIONS, localize2('ribbon.sec.bimAdditions', "BIM Additions"), 'bim', 'additions');
registerSectionOpener(CMD_SEC_BIM_SUMMARY, localize2('ribbon.sec.bimSummary', "BIM Summary"), 'bim', 'summary');

const CMD_SEC_MEP_COORDINATION = 'saengine.ribbon.openSection.mep.coordination';
const CMD_SEC_MEP_PLUMBING = 'saengine.ribbon.openSection.mep.plumbing';
const CMD_SEC_MEP_HVAC = 'saengine.ribbon.openSection.mep.hvac';
const CMD_SEC_MEP_ELECTRICAL = 'saengine.ribbon.openSection.mep.electrical';
const CMD_SEC_MEP_FIRE = 'saengine.ribbon.openSection.mep.fire';
const CMD_SEC_MEP_SYSTEMS = 'saengine.ribbon.openSection.mep.systems';

registerSectionOpener(CMD_SEC_MEP_COORDINATION, localize2('ribbon.sec.mepCoordination', "MEP Coordination"), 'mep', 'coordination');
registerSectionOpener(CMD_SEC_MEP_PLUMBING, localize2('ribbon.sec.mepPlumbing', "Plumbing"), 'mep', 'plumbing');
registerSectionOpener(CMD_SEC_MEP_HVAC, localize2('ribbon.sec.mepHvac', "HVAC"), 'mep', 'hvac');
registerSectionOpener(CMD_SEC_MEP_ELECTRICAL, localize2('ribbon.sec.mepElectrical', "Electrical"), 'mep', 'electrical');
registerSectionOpener(CMD_SEC_MEP_FIRE, localize2('ribbon.sec.mepFire', "Fire Protection"), 'mep', 'fire');
registerSectionOpener(CMD_SEC_MEP_SYSTEMS, localize2('ribbon.sec.mepSystems', "MEP Systems"), 'mep', 'systems');

//#endregion

//#region Group labels and Workflow custom group

const GROUP_LABELS: readonly [string, string][] = [
	['Project', localize('ribbon.grp.project', "Project")],
	['Workflow', localize('ribbon.grp.workflow', "Workflow")],
	['Run', localize('ribbon.grp.run', "Run")],
	['Workspace', localize('ribbon.grp.workspace', "Workspace")],
	['Code', localize('ribbon.grp.code', "Code")],
	['SiteAndSoil', localize('ribbon.grp.siteAndSoil', "Site & Soil")],
	['Materials', localize('ribbon.grp.materials', "Materials")],
	['Sections', localize('ribbon.grp.sections', "Sections")],
	['Packages', localize('ribbon.grp.packages', "Packages")],
	['GridsAndStories', localize('ribbon.grp.gridsAndStories', "Grids & Stories")],
	['Structure', localize('ribbon.grp.structure', "Structure")],
	['Architecture', localize('ribbon.grp.architecture', "Architecture")],
	['UnderlayAndImport', localize('ribbon.grp.underlayImport', "Underlay & Import")],
	['Selection', localize('ribbon.grp.selection', "Selection")],
	['Modify', localize('ribbon.grp.modify', "Modify")],
	['ViewAndAids', localize('ribbon.grp.viewAids', "View & Aids")],
	['Gravity', localize('ribbon.grp.gravity', "Area Loads")],
	['Lateral', localize('ribbon.grp.lateral', "Lateral")],
	['SpecialAndCombos', localize('ribbon.grp.specialCombos', "Special & Combos")],
	['Solver', localize('ribbon.grp.solver', "Solver")],
	['Advanced', localize('ribbon.grp.advanced', "Advanced")],
	['Results', localize('ribbon.grp.results', "Results")],
	['Superstructure', localize('ribbon.grp.superstructure', "Superstructure")],
	['Substructure', localize('ribbon.grp.substructure', "Substructure")],
	['Standards', localize('ribbon.grp.standards', "Standards")],
	['Coordination', localize('ribbon.grp.coordination', "Coordination")],
	['Plumbing', localize('ribbon.grp.plumbing', "Plumbing")],
	['HVAC', localize('ribbon.grp.hvac', "HVAC")],
	['Electrical', localize('ribbon.grp.electrical', "Electrical")],
	['FireAndSystems', localize('ribbon.grp.fireSystems', "Fire & Systems")],
	['Drawings', localize('ribbon.grp.drawings', "Drawings")],
	['Annotation', localize('ribbon.grp.annotation', "Annotation")],
	['SchedulesAndBOQ', localize('ribbon.grp.schedulesBoq', "Schedules & BOQ")],
	['Report', localize('ribbon.grp.report', "Report")],
	['Exports', localize('ribbon.grp.exports', "Exports")],
	['BIMAndCAD', localize('ribbon.grp.bimCad', "BIM & CAD")],
	['Exchange', localize('ribbon.grp.exchange', "Exchange")],
	['BOQAndReports', localize('ribbon.grp.boqReports', "BOQ & Reports")],
	['WebAndArchive', localize('ribbon.grp.webArchive', "Web & Archive")],
	['ConstructionAndCost', localize('ribbon.grp.constructionCost', "Construction & Cost")],
	['Environmental', localize('ribbon.grp.environmental', "Environmental")],
	['Optioneering', localize('ribbon.grp.optioneering', "Optioneering")],
	['SyncAndWorksharing', localize('ribbon.grp.syncWorksharing', "Sync & Worksharing")],
	['LiveCoEditing', localize('ribbon.grp.liveCoEditing', "Live Co-Editing")],
	['ReviewAndVersions', localize('ribbon.grp.reviewVersions', "Review & Versions")],
	['OfficeServer', localize('ribbon.grp.officeServer', "Office Server")],
	['AIControl', localize('ribbon.grp.aiControl', "AI Control")],
	['Automation', localize('ribbon.grp.automation', "Automation")],
	['SettingsAndHelp', localize('ribbon.grp.settingsHelp', "Settings & Help")],
];

for (const [key, label] of GROUP_LABELS) {
	registerRibbonGroupLabel(key, label);
}

registerRibbonCustomGroup({
	tabId: 'home',
	group: '2_Workflow',
	label: localize('ribbon.grp.workflow', "Workflow"),
	render: (container, instantiationService) => {
		const stageBar = instantiationService.createInstance(ProjectStageBar);
		container.appendChild(stageBar.element);
		return stageBar;
	},
});

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

//#endregion

//#region Tab 1: Home

addItem(RibbonMenus.Home, '1_Project', 1, 'saengine.project.new', localize('rib.home.new', "New"), Codicon.newFolder, 'large');
addSubmenu(RibbonMenus.Home, '1_Project', 2, RibbonSubmenus.HomeOpen, localize('rib.home.open', "Open"), Codicon.folderOpened, 'large', true, 'saengine.project.open');
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 1, 'saengine.project.open', localize('rib.home.openProject', "Open Project..."), Codicon.folderOpened);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 2, 'saengine.project.openArchive', localize('rib.home.openArchive', "Open Project Archive..."), Codicon.archive);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 3, 'saengine.project.openSample', localize('rib.home.openSample', "Open Sample Project..."), Codicon.project);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 4, 'saengine.share.openShared', localize('rib.home.openShared', "Open Shared Project..."), Codicon.organization);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 5, 'saengine.project.showStart', localize('rib.home.showStart', "Show Start Window"), Codicon.home);

addSubmenu(RibbonMenus.Home, '1_Project', 3, RibbonSubmenus.HomeSave, localize('rib.home.save', "Save"), Codicon.save, 'large', true, 'saveAll');
addSubItem(RibbonSubmenus.HomeSave, '1_save', 1, 'saveAll', localize('rib.home.saveAll', "Save All"), Codicon.saveAll);
addSubItem(RibbonSubmenus.HomeSave, '1_save', 2, 'workbench.action.files.save', localize('rib.home.saveFile', "Save Active File"), Codicon.save);

addSubmenu(RibbonMenus.Home, '1_Project', 4, RibbonSubmenus.HomeVersions, localize('rib.home.versions', "Versions"), Codicon.history, 'large', true, 'saengine.project.showVersions');
addSubItem(RibbonSubmenus.HomeVersions, '1_ver', 1, 'saengine.project.showVersions', localize('rib.home.showVersions', "Versions"), Codicon.history, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeVersions, '1_ver', 2, 'saengine.project.saveVersion', localize('rib.home.saveVersion', "Save Version..."), Codicon.gitCommit, { precondition: projectOpen });

addItem(RibbonMenus.Home, '1_Project', 5, 'saengine.project.showOverview', localize('rib.home.overview', "Overview"), Codicon.dashboard, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '1_Project', 6, 'saengine.project.revealInOS', localize('rib.home.reveal', "Open Folder"), Codicon.folder, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '1_Project', 7, 'saengine.showProgress', localize('rib.home.progress', "Progress"), Codicon.tasklist, 'small', { precondition: projectOpen });

// 2_Workflow is rendered by ProjectStageBar via registerRibbonCustomGroup above.

addItem(RibbonMenus.Home, '3_Run', 1, 'saengine.runAll', localize('rib.home.runAll', "Run All"), Codicon.play, 'large', { precondition: projectOpen, when: runAllRunning.negate() });
addItem(RibbonMenus.Home, '3_Run', 1, 'saengine.runAll.cancel', localize('rib.home.stopRunAll', "Stop"), Codicon.debugStop, 'large', { precondition: runAllRunning, when: runAllRunning });
addSubmenu(RibbonMenus.Home, '3_Run', 2, RibbonSubmenus.HomeRun, localize('rib.home.run', "Run"), Codicon.runAll, 'large', false);
addSubItem(RibbonSubmenus.HomeRun, '1_run', 1, 'saengine.fem.runAnalysis', localize('rib.home.runAnalysis', "Run Analysis"), Codicon.play, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '1_run', 2, 'saengine.fem.runSelectedCases', localize('rib.home.runCases', "Run Selected Cases..."), Codicon.checklist, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '1_run', 3, 'saengine.officeServer.run', localize('rib.home.runServer', "Run on Office Server"), Codicon.server, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 1, 'saengine.runAll.showSteps', localize('rib.home.showSteps', "Show Run All Steps"), Codicon.listFlat, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 2, 'saengine.restartEngine', localize('rib.home.restartEngine', "Restart Engine"), Codicon.debugRestart);

addItem(RibbonMenus.Home, '4_Workspace', 1, 'undo', localize('rib.home.undo', "Undo"), Codicon.discard, 'small');
addItem(RibbonMenus.Home, '4_Workspace', 2, 'redo', localize('rib.home.redo', "Redo"), Codicon.redo, 'small');
addItem(RibbonMenus.Home, '4_Workspace', 3, 'saengine.showProperties', localize('rib.home.properties', "Properties"), Codicon.symbolProperty, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '4_Workspace', 4, 'saengine.showModelView', localize('rib.home.modelView', "Model View"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '4_Workspace', 5, 'saengine.showTables', localize('rib.home.tables', "Tables"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '4_Workspace', 6, 'saengine.ai.openChat', localize('rib.home.aiChat', "AI Assistant"), Codicon.sparkle, 'small');

//#endregion

//#region Tab 2: Define

addSubmenu(RibbonMenus.Define, '1_Code', 1, RibbonSubmenus.DefineCode, localize('rib.define.codePack', "Design Code"), Codicon.book, 'large', true, CMD_SEC_SETTINGS_CODE);
addSubItem(RibbonSubmenus.DefineCode, '1_code', 1, CMD_SEC_SETTINGS_CODE, localize('rib.define.codeSite', "Code, Occupancy & Site"), Codicon.book, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DefineCode, '1_code', 2, CMD_SEC_SETTINGS_CODE_VALUES, localize('rib.define.codeValues', "Code Values"), Codicon.law, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DefineCode, '2_packs', 1, 'saengine.packages.show', localize('rib.define.browsePacks', "Manage Code Packs..."), Codicon.package);
addSubItem(RibbonSubmenus.DefineCode, '2_packs', 2, 'saengine.codePacks.new', localize('rib.define.newPack', "New Code Pack..."), Codicon.newFile);
addSubItem(RibbonSubmenus.DefineCode, '2_packs', 3, 'saengine.codePacks.install', localize('rib.define.installPack', "Install Package from File..."), Codicon.cloudDownload);
addItem(RibbonMenus.Define, '1_Code', 2, 'saengine.project.openSettings', localize('rib.define.settings', "Project Settings"), Codicon.settingsGear, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Define, '2_SiteAndSoil', 1, CMD_OPEN_SOIL, localize('rib.define.soilReport', "Soil Report"), Codicon.globe, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Define, '2_SiteAndSoil', 2, 'saengine.soil.addBorehole', localize('rib.define.addBorehole', "Add Borehole"), Codicon.add, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Define, '2_SiteAndSoil', 3, 'saengine.soil.importFile', localize('rib.define.importBoreholes', "Import Boreholes..."), Codicon.cloudDownload, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Define, '2_SiteAndSoil', 4, 'saengine.soil.saveTemplate', localize('rib.define.boreholeTpl', "Borehole Template"), Codicon.notebookTemplate, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Define, '3_Materials', 1, CMD_OPEN_MATERIALS, localize('rib.define.materials', "Materials"), Codicon.layers, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Define, '4_Sections', 1, CMD_OPEN_OBJECTS, localize('rib.define.objects', "Object Types"), Codicon.symbolStructure, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Define, '4_Sections', 2, 'saengine.section.new', localize('rib.define.sectionDesigner', "Section Designer"), Codicon.symbolRuler, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Define, '5_Packages', 1, 'saengine.packages.show', localize('rib.define.packages', "Packages"), Codicon.package, 'large');
addItem(RibbonMenus.Define, '5_Packages', 2, 'saengine.codePacks.new', localize('rib.define.newCodePack', "New Code Pack"), Codicon.newFile, 'small');
addItem(RibbonMenus.Define, '5_Packages', 3, 'saengine.codePacks.install', localize('rib.define.installPkg', "Install Package"), Codicon.cloudDownload, 'small');

//#endregion

//#region Tab 3: Model

addItem(RibbonMenus.Model, '1_GridsAndStories', 1, CMD_SEC_GRIDS, localize('rib.model.grids', "Grids & Stories"), Codicon.layout, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Model, '2_Structure', 1, CMD_OPEN_FLOOR_PLAN, localize('rib.model.floorPlan', "Floor Plan"), Codicon.layoutPanel, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Model, '2_Structure', 2, CMD_SEC_BIM_3D, localize('rib.model.3dView', "3D Model"), Codicon.symbolNamespace, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Model, '2_Structure', 3, 'saengine.floorPlan.openMembersTable', localize('rib.model.membersTable', "Members Table"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Model, '2_Structure', 4, CMD_SEC_BIM_ADDITIONS, localize('rib.model.additions', "BIM Additions"), Codicon.add, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Model, '2_Structure', 5, CMD_SEC_BIM_SUMMARY, localize('rib.model.summary', "BIM Summary"), Codicon.listFlat, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Model, '3_Architecture', 1, 'saengine.architecture.open', localize('rib.model.architecture', "Architecture"), Codicon.home, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Model, '4_UnderlayAndImport', 1, 'saengine.project.importStructural', localize('rib.model.importStructural', "Import Model"), Codicon.cloudDownload, 'large');
addItem(RibbonMenus.Model, '4_UnderlayAndImport', 2, 'saengine.revit.importUi', localize('rib.model.importRevit', "Import Revit..."), Codicon.sync, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Model, '4_UnderlayAndImport', 3, 'saengine.cad.openDxf', localize('rib.model.openDxf', "Open DXF in CAD"), Codicon.fileMedia, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Model, '4_UnderlayAndImport', 4, 'saengine.project.showImportReport', localize('rib.model.importReport', "Import Report"), Codicon.fileText, 'small');

//#endregion

//#region Tab 4: Draft (Contextual)

addItem(RibbonMenus.Draft, '1_Selection', 1, 'saengine.floorPlan.bulk.selectAll', localize('rib.draft.selectAll', "Select All"), Codicon.checkAll, 'large', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '1_Selection', 2, 'saengine.floorPlan.bulk.selectByType', localize('rib.draft.selectByType', "Select by Type"), Codicon.filter, 'small', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '1_Selection', 3, 'saengine.floorPlan.bulk.deleteSelection', localize('rib.draft.delete', "Delete"), Codicon.trash, 'small', { precondition: floorPlanActive });

addItem(RibbonMenus.Draft, '2_Modify', 1, 'saengine.floorPlan.bulk.mirror', localize('rib.draft.mirror', "Mirror"), Codicon.splitHorizontal, 'large', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '2_Modify', 2, 'saengine.floorPlan.bulk.copyToStories', localize('rib.draft.copyStories', "Copy to Stories"), Codicon.copy, 'large', { precondition: floorPlanActive });

addItem(RibbonMenus.Draft, '3_ViewAndAids', 1, 'saengine.floorPlan.toggleCommandLine', localize('rib.draft.cmdLine', "Command Line"), Codicon.terminal, 'large', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '3_ViewAndAids', 2, 'saengine.floorPlan.toggleGridLines', localize('rib.draft.gridLines', "Grid Lines"), Codicon.layout, 'small', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '3_ViewAndAids', 3, 'saengine.floorPlan.properties', localize('rib.draft.properties', "Properties"), Codicon.symbolProperty, 'small', { precondition: floorPlanActive });
addItem(RibbonMenus.Draft, '3_ViewAndAids', 4, 'saengine.cad.openDxf', localize('rib.draft.openCad', "Open DXF in CAD"), Codicon.linkExternal, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 5: Loads

addItem(RibbonMenus.Loads, '1_Gravity', 1, CMD_SEC_SETTINGS_AREA_LOADS, localize('rib.loads.area', "Area Loads"), Codicon.arrowDown, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Loads, '2_Lateral', 1, CMD_SEC_SETTINGS_SEISMIC, localize('rib.loads.seismic', "Seismic"), Codicon.pulse, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Loads, '2_Lateral', 2, CMD_SEC_SETTINGS_WIND, localize('rib.loads.wind', "Wind"), Codicon.symbolEvent, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Loads, '3_SpecialAndCombos', 1, CMD_SEC_SETTINGS_CRANES, localize('rib.loads.cranes', "Cranes"), Codicon.tools, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Loads, '3_SpecialAndCombos', 2, CMD_SEC_SETTINGS_SPECIAL, localize('rib.loads.special', "Special"), Codicon.compass, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Loads, '3_SpecialAndCombos', 3, CMD_SEC_SETTINGS_COMBINATIONS, localize('rib.loads.combos', "Combinations"), Codicon.table, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 6: Analyze

addItem(RibbonMenus.Analyze, '1_Solver', 1, 'saengine.runAll', localize('rib.analyze.runAll', "Run All"), Codicon.play, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 2, 'saengine.fem.runAnalysis', localize('rib.analyze.runAnalysis', "Run Analysis"), Codicon.runAll, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 3, 'saengine.fem.runSelectedCases', localize('rib.analyze.selectedCases', "Selected Cases"), Codicon.checklist, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 4, CMD_OPEN_FEM, localize('rib.analyze.femModel', "FEM Model"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 5, CMD_SEC_SETTINGS_ANALYSIS, localize('rib.analyze.modelSettings', "Analysis Settings"), Codicon.settingsGear, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '2_Advanced', 1, 'saengine.fem.openPushover', localize('rib.analyze.pushover', "Pushover"), Codicon.graphLine, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '2_Advanced', 2, 'saengine.fem.cfdWind', localize('rib.analyze.cfdWind', "CFD Wind Tunnel"), Codicon.symbolEvent, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '2_Advanced', 3, 'saengine.fem.showBridgeResults', localize('rib.analyze.bridgeResults', "Bridge Results"), Codicon.compass, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '3_Results', 1, 'saengine.fem.showCharts', localize('rib.analyze.charts', "Analysis Charts"), Codicon.graph, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_Results', 2, 'saengine.showTables', localize('rib.analyze.tables', "Result Tables"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_Results', 3, 'saengine.fem.showLog', localize('rib.analyze.log', "Analysis Log"), Codicon.output, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_Results', 4, 'saengine.runAll.showSteps', localize('rib.analyze.steps', "Run All Steps"), Codicon.listFlat, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_Results', 5, 'saengine.restartEngine', localize('rib.analyze.restart', "Restart Engine"), Codicon.debugRestart, 'small');

//#endregion

//#region Tab 7: Design

addItem(RibbonMenus.Design, '1_Superstructure', 1, 'saengine.fem.designReinforcement', localize('rib.design.reinforcement', "Design Rebar"), Codicon.symbolRuler, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Superstructure', 2, 'saengine.fem.pickMember', localize('rib.design.memberDetails', "Member Details"), Codicon.search, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Superstructure', 3, 'saengine.fem.strutAndTie', localize('rib.design.strutAndTie', "Strut-and-Tie"), Codicon.symbolStructure, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Design, '2_Substructure', 1, CMD_OPEN_SUBSTRUCTURE, localize('rib.design.substructure', "Substructure"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Substructure', 2, 'saengine.substructure.sizeAll', localize('rib.design.sizeFootings', "Size Footings"), Codicon.wand, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Substructure', 3, 'saengine.substructure.importFootings', localize('rib.design.importFootings', "Import Footings"), Codicon.cloudDownload, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Substructure', 4, CMD_SEC_SETTINGS_FOUNDATION, localize('rib.design.fdnSettings', "Foundation Settings"), Codicon.settingsGear, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Design, '3_Standards', 1, CMD_SEC_SETTINGS_CODE_VALUES, localize('rib.design.codeValues', "Code Values"), Codicon.law, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 8: MEP

addItem(RibbonMenus.MEP, '1_Coordination', 1, CMD_SEC_MEP_COORDINATION, localize('rib.mep.coordination', "Coordination"), Codicon.warning, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '1_Coordination', 2, 'saengine.mep.editor.suggestSleeves', localize('rib.mep.suggestSleeves', "Suggest Sleeves"), Codicon.wand, 'large', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '2_Plumbing', 1, CMD_SEC_MEP_PLUMBING, localize('rib.mep.plumbing', "Plumbing"), Codicon.beaker, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '3_HVAC', 1, CMD_SEC_MEP_HVAC, localize('rib.mep.hvac', "HVAC"), Codicon.dashboard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 1, CMD_SEC_MEP_ELECTRICAL, localize('rib.mep.electrical', "Electrical"), Codicon.plug, 'large', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '5_FireAndSystems', 1, CMD_SEC_MEP_FIRE, localize('rib.mep.fire', "Fire"), Codicon.flame, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 2, CMD_SEC_MEP_SYSTEMS, localize('rib.mep.systems', "Systems"), Codicon.circuitBoard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 3, 'saengine.office.fabrication', localize('rib.mep.fabrication', "MEP Fabrication"), Codicon.tools, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 9: Documents

addItem(RibbonMenus.Documents, '1_Drawings', 1, 'saengine.project.showExports', localize('rib.docs.drawings', "Drawing Set"), Codicon.files, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '1_Drawings', 2, CMD_SEC_SETTINGS_DRAWINGS, localize('rib.docs.titleBlock', "Title Block & Detailing"), Codicon.settingsGear, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '1_Drawings', 3, 'saengine.cad.openDxf', localize('rib.docs.openCad', "Open DXF in CAD"), Codicon.linkExternal, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '1_Drawings', 4, 'saengine.office.takeoff', localize('rib.docs.takeoff', "PDF Takeoff"), Codicon.preview, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Documents, '2_Annotation', 1, 'saengine.drawings.autoDimension', localize('rib.docs.autoDim', "Auto-Dimension"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Annotation', 2, 'saengine.drawings.autoTag', localize('rib.docs.autoTag', "Auto-Tag"), Codicon.symbolKey, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Annotation', 3, 'saengine.drawings.autoArrange', localize('rib.docs.autoArrange', "Arrange Labels"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '2_Annotation', 4, 'saengine.drawings.undoAutomation', localize('rib.docs.undoAuto', "Undo Automation"), Codicon.discard, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Documents, '3_SchedulesAndBOQ', 1, CMD_OPEN_BOQ, localize('rib.docs.boq', "Bill of Quantities"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_SchedulesAndBOQ', 2, 'saengine.boq.editRates', localize('rib.docs.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_SchedulesAndBOQ', 3, 'saengine.boq.editCarbon', localize('rib.docs.carbon', "Carbon Factors"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '3_SchedulesAndBOQ', 4, 'saengine.floorPlan.openMembersTable', localize('rib.docs.membersTable', "Members Schedule"), Codicon.listFlat, 'small', { precondition: projectOpen });

addSubmenu(RibbonMenus.Documents, '4_Report', 1, RibbonSubmenus.DocsReport, localize('rib.docs.report', "Design Report"), Codicon.filePdf, 'large', true, 'saengine.report.print');
addSubItem(RibbonSubmenus.DocsReport, '1_report', 1, 'saengine.report.print', localize('rib.docs.printReport', "Print Design Report"), Codicon.filePdf, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '1_report', 2, 'saengine.report.exportWord', localize('rib.docs.wordReport', "Export Report to Word"), Codicon.fileText, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '2_config', 1, 'saengine.report.configure', localize('rib.docs.configureReport', "Configure Design Report..."), Codicon.settingsGear, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '2_config', 2, CMD_SEC_SETTINGS_REPORT, localize('rib.docs.reportSettings', "Design Report Settings"), Codicon.book, { precondition: projectOpen });

addSubmenu(RibbonMenus.Documents, '4_Report', 2, RibbonSubmenus.DocsWorksheets, localize('rib.docs.worksheets', "Worksheets"), Codicon.symbolNumeric, 'large', true, 'saengine.worksheets.open');
addSubItem(RibbonSubmenus.DocsWorksheets, '1_ws', 1, 'saengine.worksheets.open', localize('rib.docs.openWorksheets', "Calculation Worksheets..."), Codicon.symbolNumeric, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsWorksheets, '1_ws', 2, 'saengine.worksheets.new', localize('rib.docs.newWorksheet', "New Calculation Worksheet..."), Codicon.add, { precondition: projectOpen });

//#endregion

//#region Tab 10: Output

addItem(RibbonMenus.Output, '1_Exports', 1, 'saengine.project.showExports', localize('rib.out.exports', "All Exports"), Codicon.export, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Output, '2_BIMAndCAD', 1, 'saengine.bim.exportIfc', localize('rib.out.ifc', "Export IFC"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_BIMAndCAD', 2, 'saengine.floorPlan.exportDxf', localize('rib.out.dxf', "DXF Floor Plans"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_BIMAndCAD', 3, 'saengine.revit.exportUi', localize('rib.out.revitExport', "Export for Revit"), Codicon.sync, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '2_BIMAndCAD', 4, 'saengine.revit.importUi', localize('rib.out.revitImport', "Import from Revit..."), Codicon.cloudDownload, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '3_Exchange', 1, 'saengine.export.s2k', localize('rib.out.s2k', "SAP2000 .s2k"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_Exchange', 2, 'saengine.export.std', localize('rib.out.std', "STAAD .std"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_Exchange', 3, 'saengine.export.saf', localize('rib.out.saf', "SAF (.xlsx)"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_Exchange', 4, 'saengine.export.cis2', localize('rib.out.cis2', "CIS/2"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_Exchange', 5, 'saengine.export.sdnf', localize('rib.out.sdnf', "SDNF Steel"), Codicon.tools, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '3_Exchange', 6, 'saengine.export.detailingNote', localize('rib.out.detailingNote', "Steel Detailing Guide"), Codicon.info, 'small');

addItem(RibbonMenus.Output, '4_BOQAndReports', 1, 'saengine.boq.exportXlsx', localize('rib.out.boqXlsx', "BOQ Excel"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_BOQAndReports', 2, 'saengine.boq.exportCsv', localize('rib.out.boqCsv', "BOQ CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '4_BOQAndReports', 3, 'saengine.report.exportWord', localize('rib.out.wordReport', "Word Report"), Codicon.fileText, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Output, '5_WebAndArchive', 1, 'saengine.export.webViewer', localize('rib.out.webViewer', "Web Viewer"), Codicon.browser, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Output, '5_WebAndArchive', 2, RibbonSubmenus.OutputArchive, localize('rib.out.archive', "Archive .civil"), Codicon.archive, 'large', true, 'saengine.project.exportArchive');
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 1, 'saengine.project.exportArchive', localize('rib.out.exportArchive', "Export Project (.civil)..."), Codicon.archive, { precondition: projectOpen });
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 2, 'saengine.project.openArchive', localize('rib.out.openArchive', "Open Project Archive..."), Codicon.folderOpened);

//#endregion

//#region Tab 11: Studies

addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 1, 'saengine.office.schedule', localize('rib.studies.4d', "4D Programme"), Codicon.calendar, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 2, 'saengine.office.cost', localize('rib.studies.cost', "Cost Optimisation"), Codicon.graph, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 3, 'saengine.bim.play4d', localize('rib.studies.play4d', "Play 4D in BIM"), Codicon.play, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 4, 'saengine.office.takeoff', localize('rib.studies.takeoff', "2D PDF Takeoff"), Codicon.preview, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '1_ConstructionAndCost', 5, 'saengine.office.fabrication', localize('rib.studies.fabrication', "MEP Fabrication"), Codicon.tools, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Studies, '2_Environmental', 1, 'saengine.office.site', localize('rib.studies.site', "Terrain, Sun & Noise"), Codicon.compass, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Studies, '3_Optioneering', 1, 'saengine.office.phasing', localize('rib.studies.phasing', "Phases & Options"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Studies, '3_Optioneering', 2, 'saengine.studies.open', localize('rib.studies.designStudies', "Design Studies"), Codicon.beaker, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Studies, '3_Optioneering', 3, RibbonSubmenus.StudiesGraph, localize('rib.studies.visualProgram', "Visual Program"), Codicon.circuitBoard, 'large', true, 'saengine.graph.open');
addSubItem(RibbonSubmenus.StudiesGraph, '1_graph', 1, 'saengine.graph.open', localize('rib.studies.openGraph', "Open Visual Program..."), Codicon.circuitBoard, { precondition: projectOpen });
addSubItem(RibbonSubmenus.StudiesGraph, '1_graph', 2, 'saengine.graph.new', localize('rib.studies.newGraph', "New Visual Program..."), Codicon.add, { precondition: projectOpen });

//#endregion

//#region Tab 12: Collaborate

addItem(RibbonMenus.Collaborate, '1_SyncAndWorksharing', 1, 'saengine.share.shareProject', localize('rib.collab.share', "Share Project"), Codicon.organization, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Collaborate, '1_SyncAndWorksharing', 2, 'saengine.share.syncNow', localize('rib.collab.sync', "Sync"), Codicon.sync, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Collaborate, '1_SyncAndWorksharing', 3, RibbonSubmenus.CollabLocks, localize('rib.collab.lockPart', "Lock Part"), Codicon.lock, 'large', true, 'saengine.share.lockPart');
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 1, 'saengine.share.lockPart', localize('rib.collab.lock', "Lock Part for Editing..."), Codicon.lock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 2, 'saengine.share.unlockPart', localize('rib.collab.unlock', "Release Part Lock..."), Codicon.unlock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '2_stop', 1, 'saengine.share.stopSharing', localize('rib.collab.stopSharing', "Stop Sharing..."), Codicon.debugStop, { precondition: projectOpen });
addItem(RibbonMenus.Collaborate, '1_SyncAndWorksharing', 4, 'saengine.share.openShared', localize('rib.collab.openShared', "Open Shared"), Codicon.folderOpened, 'small');

addSubmenu(RibbonMenus.Collaborate, '2_LiveCoEditing', 1, RibbonSubmenus.CollabLive, localize('rib.collab.live', "Live Co-Editing"), Codicon.broadcast, 'large', true, 'saengine.share.liveCoEditing');
addSubItem(RibbonSubmenus.CollabLive, '1_live', 1, 'saengine.share.liveCoEditing', localize('rib.collab.liveSetup', "Live Co-Editing..."), Codicon.broadcast, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLive, '1_live', 2, 'saengine.collaboration.start', localize('rib.collab.liveStart', "Start Live Co-Editing"), Codicon.play, { precondition: ContextKeyExpr.and(projectOpen, liveCoEditing.negate()) });
addSubItem(RibbonSubmenus.CollabLive, '1_live', 3, 'saengine.collaboration.stop', localize('rib.collab.liveStop', "Stop Live Co-Editing"), Codicon.debugStop, { precondition: liveCoEditing });
addSubItem(RibbonSubmenus.CollabLive, '2_relay', 1, 'saengine.collaboration.hostRelay', localize('rib.collab.hostRelay', "Host Co-Editing Relay"), Codicon.server, { precondition: relayHosted.negate() });
addSubItem(RibbonSubmenus.CollabLive, '2_relay', 2, 'saengine.collaboration.stopRelay', localize('rib.collab.stopRelay', "Stop Hosting Relay"), Codicon.debugStop, { precondition: relayHosted });

addItem(RibbonMenus.Collaborate, '3_ReviewAndVersions', 1, 'saengine.project.showVersions', localize('rib.collab.versions', "Versions"), Codicon.history, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Collaborate, '3_ReviewAndVersions', 2, 'saengine.project.saveVersion', localize('rib.collab.saveVersion', "Save Version"), Codicon.gitCommit, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 13: Manage

addSubmenu(RibbonMenus.Manage, '1_Standards', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package, 'large', true, 'saengine.packages.show');
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 1, 'saengine.packages.show', localize('rib.manage.showPackages', "Packages..."), Codicon.package);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 2, 'saengine.codePacks.new', localize('rib.manage.newCodePack', "New Code Pack..."), Codicon.newFile);
addSubItem(RibbonSubmenus.ManagePackages, '1_pkg', 3, 'saengine.codePacks.install', localize('rib.manage.installPkg', "Install Package from File..."), Codicon.cloudDownload);
addItem(RibbonMenus.Manage, '1_Standards', 2, 'saengine.showPlannedFeatures', localize('rib.manage.planned', "Planned Features"), Codicon.lightbulb, 'small');
addItem(RibbonMenus.Manage, '1_Standards', 3, 'saengine.components.show', localize('rib.manage.components', "Installer Components"), Codicon.extensions, 'small');
addItem(RibbonMenus.Manage, '1_Standards', 4, 'saengine.update.check', localize('rib.manage.updates', "Check Updates"), Codicon.refresh, 'small');

addItem(RibbonMenus.Manage, '2_OfficeServer', 1, 'saengine.officeServer.run', localize('rib.manage.runServer', "Run on Server"), Codicon.server, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Manage, '2_OfficeServer', 2, 'saengine.officeServer.check', localize('rib.manage.checkServer', "Check Server"), Codicon.pass, 'small');
addItem(RibbonMenus.Manage, '2_OfficeServer', 3, 'saengine.officeServer.setToken', localize('rib.manage.setToken', "Set Server Token"), Codicon.key, 'small');
addItem(RibbonMenus.Manage, '2_OfficeServer', 4, 'saengine.officeServer.clearToken', localize('rib.manage.clearToken', "Forget Token"), Codicon.trash, 'small');

addItem(RibbonMenus.Manage, '3_AIControl', 1, 'saengine.ai.openChat', localize('rib.manage.aiChat', "AI Assistant"), Codicon.sparkle, 'large');
addSubmenu(RibbonMenus.Manage, '3_AIControl', 2, RibbonSubmenus.ManageAi, localize('rib.manage.aiControl', "AI Control"), Codicon.robot, 'large', true, 'saengine.ai.allowControl');
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 1, 'saengine.ai.allowControl', localize('rib.manage.aiAllow', "Allow AI Window Control"), Codicon.robot);
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 2, 'saengine.ai.stop', localize('rib.manage.aiStop', "Stop AI Access"), Codicon.debugStop, { precondition: aiRunning });
addSubItem(RibbonSubmenus.ManageAi, '1_ai', 3, 'saengine.ai.showConnection', localize('rib.manage.aiDetails', "Show AI Connection Details"), Codicon.info, { precondition: aiRunning });
addSubItem(RibbonSubmenus.ManageAi, '2_edits', 1, 'saengine.ai.allowEdits', localize('rib.manage.aiAllowEdits', "Allow AI Edits for Session"), Codicon.edit, { precondition: ContextKeyExpr.and(aiRunning, aiEditsAllowed.negate()) });
addSubItem(RibbonSubmenus.ManageAi, '2_edits', 2, 'saengine.ai.disallowEdits', localize('rib.manage.aiDisallowEdits', "Stop AI Edits"), Codicon.lock, { precondition: aiEditsAllowed });
addSubItem(RibbonSubmenus.ManageAi, '3_privacy', 1, 'saengine.ai.manageProjectConsent', localize('rib.manage.aiConsent', "AI Data Sharing for Project..."), Codicon.shield);
addSubItem(RibbonSubmenus.ManageAi, '3_privacy', 2, 'saengine.ai.showActivity', localize('rib.manage.aiActivity', "Show AI Activity"), Codicon.output);
addItem(RibbonMenus.Manage, '3_AIControl', 3, 'saengine.ai.manageModels', localize('rib.manage.aiModels', "AI Models & Providers"), Codicon.settingsGear, 'small');
addItem(RibbonMenus.Manage, '3_AIControl', 4, 'saengine.ai.useAnthropicKey', localize('rib.manage.anthropicKey', "Anthropic API Key"), Codicon.key, 'small');
addItem(RibbonMenus.Manage, '3_AIControl', 5, 'saengine.ai.useEndpoint', localize('rib.manage.endpoint', "Self-Hosted Endpoint"), Codicon.globe, 'small');

addItem(RibbonMenus.Manage, '4_Automation', 1, 'saengine.actions.runFromFile', localize('rib.manage.runActions', "Run Actions File..."), Codicon.play, 'small');
addItem(RibbonMenus.Manage, '4_Automation', 2, 'saengine.actions.showCatalogue', localize('rib.manage.actionCatalogue', "Action Catalogue"), Codicon.book, 'small');
addItem(RibbonMenus.Manage, '4_Automation', 3, 'saengine.checkPythonRuntime', localize('rib.manage.pythonRuntime', "Check Python Runtime"), Codicon.terminal, 'small');

addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 1, 'saengine.openSettings', localize('rib.manage.settings', "Settings"), Codicon.settingsGear, 'large');
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 2, 'saengine.toggleDeveloperMode', localize('rib.manage.devMode', "Developer Mode"), Codicon.code, 'small', { toggled: developerMode });
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 3, 'saengine.help.userManual', localize('rib.manage.userManual', "User Manual"), Codicon.book, 'small');
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 4, 'saengine.help.tutorial', localize('rib.manage.tutorial', "Sample Tutorial"), Codicon.mortarBoard, 'small');
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 5, 'saengine.feedback.reportBug', localize('rib.manage.reportBug', "Report a Bug"), Codicon.bug, 'small');
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 6, 'saengine.feedback.send', localize('rib.manage.sendFeedback', "Send Feedback"), Codicon.commentDiscussion, 'small');
addItem(RibbonMenus.Manage, '5_SettingsAndHelp', 7, 'saengine.diagnostics.create', localize('rib.manage.diagnostics', "Diagnostics Bundle"), Codicon.shield, 'small');

//#endregion
