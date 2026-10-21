/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { basename } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const proposalIcon = registerIcon('saengine-fem-design-proposal-label-icon', Codicon.symbolRuler, localize('femProposalLabelIcon', "Icon of the Design Reinforcement page label."));

/** The Design Reinforcement page of an analysis model (`08 FEM/model.osmodel`): bars proposed from its last run. */
export class FemDesignProposalInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.femDesignProposal';
	static readonly EDITOR_ID = 'workbench.editor.saengine.femDesignProposal';

	/** `resource` is the analysis model; the page itself has no file. */
	constructor(readonly model: URI) {
		super();
	}

	override get resource(): URI | undefined {
		return undefined;
	}

	override get typeId(): string {
		return FemDesignProposalInput.ID;
	}

	override get editorId(): string {
		return FemDesignProposalInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return basename(this.model) === 'model.osmodel'
			? localize('femProposal.tabTitle', "Design Reinforcement")
			: localize('femProposal.tabTitleOf', "Design Reinforcement: {0}", basename(this.model));
	}

	override getIcon(): ThemeIcon {
		return proposalIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof FemDesignProposalInput && other.model.toString() === this.model.toString();
	}
}

export class FemDesignProposalInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FemDesignProposalInput): string {
		return JSON.stringify({ model: editor.model.toJSON() });
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): FemDesignProposalInput {
		const { model } = JSON.parse(serialized);
		return new FemDesignProposalInput(URI.revive(model));
	}
}
