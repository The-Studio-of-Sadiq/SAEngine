/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/**
 * The subset of the opensees-studio `.osmodel` schema that the viewport renders.
 * Field names match the JSON on disk so a parsed `.osmodel` can be passed straight in.
 * Model space follows the SAP2000/OpenSees convention: Z is up in 3D, Y is up in 2D.
 */

export interface FemNode {
	readonly id: number;
	readonly name?: string;
	readonly coords: readonly number[];
	readonly restraint?: readonly boolean[];
}

export interface FemElement {
	readonly id: number;
	readonly name?: string;
	readonly type: string;
	readonly nodes: readonly number[];
}

export interface FemModel {
	readonly ndm: number;
	readonly nodes: readonly FemNode[];
	readonly elements: readonly FemElement[];
}

export type FemSelection =
	| { readonly kind: 'node'; readonly id: number }
	| { readonly kind: 'element'; readonly id: number };

export function sameSelection(a: FemSelection | undefined, b: FemSelection | undefined): boolean {
	return a?.kind === b?.kind && a?.id === b?.id;
}
