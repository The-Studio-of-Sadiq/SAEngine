/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';

/** A field of a planned feature's preview form, shown disabled. */
export interface IPlannedFeatureInput {
	readonly label: string;
	readonly unit?: string;
	/** An example value, shown greyed in the field. */
	readonly example?: string;
}

/**
 * A feature that the MVP shows but does not compute yet: mostly methods from codes and guides
 * other than BNBC 2020. Its page tells testers what it will do, in which part, and from which
 * references, so the intent is visible without fake results. The part that will hold the
 * feature registers it, in its own contribution file.
 */
export interface IPlannedFeature {
	/** `<part>.<slug>`, for example `fem.pushover`. */
	readonly id: string;
	/** Id of the part that will hold it (see `PROJECT_PARTS`). */
	readonly part: string;
	readonly title: string;
	/** One or two sentences of what it will do. */
	readonly summary: string;
	/** The planned workflow, one step per line. */
	readonly steps?: readonly string[];
	readonly inputs?: readonly IPlannedFeatureInput[];
	/** What it will produce: tables, drawings, report sections. */
	readonly outputs?: readonly string[];
	/** Codes and guides it will follow, for example "ASCE 41-17 Ch 10". */
	readonly references?: readonly string[];
}

const features = new Map<string, IPlannedFeature>();
const onDidChange = new Emitter<void>();

/** Fires when a planned feature is registered or removed. */
export const onDidChangePlannedFeatures: Event<void> = onDidChange.event;

/** Registers a planned feature; disposing removes it (when the real feature lands). */
export function registerPlannedFeature(feature: IPlannedFeature): IDisposable {
	features.set(feature.id, feature);
	onDidChange.fire();
	return toDisposable(() => {
		if (features.get(feature.id) === feature) {
			features.delete(feature.id);
			onDidChange.fire();
		}
	});
}

export function plannedFeature(id: string): IPlannedFeature | undefined {
	return features.get(id);
}

/** All planned features, or those of one part. */
export function plannedFeatures(part?: string): IPlannedFeature[] {
	const all = [...features.values()];
	return part === undefined ? all : all.filter(f => f.part === part);
}
