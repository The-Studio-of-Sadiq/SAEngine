/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcCmColor, AcCmColorMethod, AcDbCircle, AcDbDatabase, AcDbEntity, AcDbLayerTableRecord, AcDbLine, AcDbMText,
	AcDbPolyline, AcGePoint2d, AcGiMTextAttachmentPoint,
} from '@mlightcad/data-model';

export type CadPoint = readonly [x: number, y: number];

/** A layer the host owns; it is created or updated to match and locked. */
export interface CadLayerSpec {
	readonly name: string;
	/** AutoCAD Color Index (1 red, 2 yellow, 3 green, 4 cyan, 5 blue, 6 magenta, 7 white/black, 8 grey, ...). */
	readonly color: number;
	/** Linetype from the drawing's template, e.g. "CENTER" or "DASHED"; continuous if omitted. */
	readonly linetype?: string;
	readonly description?: string;
}

interface CadEntityBase {
	readonly layer: string;
	/** Linetype scale of the entity (the template's patterns are a few drawing units long). */
	readonly linetypeScale?: number;
}

export type CadEntitySpec = CadEntityBase & (
	| { readonly kind: 'line'; readonly start: CadPoint; readonly end: CadPoint }
	| { readonly kind: 'circle'; readonly center: CadPoint; readonly radius: number }
	| { readonly kind: 'polyline'; readonly points: readonly CadPoint[]; readonly closed?: boolean }
	/** Single-line text centred on `position`. */
	| { readonly kind: 'text'; readonly position: CadPoint; readonly height: number; readonly text: string }
);

/** Drawing content generated from a model by the host, replaced as a whole whenever the model changes. */
export interface CadGeneratedDrawing {
	readonly layers: readonly CadLayerSpec[];
	readonly entities: readonly CadEntitySpec[];
}

const LOCKED_FLAG = 0x04;

function color(index: number): AcCmColor {
	return new AcCmColor(AcCmColorMethod.ByACI, index);
}

function updateLayers(database: AcDbDatabase, layers: readonly CadLayerSpec[]): void {
	const table = database.tables.layerTable;
	const linetypes = database.tables.linetypeTable;
	for (const spec of layers) {
		const linetype = spec.linetype && linetypes.has(spec.linetype) ? spec.linetype : 'Continuous';
		let layer = table.getAt(spec.name);
		if (!layer) {
			layer = new AcDbLayerTableRecord({ name: spec.name, isOff: false, isPlottable: true, color: color(spec.color), linetype, standardFlags: LOCKED_FLAG, description: spec.description ?? '' });
			table.add(layer);
			continue;
		}
		if (layer.color.colorIndex !== spec.color) {
			layer.color = color(spec.color);
		}
		if (layer.linetype !== linetype) {
			layer.linetype = linetype;
		}
		if (!layer.isLocked) {
			layer.isLocked = true;
		}
	}
}

function createEntity(spec: CadEntitySpec): AcDbEntity {
	let entity: AcDbEntity;
	switch (spec.kind) {
		case 'line':
			entity = new AcDbLine({ x: spec.start[0], y: spec.start[1], z: 0 }, { x: spec.end[0], y: spec.end[1], z: 0 });
			break;
		case 'circle':
			entity = new AcDbCircle({ x: spec.center[0], y: spec.center[1], z: 0 }, spec.radius);
			break;
		case 'polyline': {
			const polyline = new AcDbPolyline();
			spec.points.forEach(([x, y], i) => polyline.addVertexAt(i, new AcGePoint2d(x, y)));
			polyline.closed = !!spec.closed;
			entity = polyline;
			break;
		}
		case 'text': {
			const text = new AcDbMText();
			text.contents = spec.text;
			text.height = spec.height;
			text.location = { x: spec.position[0], y: spec.position[1], z: 0 };
			text.attachmentPoint = AcGiMTextAttachmentPoint.MiddleCenter;
			entity = text;
			break;
		}
	}
	entity.layer = spec.layer;
	if (spec.linetypeScale !== undefined) {
		entity.linetypeScale = spec.linetypeScale;
	}
	return entity;
}

/**
 * Replaces the entities generated earlier (`previous`, by object id) with `drawing`; returns
 * the ids of the new entities.
 */
export function applyGenerated(database: AcDbDatabase, previous: ReadonlySet<string>, drawing: CadGeneratedDrawing): Set<string> {
	const modelSpace = database.tables.blockTable.modelSpace;
	for (const id of previous) {
		modelSpace.getIdAt(id)?.erase();
	}
	updateLayers(database, drawing.layers);
	const entities = drawing.entities.map(createEntity);
	if (entities.length) {
		modelSpace.appendEntity(entities);
	}
	return new Set(entities.map(e => e.objectId));
}
