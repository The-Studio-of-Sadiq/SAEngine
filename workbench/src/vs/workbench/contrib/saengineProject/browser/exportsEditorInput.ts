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

const exportsIcon = registerIcon('saengine-exports-editor-icon', Codicon.export, localize('saengineExportsIcon', "Icon of the SAEngine exports page."));

/** Scheme of the exports page's resource; the project sidebar selects part 11 while it is active. */
export const EXPORTS_SCHEME = 'saengine-exports';

/**
 * Part 11 of the open project: what it hands over (design report, IFC, DXF floor plans, the bill
 * of quantities as CSV), when each was made, and the actions that make them.
 */
export class ExportsEditorInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.exports';
	static readonly EDITOR_ID = 'workbench.editor.saengine.exports';

	private static _instance: ExportsEditorInput | undefined;
	static get instance(): ExportsEditorInput {
		if (!ExportsEditorInput._instance || ExportsEditorInput._instance.isDisposed()) {
			ExportsEditorInput._instance = new ExportsEditorInput();
		}
		return ExportsEditorInput._instance;
	}

	readonly resource = URI.from({ scheme: EXPORTS_SCHEME, path: '/default' });

	override get typeId(): string {
		return ExportsEditorInput.ID;
	}

	override get editorId(): string {
		return ExportsEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('saengineExports', "Exports");
	}

	override getIcon(): ThemeIcon {
		return exportsIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof ExportsEditorInput;
	}
}

/** Restores the exports page with the window. */
export class ExportsEditorInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(): string {
		return '';
	}

	deserialize(): ExportsEditorInput {
		return ExportsEditorInput.instance;
	}
}
