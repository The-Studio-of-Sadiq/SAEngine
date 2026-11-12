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
import { EditorInputCapabilities, GroupIdentifier, IEditorSerializer, IRevertOptions, ISaveOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';

const boqIcon = registerIcon('saengine-boq-editor-icon', Codicon.listOrdered, localize('boqEditorIcon', "Icon of the bill of quantities editor."));

/**
 * The project's bill of quantities (`10 BOQ/boq.json`) opened in its editor. The JSON text model
 * stays the document: dirty state, save, revert and undo come from the text file service.
 */
export class BoqEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.boq';
	static readonly EDITOR_ID = 'workbench.editor.saengine.boq';

	private modelReference: Promise<IReference<IResolvedTextEditorModel>> | undefined;

	constructor(
		readonly resource: URI,
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
		return BoqEditorInput.ID;
	}

	override get editorId(): string {
		return BoqEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		return localize('boqEditor', "Bill of Quantities");
	}

	override getIcon(): ThemeIcon {
		return boqIcon;
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

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof BoqEditorInput && isEqual(other.resource, this.resource);
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

export class BoqEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: BoqEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON() });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): BoqEditorInput {
		const { resource } = JSON.parse(serialized);
		return instantiationService.createInstance(BoqEditorInput, URI.revive(resource));
	}
}
