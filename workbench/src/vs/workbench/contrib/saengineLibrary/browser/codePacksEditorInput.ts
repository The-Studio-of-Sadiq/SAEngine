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

const codePacksIcon = registerIcon('saengine-code-packs-editor-icon', Codicon.law, localize('saengineCodePacksIcon', "Icon of the SAEngine packages page."));

/** The Packages page (formerly Code Packs): the packages installed, published and with updates. */
export class CodePacksEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.codePacks';
	static readonly EDITOR_ID = 'workbench.editor.saengine.codePacks';

	private static _instance: CodePacksEditorInput | undefined;
	static get instance(): CodePacksEditorInput {
		if (!CodePacksEditorInput._instance || CodePacksEditorInput._instance.isDisposed()) {
			CodePacksEditorInput._instance = new CodePacksEditorInput();
		}
		return CodePacksEditorInput._instance;
	}

	readonly resource = URI.from({ scheme: 'saengine-code-packs', path: '/default' });

	override get typeId(): string {
		return CodePacksEditorInput.ID;
	}

	override get editorId(): string {
		return CodePacksEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('saenginePackages', "Packages");
	}

	override getIcon(): ThemeIcon {
		return codePacksIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof CodePacksEditorInput;
	}
}

/** Restores the Packages page with the window. */
export class CodePacksEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(): string {
		return '';
	}

	deserialize(): CodePacksEditorInput {
		return CodePacksEditorInput.instance;
	}
}
