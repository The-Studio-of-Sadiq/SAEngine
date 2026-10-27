/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';

/*
 * A new object type made from the floor plan's tools ("New type..." in the Type picker), so a
 * new project can be drawn without first leaving for 04 Objects: a concrete column, beam, slab or
 * wall of a typed size. It has no reinforcement yet; 04 Objects (the owner of object types) and
 * the design proposal give it that.
 */

type Json = { readonly [key: string]: unknown };

export type NewTypeKind = 'column' | 'beam' | 'slab' | 'wall';

/** What the size prompt asks for each kind, and its usual BNBC-practice default. */
export const NEW_TYPE_PROMPTS: { readonly [kind in NewTypeKind]: { readonly prompt: string; readonly value: string } } = {
	column: { prompt: localize('newType.column', "Column size: width × depth in mm"), value: '400x400' },
	beam: { prompt: localize('newType.beam', "Beam size: width × depth in mm"), value: '250x450' },
	slab: { prompt: localize('newType.slab', "Slab thickness in mm"), value: '125' },
	wall: { prompt: localize('newType.wall', "Wall thickness in mm"), value: '250' },
};

const PREFIX: { readonly [kind in NewTypeKind]: string } = { column: 'C', beam: 'B', slab: 'S', wall: 'W' };
const NAME: { readonly [kind in NewTypeKind]: string } = {
	column: localize('newType.columnName', "Column"),
	beam: localize('newType.beamName', "Beam"),
	slab: localize('newType.slabName', "Slab"),
	wall: localize('newType.wallName', "Wall"),
};

function isObject(value: unknown): value is Json {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(value: unknown): Json[] {
	return Array.isArray(value) ? value.filter(isObject) : [];
}

/** Why `text` is not a size for `kind`, or undefined when it is one. */
export function validateSize(kind: NewTypeKind, text: string): string | undefined {
	return parseSize(kind, text) ? undefined : kind === 'column' || kind === 'beam'
		? localize('newType.badRect', "Type the width and depth in mm, e.g. {0}.", NEW_TYPE_PROMPTS[kind].value)
		: localize('newType.badThickness', "Type the thickness in mm, e.g. {0}.", NEW_TYPE_PROMPTS[kind].value);
}

function parseSize(kind: NewTypeKind, text: string): number[] | undefined {
	const parts = text.trim().split(/\s*[x×*,\s]\s*/i).filter(Boolean).map(Number);
	const count = kind === 'column' || kind === 'beam' ? 2 : 1;
	return parts.length === count && parts.every(v => Number.isFinite(v) && v >= 50 && v <= 5000) ? parts : undefined;
}

/**
 * `objects` (the text of `objects.json`) with a new concrete `kind` type of size `text`: the
 * concrete most used by the other types, else the first in `materials`. Its id is the size
 * ("B250x450"); an existing type of that id is reused, not doubled.
 */
export function addObjectType(objects: unknown, materials: unknown, kind: NewTypeKind, text: string): { readonly ok: true; readonly objects: Json; readonly id: string; readonly existed: boolean } | { readonly ok: false; readonly error: string } {
	const size = parseSize(kind, text);
	if (!size) {
		return { ok: false, error: validateSize(kind, text)! };
	}
	const types = list(isObject(objects) ? objects.objects : undefined);
	const label = size.map(String).join('x');
	const id = `${PREFIX[kind]}${label}`;
	if (types.some(t => t.id === id)) {
		return types.find(t => t.id === id)!.kind === kind
			? { ok: true, objects: objects as Json, id, existed: true }
			: { ok: false, error: localize('newType.idTaken', "There is already an object type {0} of another kind; make this one in 04 Objects.", id) };
	}
	const concretes = list(isObject(materials) ? materials.materials : undefined).filter(m => m.category === 'concrete' && typeof m.id === 'string').map(m => m.id as string);
	const used = new Map<string, number>();
	for (const t of types) {
		if (typeof t.material === 'string' && concretes.includes(t.material)) {
			used.set(t.material, (used.get(t.material) ?? 0) + 1);
		}
	}
	const material = [...used].sort((a, b) => b[1] - a[1])[0]?.[0] ?? concretes[0];
	if (!material) {
		return { ok: false, error: localize('newType.noConcrete', "Add a concrete in 03 Materials first.") };
	}
	const type: Json = kind === 'column' || kind === 'beam'
		? { id, name: `${NAME[kind]} ${label}`, kind, material, profile: { shape: 'rectangle', xDim: size[0], yDim: size[1] } }
		: { id, name: `${NAME[kind]} ${label}`, kind, material, thickness: size[0] };
	const base = { schema: 'saengine.objects/1', ...(isObject(objects) ? objects : {}) };
	return { ok: true, objects: { ...base, objects: [...types, type] }, id, existed: false };
}
