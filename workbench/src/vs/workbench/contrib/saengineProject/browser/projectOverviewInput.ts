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

const overviewIcon = registerIcon('saengine-overview-label-icon', Codicon.project, localize('saengineOverviewIcon', "Icon of the SAEngine project overview."));

/** The overview of the open project: its parts, their status and what to do next. */
export class ProjectOverviewInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.overview';
	static readonly EDITOR_ID = 'workbench.editor.saengine.overview';

	private static _instance: ProjectOverviewInput | undefined;
	static get instance(): ProjectOverviewInput {
		if (!ProjectOverviewInput._instance || ProjectOverviewInput._instance.isDisposed()) {
			ProjectOverviewInput._instance = new ProjectOverviewInput();
		}
		return ProjectOverviewInput._instance;
	}

	readonly resource = URI.from({ scheme: 'saengine-overview', path: 'default' });

	override get typeId(): string {
		return ProjectOverviewInput.ID;
	}

	override get editorId(): string {
		return ProjectOverviewInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('saengineOverview', "Overview");
	}

	override getIcon(): ThemeIcon {
		return overviewIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof ProjectOverviewInput;
	}
}
