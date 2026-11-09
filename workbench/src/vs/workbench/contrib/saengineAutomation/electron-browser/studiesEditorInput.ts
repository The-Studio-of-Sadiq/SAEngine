/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const studiesIcon = registerIcon('saengine-studies-label-icon', Codicon.beaker, localize('saengineStudiesIcon', "Icon of SAEngine design studies."));

/** The design studies of a project (`12 Automation/studies`). */
export class StudiesEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.studies';

	readonly resource: URI;

	constructor(readonly projectRoot: URI) {
		super();
		this.resource = URI.from({ scheme: 'saengine-studies', path: projectRoot.path });
	}

	override get typeId(): string {
		return StudiesEditorInput.ID;
	}

	override get editorId(): string {
		return 'workbench.editor.saengine.studies';
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('studies.name', "Design Studies");
	}

	override getIcon(): ThemeIcon {
		return studiesIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof StudiesEditorInput && other.projectRoot.toString() === this.projectRoot.toString());
	}
}
