/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';

const femModelEditorIcon = registerIcon('saengine-fem-model-editor-label-icon', Codicon.symbolStructure, localize('femModelEditorLabelIcon', "Icon of the FEM model editor label."));

/**
 * Opens an OpenSees Studio `.osmodel` file in the FEM model viewport.
 */
export class FemModelEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.femModel';
	static readonly EDITOR_ID = 'workbench.editor.saengine.femModel';

	constructor(readonly resource: URI) {
		super();
	}

	override get typeId(): string {
		return FemModelEditorInput.ID;
	}

	override get editorId(): string {
		return FemModelEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		// Read-only until model editing lands; the file is still editable as JSON via "Reopen Editor With".
		return EditorInputCapabilities.Readonly;
	}

	override getName(): string {
		return basename(this.resource);
	}

	override getIcon(): ThemeIcon {
		return femModelEditorIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof FemModelEditorInput && other.resource.toString() === this.resource.toString();
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: FemModelEditorInput.EDITOR_ID } };
	}
}

export class FemModelEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FemModelEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON() });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): FemModelEditorInput {
		const { resource } = JSON.parse(serialized);
		return new FemModelEditorInput(URI.revive(resource));
	}
}
