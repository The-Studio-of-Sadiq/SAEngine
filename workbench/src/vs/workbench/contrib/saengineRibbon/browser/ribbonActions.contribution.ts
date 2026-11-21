/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveDocument } from '../../../../base/browser/dom.js';
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
import {
	registerRibbonCustomGroup,
	registerRibbonGroupLabel,
	registerRibbonGroupPriority,
	registerRibbonItemHint,
	RibbonButtonSize,
	RibbonMenus,
	SAENGINE_EDITOR_IDS,
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
	HomeVersions: MenuId.for('SaengineRibbon.Submenu.HomeVersions'),
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

//#region Part, section, and clipboard commands

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
const CMD_SEC_SETTINGS_OCCUPANCY = 'saengine.ribbon.openSection.settings.occupancy';
const CMD_SEC_SETTINGS_SITE = 'saengine.ribbon.openSection.settings.site';
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

registerSectionOpener(CMD_SEC_SETTINGS_CODE, localize2('ribbon.sec.code', "Design Code & Project"), 'settings', 'code', ['project', 'occupancy', 'construction', 'site']);
registerSectionOpener(CMD_SEC_SETTINGS_OCCUPANCY, localize2('ribbon.sec.occupancy', "Occupancy & Construction"), 'settings', 'occupancy', ['occupancy']);
registerSectionOpener(CMD_SEC_SETTINGS_SITE, localize2('ribbon.sec.site', "Site & Location"), 'settings', 'site', ['site']);
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
	['Coordination', localize('ribbon.grp.coordination', "Coordination")],
	['Plumbing', localize('ribbon.grp.plumbing', "Plumbing")],
	['HVAC', localize('ribbon.grp.hvac', "HVAC")],
	['Electrical', localize('ribbon.grp.electrical', "Electrical")],
	['FireAndSystems', localize('ribbon.grp.fireSystems', "Fire & Systems")],
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
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 4, 'saengine.share.openShared', localize('rib.home.openShared', "Open Shared Project..."), Codicon.organization);
addSubItem(RibbonSubmenus.HomeOpen, '1_open', 5, 'saengine.project.showStart', localize('rib.home.showStart', "Show Start Window"), Codicon.home);

addSubmenu(RibbonMenus.Home, '1_Project', 3, RibbonSubmenus.HomeSave, localize('rib.home.save', "Save"), Codicon.save, 'large', true, 'saveAll');
addSubItem(RibbonSubmenus.HomeSave, '1_save', 1, 'saveAll', localize('rib.home.saveAll', "Save All"), Codicon.saveAll);
addSubItem(RibbonSubmenus.HomeSave, '1_save', 2, 'workbench.action.files.save', localize('rib.home.saveFile', "Save Active File"), Codicon.save);

addSubmenu(RibbonMenus.Home, '1_Project', 4, RibbonSubmenus.HomeVersions, localize('rib.home.versions', "Versions"), Codicon.history, 'small', true, 'saengine.project.showVersions');
addSubItem(RibbonSubmenus.HomeVersions, '1_ver', 1, 'saengine.project.showVersions', localize('rib.home.showVersions', "Versions"), Codicon.history, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeVersions, '1_ver', 2, 'saengine.project.saveVersion', localize('rib.home.saveVersion', "Save Version..."), Codicon.gitCommit, { precondition: projectOpen });
addItem(RibbonMenus.Home, '1_Project', 5, 'saengine.project.showOverview', localize('rib.home.overview', "Overview"), Codicon.dashboard, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '1_Project', 6, 'saengine.project.revealInOS', localize('rib.home.reveal', "Open Folder"), Codicon.folder, 'small', { precondition: projectOpen });

addSubmenu(RibbonMenus.Home, '2_Parts', 1, RibbonSubmenus.HomeParts, localize('rib.home.parts', "Parts"), Codicon.layers, 'large', false);
addSubItem(RibbonSubmenus.HomeParts, '1_site', 1, CMD_OPEN_SOIL, localize('rib.parts.soil', "01 Soil Report"), Codicon.globe, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '1_site', 2, 'saengine.project.openSettings', localize('rib.parts.settings', "02 Project Settings"), Codicon.settingsGear, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '2_library', 1, CMD_OPEN_MATERIALS, localize('rib.parts.materials', "03 Materials"), Codicon.layers, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '2_library', 2, CMD_OPEN_OBJECTS, localize('rib.parts.objects', "04 Object Types"), Codicon.symbolStructure, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '2_library', 3, 'saengine.section.new', localize('rib.parts.sectionDesigner', "Section Designer..."), Codicon.symbolRuler, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '3_model', 1, CMD_SEC_GRIDS, localize('rib.parts.grids', "Grids & Stories"), Codicon.layout, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '3_model', 2, CMD_OPEN_FLOOR_PLAN, localize('rib.parts.floorPlan', "05 Floor Plan / Structural Model"), Codicon.layoutPanel, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '3_model', 3, 'saengine.architecture.open', localize('rib.parts.architecture', "Architecture"), Codicon.home, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '3_model', 4, CMD_SEC_BIM_3D, localize('rib.parts.bim3d', "06 3D Building Model"), Codicon.symbolNamespace, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '3_model', 5, CMD_SEC_MEP_COORDINATION, localize('rib.parts.mep', "07 MEP"), Codicon.plug, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '4_analysis', 1, CMD_OPEN_FEM, localize('rib.parts.fem', "08 Analysis Model (FEM)"), Codicon.runAll, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '4_analysis', 2, 'saengine.fem.showCharts', localize('rib.parts.charts', "Analysis Charts"), Codicon.graph, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '4_analysis', 3, 'saengine.fem.openPushover', localize('rib.parts.pushover', "Pushover Model"), Codicon.graphLine, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '4_analysis', 4, CMD_OPEN_SUBSTRUCTURE, localize('rib.parts.substructure', "09 Substructure & Foundations"), Codicon.layers, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '5_outputs', 1, CMD_OPEN_BOQ, localize('rib.parts.boq', "10 Bill of Quantities"), Codicon.table, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '5_outputs', 2, 'saengine.project.showExports', localize('rib.parts.exports', "11 Exports & Drawings"), Codicon.export, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeParts, '5_outputs', 3, 'saengine.office.schedule', localize('rib.parts.office', "Office Tools & Studies"), Codicon.calendar, { precondition: projectOpen });

addItem(RibbonMenus.Home, '2_Parts', 2, 'saengine.showProperties', localize('rib.home.properties', "Properties"), Codicon.symbolProperty, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '2_Parts', 3, 'saengine.showModelView', localize('rib.home.modelView', "Model View"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Home, '2_Parts', 4, 'saengine.showTables', localize('rib.home.tables', "Tables"), Codicon.table, 'small', { precondition: projectOpen });

// 3_Workflow is rendered by ProjectStageBar via registerRibbonCustomGroup above.

addItem(RibbonMenus.Home, '4_Run', 1, 'saengine.runAll', localize('rib.home.runAll', "Run All"), Codicon.play, 'large', { precondition: projectOpen, when: runAllRunning.negate() });
addItem(RibbonMenus.Home, '4_Run', 1, 'saengine.runAll.cancel', localize('rib.home.stopRunAll', "Stop"), Codicon.debugStop, 'large', { precondition: runAllRunning, when: runAllRunning });
addSubmenu(RibbonMenus.Home, '4_Run', 2, RibbonSubmenus.HomeRun, localize('rib.home.run', "Run"), Codicon.runAll, 'large', false);
addSubItem(RibbonSubmenus.HomeRun, '1_run', 1, 'saengine.fem.runAnalysis', localize('rib.home.runAnalysis', "Run Analysis"), Codicon.play, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '1_run', 2, 'saengine.fem.runSelectedCases', localize('rib.home.runCases', "Run Selected Cases..."), Codicon.checklist, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '1_run', 3, 'saengine.officeServer.run', localize('rib.home.runServer', "Run on Office Server"), Codicon.server, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 1, 'saengine.runAll.showSteps', localize('rib.home.showSteps', "Show Run All Steps"), Codicon.listFlat, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 2, 'saengine.showProgress', localize('rib.home.progress', "Progress"), Codicon.tasklist, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeRun, '2_log', 3, 'saengine.restartEngine', localize('rib.home.restartEngine', "Restart Engine"), Codicon.debugRestart);

addItem(RibbonMenus.Home, '5_Clipboard', 1, 'undo', localize('rib.home.undo', "Undo"), Codicon.discard, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 2, 'redo', localize('rib.home.redo', "Redo"), Codicon.redo, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 3, CMD_CUT, localize('rib.home.cut', "Cut"), Codicon.clippy, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 4, CMD_COPY, localize('rib.home.copy', "Copy"), Codicon.copy, 'small');
addItem(RibbonMenus.Home, '5_Clipboard', 5, CMD_PASTE, localize('rib.home.paste', "Paste"), Codicon.insert, 'small');

addSubmenu(RibbonMenus.Home, '6_Workspace', 1, RibbonSubmenus.HomeCollaborate, localize('rib.home.collaborate', "Collaborate"), Codicon.organization, 'small', false);
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 1, 'saengine.share.shareProject', localize('rib.collab.share', "Share Project"), Codicon.organization, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 2, 'saengine.share.syncNow', localize('rib.collab.sync', "Sync"), Codicon.sync, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '1_sync', 3, 'saengine.share.openShared', localize('rib.collab.openShared', "Open Shared"), Codicon.folderOpened);
addNestedSubmenu(RibbonSubmenus.HomeCollaborate, '2_locks', 1, RibbonSubmenus.CollabLocks, localize('rib.collab.lockPart', "Lock Part"), Codicon.lock);
addNestedSubmenu(RibbonSubmenus.HomeCollaborate, '2_locks', 2, RibbonSubmenus.CollabLive, localize('rib.collab.live', "Live Co-Editing"), Codicon.broadcast);
addSubItem(RibbonSubmenus.HomeCollaborate, '3_versions', 1, 'saengine.project.showVersions', localize('rib.collab.versions', "Versions"), Codicon.history, { precondition: projectOpen });
addSubItem(RibbonSubmenus.HomeCollaborate, '3_versions', 2, 'saengine.project.saveVersion', localize('rib.collab.saveVersion', "Save Version"), Codicon.gitCommit, { precondition: projectOpen });

addSubmenu(RibbonMenus.Home, '6_Workspace', 2, RibbonSubmenus.HomeManage, localize('rib.home.manage', "Manage"), Codicon.settingsGear, 'small', false);
addNestedSubmenu(RibbonSubmenus.HomeManage, '1_standards', 1, RibbonSubmenus.ManagePackages, localize('rib.manage.packages', "Packages"), Codicon.package);
addNestedSubmenu(RibbonSubmenus.HomeManage, '1_standards', 2, RibbonSubmenus.ManageAi, localize('rib.manage.aiControl', "AI Control"), Codicon.robot);
addSubItem(RibbonSubmenus.HomeManage, '2_server', 1, 'saengine.officeServer.run', localize('rib.manage.runServer', "Run on Server"), Codicon.server, { precondition: projectOpen });
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

addItem(RibbonMenus.Project, '1_Parts', 1, CMD_OPEN_SOIL, localize('rib.proj.soil', "Soil Report"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 2, 'saengine.project.openSettings', localize('rib.proj.settings', "Settings"), Codicon.settingsGear, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 3, CMD_OPEN_MATERIALS, localize('rib.proj.materials', "Materials"), Codicon.layers, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 4, CMD_OPEN_OBJECTS, localize('rib.proj.objects', "Object Types"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 5, CMD_OPEN_FLOOR_PLAN, localize('rib.proj.floorPlan', "Floor Plan"), Codicon.layoutPanel, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 6, 'saengine.architecture.open', localize('rib.proj.architecture', "Architecture"), Codicon.home, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 7, CMD_SEC_BIM_3D, localize('rib.proj.bim', "3D Model"), Codicon.symbolNamespace, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 8, CMD_SEC_MEP_COORDINATION, localize('rib.proj.mep', "MEP"), Codicon.plug, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 9, CMD_OPEN_FEM, localize('rib.proj.fem', "FEM Model"), Codicon.runAll, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 10, CMD_OPEN_SUBSTRUCTURE, localize('rib.proj.substructure', "Foundations"), Codicon.layers, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 11, CMD_OPEN_BOQ, localize('rib.proj.boq', "BOQ"), Codicon.table, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Project, '1_Parts', 12, 'saengine.project.showExports', localize('rib.proj.exports', "Exports"), Codicon.export, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Project, '2_SyncAndWorksharing', 1, 'saengine.share.shareProject', localize('rib.collab.share', "Share Project"), Codicon.organization, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Project, '2_SyncAndWorksharing', 2, 'saengine.share.syncNow', localize('rib.collab.sync', "Sync"), Codicon.sync, 'large', { precondition: projectOpen });
addSubmenu(RibbonMenus.Project, '2_SyncAndWorksharing', 3, RibbonSubmenus.CollabLocks, localize('rib.collab.lockPart', "Lock Part"), Codicon.lock, 'large', true, 'saengine.share.lockPart');
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 1, 'saengine.share.lockPart', localize('rib.collab.lock', "Lock Part for Editing..."), Codicon.lock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '1_lock', 2, 'saengine.share.unlockPart', localize('rib.collab.unlock', "Release Part Lock..."), Codicon.unlock, { precondition: projectOpen });
addSubItem(RibbonSubmenus.CollabLocks, '2_stop', 1, 'saengine.share.stopSharing', localize('rib.collab.stopSharing', "Stop Sharing..."), Codicon.debugStop, { precondition: projectOpen });
addItem(RibbonMenus.Project, '2_SyncAndWorksharing', 4, 'saengine.share.openShared', localize('rib.collab.openShared', "Open Shared"), Codicon.folderOpened, 'small');

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

addItem(RibbonMenus.Project, '6_AIControl', 1, 'saengine.ai.openChat', localize('rib.manage.aiChat', "AI Assistant"), Codicon.sparkle, 'large');
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

addItem(RibbonMenus.Soil, '5_Settings', 1, CMD_SEC_SETTINGS_FOUNDATION, localize('rib.soil.fdnSettings', "Foundation Settings"), Codicon.settingsGear, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 4: Settings (Project Settings & Code Packs)

addItem(RibbonMenus.Settings, '1_ProjectAndSite', 1, CMD_SEC_SETTINGS_CODE, localize('rib.set.code', "Design Code"), Codicon.book, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '1_ProjectAndSite', 2, CMD_SEC_SETTINGS_OCCUPANCY, localize('rib.set.occupancy', "Occupancy"), Codicon.organization, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '1_ProjectAndSite', 3, CMD_SEC_SETTINGS_SITE, localize('rib.set.site', "Site"), Codicon.globe, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '2_Loads', 1, CMD_SEC_SETTINGS_AREA_LOADS, localize('rib.set.areaLoads', "Area Loads"), Codicon.arrowDown, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_Loads', 2, CMD_SEC_SETTINGS_CRANES, localize('rib.set.cranes', "Cranes"), Codicon.tools, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_Loads', 3, CMD_SEC_SETTINGS_SPECIAL, localize('rib.set.special', "Special"), Codicon.compass, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_Loads', 4, CMD_SEC_SETTINGS_SEISMIC, localize('rib.set.seismic', "Seismic"), Codicon.pulse, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_Loads', 5, CMD_SEC_SETTINGS_WIND, localize('rib.set.wind', "Wind"), Codicon.symbolEvent, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '2_Loads', 6, CMD_SEC_SETTINGS_COMBINATIONS, localize('rib.set.combinations', "Combinations"), Codicon.table, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '3_Engineering', 1, CMD_SEC_SETTINGS_ANALYSIS, localize('rib.set.analysis', "Analysis"), Codicon.runAll, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '3_Engineering', 2, CMD_SEC_SETTINGS_FOUNDATION, localize('rib.set.foundation', "Foundation"), Codicon.layers, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '3_Engineering', 3, CMD_SEC_SETTINGS_CODE_VALUES, localize('rib.set.codeValues', "Code Values"), Codicon.law, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '4_Outputs', 1, CMD_SEC_SETTINGS_DRAWINGS, localize('rib.set.drawings', "Drawings"), Codicon.files, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '4_Outputs', 2, CMD_SEC_SETTINGS_REPORT, localize('rib.set.report', "Report"), Codicon.filePdf, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Settings, '4_Outputs', 3, 'saengine.settings.resetDefaults', localize('rib.set.reset', "Reset to Defaults"), Codicon.discard, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Settings, '5_Packages', 1, 'saengine.packages.show', localize('rib.set.packages', "Packages"), Codicon.package, 'large', { when: ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.codePacks) });
addItem(RibbonMenus.Settings, '5_Packages', 2, 'saengine.project.openSettings', localize('rib.set.openSettings', "Project Settings"), Codicon.settingsGear, 'large', { precondition: projectOpen, when: ActiveEditorContext.isEqualTo(SAENGINE_EDITOR_IDS.codePacks) });
addItem(RibbonMenus.Settings, '5_Packages', 3, 'saengine.codePacks.new', localize('rib.set.newCodePack', "New Code Pack"), Codicon.newFile, 'small');
addItem(RibbonMenus.Settings, '5_Packages', 4, 'saengine.codePacks.install', localize('rib.set.installPkg', "Install Package"), Codicon.cloudDownload, 'small');

//#endregion

//#region Tab 5: Library (Materials, Object Types, Section Designer; editor actions in saengineLibrary)

addItem(RibbonMenus.Library, '1_Switch', 1, CMD_OPEN_MATERIALS, localize('rib.lib.materials', "Materials"), Codicon.layers, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Library, '1_Switch', 2, CMD_OPEN_OBJECTS, localize('rib.lib.objects', "Object Types"), Codicon.symbolStructure, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Library, '4_Sections', 1, 'saengine.section.new', localize('rib.lib.sectionDesigner', "Section Designer"), Codicon.symbolRuler, 'large', { precondition: projectOpen });

//#endregion

//#region Tab 6: Plan (cross-part links; Floor Plan tools registered in saengineCad)

addItem(RibbonMenus.Plan, '5_ModelData', 1, CMD_OPEN_FLOOR_PLAN, localize('rib.plan.floorPlan', "Floor Plan"), Codicon.layoutPanel, 'small', { precondition: projectOpen, when: ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.floorPlan) });
addItem(RibbonMenus.Plan, '5_ModelData', 2, CMD_SEC_GRIDS, localize('rib.plan.grids', "Grids & Stories"), Codicon.layout, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Plan, '5_ModelData', 3, 'saengine.floorPlan.openMembersTable', localize('rib.plan.membersTable', "Members Table"), Codicon.table, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 11: MEP

addItem(RibbonMenus.MEP, '1_Coordination', 1, CMD_SEC_MEP_COORDINATION, localize('rib.mep.coordination', "Coordination"), Codicon.warning, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '1_Coordination', 2, 'saengine.mep.editor.suggestSleeves', localize('rib.mep.suggestSleeves', "Suggest Sleeves"), Codicon.wand, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '1_Coordination', 3, 'saengine.mep.editor.importIfc', localize('rib.mep.importIfc', "Import MEP IFC"), Codicon.cloudDownload, 'small', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '2_Plumbing', 1, CMD_SEC_MEP_PLUMBING, localize('rib.mep.plumbing', "Plumbing"), Codicon.beaker, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '2_Plumbing', 2, 'saengine.mep.plumbing.hotWater', localize('rib.mep.hotWater', "Hot Water"), Codicon.beaker, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '2_Plumbing', 3, 'saengine.mep.plumbing.gas', localize('rib.mep.gas', "Gas & Medical Gas"), Codicon.flame, 'small', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '3_HVAC', 1, CMD_SEC_MEP_HVAC, localize('rib.mep.hvac', "HVAC"), Codicon.dashboard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '3_HVAC', 2, 'saengine.mep.hvac.roomLoads', localize('rib.mep.roomLoads', "Room Loads"), Codicon.dashboard, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '3_HVAC', 3, 'saengine.mep.hvac.heatingLoads', localize('rib.mep.heatingLoads', "Heating Loads"), Codicon.flame, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '3_HVAC', 4, 'saengine.mep.hvac.ductPressure', localize('rib.mep.ductPressure', "Duct Pressure"), Codicon.compass, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '3_HVAC', 5, 'saengine.mep.hvac.routeDucts', localize('rib.mep.routeDucts', "Route Ducts"), Codicon.wand, 'small', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '4_Electrical', 1, CMD_SEC_MEP_ELECTRICAL, localize('rib.mep.electrical', "Electrical"), Codicon.plug, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 2, 'saengine.mep.electrical.boards', localize('rib.mep.boards', "Boards & Circuits"), Codicon.circuitBoard, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 3, 'saengine.mep.electrical.cables', localize('rib.mep.cables', "Cable Sizing"), Codicon.plug, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 4, 'saengine.mep.electrical.voltageDrop', localize('rib.mep.voltageDrop', "Voltage Drop"), Codicon.pulse, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 5, 'saengine.mep.electrical.shortCircuit', localize('rib.mep.shortCircuit', "Short Circuit"), Codicon.symbolEvent, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '4_Electrical', 6, 'saengine.mep.electrical.lighting', localize('rib.mep.lighting', "Lighting"), Codicon.lightbulb, 'small', { precondition: projectOpen });

addItem(RibbonMenus.MEP, '5_FireAndSystems', 1, CMD_SEC_MEP_FIRE, localize('rib.mep.fire', "Fire"), Codicon.flame, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 2, CMD_SEC_MEP_SYSTEMS, localize('rib.mep.systems', "Systems"), Codicon.circuitBoard, 'large', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 3, 'saengine.office.fabrication', localize('rib.mep.fabrication', "MEP Fabrication"), Codicon.tools, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 4, 'saengine.mep.fire.sprinklers', localize('rib.mep.sprinklers', "Place Sprinklers"), Codicon.flame, 'small', { precondition: projectOpen });
addItem(RibbonMenus.MEP, '5_FireAndSystems', 5, 'saengine.mep.fire.alarm', localize('rib.mep.alarm', "Fire Alarm"), Codicon.warning, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 12: Analyze

addItem(RibbonMenus.Analyze, '1_Solver', 1, 'saengine.runAll', localize('rib.analyze.runAll', "Run All"), Codicon.play, 'large', { precondition: projectOpen, when: runAllRunning.negate() });
addItem(RibbonMenus.Analyze, '1_Solver', 1, 'saengine.runAll.cancel', localize('rib.analyze.stopRunAll', "Stop"), Codicon.debugStop, 'large', { precondition: runAllRunning, when: runAllRunning });
addSubmenu(RibbonMenus.Analyze, '1_Solver', 2, RibbonSubmenus.AnalyzeRun, localize('rib.analyze.run', "Run"), Codicon.runAll, 'large', true, 'saengine.fem.runAnalysis');
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 1, 'saengine.fem.runAnalysis', localize('rib.analyze.runAnalysis', "Run Analysis"), Codicon.runAll, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 2, 'saengine.analyze.runDerive', localize('rib.analyze.deriveOnly', "Derive Only"), Codicon.symbolStructure, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 3, 'saengine.analyze.runAnalyse', localize('rib.analyze.analyseOnly', "Analyse Only"), Codicon.runAll, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '1_run', 4, 'saengine.analyze.runDesign', localize('rib.analyze.designOnly', "Design Only"), Codicon.symbolRuler, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '2_check', 1, 'saengine.analyze.checkProject', localize('rib.analyze.checkProject', "Check Project"), Codicon.checklist, { precondition: projectOpen });
addSubItem(RibbonSubmenus.AnalyzeRun, '2_check', 2, 'saengine.analyze.validateProject', localize('rib.analyze.validate', "Validate"), Codicon.pass, { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 3, 'saengine.fem.runSelectedCases', localize('rib.analyze.selectedCases', "Selected Cases"), Codicon.checklist, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 4, 'saengine.fem.deriveModel', localize('rib.analyze.deriveModel', "Derive Model"), Codicon.symbolStructure, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '1_Solver', 5, CMD_SEC_SETTINGS_ANALYSIS, localize('rib.analyze.modelSettings', "Analysis Settings"), Codicon.settingsGear, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '2_Advanced', 1, 'saengine.fem.openPushover', localize('rib.analyze.pushover', "Pushover"), Codicon.graphLine, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '2_Advanced', 2, 'saengine.fem.cfdWind', localize('rib.analyze.cfdWind', "CFD Wind Tunnel"), Codicon.symbolEvent, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '2_Advanced', 3, CMD_OPEN_FEM, localize('rib.analyze.femModel', "FEM Model"), Codicon.symbolStructure, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Analyze, '3_MeshAndView', 1, 'saengine.fem.toggleMeshNodes', localize('rib.analyze.meshNodes', "Mesh Nodes"), Codicon.circleSmallFilled, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 2, 'saengine.fem.fitView', localize('rib.analyze.fitView', "Zoom to Fit"), Codicon.screenFull, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 3, 'saengine.fem.showLog', localize('rib.analyze.log', "Analysis Log"), Codicon.output, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 4, 'saengine.runAll.showSteps', localize('rib.analyze.steps', "Run All Steps"), Codicon.listFlat, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Analyze, '3_MeshAndView', 5, 'saengine.restartEngine', localize('rib.analyze.restart', "Restart Engine"), Codicon.debugRestart, 'small');
addItem(RibbonMenus.Analyze, '3_MeshAndView', 6, 'saengine.manage.verificationManual', localize('rib.analyze.verification', "Verification Manual"), Codicon.filePdf, 'small');

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

addItem(RibbonMenus.Results, '2_ChartsAndTables', 1, 'saengine.fem.showCharts', localize('rib.res.charts', "Analysis Charts"), Codicon.graph, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 2, 'saengine.fem.toggleTables', localize('rib.res.tables', "Result Tables"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 3, 'saengine.fem.exportResultTables', localize('rib.res.exportTables', "Export Tables"), Codicon.export, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 4, 'saengine.fem.showBridgeResults', localize('rib.res.bridge', "Bridge Results"), Codicon.compass, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '2_ChartsAndTables', 5, 'saengine.fem.pickMember', localize('rib.res.memberDetails', "Member Details"), Codicon.search, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Results, '3_Inspect3D', 1, 'saengine.fem.sectionBox', localize('rib.res.sectionBox', "Section Box"), Codicon.symbolMisc, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '3_Inspect3D', 2, 'saengine.fem.measure', localize('rib.res.measure', "Measure"), Codicon.symbolRuler, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Results, '3_Inspect3D', 3, 'saengine.fem.revealHidden', localize('rib.res.revealHidden', "Reveal Hidden"), Codicon.lightbulb, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 14: Design

addItem(RibbonMenus.Design, '1_Checks', 1, 'saengine.fem.toggleDesignUtilisation', localize('rib.design.utilisation', "Utilisation"), Codicon.checklist, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Checks', 2, 'saengine.analyze.checkProject', localize('rib.design.checkProject', "Check Project"), Codicon.pass, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '1_Checks', 3, 'saengine.analyze.validateProject', localize('rib.design.validate', "Validate"), Codicon.shield, 'small', { precondition: projectOpen });

addItem(RibbonMenus.Design, '2_Detailing', 1, 'saengine.fem.designReinforcement', localize('rib.design.reinforcement', "Design Rebar"), Codicon.symbolRuler, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Detailing', 2, 'saengine.fem.pickMember', localize('rib.design.memberDetails', "Member Details"), Codicon.search, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '2_Detailing', 3, 'saengine.fem.strutAndTie', localize('rib.design.strutAndTie', "Strut-and-Tie"), Codicon.symbolStructure, 'large', { precondition: projectOpen });

addItem(RibbonMenus.Design, '3_Standards', 1, CMD_SEC_SETTINGS_CODE_VALUES, localize('rib.design.codeValues', "Code Values"), Codicon.law, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Design, '3_Standards', 2, CMD_OPEN_SUBSTRUCTURE, localize('rib.design.substructure', "Substructure"), Codicon.layers, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 15: Foundations (cross-part settings link; domain commands registered in saengineSubstructure)

addItem(RibbonMenus.Foundations, '4_Design', 5, CMD_SEC_SETTINGS_FOUNDATION, localize('rib.fdn.settings', "Foundation Settings"), Codicon.settingsGear, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 16: BOQ (cross-part links; domain commands registered in saengineBoq)

addItem(RibbonMenus.BOQ, '1_Measure', 1, CMD_OPEN_BOQ, localize('rib.boq.open', "Bill of Quantities"), Codicon.table, 'large', { precondition: projectOpen, when: ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.boq) });
addItem(RibbonMenus.BOQ, '2_RatesAndCarbon', 1, 'saengine.boq.editRates', localize('rib.boq.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '2_RatesAndCarbon', 2, 'saengine.boq.editCarbon', localize('rib.boq.carbon', "Carbon Factors"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '4_Export', 1, 'saengine.boq.exportXlsx', localize('rib.boq.xlsx', "Export Excel"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.BOQ, '4_Export', 2, 'saengine.boq.exportCsv', localize('rib.boq.csv', "Export CSV"), Codicon.fileCode, 'small', { precondition: projectOpen });

//#endregion

//#region Tab 17: Output

addItem(RibbonMenus.Output, '1_Exports', 1, 'saengine.project.showExports', localize('rib.out.exports', "Exports Overview"), Codicon.export, 'large', { precondition: projectOpen, when: ActiveEditorContext.notEqualsTo(SAENGINE_EDITOR_IDS.exports) });
addItem(RibbonMenus.Output, '1_Exports', 2, 'saengine.exports.revealFolder', localize('rib.out.revealFolder', "Exports Folder"), Codicon.folderOpened, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Output, '1_Exports', 3, 'saengine.exports.refresh', localize('rib.out.refresh', "Refresh"), Codicon.refresh, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Output, '1_Exports', 4, 'saengine.manage.verificationManual', localize('rib.out.verification', "Verification Manual"), Codicon.filePdf, 'small');

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
addSubItem(RibbonSubmenus.OutputArchive, '1_arc', 2, 'saengine.project.openArchive', localize('rib.out.openArchive', "Open Project Archive..."), Codicon.folderOpened);

//#endregion

//#region Tab 18: Documents

addItem(RibbonMenus.Documents, '1_Drawings', 1, 'saengine.project.showExports', localize('rib.docs.drawings', "Drawing Set"), Codicon.files, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '1_Drawings', 2, CMD_SEC_SETTINGS_DRAWINGS, localize('rib.docs.titleBlock', "Title Block & Detailing"), Codicon.settingsGear, 'small', { precondition: projectOpen });
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
addItem(RibbonMenus.Documents, '4_Schedules', 2, CMD_OPEN_BOQ, localize('rib.docs.boq', "Bill of Quantities"), Codicon.table, 'large', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '4_Schedules', 3, 'saengine.boq.editRates', localize('rib.docs.rates', "Schedule of Rates"), Codicon.symbolNumeric, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '4_Schedules', 4, 'saengine.boq.editCarbon', localize('rib.docs.carbon', "Carbon Factors"), Codicon.globe, 'small', { precondition: projectOpen });
addItem(RibbonMenus.Documents, '4_Schedules', 5, 'saengine.floorPlan.openMembersTable', localize('rib.docs.membersTable', "Members Schedule"), Codicon.listFlat, 'small', { precondition: projectOpen });

addSubmenu(RibbonMenus.Documents, '5_Report', 1, RibbonSubmenus.DocsReport, localize('rib.docs.report', "Design Report"), Codicon.filePdf, 'large', true, 'saengine.report.print');
addSubItem(RibbonSubmenus.DocsReport, '1_report', 1, 'saengine.report.print', localize('rib.docs.printReport', "Print Design Report"), Codicon.filePdf, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '1_report', 2, 'saengine.report.exportWord', localize('rib.docs.wordReport', "Export Report to Word"), Codicon.fileText, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '2_config', 1, 'saengine.report.configure', localize('rib.docs.configureReport', "Configure Design Report..."), Codicon.settingsGear, { precondition: projectOpen });
addSubItem(RibbonSubmenus.DocsReport, '2_config', 2, CMD_SEC_SETTINGS_REPORT, localize('rib.docs.reportSettings', "Design Report Settings"), Codicon.book, { precondition: projectOpen });

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
