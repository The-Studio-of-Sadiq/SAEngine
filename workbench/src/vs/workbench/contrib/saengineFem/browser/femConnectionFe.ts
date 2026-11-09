/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * Alpha 9 L6: the finite element (CBFEM) check of a steel member's end connection
 * (`saengine.design.connection_fe.check_member_joint`): plain data and the Properties panel's
 * items built from it, no DOM.
 */

import { localize } from '../../../../nls.js';
import { IFemDesignCheck, IFemDesignElement } from './femDesign.js';
import { FemDetailingItem } from './femSeismicDetailing.js';
import { steelOf } from './femSteelDesign.js';

/** `(model: URI, member: string) => IFemConnectionFe`: the FE check of the member's end connection (slow: seconds to minutes). */
export const FEM_CONNECTION_FE_COMMAND = 'saengine.fem.connectionFe';

/** The connection kinds the FE check builds. */
const FE_KINDS: ReadonlySet<string> = new Set(['endPlate', 'finPlate']);

export interface IFemConnectionFe {
	readonly error?: string;
	readonly connection?: string;
	readonly checks?: readonly IFemDesignCheck[];
	readonly utilisation?: number;
	readonly ok?: boolean;
	/** The largest equivalent plastic strain of the plates and its limit (shares, 0.05 = 5 %). */
	readonly plasticStrain?: number;
	readonly plasticStrainLimit?: number;
	/** The share of the design forces the joint carried (1: all). */
	readonly loadShare?: number;
	readonly forces?: { readonly V: number; readonly N: number; readonly M: number; readonly combination?: string | null };
	/** Sj,ini [kN·m/rad]. */
	readonly stiffness?: number | null;
	readonly classification?: { readonly class: 'rigid' | 'semiRigid' | 'pinned' | null; readonly ratio: number | null; readonly pinned?: number; readonly rigid?: number };
	readonly assumptions?: readonly string[];
	readonly code?: string;
}

/** Whether the member has a connection the FE check builds (an end plate or a fin plate). */
export function hasFeCheck(element: IFemDesignElement): boolean {
	return (steelOf(element)?.connections ?? []).some(c => !!c.kind && FE_KINDS.has(c.kind));
}

function classLabel(kind: string | null | undefined): string {
	switch (kind) {
		case 'rigid': return localize('femConnectionFe.rigid', "rigid");
		case 'semiRigid': return localize('femConnectionFe.semiRigid', "semi-rigid");
		case 'pinned': return localize('femConnectionFe.pinned', "pinned");
		default: return localize('femConnectionFe.notClassified', "not classified");
	}
}

/** The FE check's lines for the Properties panel: the forces, plastic strain, stiffness and its checks. */
export function connectionFeItems(found: IFemConnectionFe): FemDetailingItem[] {
	const items: FemDetailingItem[] = [{ kind: 'subheading', text: localize('femConnectionFe.heading', "FE check (CBFEM){0}", found.code ? `, ${found.code}` : '') }];
	if (found.error) {
		items.push({ kind: 'note', text: localize('femConnectionFe.error', "The FE check could not be made: {0}", found.error) });
		return items;
	}
	const f = found.forces;
	if (f) {
		items.push({ kind: 'row', name: localize('femConnectionFe.forces', "Design forces"), value: localize('femConnectionFe.forcesValue', "V {0} kN, N {1} kN, M {2} kN·m ({3})", f.V.toFixed(1), f.N.toFixed(1), f.M.toFixed(1), f.combination ?? '') });
	}
	if (found.plasticStrain !== undefined) {
		const limit = found.plasticStrainLimit ?? 0.05;
		items.push({
			kind: 'row', name: localize('femConnectionFe.strain', "Plastic strain"),
			value: localize('femConnectionFe.strainValue', "{0} % (limit {1} %)", (100 * found.plasticStrain).toFixed(2), (100 * limit).toFixed(1)),
			ok: found.plasticStrain <= limit,
		});
	}
	if (found.loadShare !== undefined && found.loadShare < 1) {
		items.push({ kind: 'note', text: localize('femConnectionFe.share', "The joint carried {0} % of the design forces before the analysis stopped converging.", (100 * found.loadShare).toFixed(0)) });
	}
	const c = found.classification;
	if (found.stiffness !== undefined && found.stiffness !== null && c?.ratio !== null && c?.ratio !== undefined) {
		items.push({
			kind: 'row', name: localize('femConnectionFe.stiffness', "Sj,ini"),
			value: localize('femConnectionFe.stiffnessValue', "{0} kN·m/rad, Sj Lb / E Ib = {1}: {2}", found.stiffness.toFixed(0), c.ratio.toFixed(2), classLabel(c.class)),
		});
	}
	for (const check of [...(found.checks ?? [])].sort((a, b) => b.utilisation - a.utilisation)) {
		items.push({
			kind: 'check',
			name: check.name,
			value: `${(100 * check.utilisation).toFixed(0)} %`,
			detail: localize('femConnectionFe.checkDetail', "{0} / {1} {2}", check.demand.toFixed(2), check.capacity.toFixed(2), check.unit),
			ok: check.ok,
			note: check.note || undefined,
		});
	}
	if (found.assumptions?.length) {
		items.push({ kind: 'note', text: localize('femConnectionFe.assumes', "Assumes: {0}.", found.assumptions.join('; ')) });
	}
	return items;
}
