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

export function plannedCodePacks(): readonly IPlannedCodePack[] {
	return [
		{ feature: PLANNED_CODE_PACK_US, name: localize('plannedPack.us', "ACI 318-19 + ASCE 7-22"), region: localize('plannedPack.usRegion', "United States"), coveredBy: { packId: 'aci318-asce7-22', what: localize('plannedPack.usCovered', "The loads (ASCE 7-22: combinations, live loads, seismic from the site's mapped SDS and SD1, wind, snow) and structural concrete (ACI 318-19: members, slabs, walls and special walls, seismic detailing, development and splices, strut-and-tie), structural steel (AISC 360-22 members, connections, stability with the bracing forces, ponding, fatigue, composite members and steel in fire by Appendix 4, LRFD or ASD; AISC 341-22 seismic provisions; AISI S100-16 cold-formed members), timber (NDS 2018, ASD or LRFD) masonry (TMS 402-22 allowable stress and strength design), the foundations (IBC 2021 presumptive values, depths and factors of safety with the ASCE 7-22 allowable stress combinations), anchorage to concrete (ACI 318-19 Chapter 17), RC water tanks (ACI 350-06) and member deflection limits (IBC 2021 Table 1604.3) are covered by the built-in ACI 318-19 + ASCE 7-22 pack; settlement limits, subgrade moduli and pile static methods stay SAEngine practice (no US code value).") } },
		{ feature: PLANNED_CODE_PACK_EUROCODES, name: localize('plannedPack.eurocodes', "Eurocodes National Annexes"), region: localize('plannedPack.eurocodesRegion', "Europe"), coveredBy: { packId: 'eurocodes', what: localize('plannedPack.eurocodesCovered', "Loads and seismic actions (EN 1990, EN 1991, EN 1998-1), concrete design (EN 1992-1-1: members, slabs, stairs, walls, punching, slenderness, cracks and deflection, anchorage and laps; EN 1998-1 Section 5: DCM and DCH capacity design) the geotechnical design (EN 1997-1: footings by the design approach, piles with the correlation factors), steel (EN 1993-1-1 members with torsion and the bracing forces, EN 1993-1-8 joints with the column side and hollow section joints, EN 1998-1 Section 6 dissipative frames with the EBF links, EN 1993-1-3 cold-formed members, EN 1993-1-2 steel in fire), composite members (EN 1994-1-1), timber (EN 1995-1-1), masonry (EN 1996-1-1) and aluminium members (EN 1999-1-1) are covered by the built-in Eurocodes pack with the recommended values; the National Annexes (packs that extend it and set their Nationally Determined Parameters), shell buckling of class 4 tubes (EN 1993-1-6), timber joints and serviceability, and aluminium joints are planned.") } },
		// Alpha 9 C9: India left the list; the built-in Indian Standards (IS) pack covers the loads,
		// concrete, foundations, steel (IS 800), masonry (IS 1905), timber (IS 883) and composite
		// beams (IS 11384).
	];
}
