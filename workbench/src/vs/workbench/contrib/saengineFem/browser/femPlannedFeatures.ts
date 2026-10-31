/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { combinedDisposable, IDisposable } from '../../../../base/common/lifecycle.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { appendPropertyHeading } from '../../saengineProject/browser/editorFrame.js';
import { appendPlannedFeatureChip } from '../../saengineProject/browser/plannedFeatureEditor.js';

/**
 * Ids of the FEM part's planned features: analyses and designs from guides other than BNBC
 * 2020, shown in this MVP without computing anything. They are registered in
 * `saengineFem.contribution.ts`; the panels show chips to their pages where they will appear.
 */
export const FemPlanned = {
	/** T17: staged construction with all loads and time. */
	stagedConstruction: 'fem.stagedConstruction',
	creepShrinkage: 'fem.creepShrinkage',
	columnShortening: 'fem.columnShortening',
	/** T21: pushover acceptance and performance point. */
	pushoverHinges: 'fem.pushoverHinges',
	fibreWalls: 'fem.fibreWalls',
	performancePoint: 'fem.performancePoint',
	/** T22: existing RC buildings. */
	existingAssessment: 'fem.existingAssessment',
	retrofit: 'fem.retrofit',
	/** T35: nonlinear time history. */
	nonlinearTimeHistory: 'fem.nonlinearTimeHistory',
	timeHistoryDesign: 'fem.timeHistoryDesign',
	recordScaling: 'fem.recordScaling',
	/** T36: isolators and dampers. */
	baseIsolation: 'fem.baseIsolation',
	dampers: 'fem.dampers',
	/** T44: composite steel and concrete. */
	compositeBeams: 'fem.compositeBeams',
	compositeColumns: 'fem.compositeColumns',
	/** T14: cracked long-term FE deflection of slabs, and crack widths. */
	crackedSlabDeflection: 'fem.crackedSlabDeflection',
	crackWidths: 'fem.crackWidths',
	/** T15: automatic tendon layout and time-step long-term losses of PT slabs. */
	tendonLayout: 'fem.tendonLayout',
	tendonLongTermLosses: 'fem.tendonLongTermLosses',
	/** T26: floor vibration from walking. */
	floorVibration: 'fem.floorVibration',
	/** T27: base plate thickness and moment bases, anchors in concrete, end-plate moment connections. */
	basePlateDesign: 'fem.basePlateDesign',
	anchorConcrete: 'fem.anchorConcrete',
	endPlateMoment: 'fem.endPlateMoment',
	/** T28: the direct analysis method, AISC 341 seismic systems, member torsion. */
	directAnalysis: 'fem.directAnalysis',
	steelSeismic: 'fem.steelSeismic',
	steelTorsion: 'fem.steelTorsion',
} as const;

/** The planned steel connection features, shown with the steel members' checks. */
export const STEEL_CONNECTIONS_PLANNED: readonly string[] = [FemPlanned.basePlateDesign, FemPlanned.anchorConcrete, FemPlanned.endPlateMoment];

/** The planned steel stability and seismic features, shown with the steel members' checks. */
export const STEEL_STABILITY_PLANNED: readonly string[] = [FemPlanned.directAnalysis, FemPlanned.steelSeismic, FemPlanned.steelTorsion];

/**
 * A row of "Planned" chips, under a Properties panel heading when `heading` is given. The
 * caller registers the returned disposable with the panel's contents.
 */
export function appendPlannedChips(parent: HTMLElement, heading: string | undefined, ids: readonly string[], commandService: ICommandService): IDisposable {
	if (heading) {
		appendPropertyHeading(parent, heading);
	}
	const row = append(parent, $('.fem-planned-chips'));
	return combinedDisposable(...ids.map(id => appendPlannedFeatureChip(row, id, commandService)));
}
