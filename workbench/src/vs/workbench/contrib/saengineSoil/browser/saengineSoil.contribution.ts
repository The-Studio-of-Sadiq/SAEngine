/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ThemeIcon } from '../../../../base/common/themables.js';
import './soilDataPanels.contribution.js';
import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { OPEN_PLANNED_FEATURE_COMMAND } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { SoilEditor } from './soilEditor.js';
import { SITE_RESPONSE_FEATURE } from './soilStrata.js';
import { SoilEditorInput, SoilEditorInputSerializer } from './soilEditorInput.js';
import { SOIL_ADD_BOREHOLE_COMMAND, SOIL_IMPORT_FILE_COMMAND, SOIL_SAVE_TEMPLATE_COMMAND } from './soilDocument.js';
import { defaultCodeName } from '../../../services/saengineProject/common/activeCodePack.js';
import { registerPartEditor } from '../../saengineProject/browser/projectParts.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SoilEditor, SoilEditor.ID, localize('soilEditorPane', "SAEngine Soil Report")),
	[new SyncDescriptor(SoilEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(SoilEditorInput.ID, SoilEditorInputSerializer);

/** Opens the project's `01 Soil Report/soil-report.json` in the soil report editor. */
class SoilEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.soilEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('soil');
		if (!part?.mainFile) {
			return;
		}
		this._register(registerPartEditor(part.id, SoilEditor.ID));
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: SoilEditor.ID,
				label: localize('soilEditor.label', "Soil Report"),
				detail: localize('soilEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isSoilReport(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(SoilEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isSoilReport(resource: URI): boolean {
		const part = partById('soil');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(SoilEditorResolverContribution.ID, SoilEditorResolverContribution, WorkbenchPhase.BlockStartup);

/**
 * Ctrl+Z / Ctrl+Y in the soil report editor undo the file's text edits, wherever the keyboard
 * is in it (the list, a grid, a button), and say what was undone; inside a text field the
 * field's own undo still applies.
 */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	if (!(pane instanceof SoilEditor) || !pane.resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	return pane.undoRedo(redo);
}

UndoCommand.addImplementation(110, 'saengine-soil', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-soil', accessor => undoRedo(accessor, true));

/** The soil report editor, opened on the project's report if it is not the active editor. */
async function soilEditor(accessor: ServicesAccessor): Promise<SoilEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	const project = accessor.get(ISaengineProjectService).project;
	if (editorService.activeEditorPane instanceof SoilEditor) {
		return editorService.activeEditorPane;
	}
	const part = partById('soil');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof SoilEditor ? pane : undefined;
}

/** A file argument: a URI, or a file system path (scripts and tests pass one to skip the dialog). */
function fileArgument(file: URI | string | undefined): URI | undefined {
	return typeof file === 'string' ? URI.file(file) : URI.isUri(file) ? file : undefined;
}

const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_IMPORT_FILE_COMMAND,
			title: localize2('saengine.soil.importFile', "Import Boreholes from CSV, Excel, AGS4 or DIGGS..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.cloudDownload,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor, file?: URI | string): Promise<void> {
		const target = fileArgument(file);
		await (await soilEditor(accessor))?.importFile(target);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_SAVE_TEMPLATE_COMMAND,
			title: localize2('saengine.soil.saveTemplate', "Save Borehole Template..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.notebookTemplate,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor, file?: URI | string): Promise<void> {
		const target = fileArgument(file);
		await (await soilEditor(accessor))?.saveTemplate(target);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SOIL_ADD_BOREHOLE_COMMAND,
			title: localize2('saengine.soil.addBorehole', "Add Borehole to the Soil Report"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.add,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		(await soilEditor(accessor))?.addBorehole();
	}
});

function registerSoilRibbonCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: ThemeIcon,
	runWithEditor: (editor: SoilEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.category', "SAEngine"),
				icon,
				f1: true,
				precondition: projectOpen,
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await soilEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

registerSoilRibbonCommand('saengine.soil.editBorehole', localize2('soil.rib.editTitle', "Edit Borehole"), Codicon.edit, e => e.editBorehole());
registerSoilRibbonCommand('saengine.soil.duplicateBorehole', localize2('soil.rib.dupTitle', "Duplicate Borehole"), Codicon.copy, e => e.duplicateBorehole());
registerSoilRibbonCommand('saengine.soil.deleteBorehole', localize2('soil.rib.delTitle', "Delete Borehole"), Codicon.trash, e => e.deleteBorehole());
registerSoilRibbonCommand('saengine.soil.toggleExcludeBearing', localize2('soil.rib.excludeTitle', "Leave Borehole Out of Site Bearing Table"), Codicon.circleSlash, e => e.toggleExcludeFromSite());

registerSoilRibbonCommand('saengine.soil.viewLog', localize2('soil.rib.logTitle', "Soil View: Log"), Codicon.layers, e => e.showView('log'));
registerSoilRibbonCommand('saengine.soil.viewResults', localize2('soil.rib.resTitle', "Soil View: Results"), Codicon.graphLine, e => e.showView('results'));
registerSoilRibbonCommand('saengine.soil.viewStrata', localize2('soil.rib.strataTitle', "Soil View: Strata"), Codicon.symbolStructure, e => e.showView('strata'));
registerSoilRibbonCommand('saengine.soil.viewMap', localize2('soil.rib.mapTitle', "Soil View: Map"), Codicon.globe, e => e.showView('map'));
registerSoilRibbonCommand('saengine.soil.viewStrata3d', localize2('soil.rib.strata3dTitle', "Soil View: 3D Strata"), Codicon.symbolNamespace, e => e.showStrata3d());
registerSoilRibbonCommand('saengine.soil.toggleFence', localize2('soil.rib.fenceTitle', "Show All Boreholes Side by Side"), Codicon.splitHorizontal, e => e.toggleFence());

registerSoilRibbonCommand('saengine.soil.editSpt', localize2('soil.rib.sptTitle', "Edit Borehole SPT & Samples"), Codicon.listFlat, e => e.editBorehole('tests'));
registerSoilRibbonCommand('saengine.soil.editLabTests', localize2('soil.rib.labTitle', "Edit Sample Lab Tests"), Codicon.beaker, e => e.editLabTests());
registerSoilRibbonCommand('saengine.soil.bearingOverride', localize2('soil.rib.bearingTitle', "Allowable Bearing Pressure Override..."), Codicon.symbolNumeric, e => e.editBearingOverride());
registerSoilRibbonCommand('saengine.soil.recompute', localize2('soil.rib.recomputeTitle', "Recompute Soil Results"), Codicon.refresh, e => e.compute());

registerSoilRibbonCommand('saengine.soil.exportAgs4', localize2('soil.rib.agsTitle', "Export Boreholes as AGS4..."), Codicon.cloudUpload, async e => { await e.exportFile(undefined, 'ags'); });
registerSoilRibbonCommand('saengine.soil.exportDiggs', localize2('soil.rib.diggsTitle', "Export Boreholes as DIGGS..."), Codicon.fileCode, async e => { await e.exportFile(undefined, 'diggs'); });
registerSoilRibbonCommand('saengine.soil.exportGeoJson', localize2('soil.rib.geojsonTitle', "Export Site & Boreholes as GeoJSON..."), Codicon.globe, async e => { await e.exportGis('geojson'); });
registerSoilRibbonCommand('saengine.soil.exportGeoPackage', localize2('soil.rib.gpkgTitle', "Export Site & Boreholes as GeoPackage..."), Codicon.package, async e => { await e.exportGis('gpkg'); });
registerSoilRibbonCommand('saengine.soil.importGis', localize2('soil.rib.impGisTitle', "Import Boreholes from GeoJSON / GeoPackage..."), Codicon.cloudDownload, e => e.importGis());
registerSoilRibbonCommand('saengine.soil.openInQgis', localize2('soil.rib.qgisTitle', "Open Soil Map in QGIS"), Codicon.linkExternal, e => e.openInQgis());

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.soil.siteResponse',
			title: localize2('soil.planned.siteResponseTitle', "1D Site Response Spectra"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.pulse,
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand(OPEN_PLANNED_FEATURE_COMMAND, SITE_RESPONSE_FEATURE);
	}
});

// 1D site response is planned (not in this MVP): the code pack asks for a site-specific study for
// site classes S1 and S2 (it gives no spectrum for them; SE has its own) but gives no method.
registerPlannedFeature({
	id: SITE_RESPONSE_FEATURE,
	part: 'soil',
	title: localize('soil.planned.siteResponse', "1D Site Response"),
	summary: localize('soil.planned.siteResponseSummary', "An equivalent-linear 1D site response of the soil column under the building, whose surface spectrum feeds the response spectrum analysis for site classes S1 and S2, which the code gives no spectrum for (SE has its own). Until then SAEngine warns and keeps an assumed class."),
	steps: [
		localize('soil.planned.siteResponse1', "Build the soil column from the 3D stratigraphy at the building: thickness, unit weight and shear wave velocity of each unit."),
		localize('soil.planned.siteResponse2', "Pick the modulus reduction and damping curves of each unit and the rock outcrop motions."),
		localize('soil.planned.siteResponse3', "Run the equivalent-linear analysis and take the mean surface spectrum."),
		localize('soil.planned.siteResponse4', "Hand the site-specific spectrum to the response spectrum analysis of 08 FEM."),
	],
	inputs: [
		{ label: localize('soil.planned.vs', "Shear wave velocity per unit"), unit: 'm/s', example: '180' },
		{ label: localize('soil.planned.curves', "Modulus reduction and damping curves"), example: localize('soil.planned.curvesExample', "by plasticity index") },
		{ label: localize('soil.planned.motions', "Input motions (rock outcrop)"), example: '7' },
	],
	outputs: [
		localize('soil.planned.out1', "Surface response spectrum and amplification against period"),
		localize('soil.planned.out2', "Peak shear strain and acceleration profiles"),
	],
	references: [`${defaultCodeName()} Part 6 Chapter 2, Table 6.2.13 (site classes SE, S1, S2)`, 'ASCE 7-16 Chapter 21 (site response analysis)'],
});
