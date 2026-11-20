/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/** Temporary and permanent element/category hide & isolate state for a 3D view. */
export interface VisibilityState<C extends string = string> {
	readonly permanentHiddenElements: readonly string[];
	readonly tempHiddenElements: readonly string[];
	readonly tempIsolatedElements: readonly string[] | undefined;
	readonly tempHiddenCategories: readonly C[];
	readonly tempIsolatedCategories: readonly C[] | undefined;
	readonly revealHidden: boolean;
}

/** High-level summary of the current hide/isolate state for UI banners and buttons. */
export interface VisibilitySummary {
	readonly hasTemporary: boolean;
	readonly permanentHiddenCount: number;
	readonly tempHiddenCount: number;
	readonly isIsolated: boolean;
	readonly revealHidden: boolean;
}

export function emptyVisibilityState<C extends string = string>(): VisibilityState<C> {
	return {
		permanentHiddenElements: [],
		tempHiddenElements: [],
		tempIsolatedElements: undefined,
		tempHiddenCategories: [],
		tempIsolatedCategories: undefined,
		revealHidden: false,
	};
}

function unique<T>(items: Iterable<T>): T[] {
	return [...new Set(items)];
}

/** Temporarily hides `ids` (Revit `HH`). */
export function hideElementsTemp<C extends string>(state: VisibilityState<C>, ids: readonly string[]): VisibilityState<C> {
	if (!ids.length) {
		return state;
	}
	const hideSet = new Set(ids);
	return {
		...state,
		tempHiddenElements: unique([...state.tempHiddenElements, ...ids]),
		tempIsolatedElements: state.tempIsolatedElements?.filter(id => !hideSet.has(id)),
	};
}

/** Temporarily isolates `ids` (Revit `HI`). */
export function isolateElementsTemp<C extends string>(state: VisibilityState<C>, ids: readonly string[]): VisibilityState<C> {
	if (!ids.length) {
		return state;
	}
	const iso = unique(ids);
	const isoSet = new Set(iso);
	return {
		...state,
		tempIsolatedElements: iso,
		tempHiddenElements: state.tempHiddenElements.filter(id => !isoSet.has(id)),
	};
}

/** Temporarily hides `categories` (Revit `HC`). */
export function hideCategoriesTemp<C extends string>(state: VisibilityState<C>, categories: readonly C[]): VisibilityState<C> {
	if (!categories.length) {
		return state;
	}
	const hideSet = new Set(categories);
	return {
		...state,
		tempHiddenCategories: unique([...state.tempHiddenCategories, ...categories]),
		tempIsolatedCategories: state.tempIsolatedCategories?.filter(c => !hideSet.has(c)),
	};
}

/** Temporarily isolates `categories` (Revit `IC`). */
export function isolateCategoriesTemp<C extends string>(state: VisibilityState<C>, categories: readonly C[]): VisibilityState<C> {
	if (!categories.length) {
		return state;
	}
	const iso = unique(categories);
	const isoSet = new Set(iso);
	return {
		...state,
		tempIsolatedCategories: iso,
		tempHiddenCategories: state.tempHiddenCategories.filter(c => !isoSet.has(c)),
	};
}

/** Resets all temporary hide/isolate overrides while keeping permanent hides (Revit `HR`). */
export function resetTemporaryVisibility<C extends string>(state: VisibilityState<C>): VisibilityState<C> {
	return {
		...state,
		tempHiddenElements: [],
		tempIsolatedElements: undefined,
		tempHiddenCategories: [],
		tempIsolatedCategories: undefined,
	};
}

/** Permanently hides `ids` in the view state. */
export function hideElementsPermanent<C extends string>(state: VisibilityState<C>, ids: readonly string[]): VisibilityState<C> {
	if (!ids.length) {
		return state;
	}
	const hideSet = new Set(ids);
	return {
		...state,
		permanentHiddenElements: unique([...state.permanentHiddenElements, ...ids]),
		tempIsolatedElements: state.tempIsolatedElements?.filter(id => !hideSet.has(id)),
	};
}

/** Unhides `ids` from both permanent and temporary element hides. */
export function unhideElementsPermanent<C extends string>(state: VisibilityState<C>, ids: readonly string[]): VisibilityState<C> {
	if (!ids.length) {
		return state;
	}
	const unhideSet = new Set(ids);
	return {
		...state,
		permanentHiddenElements: state.permanentHiddenElements.filter(id => !unhideSet.has(id)),
		tempHiddenElements: state.tempHiddenElements.filter(id => !unhideSet.has(id)),
	};
}

/** Clears all permanently hidden elements. */
export function unhideAllPermanent<C extends string>(state: VisibilityState<C>): VisibilityState<C> {
	return {
		...state,
		permanentHiddenElements: [],
	};
}

/** Commits all currently temporarily hidden elements to permanent hide and clears temporary overrides. */
export function applyTemporaryToPermanent<C extends string>(
	state: VisibilityState<C>,
	allElements: readonly { readonly id: string; readonly category?: C }[],
): VisibilityState<C> {
	const tempHiddenIds: string[] = [];
	const tempHideSet = new Set(state.tempHiddenElements);
	const tempIsoSet = state.tempIsolatedElements ? new Set(state.tempIsolatedElements) : undefined;
	const tempHideCat = new Set(state.tempHiddenCategories);
	const tempIsoCat = state.tempIsolatedCategories ? new Set(state.tempIsolatedCategories) : undefined;
	for (const el of allElements) {
		const hiddenByTemp = tempHideSet.has(el.id)
			|| (tempIsoSet !== undefined && !tempIsoSet.has(el.id))
			|| (el.category !== undefined && tempHideCat.has(el.category))
			|| (tempIsoCat !== undefined && (el.category === undefined || !tempIsoCat.has(el.category)));
		if (hiddenByTemp) {
			tempHiddenIds.push(el.id);
		}
	}
	return resetTemporaryVisibility({
		...state,
		permanentHiddenElements: unique([...state.permanentHiddenElements, ...tempHiddenIds]),
	});
}

/**
 * Resolves which elements should be hidden and which should be highlighted as revealed-hidden.
 * `externalHidden` (e.g. story filter, legend layer, 4D not-started, phase absent) always stays hidden.
 */
export function computeElementVisibility<C extends string>(
	allElements: readonly { readonly id: string; readonly category?: C }[],
	state: VisibilityState<C>,
	externalHidden?: ReadonlySet<string>,
): { readonly hidden: Set<string>; readonly revealed: Set<string> } {
	const hidden = new Set<string>();
	const revealed = new Set<string>();
	const permHide = new Set(state.permanentHiddenElements);
	const tempHide = new Set(state.tempHiddenElements);
	const tempIso = state.tempIsolatedElements ? new Set(state.tempIsolatedElements) : undefined;
	const tempHideCat = new Set(state.tempHiddenCategories);
	const tempIsoCat = state.tempIsolatedCategories ? new Set(state.tempIsolatedCategories) : undefined;

	for (const el of allElements) {
		if (externalHidden?.has(el.id)) {
			hidden.add(el.id);
			continue;
		}
		const userHidden = permHide.has(el.id)
			|| tempHide.has(el.id)
			|| (tempIso !== undefined && !tempIso.has(el.id))
			|| (el.category !== undefined && tempHideCat.has(el.category))
			|| (tempIsoCat !== undefined && (el.category === undefined || !tempIsoCat.has(el.category)));
		if (!userHidden) {
			continue;
		}
		if (state.revealHidden) {
			revealed.add(el.id);
		} else {
			hidden.add(el.id);
		}
	}
	return { hidden, revealed };
}

export function summarizeVisibility<C extends string>(state: VisibilityState<C>): VisibilitySummary {
	const hasTemporary = state.tempHiddenElements.length > 0
		|| state.tempIsolatedElements !== undefined
		|| state.tempHiddenCategories.length > 0
		|| state.tempIsolatedCategories !== undefined;
	const isIsolated = state.tempIsolatedElements !== undefined || state.tempIsolatedCategories !== undefined;
	return {
		hasTemporary,
		permanentHiddenCount: state.permanentHiddenElements.length,
		tempHiddenCount: state.tempHiddenElements.length,
		isIsolated,
		revealHidden: state.revealHidden,
	};
}
