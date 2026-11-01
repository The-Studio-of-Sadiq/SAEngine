/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { IFemDesignElement } from './femDesign.js';
import { FemDetailingItem } from './femSeismicDetailing.js';

/** What `saengine.design.timber.design_timber_member` adds to a timber member's entry. */
export interface IFemTimberDesign {
	readonly label?: string | null;
	/** Strength group of the code pack's timber table ("A", "B", "C"). */
	readonly group?: string | null;
	/** Species id of the code pack's table, when the material names one. */
	readonly species?: string | null;
	/** "inside", "outside" or "wet". */
	readonly location?: string | null;
	/** Modulus of elasticity [MPa]. */
	readonly E?: number | null;
	/** Permissible stresses [MPa]: Fb, Ft, Fv, Fc, Fcn (before K2). */
	readonly stresses?: { readonly [name: string]: number } | null;
	/** Factors applied to the stresses: grade, durability, K1. */
	readonly factors?: { readonly [name: string]: number } | null;
	/** The code pack's name and the chapter clause the member is designed to. */
	readonly code?: string | null;
	readonly basis?: string | null;
	/** The end joint: type ("nails", "bolts", "splitRing", "discDowel") and count. */
	readonly joint?: { readonly type?: string; readonly count?: number; readonly size?: string; readonly diameter?: number } | null;
	/** Member length, the column's Le [mm]. */
	readonly length?: number | null;
}

export function timberOf(element: IFemDesignElement): IFemTimberDesign | undefined {
	const timber = (element as IFemDesignElement & { readonly timber?: IFemTimberDesign | null }).timber;
	return timber && typeof timber === 'object' ? timber : undefined;
}

function locationLabel(location: string | null | undefined): string {
	switch (location) {
		case 'inside': return localize('femTimber.inside', "inside");
		case 'outside': return localize('femTimber.outside', "outside");
		case 'wet': return localize('femTimber.wet', "wet");
		default: return location ?? '';
	}
}

function jointLabel(joint: NonNullable<IFemTimberDesign['joint']>): string {
	const count = joint.count ?? 0;
	switch (joint.type) {
		case 'nails': return localize('femTimber.nails', "{0} nails {1} mm per end", count, joint.size ?? '');
		case 'bolts': return localize('femTimber.bolts', "{0} bolts M{1} per end", count, joint.diameter ?? '');
		case 'splitRing': return localize('femTimber.rings', "{0} split rings {1} mm per end", count, joint.diameter ?? '');
		case 'discDowel': return localize('femTimber.dowels', "{0} disc-dowels {1} mm per end", count, joint.diameter ?? '');
		default: return joint.type ?? '';
	}
}

/** The Properties panel's section of a timber member: its section, group and permissible stresses. */
export function timberSection(element: IFemDesignElement): FemDetailingItem[] {
	const timber = timberOf(element);
	if (!timber) {
		return [];
	}
	const items: FemDetailingItem[] = [{ kind: 'heading', text: localize('femTimber.heading', "Timber Member") }];
	if (timber.label) {
		items.push({ kind: 'row', name: localize('femTimber.section', "Section"), value: timber.label });
	}
	if (timber.species) {
		items.push({ kind: 'row', name: localize('femTimber.species', "Species"), value: timber.species });
	}
	if (timber.group) {
		items.push({ kind: 'row', name: localize('femTimber.group', "Strength group"), value: localize('femTimber.groupValue', "{0}, {1} location", timber.group, locationLabel(timber.location)) });
	}
	const s = timber.stresses ?? {};
	const value = (name: string) => typeof s[name] === 'number' ? s[name].toFixed(2) : '-';
	if (Object.keys(s).length) {
		items.push({
			kind: 'row', name: localize('femTimber.stresses', "Permissible stresses"),
			value: localize('femTimber.stressesValue', "Fb {0}, Ft {1}, Fv {2}, Fc {3}, Fc⊥ {4} MPa", value('Fb'), value('Ft'), value('Fv'), value('Fc'), value('Fcn')),
		});
	}
	if (typeof timber.E === 'number') {
		items.push({ kind: 'row', name: localize('femTimber.e', "E"), value: localize('femTimber.eValue', "{0} MPa", timber.E.toFixed(0)) });
	}
	const factors = Object.entries(timber.factors ?? {}).filter(([, v]) => typeof v === 'number' && v !== 1);
	if (factors.length) {
		items.push({ kind: 'row', name: localize('femTimber.factors', "Factors"), value: factors.map(([k, v]) => `${k} ${v.toFixed(2)}`).join(', ') });
	}
	const joint = timber.joint;
	if (joint && joint.type) {
		items.push({ kind: 'row', name: localize('femTimber.joint', "End joint"), value: jointLabel(joint) });
	}
	items.push({ kind: 'note', text: localize('femTimber.basisPack', "Permissible stress design ({0}) under the allowable stress combinations, with the load duration factor of each combination.", timber.basis || timber.code || '') });
	return items;
}
