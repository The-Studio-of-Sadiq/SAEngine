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

/**
 * One analysis result ready to draw (SAEngine backend `results/view`): node displacements
 * `[id, ux, uy, uz, rx, ry, rz]`, support reactions `[id, fx, fy, fz, mx, my, mz]`, and per frame
 * element its local y/z axes with displacements (global) and section forces
 * `[N, Vy, Vz, T, My, Mz]` (local, tension positive) at stations evenly spaced from node i to j.
 */
export interface FemResultView {
	readonly label: string;
	readonly kind: 'static' | 'combination' | 'modal';
	readonly nodes: readonly (readonly number[])[];
	readonly reactions: readonly (readonly number[])[];
	readonly elements: readonly FemResultElement[];
	/** Shell elements with their section forces per unit length at the centre (local axes). */
	readonly shells?: readonly FemResultShell[];
}

export interface FemResultShell {
	readonly id: number;
	readonly name: string;
	readonly nodes: readonly number[];
	/** N11, N22, N12, M11, M22, M12, Q13, Q23. */
	readonly forces?: readonly number[];
}

export interface FemResultElement {
	readonly id: number;
	readonly name: string;
	readonly y: readonly number[];
	readonly z: readonly number[];
	readonly displacements: readonly (readonly number[])[];
	readonly forces?: readonly (readonly number[])[];
}

/** Kinds of values the labels show. */
export type FemValueQuantity = 'length' | 'force' | 'moment' | 'forcePerLength' | 'momentPerLength';

/** What to draw of a result: the deflected shape, one section force's diagram, or the reactions. */
export type FemResultQuantity = 'deformed' | 'N' | 'Vy' | 'Vz' | 'T' | 'My' | 'Mz' | 'reactions'
	| 'N11' | 'N22' | 'N12' | 'M11' | 'M22' | 'M12' | 'Q13' | 'Q23';

export const FORCE_COMPONENTS: readonly FemResultQuantity[] = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'];

/** Shell section forces per unit length, in the order of {@link FemResultShell.forces}. */
export const SHELL_COMPONENTS: readonly FemResultQuantity[] = ['N11', 'N22', 'N12', 'M11', 'M22', 'M12', 'Q13', 'Q23'];

export interface FemResultDisplay {
	readonly show: FemResultQuantity;
	/** Multiplier on the automatic scale (largest value drawn at a fixed share of the model size). */
	readonly scale: number;
	/** Mode shapes only: oscillate the shape. */
	readonly animate: boolean;
	/** Text of a value for the labels, in the units the user reads. */
	readonly format: (quantity: FemValueQuantity, value: number) => string;
}
