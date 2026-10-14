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

const startIcon = registerIcon('saengine-start-label-icon', Codicon.home, localize('saengineStartIcon', "Icon of the SAEngine start window."));

/** The SAEngine start window: create, open or reopen a project. Always shown as a modal. */
export class StartEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.start';
	static readonly EDITOR_ID = 'workbench.editor.saengine.start';

	private static _instance: StartEditorInput | undefined;
	static get instance(): StartEditorInput {
		if (!StartEditorInput._instance || StartEditorInput._instance.isDisposed()) {
			StartEditorInput._instance = new StartEditorInput();
		}
		return StartEditorInput._instance;
	}

	readonly resource = URI.from({ scheme: 'saengine-start', path: 'default' });

	override get typeId(): string {
		return StartEditorInput.ID;
	}

	override get editorId(): string {
		return StartEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton | EditorInputCapabilities.RequiresModal;
	}

	override getName(): string {
		return localize('saengineStart', "SAEngine");
	}

	override getIcon(): ThemeIcon {
		return startIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof StartEditorInput;
	}
}
