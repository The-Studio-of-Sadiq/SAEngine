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
	 * The built-in pack that already covers the code's loads (selectable while its materials
	 * are planned; they fall back to the default pack until then). The entry stays here until
	 * the pack covers a material too.
	 */
	readonly loadsPack?: string;
	/** The name of {@link loadsPack} in the selectors. */
	readonly loadsName?: string;
}

/** The built-in US pack: the loads of ASCE 7-22 (alpha 9, track C1); concrete and steel follow later. */
export const US_LOADS_PACK_ID = 'aci318-asce7-22';

export const PLANNED_CODE_PACK_US = 'settings.codePackUs';
export const PLANNED_CODE_PACK_EUROCODES = 'settings.codePackEurocodes';
export const PLANNED_CODE_PACK_INDIA = 'settings.codePackIndia';

export function plannedCodePacks(): readonly IPlannedCodePack[] {
	return [
		{ feature: PLANNED_CODE_PACK_US, name: localize('plannedPack.us', "ACI 318-19 + ASCE 7-22"), region: localize('plannedPack.usRegion', "United States"), loadsPack: US_LOADS_PACK_ID, loadsName: localize('plannedPack.usLoads', "ACI 318-19 + ASCE 7-22 (loads; materials planned)") },
		{ feature: PLANNED_CODE_PACK_EUROCODES, name: localize('plannedPack.eurocodes', "Eurocodes EN 1990–1998 with National Annexes"), region: localize('plannedPack.eurocodesRegion', "Europe") },
		{ feature: PLANNED_CODE_PACK_INDIA, name: localize('plannedPack.india', "IS 456, 1893, 800, 875, 13920"), region: localize('plannedPack.indiaRegion', "India") },
	];
}
