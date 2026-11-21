/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { defaultPanelIcon, getEngineDataPanel } from './engineDataPanelRegistry.js';

const DATA_PANEL_SCHEME = 'saengine-panel';

/** Opens (or focuses) a registered U3 data panel editor by id. */
export function openEngineDataPanel(editorService: IEditorService, panelId: string): Promise<unknown> {
	return editorService.openEditor(new EngineDataPanelInput(panelId), { pinned: true });
}

/** Editor input for one registered {@link IEngineDataPanelDescriptor}; one tab per panel id. */
export class EngineDataPanelInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.dataPanel';
	static readonly EDITOR_ID = 'workbench.editor.saengine.dataPanel';

	readonly resource: URI;

	constructor(readonly panelId: string) {
		super();
		this.resource = URI.from({ scheme: DATA_PANEL_SCHEME, path: `/${panelId}` });
	}

	override get typeId(): string {
		return EngineDataPanelInput.ID;
	}

	override get editorId(): string {
		return EngineDataPanelInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return getEngineDataPanel(this.panelId)?.title ?? localize('saengine.dataPanel.unknown', "SAEngine Panel");
	}

	override getIcon(): ThemeIcon {
		return defaultPanelIcon(getEngineDataPanel(this.panelId));
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || (other instanceof EngineDataPanelInput && other.panelId === this.panelId);
	}
}

export class EngineDataPanelInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: EngineDataPanelInput): string {
		return editor.panelId;
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): EngineDataPanelInput {
		return new EngineDataPanelInput(serialized);
	}
}
