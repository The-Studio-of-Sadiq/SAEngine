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
import { IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { GRAPH_EXTENSION } from '../common/automationModel.js';

const graphIcon = registerIcon('saengine-graph-label-icon', Codicon.typeHierarchy, localize('saengineGraphIcon', "Icon of SAEngine visual programs."));

/** A visual program (`12 Automation/graphs/<name>.sagraph.json`) in the node editor. */
export class GraphEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.graph';

	constructor(readonly resource: URI) {
		super();
	}

	override get typeId(): string {
		return GraphEditorInput.ID;
	}

	override get editorId(): string {
		return 'workbench.editor.saengine.graph';
	}

	override getName(): string {
		const name = basename(this.resource);
		return name.endsWith(GRAPH_EXTENSION) ? name.slice(0, -GRAPH_EXTENSION.length) : name;
	}

	override getDescription(): string {
		return localize('graph.description', "Visual program");
	}

	override getIcon(): ThemeIcon {
		return graphIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof GraphEditorInput && other.resource.toString() === this.resource.toString());
	}
}
