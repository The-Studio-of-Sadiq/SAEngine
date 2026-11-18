export interface AnnotationPoint { readonly x: number; readonly y: number; readonly z: number }
export interface Segment { readonly start: AnnotationPoint; readonly end: AnnotationPoint }
export interface Point3 { readonly x: number; readonly y: number; readonly z: number }

/** Anchor position of a single-line TEXT justification, rotated about the anchor. */
export function justifiedTextAnchor(point: AnnotationPoint, width: number, height: number, horizontal: 'left'|'center'|'right'|'aligned'|'middle'|'fit', vertical: 'baseline'|'bottom'|'middle'|'top', rotation: number): Point3 {
	const hx = horizontal === 'center' || horizontal === 'middle' ? -width / 2 : horizontal === 'right' ? -width : 0;
	const vy = vertical === 'middle' ? -height / 2 : vertical === 'top' ? -height : 0;
	const c = Math.cos(rotation), s = Math.sin(rotation);
	return { x: point.x + hx*c - vy*s, y: point.y + hx*s + vy*c, z: point.z };
}

/** Estimate TEXT advance for anchor math without requiring a font renderer. */
export function estimatedTextWidth(value: string, height: number, widthFactor = 1): number {
	return [...value].length * height * 0.6 * widthFactor;
}

export function centerMarkSegments(center: AnnotationPoint, size: number): Segment[] {
	const d = size / 2;
	return [
		{ start: { x: center.x - d, y: center.y, z: center.z }, end: { x: center.x + d, y: center.y, z: center.z } },
		{ start: { x: center.x, y: center.y - d, z: center.z }, end: { x: center.x, y: center.y + d, z: center.z } },
	];
}

export function tableGrid(rows: number, columns: number, rowHeight: number, columnWidth: number, origin: AnnotationPoint): Segment[] {
	if (!Number.isInteger(rows) || rows < 1 || !Number.isInteger(columns) || columns < 1 || rowHeight <= 0 || columnWidth <= 0) throw new Error('Invalid table dimensions');
	const lines: Segment[] = [];
	for (let r=0; r<=rows; r++) lines.push({ start: {x:origin.x,y:origin.y-r*rowHeight,z:origin.z}, end: {x:origin.x+columns*columnWidth,y:origin.y-r*rowHeight,z:origin.z} });
	for (let c=0; c<=columns; c++) lines.push({ start: {x:origin.x+c*columnWidth,y:origin.y,z:origin.z}, end: {x:origin.x+c*columnWidth,y:origin.y-rows*rowHeight,z:origin.z} });
	return lines;
}

export function point3(p: AnnotationPoint): Point3 { return { x:p.x, y:p.y, z:p.z }; }
