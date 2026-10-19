/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { EditorInputCapabilities, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';

const versionsIcon = registerIcon('saengine-versions-editor-icon', Codicon.history, localize('saengineVersionsIcon', "Icon of the SAEngine Versions editor."));

const VERSIONS_SCHEME = 'saengine-versions';

/** The open project's versions: the list, the changes between them, save, restore and issue. */
export class VersionsEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.versions';
	static readonly EDITOR_ID = 'workbench.editor.saengine.versions';

	private static _instance: VersionsEditorInput | undefined;
	static get instance(): VersionsEditorInput {
		if (!VersionsEditorInput._instance || VersionsEditorInput._instance.isDisposed()) {
			VersionsEditorInput._instance = new VersionsEditorInput();
		}
		return VersionsEditorInput._instance;
	}

	readonly resource = URI.from({ scheme: VERSIONS_SCHEME, path: '/default' });

	override get typeId(): string {
		return VersionsEditorInput.ID;
	}

	override get editorId(): string {
		return VersionsEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('saengineVersions', "Versions");
	}

	override getIcon(): ThemeIcon {
		return versionsIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof VersionsEditorInput;
	}
}

/** Restores the Versions editor with the window. */
export class VersionsEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(): string {
		return '';
	}

	deserialize(): VersionsEditorInput {
		return VersionsEditorInput.instance;
	}
}
