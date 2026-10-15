/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { IReference } from '../../../../base/common/lifecycle.js';
import { isEqual } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, GroupIdentifier, IEditorDescriptor, IEditorPane, IEditorSerializer, IRevertOptions, ISaveOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';

export type LibraryKind = 'materials' | 'objects' | 'settings' | 'floorPlan' | 'structure' | 'bim';

const materialsIcon = registerIcon('saengine-materials-editor-icon', Codicon.symbolColor, localize('materialsEditorIcon', "Icon of the materials editor."));
const objectsIcon = registerIcon('saengine-objects-editor-icon', Codicon.symbolStructure, localize('objectsEditorIcon', "Icon of the object types editor."));
const settingsIcon = registerIcon('saengine-settings-editor-icon', Codicon.settingsGear, localize('settingsEditorIcon', "Icon of the project settings editor."));
const gridsIcon = registerIcon('saengine-grids-editor-icon', Codicon.table, localize('gridsEditorIcon', "Icon of the grids and stories editor."));
const structureIcon = registerIcon('saengine-structure-editor-icon', Codicon.symbolStructure, localize('structureEditorIcon', "Icon of the structural model editor."));
const buildingIcon = registerIcon('saengine-building-editor-icon', Codicon.layers, localize('buildingEditorIcon', "Icon of the building model editor."));

/**
 * A SAEngine project file (`materials.json`, `objects.json`, `floor-plan.json`, `bim.json`) opened in its visual editor.
 * The JSON text model stays the document: dirty state, save, revert, backups and undo come
 * from the text file service, exactly as for a text editor on the same file.
 */
export class LibraryEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.library';
	static readonly EDITOR_ID = 'workbench.editor.saengine.library';
	static readonly BUILDING_EDITOR_ID = 'workbench.editor.saengine.building';
	static readonly GRIDS_EDITOR_ID = 'workbench.editor.saengine.grids';
	static readonly SETTINGS_EDITOR_ID = 'workbench.editor.saengine.settings';
	static readonly STRUCTURE_EDITOR_ID = 'workbench.editor.saengine.structure';

	private modelReference: Promise<IReference<IResolvedTextEditorModel>> | undefined;

	constructor(
		readonly resource: URI,
		readonly kind: LibraryKind,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
	) {
		super();
		this._register(this.textFileService.files.onDidChangeDirty(model => {
			if (isEqual(model.resource, this.resource)) {
				this._onDidChangeDirty.fire();
			}
		}));
	}

	override get typeId(): string {
		return LibraryEditorInput.ID;
	}

	override get editorId(): string {
		switch (this.kind) {
			case 'bim': return LibraryEditorInput.BUILDING_EDITOR_ID;
			case 'floorPlan': return LibraryEditorInput.GRIDS_EDITOR_ID;
			case 'settings': return LibraryEditorInput.SETTINGS_EDITOR_ID;
			case 'structure': return LibraryEditorInput.STRUCTURE_EDITOR_ID;
			default: return LibraryEditorInput.EDITOR_ID;
		}
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		switch (this.kind) {
			case 'materials': return localize('materialsEditor', "Materials");
			case 'objects': return localize('objectsEditor', "Object Types");
			case 'settings': return localize('settingsEditor', "Project Settings");
			case 'floorPlan': return localize('gridsEditor', "Grids & Stories");
			case 'bim': return localize('buildingEditor', "Building Model");
			case 'structure': return localize('structureEditor', "Structural Model");
		}
	}

	override getIcon(): ThemeIcon {
		switch (this.kind) {
			case 'materials': return materialsIcon;
			case 'objects': return objectsIcon;
			case 'settings': return settingsIcon;
			case 'floorPlan': return gridsIcon;
			case 'bim': return buildingIcon;
			case 'structure': return structureIcon;
		}
	}

	/** The shared text model of the file; released when the input is disposed. */
	override resolve(): Promise<IReference<IResolvedTextEditorModel>> {
		if (!this.modelReference) {
			this.modelReference = this.textModelService.createModelReference(this.resource);
			this.modelReference.catch(() => this.modelReference = undefined);
		}
		return this.modelReference;
	}

	override isDirty(): boolean {
		return this.textFileService.isDirty(this.resource);
	}

	override async save(_group: GroupIdentifier, options?: ISaveOptions): Promise<EditorInput | IUntypedEditorInput | undefined> {
		const saved = await this.textFileService.save(this.resource, options);
		return saved ? this : undefined;
	}

	override async revert(_group: GroupIdentifier, options?: IRevertOptions): Promise<void> {
		await this.textFileService.revert(this.resource, options);
	}

	/** Several panes are registered for this input (library, grids and building editor); pick by kind. */
	override prefersEditorPane<T extends IEditorDescriptor<IEditorPane>>(editorPanes: T[]): T | undefined {
		return editorPanes.find(pane => pane.typeId === this.editorId) ?? editorPanes[0];
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof LibraryEditorInput && isEqual(other.resource, this.resource);
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: this.editorId } };
	}

	override dispose(): void {
		this.modelReference?.then(reference => reference.dispose(), () => { });
		this.modelReference = undefined;
		super.dispose();
	}
}

export class LibraryEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: LibraryEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON(), kind: editor.kind });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): LibraryEditorInput {
		const { resource, kind } = JSON.parse(serialized);
		return instantiationService.createInstance(LibraryEditorInput, URI.revive(resource), kind);
	}
}
