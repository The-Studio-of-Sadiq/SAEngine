/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';

/*
 * The sections of a part's editor that the sidebar lists under the part (Settings: Seismic,
 * Wind, ...; MEP: Plumbing, HVAC, ...). The sidebar opens the part's editor with
 * `{ section }` in its options; the editor shows that section and says which one it shows.
 */

/** Editor options that open a part's editor at one of its sections. */
export interface IPartSectionOptions extends IEditorOptions {
	/** The section to show (the editor's own id of it); unknown ids are ignored. */
	readonly section?: string;
}

/** An editor pane that shows one section of its part at a time. */
export interface IPartSectionPane {
	/** The section shown now. */
	readonly partSection: string | undefined;
	readonly onDidChangePartSection: Event<void>;
}

export function isPartSectionPane(pane: unknown): pane is IPartSectionPane {
	const candidate = pane as Partial<IPartSectionPane> | undefined;
	return !!candidate && typeof candidate.onDidChangePartSection === 'function' && 'partSection' in candidate;
}

/** The `section` of editor options, if there is one. */
export function sectionOption(options: IEditorOptions | undefined): string | undefined {
	const section = (options as IPartSectionOptions | undefined)?.section;
	return typeof section === 'string' ? section : undefined;
}
