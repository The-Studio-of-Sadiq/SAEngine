/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { getActiveElement, isEditableElement } from '../../../../base/browser/dom.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { extUri, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { RedoCommand, UndoCommand } from '../../../../editor/browser/editorExtensions.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IUndoRedoService } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IEditorResolverService, RegisteredEditorPriority } from '../../../services/editor/common/editorResolverService.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { SectionDesignerEditor } from './sectionDesignerEditor.js';
import { SectionDesignerInput, SectionDesignerInputSerializer } from './sectionDesignerInput.js';
import { newSection, SECTIONS_FOLDER, serializeSection } from './sectionDesignerModel.js';

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(SectionDesignerEditor, SectionDesignerEditor.ID, localize('sectionDesignerPane', "SAEngine Section Designer")),
	[new SyncDescriptor(SectionDesignerInput)]
);

Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(SectionDesignerInput.ID, SectionDesignerInputSerializer);

/** Opens `04 Objects/sections/*.json` of the project in the Section Designer by default. */
class SectionDesignerResolverContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.sectionDesignerResolver';

	constructor(
		@IEditorResolverService editorResolverService: IEditorResolverService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IInstantiationService instantiationService: IInstantiationService,
	) {
		super();
		this._register(editorResolverService.registerEditor(
			`**/${SECTIONS_FOLDER}/*.json`,
			{
				id: SectionDesignerEditor.ID,
				label: localize('sectionDesigner.label', "Section Designer"),
				detail: localize('sectionDesigner.detail', "SAEngine"),
				priority: RegisteredEditorPriority.default,
			},
			{
				singlePerResource: true,
				canSupportResource: resource => this.isSection(resource),
			},
			{
				createEditorInput: ({ resource, options }) => ({
					editor: instantiationService.createInstance(SectionDesignerInput, resource),
					options,
				}),
			}
		));
	}

	private isSection(resource: URI): boolean {
		const root = this.projectService.project?.root;
		// Without a detected project yet, any sections folder of an "04 Objects" folder qualifies.
		return root ? extUri.isEqualOrParent(resource, joinPath(root, SECTIONS_FOLDER)) : /[\\/]04 Objects[\\/]sections[\\/][^\\/]+\.json$/i.test(resource.path);
	}
}

registerWorkbenchContribution2(SectionDesignerResolverContribution.ID, SectionDesignerResolverContribution, WorkbenchPhase.BlockStartup);

/** Ctrl+Z / Ctrl+Y in the Section Designer undo the file's edits; inside a text field the field's own undo applies. */
function undoRedo(accessor: ServicesAccessor, redo: boolean): boolean | Promise<void> {
	const pane = accessor.get(IEditorService).activeEditorPane;
	const resource = pane instanceof SectionDesignerEditor ? pane.resource : undefined;
	if (!resource || isEditableElement(getActiveElement() as HTMLElement)) {
		return false;
	}
	const undoRedoService = accessor.get(IUndoRedoService);
	return Promise.resolve(redo ? undoRedoService.redo(resource) : undoRedoService.undo(resource));
}

UndoCommand.addImplementation(110, 'saengine-section-designer', accessor => undoRedo(accessor, false));
RedoCommand.addImplementation(110, 'saengine-section-designer', accessor => undoRedo(accessor, true));

export const NEW_SECTION_COMMAND = 'saengine.section.new';

/** A section id: letters, digits, `.`, `_` and `-` (the object types' id rule). */
export function validSectionId(value: string): boolean {
	return /^[A-Za-z0-9._-]{1,64}$/.test(value);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: NEW_SECTION_COMMAND,
			title: localize2('saengine.section.new', "New Designed Section..."),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.symbolRuler,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override async run(accessor: ServicesAccessor, id?: string): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const fileService = accessor.get(IFileService);
		const editorService = accessor.get(IEditorService);
		if (!project) {
			return;
		}
		const folder = joinPath(project.root, SECTIONS_FOLDER);
		const sectionId = id ?? await accessor.get(IQuickInputService).input({
			title: localize('section.new.title', "New Designed Section"),
			prompt: localize('section.new.prompt', "Id of the section (letters, digits, '.', '_', '-'); object types refer to it."),
			value: 'SD1',
			validateInput: async value => {
				if (!validSectionId(value)) {
					return localize('section.new.invalid', "Use letters, digits, '.', '_' or '-'.");
				}
				return await fileService.exists(joinPath(folder, `${value}.json`)) ? localize('section.new.exists', "A section with this id exists.") : undefined;
			},
		});
		if (!sectionId || !validSectionId(sectionId)) {
			return;
		}
		const resource = joinPath(folder, `${sectionId}.json`);
		if (!await fileService.exists(resource)) {
			const { concrete, rebar } = await defaultMaterials(fileService, project.root);
			await fileService.writeFile(resource, VSBuffer.fromString(serializeSection(newSection(sectionId, concrete, rebar))));
		}
		await editorService.openEditor({ resource, options: { pinned: true } });
	}
});

/** The first concrete and rebar materials of the project (03 Materials), else BNBC defaults. */
async function defaultMaterials(fileService: IFileService, root: URI): Promise<{ concrete: string; rebar: string }> {
	let concrete = 'C27.6', rebar = 'B420DWR';
	try {
		const data = JSON.parse((await fileService.readFile(joinPath(root, '03 Materials', 'materials.json'))).value.toString());
		const materials: { id: string; category: string }[] = Array.isArray(data?.materials) ? data.materials : [];
		concrete = materials.find(m => m.category === 'concrete')?.id ?? concrete;
		rebar = materials.find(m => m.category === 'rebar')?.id ?? rebar;
	} catch {
		// No materials file: the defaults.
	}
	return { concrete, rebar };
}
