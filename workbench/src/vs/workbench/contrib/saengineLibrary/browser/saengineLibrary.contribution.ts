/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, MenuId, MenuRegistry, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { MATERIALS_SCHEMA, OBJECTS_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { BimStudies, RenderPreset } from '../../saengineOffice/browser/bimStudies.js';
import { registerRibbonItemHint, RibbonMenus } from '../../saengineRibbon/browser/ribbonRegistry.js';
import { BuildingEditor } from './buildingEditor.js';
import { GridsEditor } from './gridsEditor.js';
import { SettingsEditor } from './settingsEditor.js';
import { StructureEditor } from './structureEditor.js';
import { JsonDocumentEditor } from './jsonDocumentEditor.js';
import { LibraryEditor } from './libraryEditor.js';
import { LibraryEditorInput, LibraryEditorInputSerializer, LibraryKind } from './libraryEditorInput.js';
import { humanize } from './schemaForm.js';
import './codePacks.contribution.js';
import './sectionDesigner.contribution.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(LibraryEditor, LibraryEditorInput.EDITOR_ID, localize('libraryEditor', "SAEngine Library Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(BuildingEditor, LibraryEditorInput.BUILDING_EDITOR_ID, localize('buildingEditor', "SAEngine Building Model Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(GridsEditor, LibraryEditorInput.GRIDS_EDITOR_ID, localize('gridsEditor', "SAEngine Grids and Stories Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SettingsEditor, LibraryEditorInput.SETTINGS_EDITOR_ID, localize('settingsEditorPane', "SAEngine Project Settings Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(StructureEditor, LibraryEditorInput.STRUCTURE_EDITOR_ID, localize('structureEditorPane', "SAEngine Structural Model Editor")),
	[new SyncDescriptor(LibraryEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(LibraryEditorInput.ID, LibraryEditorInputSerializer);

/** Project files with a visual editor; each is the main file of the project part with that id. */
const KINDS: readonly LibraryKind[] = ['settings', 'materials', 'objects', 'floorPlan', 'structure', 'bim'];

const EDITOR_LABELS: { readonly [kind in LibraryKind]: string } = {
	materials: localize('materialsEditorLabel', "Materials Editor"),
	objects: localize('objectsEditorLabel', "Object Types Editor"),
	floorPlan: localize('gridsEditorLabel', "Grids & Stories Editor"),
	settings: localize('settingsEditorLabel', "Project Settings Editor"),
	bim: localize('buildingEditorLabel', "Building Model Editor"),
	structure: localize('structureEditorLabel', "Structural Model Editor"),
	reportTemplate: localize('reportTemplateEditorLabel', "Report Template Editor"),
	worksheet: localize('worksheetEditorLabel', "Calculation Worksheet Editor"),
	rates: localize('ratesEditorLabel', "Schedule of Rates Editor"),
	carbon: localize('carbonEditorLabel', "Carbon Factors Editor"),
};

const EDITOR_IDS: { readonly [kind in LibraryKind]: string } = {
	materials: LibraryEditorInput.EDITOR_ID,
	objects: LibraryEditorInput.EDITOR_ID,
	floorPlan: LibraryEditorInput.GRIDS_EDITOR_ID,
	settings: LibraryEditorInput.SETTINGS_EDITOR_ID,
	bim: LibraryEditorInput.BUILDING_EDITOR_ID,
	structure: LibraryEditorInput.STRUCTURE_EDITOR_ID,
	reportTemplate: LibraryEditorInput.REPORT_TEMPLATE_EDITOR_ID,
	worksheet: LibraryEditorInput.WORKSHEET_EDITOR_ID,
	rates: LibraryEditorInput.RATES_EDITOR_ID,
	carbon: LibraryEditorInput.RATES_EDITOR_ID,
};

/**
 * Opens the project's `03 Materials/materials.json`, `04 Objects/objects.json` and
 * `06 BIM/bim.json` in their visual editors by default. `05 Floor Plan/floor-plan.json` opens in
 * the plan view (Floor Plan editor) and offers its grids and stories form as an option. Other
 * files with the same names are not affected, and the JSON stays reachable on purpose through
 * "Reopen Editor With...".
 */
class LibraryEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.libraryEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		for (const kind of KINDS) {
			const part = partById(kind);
			if (!part?.mainFile) {
				continue;
			}
			this._register(editorResolverService.registerEditor(
				`**/${part.mainFile}`,
				{
					id: EDITOR_IDS[kind],
					label: EDITOR_LABELS[kind],
					detail: localize('libraryEditorDetail', "SAEngine"),
					// The floor plan opens in its plan view, the structural model in its 3D modeller;
					// the form is the alternative.
					priority: kind === 'floorPlan' || kind === 'structure' ? RegisteredEditorPriority.option : RegisteredEditorPriority.default,
				},
				{
					singlePerResource: true,
					canSupportResource: resource => this.kindOf(resource) === kind,
				},
				{
					createEditorInput: ({ resource, options }) => ({
						editor: instantiationService.createInstance(LibraryEditorInput, resource, kind, undefined),
						options,
					}),
				}
			));
		}
	}

	private kindOf(resource: URI): LibraryKind | undefined {
		// Project detection is asynchronous; until it finishes, a part's main file in the
		// workspace folder is matched by path so files opened at startup still get their editor.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		if (!root) {
			return undefined;
		}
		// The project's own parts only: a floor plan left in a special structure is a plain file.
		const parts = this.projectService.project ? this.projectService.parts : undefined;
		for (const kind of KINDS) {
			const part = partById(kind);
			if (parts && !parts.includes(part!)) {
				continue;
			}
			if (part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile))) {
				return kind;
			}
		}
		return undefined;
	}
}

registerWorkbenchContribution2(LibraryEditorResolverContribution.ID, LibraryEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the visual editor undo the file's text edits; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof JsonDocumentEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

const UNDO_PRIORITY = 110;
UndoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(UNDO_PRIORITY, 'saengine-library', accessor => undoRedo(accessor, true));

/**
 * W4C-13: opens 6 BIM with the 4D playback of the saved programme (Office Tools > 4D Programme >
 * Play in the BIM View): elements shown as built up to the slider's day, Play steps through it.
 */
CommandsRegistry.registerCommand('saengine.bim.play4d', async (accessor: ServicesAccessor, autoplay?: unknown) => {
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('bim');
	const editorService = accessor.get(IEditorService);
	if (!project || !part?.mainFile) {
		return;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	if (pane instanceof BuildingEditor) {
		await pane.play4d(autoplay === true);
	}
});

/** Exports the building model as IFC (the Exports page runs it): opens 6 BIM and exports from it. */
CommandsRegistry.registerCommand('saengine.bim.exportIfc', async (accessor: ServicesAccessor) => {
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('bim');
	const editorService = accessor.get(IEditorService);
	if (!project || !part?.mainFile) {
		return;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile) });
	if (pane instanceof BuildingEditor) {
		await pane.exportIfc();
	}
});

// ─────────────────────── Contextual Ribbon Commands (U4) ───────────────────────

async function activeLibraryEditor(accessor: ServicesAccessor, desiredKind?: LibraryKind): Promise<LibraryEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const project = accessor.get(ISaengineProjectService).project;
	const active = editorService.activeEditorPane;
	if (active instanceof LibraryEditor && (!desiredKind || active.libraryKind === desiredKind)) {
		return active;
	}
	const targetKind = desiredKind ?? 'materials';
	const part = partById(targetKind);
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof LibraryEditor ? pane : undefined;
}

async function activeBuildingEditor(accessor: ServicesAccessor): Promise<BuildingEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const active = editorService.activeEditorPane;
	if (active instanceof BuildingEditor) {
		return active;
	}
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('bim');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof BuildingEditor ? pane : undefined;
}

function registerBuildingStudyCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: typeof Codicon[keyof typeof Codicon] | undefined,
	group: string,
	order: number,
	size: 'large' | 'small',
	run: (studies: BimStudies) => Promise<void> | void,
): void {
	registerRibbonItemHint(id, { size }, RibbonMenus.Bim3D);
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title, icon, menu: { id: RibbonMenus.Bim3D, group, order } });
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			const notificationService = accessor.get(INotificationService);
			const pane = await activeBuildingEditor(accessor);
			const studies = pane?.bimStudies;
			if (!studies) {
				notificationService.info(localize('bim.studiesUnavailable', "Open the 3D view of the building model first."));
				return;
			}
			await run(studies);
		}
	});
}

// Settings: Reset Load Combinations to Code Defaults
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.settings.resetDefaults',
			title: localize2('settings.resetDefaults', "Reset Combinations to Code Defaults..."),
			icon: Codicon.discard,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const editorService = accessor.get(IEditorService);
		const project = accessor.get(ISaengineProjectService).project;
		const active = editorService.activeEditorPane;
		if (active instanceof SettingsEditor) {
			await active.resetCombinations();
			return;
		}
		const part = partById('settings');
		if (!project || !part?.mainFile) {
			return;
		}
		const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
		if (pane instanceof SettingsEditor) {
			await pane.resetCombinations();
		}
	}
});

// Library: Add Material Categories, Add Object Kinds, Duplicate, Delete, Stiffness Modifiers, Import/Export
const LibraryAddMaterialSubmenu = MenuId.for('saengine.ribbon.library.addMaterial');
registerRibbonItemHint(LibraryAddMaterialSubmenu.id, { size: 'large' }, RibbonMenus.Library);
MenuRegistry.appendMenuItem(RibbonMenus.Library, {
	submenu: LibraryAddMaterialSubmenu,
	title: localize2('rib.lib.addMaterialSub', "Add Material"),
	icon: Codicon.add,
	group: '2_AddMaterial',
	order: 1,
});
for (const [index, category] of ((MATERIALS_SCHEMA.$defs?.Category?.enum ?? []) as string[]).entries()) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: `saengine.library.addMaterial.${category}`,
				title: localize2('lib.addMatVariant', "Add {0}", humanize(category)),
				icon: Codicon.add,
				menu: { id: LibraryAddMaterialSubmenu, group: '1_variants', order: index + 1 },
			});
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			(await activeLibraryEditor(accessor, 'materials'))?.addByVariant(category);
		}
	});
}

const LibraryAddObjectSubmenu = MenuId.for('saengine.ribbon.library.addObject');
registerRibbonItemHint(LibraryAddObjectSubmenu.id, { size: 'large' }, RibbonMenus.Library);
MenuRegistry.appendMenuItem(RibbonMenus.Library, {
	submenu: LibraryAddObjectSubmenu,
	title: localize2('rib.lib.addObjectSub', "Add Object Type"),
	icon: Codicon.add,
	group: '3_AddObject',
	order: 1,
});
for (const [index, kind] of ((OBJECTS_SCHEMA.$defs?.Kind?.enum ?? []) as string[]).entries()) {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: `saengine.library.addObject.${kind}`,
				title: localize2('lib.addObjVariant', "Add {0}", humanize(kind)),
				icon: Codicon.add,
				menu: { id: LibraryAddObjectSubmenu, group: '1_variants', order: index + 1 },
			});
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			(await activeLibraryEditor(accessor, 'objects'))?.addByVariant(kind);
		}
	});
}

registerRibbonItemHint('saengine.library.cmd.duplicate', { size: 'small' }, RibbonMenus.Library);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.library.cmd.duplicate',
			title: localize2('rib.lib.duplicate', "Duplicate"),
			icon: Codicon.copy,
			menu: { id: RibbonMenus.Library, group: '1_Switch', order: 3 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		(await activeLibraryEditor(accessor))?.duplicateSelected();
	}
});

registerRibbonItemHint('saengine.library.cmd.delete', { size: 'small' }, RibbonMenus.Library);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.library.cmd.delete',
			title: localize2('rib.lib.delete', "Delete"),
			icon: Codicon.trash,
			menu: { id: RibbonMenus.Library, group: '1_Switch', order: 4 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeLibraryEditor(accessor))?.deleteSelected();
	}
});

registerRibbonItemHint('saengine.library.cmd.stiffnessModifiers', { size: 'small' }, RibbonMenus.Library);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.library.cmd.stiffnessModifiers',
			title: localize2('rib.lib.stiffness', "Stiffness Modifiers"),
			icon: Codicon.settings,
			menu: { id: RibbonMenus.Library, group: '4_Sections', order: 2 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		(await activeLibraryEditor(accessor, 'objects'))?.focusStiffnessModifiers();
	}
});

registerRibbonItemHint('saengine.library.cmd.import', { size: 'small' }, RibbonMenus.Library);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.library.cmd.import',
			title: localize2('rib.lib.import', "Import JSON..."),
			icon: Codicon.cloudDownload,
			menu: { id: RibbonMenus.Library, group: '5_Exchange', order: 1 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeLibraryEditor(accessor))?.importLibrary();
	}
});

registerRibbonItemHint('saengine.library.cmd.export', { size: 'small' }, RibbonMenus.Library);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.library.cmd.export',
			title: localize2('rib.lib.export', "Export JSON..."),
			icon: Codicon.export,
			menu: { id: RibbonMenus.Library, group: '5_Exchange', order: 2 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeLibraryEditor(accessor))?.exportLibrary();
	}
});

// BIM 3D View: Rebuild, Fit, Section Box/Planes, Measure, Hide/Isolate, Studies, IFC Export
registerRibbonItemHint('saengine.bim.cmd.rebuild', { size: 'large' }, RibbonMenus.Bim3D);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.bim.cmd.rebuild',
			title: localize2('rib.bim.rebuild', "Rebuild BIM"),
			icon: Codicon.refresh,
			menu: { id: RibbonMenus.Bim3D, group: '1_Section', order: 1 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeBuildingEditor(accessor))?.rebuild();
	}
});

registerRibbonItemHint('saengine.bim.cmd.fit', { size: 'small' }, RibbonMenus.Bim3D);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.bim.cmd.fit',
			title: localize2('rib.bim.fit', "Zoom to Fit"),
			icon: Codicon.screenFull,
			menu: { id: RibbonMenus.Bim3D, group: '1_Section', order: 2 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeBuildingEditor(accessor))?.fitView();
	}
});

const Bim3DSectionSubmenu = MenuId.for('saengine.ribbon.bim3d.section');
registerRibbonItemHint(Bim3DSectionSubmenu.id, { size: 'large', primaryCommandId: 'saengine.bim.section.toggle' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	submenu: Bim3DSectionSubmenu,
	title: localize2('rib.bim.sectionSub', "Section Box"),
	icon: Codicon.symbolMisc,
	group: '1_Section',
	order: 3,
	isSplitButton: true,
});
for (const [order, id, label, run] of [
	[1, 'saengine.bim.section.toggle', localize2('rib.bim.secToggle', "Toggle Section Box"), (p: BuildingEditor) => p.viewerTools?.toggleSectionBox()],
	[2, 'saengine.bim.section.fromSel', localize2('rib.bim.secFromSel', "Section Box from Selection"), (p: BuildingEditor) => p.viewerTools?.sectionBoxFromSelection()],
	[3, 'saengine.bim.section.bounds', localize2('rib.bim.secBounds', "Section Box Bounds..."), (p: BuildingEditor) => p.viewerTools?.toggleSectionBoundsPanel()],
	[4, 'saengine.bim.section.reset', localize2('rib.bim.secReset', "Reset Section Box"), (p: BuildingEditor) => p.viewerTools?.resetSectionBox()],
	[5, 'saengine.bim.section.planeX', localize2('rib.bim.secPlaneX', "Add Section Plane: X"), (p: BuildingEditor) => p.viewerTools?.addAxisPlane('x')],
	[6, 'saengine.bim.section.planeY', localize2('rib.bim.secPlaneY', "Add Section Plane: Y"), (p: BuildingEditor) => p.viewerTools?.addAxisPlane('y')],
	[7, 'saengine.bim.section.planeZ', localize2('rib.bim.secPlaneZ', "Add Section Plane: Z"), (p: BuildingEditor) => p.viewerTools?.addAxisPlane('z')],
	[8, 'saengine.bim.section.planeFace', localize2('rib.bim.secPlaneFace', "Section Plane from Face..."), (p: BuildingEditor) => p.viewerTools?.togglePlanePickMode()],
	[9, 'saengine.bim.section.clearPlanes', localize2('rib.bim.secClear', "Clear Section Planes"), (p: BuildingEditor) => p.viewerTools?.clearSectionPlanes()],
] as const) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title: label, icon: Codicon.symbolMisc, menu: { id: Bim3DSectionSubmenu, group: '1_section', order } });
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			const pane = await activeBuildingEditor(accessor);
			if (pane) {
				await run(pane);
			}
		}
	});
}

const Bim3DMeasureSubmenu = MenuId.for('saengine.ribbon.bim3d.measure');
registerRibbonItemHint(Bim3DMeasureSubmenu.id, { size: 'large', primaryCommandId: 'saengine.bim.measure.toggle' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	submenu: Bim3DMeasureSubmenu,
	title: localize2('rib.bim.measureSub', "Measure"),
	icon: Codicon.symbolRuler,
	group: '2_Measure',
	order: 1,
	isSplitButton: true,
});
for (const [order, id, label, run] of [
	[1, 'saengine.bim.measure.toggle', localize2('rib.bim.measToggle', "Measure Tool"), (p: BuildingEditor) => p.viewerTools?.toggleMeasurePanel()],
	[2, 'saengine.bim.measure.distance', localize2('rib.bim.measDist', "Point-to-Point Distance"), (p: BuildingEditor) => p.viewerTools?.selectMeasureMode('distance')],
	[3, 'saengine.bim.measure.chain', localize2('rib.bim.measChain', "Chain Distance"), (p: BuildingEditor) => p.viewerTools?.selectMeasureMode('chain')],
	[4, 'saengine.bim.measure.pointToFace', localize2('rib.bim.measP2F', "Point to Face (Perpendicular)"), (p: BuildingEditor) => p.viewerTools?.selectMeasureMode('pointToFace')],
	[5, 'saengine.bim.measure.edgeAngle', localize2('rib.bim.measAngle', "Angle Between Two Edges"), (p: BuildingEditor) => p.viewerTools?.selectMeasureMode('edgeAngle')],
	[6, 'saengine.bim.measure.clear', localize2('rib.bim.measClear', "Clear Measurements"), (p: BuildingEditor) => p.viewerTools?.clearMeasurements()],
] as const) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title: label, icon: Codicon.symbolRuler, menu: { id: Bim3DMeasureSubmenu, group: '1_measure', order } });
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			const pane = await activeBuildingEditor(accessor);
			if (pane) {
				await run(pane);
			}
		}
	});
}

const Bim3DVisibilitySubmenu = MenuId.for('saengine.ribbon.bim3d.visibility');
registerRibbonItemHint(Bim3DVisibilitySubmenu.id, { size: 'large' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	submenu: Bim3DVisibilitySubmenu,
	title: localize2('rib.bim.visSub', "Hide / Isolate"),
	icon: Codicon.eyeClosed,
	group: '3_Visibility',
	order: 1,
});
for (const [order, id, label, run] of [
	[1, 'saengine.bim.vis.hh', localize2('rib.bim.visHh', "Hide Element (HH)"), (p: BuildingEditor) => p.viewerTools?.hideTemp()],
	[2, 'saengine.bim.vis.hi', localize2('rib.bim.visHi', "Isolate Element (HI)"), (p: BuildingEditor) => p.viewerTools?.isolateTemp()],
	[3, 'saengine.bim.vis.hc', localize2('rib.bim.vis.hc', "Hide Category (HC)"), (p: BuildingEditor) => p.viewerTools?.hideCategoryTemp()],
	[4, 'saengine.bim.vis.ic', localize2('rib.bim.visIc', "Isolate Category (IC)"), (p: BuildingEditor) => p.viewerTools?.isolateCategoryTemp()],
	[5, 'saengine.bim.vis.hr', localize2('rib.bim.visHr', "Reset Temporary Hide/Isolate (HR)"), (p: BuildingEditor) => p.viewerTools?.resetTemp()],
	[6, 'saengine.bim.vis.hidePerm', localize2('rib.bim.visHidePerm', "Hide Permanently"), (p: BuildingEditor) => p.viewerTools?.hidePermanent()],
	[7, 'saengine.bim.vis.unhideSel', localize2('rib.bim.visUnhideSel', "Unhide Selected"), (p: BuildingEditor) => p.viewerTools?.unhideSelected()],
	[8, 'saengine.bim.vis.unhideAll', localize2('rib.bim.visUnhideAll', "Unhide All"), (p: BuildingEditor) => p.viewerTools?.unhideAll()],
	[9, 'saengine.bim.vis.applyPerm', localize2('rib.bim.visApplyPerm', "Apply Temporary Hide Permanently"), (p: BuildingEditor) => p.viewerTools?.applyTempPermanent()],
] as const) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id, title: label, icon: Codicon.eyeClosed, menu: { id: Bim3DVisibilitySubmenu, group: '1_vis', order } });
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			const pane = await activeBuildingEditor(accessor);
			if (pane) {
				await run(pane);
			}
		}
	});
}

registerRibbonItemHint('saengine.bim.vis.reveal', { size: 'small' }, RibbonMenus.Bim3D);
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.bim.vis.reveal',
			title: localize2('rib.bim.reveal', "Reveal Hidden"),
			icon: Codicon.lightbulb,
			menu: { id: RibbonMenus.Bim3D, group: '3_Visibility', order: 2 },
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeBuildingEditor(accessor))?.viewerTools?.toggleRevealHidden();
	}
});

const Bim3DRenderSubmenu = MenuId.for('saengine.ribbon.bim3d.render');
registerRibbonItemHint(Bim3DRenderSubmenu.id, { size: 'large' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	submenu: Bim3DRenderSubmenu,
	title: localize2('rib.bim.renderSub', "Render Preset"),
	icon: Codicon.colorMode,
	group: '4_RenderAndStudies',
	order: 1,
});
for (const [order, preset, label] of [
	[1, 'standard', localize2('rib.bim.presetStd', "Standard")],
	[2, 'daylight', localize2('rib.bim.presetDaylight', "Daylight (Sun & Shadows)")],
	[3, 'overcast', localize2('rib.bim.presetOvercast', "Overcast")],
	[4, 'dusk', localize2('rib.bim.presetDusk', "Dusk")],
	[5, 'clay', localize2('rib.bim.presetClay', "Clay Model")],
] as readonly [number, RenderPreset, ReturnType<typeof localize2>][]) {
	registerAction2(class extends Action2 {
		constructor() {
			super({ id: `saengine.bim.study.render.${preset}`, title: label, icon: Codicon.colorMode, menu: { id: Bim3DRenderSubmenu, group: '1_presets', order } });
		}
		async run(accessor: ServicesAccessor): Promise<void> {
			await (await activeBuildingEditor(accessor))?.bimStudies?.setRenderPreset(preset);
		}
	});
}

registerBuildingStudyCommand('saengine.bim.study.walk', localize2('rib.bim.walk', "Walk Mode"), Codicon.compass, '4_RenderAndStudies', 2, 'small', s => s.toggleWalkMode());
registerBuildingStudyCommand('saengine.bim.study.still', localize2('rib.bim.still', "Export Still..."), Codicon.deviceCamera, '4_RenderAndStudies', 3, 'small', s => s.exportStill());
registerBuildingStudyCommand('saengine.bim.study.sun', localize2('rib.bim.sun', "Sun at Noon"), Codicon.lightbulb, '4_RenderAndStudies', 4, 'small', s => s.sunAtNoon());
registerBuildingStudyCommand('saengine.bim.study.4d', localize2('rib.bim.4d', "4D Playback"), Codicon.calendar, '4_RenderAndStudies', 5, 'large', s => s.toggle4d());
registerBuildingStudyCommand('saengine.bim.study.terrain', localize2('rib.bim.terrain', "Show Terrain"), Codicon.globe, '4_RenderAndStudies', 6, 'small', s => s.toggleTerrain());
registerBuildingStudyCommand('saengine.bim.study.phases', localize2('rib.bim.phases', "Filter Phase..."), Codicon.layers, '4_RenderAndStudies', 7, 'small', s => s.pickPhase());

registerRibbonItemHint('saengine.bim.exportIfc', { size: 'large' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	command: { id: 'saengine.bim.exportIfc', title: localize2('rib.bim.exportIfc', "Export IFC"), icon: Codicon.export },
	group: '5_Export',
	order: 1,
});
registerRibbonItemHint('saengine.bim.exportIfcOptions', { size: 'small' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	command: { id: 'saengine.bim.exportIfcOptions', title: localize2('rib.bim.exportIfcOpts', "Export IFC Options..."), icon: Codicon.layers },
	group: '5_Export',
	order: 2,
});
registerRibbonItemHint('saengine.bim.compareIfc', { size: 'small' }, RibbonMenus.Bim3D);
MenuRegistry.appendMenuItem(RibbonMenus.Bim3D, {
	command: { id: 'saengine.bim.compareIfc', title: localize2('rib.bim.compareIfc', "Compare IFC..."), icon: Codicon.diff },
	group: '5_Export',
	order: 3,
});
