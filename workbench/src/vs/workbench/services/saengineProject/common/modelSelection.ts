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
 * The project item selected in the Floor Plan or the Model Explorer, shared so the other views
 * follow it and the Properties view shows it. Selection never edits anything.
 */
export interface ISaengineModelSelectionService {
	readonly _serviceBrand: undefined;

	readonly selection: ModelSelection | undefined;
	readonly onDidChangeSelection: Event<IModelSelectionChange>;

	setSelection(selection: ModelSelection | undefined, source: string): void;
}
