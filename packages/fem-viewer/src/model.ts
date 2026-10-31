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
	readonly kind: 'static' | 'combination' | 'modal' | 'spectrum' | 'history' | 'pushover';
	readonly nodes: readonly (readonly number[])[];
	readonly reactions: readonly (readonly number[])[];
	readonly elements: readonly FemResultElement[];
	/** Shell elements with their section forces per unit length at the centre (local axes). */
	readonly shells?: readonly FemResultShell[];
	/** Solid elements (four-node tetrahedra) with their stresses. */
	readonly solids?: readonly FemResultSolid[];
}

export interface FemResultSolid {
	readonly id: number;
	readonly name: string;
	readonly nodes: readonly number[];
	/** s11, s22, s33, s12, s23, s13 (global axes) and the von Mises stress. */
	readonly stress?: readonly number[];
}

/**
 * The outer faces of a set of tetrahedra (each face only one of them has), with the index of
 * the tetrahedron it belongs to: what of a solid can be seen.
 */
export function outerFaces(solids: readonly { readonly nodes: readonly number[] }[]): { readonly nodes: readonly [number, number, number]; readonly owner: number }[] {
	const count = new Map<string, { nodes: [number, number, number]; owner: number; seen: number }>();
	solids.forEach((solid, owner) => {
		const n = solid.nodes;
		if (n.length !== 4) {
			return;
		}
		for (const face of [[n[0], n[1], n[2]], [n[0], n[1], n[3]], [n[0], n[2], n[3]], [n[1], n[2], n[3]]] as [number, number, number][]) {
			const key = [...face].sort((a, b) => a - b).join('-');
			const entry = count.get(key);
			if (entry) {
				entry.seen++;
			} else {
				count.set(key, { nodes: face, owner, seen: 1 });
			}
		}
	});
	return [...count.values()].filter(f => f.seen === 1).map(f => ({ nodes: f.nodes, owner: f.owner }));
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
export type FemValueQuantity = 'length' | 'force' | 'moment' | 'forcePerLength' | 'momentPerLength' | 'stress' | 'areaPerLength';

/** What to draw of a result: the deflected shape, one section force's diagram, or the reactions. */
export type FemResultQuantity = 'deformed' | 'N' | 'Vy' | 'Vz' | 'T' | 'My' | 'Mz' | 'reactions'
	| 'N11' | 'N22' | 'N12' | 'M11' | 'M22' | 'M12' | 'Q13' | 'Q23'
	| 'S11' | 'S22' | 'S33' | 'SVM'
	| 'utilisation'
	| 'shellValues';

export const FORCE_COMPONENTS: readonly FemResultQuantity[] = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'];

/** Shell section forces per unit length, in the order of {@link FemResultShell.forces}. */
export const SHELL_COMPONENTS: readonly FemResultQuantity[] = ['N11', 'N22', 'N12', 'M11', 'M22', 'M12', 'Q13', 'Q23'];

/** Solid stresses drawn as contours, and their index in {@link FemResultSolid.stress}. */
export const SOLID_COMPONENTS: { readonly [quantity: string]: number } = { S11: 0, S22: 1, S33: 2, SVM: 6 };

export interface FemResultDisplay {
	readonly show: FemResultQuantity;
	/** Multiplier on the automatic scale (largest value drawn at a fixed share of the model size). */
	readonly scale: number;
	/** Mode shapes only: oscillate the shape. */
	readonly animate: boolean;
	/** Text of a value for the labels, in the units the user reads. */
	readonly format: (quantity: FemValueQuantity, value: number) => string;
	/**
	 * `show: 'utilisation'`: the design utilisation (demand / capacity) of frame and shell
	 * elements (a slab's shells carry the slab's value) by element id. Elements without a value
	 * are not coloured.
	 */
	readonly utilisation?: { readonly [elementId: number]: number };
	/**
	 * `show: 'utilisation'`: utilisation of checks at nodes (the beam-column joints), by node id,
	 * drawn as a glyph at each node in its band's colour.
	 */
	readonly nodeUtilisation?: { readonly [nodeId: number]: number };
	/**
	 * `show: 'shellValues'`: one value per shell element by element id (for example the steel a
	 * slab's layer needs there), drawn as a contour; shells without a value are not coloured.
	 */
	readonly shellValues?: { readonly [elementId: number]: number };
	/** `show: 'shellValues'`: what the values are, for the label of the largest. */
	readonly shellValueQuantity?: FemValueQuantity;
	/**
	 * Force diagrams: label every member's largest and least value (a member is the analysis
	 * elements of one name before `#`: `B1`, `B1#2`, ...), not only the largest of the model.
	 */
	readonly memberLabels?: boolean;
}

/**
 * Which part of the model is drawn: the elements listed (a floor, a grid line's elevation, one
 * storey), with their nodes; undefined draws all of it.
 */
export type FemVisibleElements = ReadonlySet<number> | undefined;

/** How the camera looks at the model: freely in 3D, or straight down a model axis (orthographic). */
export type FemCameraView = '3d' | 'top' | 'front' | 'side';

/** Utilisation below which a member is shown as passing with margin. */
export const UTILISATION_WARN = 0.9;

/** The band of a utilisation: below 0.9, from 0.9 up to 1.0, above 1.0. */
export function utilisationBand(value: number): 'pass' | 'warn' | 'fail' {
	return value > 1 ? 'fail' : value >= UTILISATION_WARN ? 'warn' : 'pass';
}

/** A utilisation to two decimals, or three where two would hide which band it is in (1.004). */
export function formatUtilisation(value: number): string {
	const short = value.toFixed(2);
	return Number(short) !== value && (short === '1.00' || short === '0.90') ? value.toFixed(3) : short;
}
