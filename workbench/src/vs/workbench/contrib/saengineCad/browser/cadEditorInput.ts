/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { VSBuffer } from '../../../../base/common/buffer.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { basename, isEqual } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, GroupIdentifier, IEditorSerializer, IRevertOptions, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const cadIcon = registerIcon('saengine-cad-editor-label-icon', Codicon.edit, localize('cadEditorLabelIcon', "Icon of the CAD drawing editor."));

/** Provides the drawing's current DXF text; set by the editor pane showing the input. */
export interface ICadDrawingSource {
	toDxf(): string;
	reload(): Promise<void>;
}

/**
 * A DXF drawing opened in the CAD editor. The drawing lives in the editor (mlightcad's
 * database); saving writes its DXF export to the file.
 */
export class CadEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.cad';
	static readonly EDITOR_ID = 'workbench.editor.saengine.cad';

	private dirty = false;
	source: ICadDrawingSource | undefined;

	constructor(
		readonly resource: URI,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
	}

	override get typeId(): string {
		return CadEditorInput.ID;
	}

	override get editorId(): string {
		return CadEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.None;
	}

	override getName(): string {
		return basename(this.resource);
	}

	override getIcon(): ThemeIcon {
		return cadIcon;
	}

	override isDirty(): boolean {
		return this.dirty;
	}

	setDirty(dirty: boolean): void {
		if (this.dirty !== dirty) {
			this.dirty = dirty;
			this._onDidChangeDirty.fire();
		}
	}

	override async save(): Promise<EditorInput | IUntypedEditorInput | undefined> {
		if (!this.source) {
			return undefined;
		}
		await this.fileService.writeFile(this.resource, VSBuffer.fromString(this.source.toDxf()));
		this.setDirty(false);
		return this;
	}

	override async revert(_group: GroupIdentifier, _options?: IRevertOptions): Promise<void> {
		await this.source?.reload();
		this.setDirty(false);
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof CadEditorInput && isEqual(other.resource, this.resource));
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: CadEditorInput.EDITOR_ID } };
	}
}

export class CadEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: CadEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON() });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): CadEditorInput {
		return instantiationService.createInstance(CadEditorInput, URI.revive(JSON.parse(serialized).resource));
	}
}
