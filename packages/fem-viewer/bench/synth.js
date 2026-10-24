/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

// A tall building as the viewer gets it (an `.osmodel`'s nodes and elements) and result views
// shaped as the backend's `results/view` (11 stations per frame element), for the benchmark.

const STATIONS = 11;

/** A deterministic pseudo-random sequence (the same building and results every run). */
function random(seed) {
	let s = seed >>> 0;
	return () => {
		s = (s * 1664525 + 1013904223) >>> 0;
		return s / 4294967296;
	};
}

/**
 * `storeys` floors on a grid of `bays` (x, y) of `span` m, columns and beams (each beam split
 * in `beamParts` elements named `B…#k`), slabs meshed into shells of about `mesh` m, and the
 * walls of the middle bay as shells; fixed supports at the base.
 */
export function synthModel({ storeys = 30, bays = [6, 5], span = 6, height = 3, mesh = 1, beamParts = 4 } = {}) {
	const nodes = [];
	const elements = [];
	const index = new Map();
	let nodeId = 0;
	let elementId = 0;
	const node = (x, y, z) => {
		const key = `${x.toFixed(4)},${y.toFixed(4)},${z.toFixed(4)}`;
		let id = index.get(key);
		if (id === undefined) {
			id = ++nodeId;
			index.set(key, id);
			nodes.push({ id, coords: [x, y, z], ...(z === 0 ? { restraint: [true, true, true, true, true, true] } : {}) });
		}
		return id;
	};
	const [nx, ny] = bays;
	const sub = Math.max(1, Math.round(span / mesh));
	const step = span / sub;
	let beam = 0;
	let column = 0;
	let slab = 0;
	for (let level = 1; level <= storeys; level++) {
		const z = level * height;
		const below = (level - 1) * height;
		for (let i = 0; i <= nx; i++) {
			for (let j = 0; j <= ny; j++) {
				column++;
				elements.push({ id: ++elementId, name: `C${column}`, type: 'ElasticTimoshenkoBeam', nodes: [node(i * span, j * span, below), node(i * span, j * span, z)] });
			}
		}
		const beamLine = (x0, y0, x1, y1) => {
			beam++;
			for (let k = 0; k < beamParts; k++) {
				const a = k / beamParts;
				const b = (k + 1) / beamParts;
				elements.push({
					id: ++elementId, name: k ? `B${beam}#${k + 1}` : `B${beam}`, type: 'ElasticTimoshenkoBeam',
					nodes: [node(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, z), node(x0 + (x1 - x0) * b, y0 + (y1 - y0) * b, z)],
				});
			}
		};
		for (let j = 0; j <= ny; j++) {
			for (let i = 0; i < nx; i++) {
				beamLine(i * span, j * span, (i + 1) * span, j * span);
			}
		}
		for (let i = 0; i <= nx; i++) {
			for (let j = 0; j < ny; j++) {
				beamLine(i * span, j * span, i * span, (j + 1) * span);
			}
		}
		for (let i = 0; i < nx * sub; i++) {
			for (let j = 0; j < ny * sub; j++) {
				slab++;
				elements.push({
					id: ++elementId, name: `S${level}/${slab}`, type: 'ShellMITC4',
					nodes: [node(i * step, j * step, z), node((i + 1) * step, j * step, z), node((i + 1) * step, (j + 1) * step, z), node(i * step, (j + 1) * step, z)],
				});
			}
		}
		// The core: walls on the four sides of the middle bay, meshed like the slabs.
		const ci = Math.floor(nx / 2) * span;
		const cj = Math.floor(ny / 2) * span;
		const walls = [[ci, cj, 1, 0], [ci, cj + span, 1, 0], [ci, cj, 0, 1], [ci + span, cj, 0, 1]];
		walls.forEach(([x, y, dx, dy], w) => {
			for (let k = 0; k < sub; k++) {
				for (let m = 0; m < 3; m++) {
					const z0 = below + height * m / 3;
					const z1 = below + height * (m + 1) / 3;
					elements.push({
						id: ++elementId, name: `W${w + 1}/${level}`, type: 'ShellMITC4',
						nodes: [node(x + dx * k * step, y + dy * k * step, z0), node(x + dx * (k + 1) * step, y + dy * (k + 1) * step, z0), node(x + dx * (k + 1) * step, y + dy * (k + 1) * step, z1), node(x + dx * k * step, y + dy * k * step, z1)],
					});
				}
			}
		});
	}
	return { ndm: 3, ndf: 6, nodes, elements };
}

const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = v => {
	const l = Math.hypot(v[0], v[1], v[2]) || 1;
	return [v[0] / l, v[1] / l, v[2] / l];
};
const round = (v, d) => Number(v.toFixed(d));

/**
 * A result view of `model` (`kind` static or modal; `mode` scales and shapes it differently),
 * with node displacements, reactions at the supports, every frame element's stations and every
 * shell's section forces, as the backend sends them (numbers rounded as it rounds them).
 */
export function synthResults(model, { kind = 'static', mode = 1, label = 'DL' } = {}) {
	const rand = random(mode * 7919);
	const nodeById = new Map(model.nodes.map(n => [n.id, n]));
	const top = Math.max(...model.nodes.map(n => n.coords[2]));
	const sway = (z, dir) => (mode % 2 ? 1 : -1) * 0.05 * Math.sin((z / top) * Math.PI / 2 * (2 * mode - 1)) * dir;
	const disp = id => {
		const c = nodeById.get(id).coords;
		return [sway(c[2], 1), sway(c[2], 0.6), -0.002 * c[2] / top];
	};
	const nodes = model.nodes.map(n => {
		const d = disp(n.id);
		return [n.id, round(d[0], 9), round(d[1], 9), round(d[2], 9), 0.001, 0.001, 0.0001];
	});
	const reactions = kind === 'modal' ? [] : model.nodes.filter(n => n.restraint).map(n => [n.id, round(rand() * 50 - 25, 3), round(rand() * 50 - 25, 3), round(800 + rand() * 400, 3), round(rand() * 20, 3), round(rand() * 20, 3), 0]);
	const elements = [];
	const shells = [];
	for (const e of model.elements) {
		if (e.nodes.length === 2) {
			const a = nodeById.get(e.nodes[0]).coords;
			const b = nodeById.get(e.nodes[1]).coords;
			const x = unit([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
			const vertical = Math.abs(x[2]) > 0.9;
			const z = unit(cross(x, vertical ? [1, 0, 0] : [0, 0, 1]));
			const y = cross(z, x);
			const da = disp(e.nodes[0]);
			const db = disp(e.nodes[1]);
			const displacements = [];
			const forces = [];
			const load = 20 + rand() * 40;
			const length = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
			for (let k = 0; k < STATIONS; k++) {
				const t = k / (STATIONS - 1);
				const bump = vertical ? 0 : -0.003 * Math.sin(Math.PI * t);
				displacements.push([round(da[0] + (db[0] - da[0]) * t, 9), round(da[1] + (db[1] - da[1]) * t, 9), round(da[2] + (db[2] - da[2]) * t + bump, 9)]);
				const shear = load * length * (0.5 - t);
				const moment = load * length * length * (t * (1 - t) / 2 - 1 / 12);
				forces.push([round(vertical ? -load * 40 : rand() * 5, 3), round(shear, 3), round(shear * 0.2, 3), round(rand(), 3), round(moment * 0.3, 3), round(moment, 3)]);
			}
			elements.push({ id: e.id, name: e.name, y: y.map(v => round(v, 6)), z: z.map(v => round(v, 6)), displacements, ...(kind === 'modal' ? {} : { forces }) });
		} else if (e.nodes.length >= 3) {
			const c = nodeById.get(e.nodes[0]).coords;
			const wave = Math.sin(c[0] / 3) * Math.cos(c[1] / 3);
			shells.push({ id: e.id, name: e.name, nodes: e.nodes, ...(kind === 'modal' ? {} : { forces: [wave * 100, -wave * 80, wave * 10, wave * 30, -wave * 25, wave * 4, wave * 12, -wave * 9].map(v => round(v, 3)) }) });
		}
	}
	return { label, kind, nodes, reactions, elements, shells };
}

/** A utilisation for every frame element and shell (as the design sends them). */
export function synthUtilisation(model) {
	const rand = random(4242);
	const result = {};
	for (const e of model.elements) {
		result[e.id] = round(0.3 + rand() * 0.85, 3);
	}
	return result;
}
