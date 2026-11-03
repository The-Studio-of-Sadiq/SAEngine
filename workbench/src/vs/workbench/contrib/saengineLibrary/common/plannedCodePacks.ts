/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/**
 * The design-code packs that are planned but not in this MVP (SAEngine is built on BNBC 2020).
 * Each one has a planned-feature page (registered in `../browser/codePacks.contribution.ts`),
 * is listed on the Packages page and shows, disabled and marked "Planned", in the New Building
 * wizard's design code selector. No tables, values or clause text of these codes are included.
 */
export interface IPlannedCodePack {
	/** The planned feature's id (`settings.<slug>`). */
	readonly feature: string;
	/** The name the selectors show. */
	readonly name: string;
	/** Region, as the Packages page's meta line shows it. */
	readonly region: string;
	/**
	 * The built-in pack that already covers part of the planned code (its loads), when there is
	 * one: the planned entry stays until the materials exist too.
	 */
	readonly coveredBy?: { readonly packId: string; readonly what: string };
}

export const PLANNED_CODE_PACK_US = 'settings.codePackUs';
export const PLANNED_CODE_PACK_EUROCODES = 'settings.codePackEurocodes';
export const PLANNED_CODE_PACK_INDIA = 'settings.codePackIndia';

export function plannedCodePacks(): readonly IPlannedCodePack[] {
	return [
		{ feature: PLANNED_CODE_PACK_US, name: localize('plannedPack.us', "ACI 318-19 + ASCE 7-22"), region: localize('plannedPack.usRegion', "United States") },
		{ feature: PLANNED_CODE_PACK_EUROCODES, name: localize('plannedPack.eurocodes', "Eurocodes EN 1990–1998 with National Annexes"), region: localize('plannedPack.eurocodesRegion', "Europe"), coveredBy: { packId: 'eurocodes', what: localize('plannedPack.eurocodesCovered', "Loads and seismic actions (EN 1990, EN 1991, EN 1998-1) are covered by the built-in Eurocodes pack; the materials (EN 1992 to EN 1999) are planned.") } },
		{ feature: PLANNED_CODE_PACK_INDIA, name: localize('plannedPack.india', "IS 456, 1893, 800, 875, 13920"), region: localize('plannedPack.indiaRegion', "India") },
	];
}
