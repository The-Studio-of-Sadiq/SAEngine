/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { isEqual } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { partName } from './projectParts.js';

const placeholderIcon = registerIcon('saengine-placeholder-editor-icon', Codicon.circleLargeOutline, localize('saenginePlaceholderIcon', "Icon of a SAEngine part that is not built yet."));

/**
 * The main file of a part whose editor is not built yet (1 Soil Report, 7 MEP, 9 Substructure),
 * opened on the page that says what the part will hold. The file stays the user's: the page
 * never writes it, and "Open as JSON" (developer mode) shows it as text.
 */
export class PlaceholderEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.placeholder';
	static readonly EDITOR_ID = 'workbench.editor.saengine.placeholder';

	constructor(
		readonly resource: URI,
		/** Id of the part (see `PROJECT_PARTS`). */
		readonly part: string,
	) {
		super();
	}

	override get typeId(): string {
		return PlaceholderEditorInput.ID;
	}

	override get editorId(): string {
		return PlaceholderEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly;
	}

	override getName(): string {
		const part = partById(this.part);
		return part ? partName(part) : this.part;
	}

	override getIcon(): ThemeIcon {
		return placeholderIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof PlaceholderEditorInput && isEqual(other.resource, this.resource);
	}

	override toUntyped(): IUntypedEditorInput {
		return { resource: this.resource, options: { override: this.editorId } };
	}
}

export class PlaceholderEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: PlaceholderEditorInput): string {
		return JSON.stringify({ resource: editor.resource.toJSON(), part: editor.part });
	}

	deserialize(instantiationService: IInstantiationService, serialized: string): PlaceholderEditorInput {
		const { resource, part } = JSON.parse(serialized);
		return new PlaceholderEditorInput(URI.revive(resource), part);
	}
}
