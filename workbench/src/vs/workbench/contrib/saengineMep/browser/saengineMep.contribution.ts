/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './mepDataPanels.contribution.js';
import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { MepEditor } from './mepEditor.js';
import { MepEditorInput, MepEditorInputSerializer } from './mepEditorInput.js';

/** Opens the MEP editor and asks the backend for the sleeves the MEP IFC models' clashes need. */
export const MEP_SUGGEST_SLEEVES_EDITOR_COMMAND = 'saengine.mep.editor.suggestSleeves';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(MepEditor, MepEditor.ID, localize('mepEditorPane', "SAEngine MEP")),
	[new SyncDescriptor(MepEditorInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(MepEditorInput.ID, MepEditorInputSerializer);

/** Opens the project's `07 MEP/mep.json` in the MEP editor. */
class MepEditorResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.mepEditorResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		const part = partById('mep');
		if (!part?.mainFile) {
			return;
		}
		this._register(editorResolverService.registerEditor(
			`**/${part.folder}/${part.mainFile}`,
			{
				id: MepEditor.ID,
				label: localize('mepEditor.label', "MEP"),
				detail: localize('mepEditor.detail', "SAEngine"),
				// Default rather than exclusive, so "Reopen Editor With..." can still open the JSON.
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isMep(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(MepEditorInput, resource),
					options,
				}),
			}
		));
	}

	private isMep(resource: URI): boolean {
		const part = partById('mep');
		// Project detection is asynchronous; until it finishes, match by the workspace folder.
		const root = this.projectService.project?.root ?? this.contextService.getWorkspaceFolder(resource)?.uri;
		return !!root && !!part?.mainFile && isEqual(resource, joinPath(root, part.folder, part.mainFile));
	}
}

registerWorkbenchContribution2(MepEditorResolverContribution.ID, MepEditorResolverContribution, WorkbenchPhase.BlockStartup);

/** Ctrl+Z / Ctrl+Y in the MEP editor undo the file's text edits; inside a text field the field's own undo still applies. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof MepEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

UndoCommand.addImplementation(110, 'saengine-mep', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-mep', accessor => undoRedo(accessor, true));

async function activeMepEditor(accessor: ServicesAccessor): Promise<MepEditor | undefined> {
	const editorService = accessor.get(IEditorService);
	if (editorService.activeEditorPane instanceof MepEditor) {
		return editorService.activeEditorPane;
	}
	const project = accessor.get(ISaengineProjectService).project;
	const part = partById('mep');
	if (!project || !part?.mainFile) {
		return undefined;
	}
	const pane = await editorService.openEditor({ resource: joinPath(project.root, part.folder, part.mainFile), options: { pinned: true } });
	return pane instanceof MepEditor ? pane : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: MEP_SUGGEST_SLEEVES_EDITOR_COMMAND,
			title: localize2('saengine.mep.suggestSleevesTitle', "Suggest Sleeves from the MEP Clashes"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.wand,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeMepEditor(accessor))?.suggestSleeves();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.mep.editor.importIfc',
			title: localize2('saengine.mep.importIfcTitle', "Import MEP IFC Model..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.cloudDownload,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await (await activeMepEditor(accessor))?.importIfc();
	}
});

function registerMepRibbonCommand(
	id: string,
	title: ReturnType<typeof localize2>,
	icon: ThemeIcon,
	runWithEditor: (editor: MepEditor) => Promise<void> | void,
): void {
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title,
				category: localize2('saengine.category', "SAEngine"),
				icon,
				f1: true,
				precondition: ContextKeyExpr.has('saengineProjectOpen'),
			});
		}

		override async run(accessor: ServicesAccessor): Promise<void> {
			const editor = await activeMepEditor(accessor);
			if (editor) {
				await runWithEditor(editor);
			}
		}
	});
}

registerMepRibbonCommand('saengine.mep.editor.addShaft', localize2('mep.rib.shaftTitle', "Add MEP Shaft"), Codicon.layers, e => e.addShaft());
registerMepRibbonCommand('saengine.mep.editor.sizeTanks', localize2('mep.rib.sizeTanksTitle', "Size Plumbing Tanks"), Codicon.wand, e => e.sizeTanks());
registerMepRibbonCommand('saengine.mep.editor.addDrain', localize2('mep.rib.addDrainTitle', "Add Roof Drain"), Codicon.arrowCircleDown, e => e.addDrain());
registerMepRibbonCommand('saengine.mep.editor.riserSleeves', localize2('mep.rib.riserSleevesTitle', "Add Sleeves for Plumbing Risers"), Codicon.circleLargeOutline, e => e.addRiserSleeves());
registerMepRibbonCommand('saengine.mep.editor.proposePlant', localize2('mep.rib.proposePlantTitle', "Propose HVAC Plant"), Codicon.wand, e => e.proposePlant());
registerMepRibbonCommand('saengine.mep.editor.calculateLoads', localize2('mep.rib.calcLoadsTitle', "Calculate HVAC Loads"), Codicon.play, e => e.calculateLoads());
registerMepRibbonCommand('saengine.mep.editor.proposeEquipment', localize2('mep.rib.proposeElecTitle', "Propose Electrical Equipment"), Codicon.wand, e => e.proposeEquipment());
registerMepRibbonCommand('saengine.mep.editor.proposeFire', localize2('mep.rib.proposeFireTitle', "Propose Fire Pumps and Tank"), Codicon.wand, e => e.proposeFire());
