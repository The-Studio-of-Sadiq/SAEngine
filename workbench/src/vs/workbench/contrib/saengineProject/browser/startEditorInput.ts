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

/**
 * The SAEngine start page: create, open or reopen a project. It opens in the editor area, and
 * fills the window while no project is open (see `StartLayoutContribution`).
 */
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

	/** Set by "New Project...": the page opens on the new project form (N-N8); taken once. */
	private newProjectRequested = false;

	requestNewProject(): void {
		this.newProjectRequested = true;
	}

	takeNewProjectRequest(): boolean {
		const requested = this.newProjectRequested;
		this.newProjectRequested = false;
		return requested;
	}

	override get typeId(): string {
		return StartEditorInput.ID;
	}

	override get editorId(): string {
		return StartEditorInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Readonly | EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('saengineStart', "Start");
	}

	override getIcon(): ThemeIcon {
		return startIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof StartEditorInput;
	}
}
