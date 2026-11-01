/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const strutAndTieIcon = registerIcon('saengine-fem-strut-and-tie-label-icon', Codicon.symbolStructure, localize('femStmLabelIcon', "Icon of the Strut-and-Tie Models page label."));

/** The Strut-and-Tie Models page of an analysis model (`08 FEM/model.osmodel`): its D-regions' models in `08 FEM/strut-and-tie.json`. */
export class FemStrutAndTieInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.femStrutAndTie';
	static readonly EDITOR_ID = 'workbench.editor.saengine.femStrutAndTie';

	/** `model` is the analysis model; the page saves its own file beside it. */
	constructor(readonly model: URI, readonly region?: string) {
		super();
	}

	override get resource(): URI | undefined {
		return undefined;
	}

	override get typeId(): string {
		return FemStrutAndTieInput.ID;
	}

	override get editorId(): string {
		return FemStrutAndTieInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('femStm.tabTitle', "Strut-and-Tie Models");
	}

	override getIcon(): ThemeIcon {
		return strutAndTieIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof FemStrutAndTieInput && other.model.toString() === this.model.toString();
	}
}

export class FemStrutAndTieInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FemStrutAndTieInput): string {
		return JSON.stringify({ model: editor.model.toJSON() });
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): FemStrutAndTieInput {
		const { model } = JSON.parse(serialized);
		return new FemStrutAndTieInput(URI.revive(model));
	}
}
