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
	/** Strength group "A", "B" or "C" (BNBC 2020 Part 6 Chapter 11). */
	readonly group?: string | null;
	/** "inside", "outside" or "wet". */
	readonly location?: string | null;
	/** Modulus of elasticity [MPa]. */
	readonly E?: number | null;
	/** Permissible stresses [MPa]: Fb, Ft, Fv, Fc, Fcp. */
	readonly stresses?: { readonly [name: string]: number } | null;
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
	if (timber.group) {
		items.push({ kind: 'row', name: localize('femTimber.group', "Strength group"), value: localize('femTimber.groupValue', "{0}, {1} location", timber.group, locationLabel(timber.location)) });
	}
	const s = timber.stresses ?? {};
	const value = (name: string) => typeof s[name] === 'number' ? s[name].toFixed(2) : '-';
	if (Object.keys(s).length) {
		items.push({
			kind: 'row', name: localize('femTimber.stresses', "Permissible stresses"),
			value: localize('femTimber.stressesValue', "Fb {0}, Ft {1}, Fv {2}, Fc {3}, Fc⊥ {4} MPa", value('Fb'), value('Ft'), value('Fv'), value('Fc'), value('Fcp')),
		});
	}
	if (typeof timber.E === 'number') {
		items.push({ kind: 'row', name: localize('femTimber.e', "E"), value: localize('femTimber.eValue', "{0} MPa", timber.E.toFixed(0)) });
	}
	items.push({ kind: 'note', text: localize('femTimber.basis', "Permissible stress design (BNBC 2020 Part 6 Chapter 11) under the allowable stress combinations; deflection, bearing across the grain and connections are not checked.") });
	return items;
}
