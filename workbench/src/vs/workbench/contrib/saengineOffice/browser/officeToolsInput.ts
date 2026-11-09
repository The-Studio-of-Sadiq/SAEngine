/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { OfficeTool } from './officeModel.js';

const officeToolsIcon = registerIcon('saengine-office-tools-label-icon', Codicon.tools, localize('saengineOfficeToolsIcon', "Icon of the SAEngine office tools."));

/** Alpha 9 L11: the Office Tools editor (4D programme, cost optimisation, takeoff, site, fabrication, phasing). One tab. */
export class OfficeToolsInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.officeTools';
	static readonly EDITOR_ID = 'workbench.editor.saengine.officeTools';

	readonly resource = URI.from({ scheme: 'saengine-office-tools', path: '/office-tools' });

	constructor(public tool: OfficeTool) {
		super();
	}

	override get typeId(): string {
		return OfficeToolsInput.ID;
	}

	override get editorId(): string {
		return OfficeToolsInput.EDITOR_ID;
	}

	override getName(): string {
		return localize('saengineOfficeTools', "Office Tools");
	}

	override getIcon(): ThemeIcon {
		return officeToolsIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof OfficeToolsInput;
	}
}
