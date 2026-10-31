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
	/** T26: floor vibration from walking. */
	floorVibration: 'fem.floorVibration',
} as const;

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
