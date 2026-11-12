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

const mepIcon = registerIcon('saengine-mep-editor-icon', Codicon.tools, localize('mepEditorIcon', "Icon of the MEP editor."));

/**
 * The project's MEP part (`07 MEP/mep.json`) opened in its editor. The JSON
 * text model stays the document: dirty state, save, revert, backups and undo come from the text
 * file service, exactly as for a text editor on the same file.
 */
export class MepEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.mep';
	static readonly EDITOR_ID = 'workbench.editor.saengine.mep';

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
		return MepEditorInput.ID;
	}

	override get editorId(): string {
		return MepEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		return localize('mepEditor', "MEP");
	}

	override getIcon(): ThemeIcon {
		return mepIcon;
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
		return other instanceof MepEditorInput && isEqual(other.resource, this.resource);
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

export class MepEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: MepEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON() });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): MepEditorInput {
		const { resource } = JSON.parse(serialized);
		return instantiationService.createInstance(MepEditorInput, URI.revive(resource));
	}
}
