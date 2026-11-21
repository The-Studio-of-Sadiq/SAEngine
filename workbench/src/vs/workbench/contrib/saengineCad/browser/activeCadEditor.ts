/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { CadEditor as CadEditorApi } from '@saengine/cad-editor';
import { Emitter, Event } from '../../../../base/common/event.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';

/** Workspace storage key for remembering whether the CAD command line is visible. */
export const CAD_COMMAND_LINE_STORAGE_KEY = 'saengine.cad.showCommandLine';

/** Common interface implemented by editor panes that host a CAD drawing editor. */
export interface ICadEditorPane {
	getCadEditor(): CadEditorApi | undefined;
	executeCadCommand?(command: string): Promise<void>;
	focusCadProperties?(): void;
	toggleCadCommandLine?(): void;
	showCadLayerPicker?(): Promise<void>;
}

const activeCadEditorEmitter = new Emitter<CadEditorApi | undefined>();

/** Fires when the active pane's underlying CadEditor instance changes (opened, switched, or released). */
export const onDidChangeActiveCadEditor: Event<CadEditorApi | undefined> = activeCadEditorEmitter.event;

/** Notifies ribbon controls that the active CAD editor instance changed. */
export function notifyActiveCadEditorChanged(editor: CadEditorApi | undefined): void {
	activeCadEditorEmitter.fire(editor);
}

/** Type guard for editor panes exposing a live CAD editor instance. */
export function isCadEditorPane(pane: unknown): pane is ICadEditorPane {
	return !!pane && typeof (pane as Partial<ICadEditorPane>).getCadEditor === 'function';
}

/** Returns the active editor pane if it hosts a CAD editor (Floor Plan or Standalone DXF). */
export function getActiveCadEditorPane(editorService: IEditorService): ICadEditorPane | undefined {
	const pane = editorService.activeEditorPane;
	return isCadEditorPane(pane) ? pane : undefined;
}

/** Returns the underlying CadEditor API for the currently active CAD editor pane, if any. */
export function getActiveCadEditor(editorService: IEditorService): CadEditorApi | undefined {
	return getActiveCadEditorPane(editorService)?.getCadEditor();
}

/** Executes a CAD command string on the active Floor Plan or Standalone CAD editor. */
export async function executeActiveCadCommand(editorService: IEditorService, command: string): Promise<void> {
	const pane = getActiveCadEditorPane(editorService);
	if (!pane) {
		return;
	}
	if (pane.executeCadCommand) {
		await pane.executeCadCommand(command);
		return;
	}
	const editor = pane.getCadEditor();
	if (!editor) {
		return;
	}
	try {
		await editor.execute(command);
	} catch {
		// Interactive CAD prompts throw on cancellation; keep ribbon actions silent.
	}
}
