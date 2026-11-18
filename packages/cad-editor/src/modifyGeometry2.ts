/** Pure planar helpers for SCALE, arrays, BREAK, JOIN, EXPLODE, STRETCH, LENGTHEN and ALIGN. */
export type P2 = readonly [number, number];
export type Segment = { kind: 'line'; start: P2; end: P2 } | { kind: 'arc'; center: P2; radius: number; startAngle: number; endAngle: number };
const add = (a: P2, b: P2): P2 => [a[0] + b[0], a[1] + b[1]];
const sub = (a: P2, b: P2): P2 => [a[0] - b[0], a[1] - b[1]];
export function scalePoint(p: P2, base: P2, factor: number): P2 { return add(base, [(p[0] - base[0]) * factor, (p[1] - base[1]) * factor]); }
export function rectangularArray<T>(items: readonly T[], rows: number, columns: number, rowSpacing: number, columnSpacing: number): { item: T; offset: P2 }[] {
 const out: { item: T; offset: P2 }[] = [];
 for (let r = 0; r < rows; r++) for (let c = 0; c < columns; c++) if (r || c) for (const item of items) out.push({ item, offset: [c * columnSpacing, r * rowSpacing] });
 return out;
}
export function polarArray<T>(items: readonly T[], center: P2, count: number, fillAngle: number, rotate: boolean): { item: T; angle: number; point: (p: P2) => P2 }[] {
 return Array.from({ length: Math.max(0, count - 1) }, (_, i) => { const a = fillAngle * (i + 1) / count; const rad = a * Math.PI / 180; return { item: items[0], angle: rotate ? a : 0, point: (p: P2): P2 => { const x = p[0] - center[0], y = p[1] - center[1]; return [center[0] + x * Math.cos(rad) - y * Math.sin(rad), center[1] + x * Math.sin(rad) + y * Math.cos(rad)]; } }; }).filter(() => items.length > 0);
}
export function breakLine(start: P2, end: P2, first: P2, second: P2): { start: P2; end: P2 }[] {
 const d = sub(end, start), len2 = d[0] ** 2 + d[1] ** 2;
 const t = (p: P2) => Math.max(0, Math.min(1, ((p[0] - start[0]) * d[0] + (p[1] - start[1]) * d[1]) / len2));
 const a = t(first), b = t(second); return a <= b ? [{ start, end: add(start, [d[0] * a, d[1] * a]) }, { start: add(start, [d[0] * b, d[1] * b]), end }] : [{ start, end: add(start, [d[0] * b, d[1] * b]) }, { start: add(start, [d[0] * a, d[1] * a]), end }];
}
export function joinLines(a: { start: P2; end: P2 }, b: { start: P2; end: P2 }): { start: P2; end: P2 } | undefined {
 const near = (p: P2, q: P2) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-8;
 const v = sub(a.end, a.start), w = sub(b.end, b.start); if (Math.abs(v[0] * w[1] - v[1] * w[0]) > 1e-8 || Math.abs(v[0] * (b.start[1] - a.start[1]) - v[1] * (b.start[0] - a.start[0])) > 1e-8) return undefined;
 const pts = [a.start, a.end, b.start, b.end].sort((p, q) => p[0] * v[0] + p[1] * v[1] - q[0] * v[0] - q[1] * v[1]);
 if (!(near(a.start, b.start) || near(a.start, b.end) || near(a.end, b.start) || near(a.end, b.end))) return undefined;
 return { start: pts[0], end: pts[3] };
}
export function explodePolyline(points: readonly P2[], closed = false): { start: P2; end: P2 }[] { const out = points.slice(1).map((p, i) => ({ start: points[i], end: p })); if (closed && points.length > 1) out.push({ start: points[points.length - 1], end: points[0] }); return out; }
export function stretchPolyline(points: readonly P2[], inside: (p: P2) => boolean, delta: P2): P2[] { return points.map(p => inside(p) ? add(p, delta) : p); }
export function lengthenLine(start: P2, end: P2, delta: number, pick: P2): { start: P2; end: P2 } { const d = sub(end, start), n = Math.hypot(...d), atEnd = Math.hypot(pick[0] - end[0], pick[1] - end[1]) < Math.hypot(pick[0] - start[0], pick[1] - start[1]); const k = delta / n; return atEnd ? { start, end: add(end, [d[0] * k, d[1] * k]) } : { start: add(start, [-d[0] * k, -d[1] * k]), end }; }
export function alignPoint(p: P2, source: P2, angle: number, destination: P2, scale = 1): P2 { const r = angle * Math.PI / 180, x = (p[0] - source[0]) * scale, y = (p[1] - source[1]) * scale; return [destination[0] + x * Math.cos(r) - y * Math.sin(r), destination[1] + x * Math.sin(r) + y * Math.cos(r)]; }
