/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';

/** Member lists of the floor plan. */
export type MemberGroup = 'columns' | 'footings' | 'walls' | 'beams' | 'slabs';

/** Something in the project the engineer has selected, wherever it was selected. */
export type ModelSelection =
	| { readonly kind: 'member'; readonly group: MemberGroup; readonly id: string }
	| { readonly kind: 'story'; readonly id: string }
	| { readonly kind: 'gridLine'; readonly axis: 'x' | 'y'; readonly label: string }
	| { readonly kind: 'objectType'; readonly id: string };

export interface IModelSelectionChange {
	readonly selection: ModelSelection | undefined;
	/** Who changed it ('floorPlan', 'explorer', ...), so a view can ignore its own changes. */
	readonly source: string;
}

export function sameSelection(a: ModelSelection | undefined, b: ModelSelection | undefined): boolean {
	return JSON.stringify(a) === JSON.stringify(b);
}

export const ISaengineModelSelectionService = createDecorator<ISaengineModelSelectionService>('saengineModelSelectionService');

/**
 * The project item selected anywhere (the model views: Floor Plan, 3D, Analysis Model; the
 * Tables; the Model Explorer; a result list), shared so the others follow it and reveal it, and
 * the Properties panel shows it. Selection never edits anything.
 */
export interface ISaengineModelSelectionService {
	readonly _serviceBrand: undefined;

	readonly selection: ModelSelection | undefined;
	readonly onDidChangeSelection: Event<IModelSelectionChange>;

	setSelection(selection: ModelSelection | undefined, source: string): void;

	/**
	 * The storey the model view shows (the Floor Plan's storey), so the Tables can show that
	 * storey's rows. Changing storey is no selection: the selected item stays selected.
	 */
	readonly activeStory: string | undefined;
	readonly onDidChangeActiveStory: Event<IActiveStoryChange>;

	setActiveStory(story: string | undefined, source: string): void;
}

export interface IActiveStoryChange {
	readonly story: string | undefined;
	readonly source: string;
}
