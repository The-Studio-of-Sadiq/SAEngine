/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

// The viewer benchmark, run in a browser window by run.cjs: time to the first frame, orbit and
// animation frame rates, result and selection switches, GPU objects and JS heap, and leaks
// across model switches. Prints `BENCH_RESULT {json}` to the console when done.

import { createFemViewer } from '../dist/fem-viewer.js';
import { synthModel, synthResults, synthUtilisation } from './synth.js';

const params = new URLSearchParams(location.search);
const nextFrame = () => new Promise(resolve => requestAnimationFrame(() => resolve(performance.now())));
const frames = async n => { for (let i = 0; i < n; i++) { await nextFrame(); } };
const gc = () => globalThis.gc?.();
/** JS heap in use (MB): the least of a few full collections a frame apart (one alone is noisy). */
const heapMb = async () => {
	if (!performance.memory) {
		return undefined;
	}
	let least = Infinity;
	for (let i = 0; i < 4; i++) {
		gc();
		await nextFrame();
		gc();
		least = Math.min(least, performance.memory.usedJSHeapSize);
	}
	return +(least / 1048576).toFixed(1);
};
const ms = v => +v.toFixed(1);
const median = values => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

async function loadModel() {
	const path = params.get('model');
	if (path) {
		const parsed = await (await fetch(path)).json();
		return { ...parsed, ndm: parsed.ndm ?? 3, nodes: parsed.nodes ?? [], elements: parsed.elements ?? [] };
	}
	return synthModel({ storeys: Number(params.get('storeys') ?? 30), mesh: 6 / 7 });
}

/** The colours the editor gives the viewer (femModelEditor computeTheme) under the default Light and Dark Modern themes. */
const THEMES = {
	dark: { background: '#1f1f1f', member: '#3794ff', node: '#cccccc', support: '#89d185', selection: '#cca700', grid: '#cccccc80', deformed: '#d18616', positive: '#3794ff', negative: '#f14c4c', reaction: '#89d185', pass: '#89d185', warn: '#d18616', fail: '#f14c4c' },
	light: { background: '#ffffff', member: '#1a85ff', node: '#3b3b3b', support: '#388a34', selection: '#bf8803', grid: '#3b3b3b80', deformed: '#d18616', positive: '#1a85ff', negative: '#e51400', reaction: '#388a34', pass: '#388a34', warn: '#d18616', fail: '#e51400' },
};

const format = (quantity, value) => `${value.toFixed(2)} ${quantity === 'length' ? 'm' : quantity === 'force' ? 'kN' : 'kNm'}`;

const out = { userAgent: navigator.userAgent };
const container = document.getElementById('viewport');
const model = await loadModel();
out.model = { nodes: model.nodes.length, elements: model.elements.length, frames: model.elements.filter(e => e.nodes.length === 2).length, shells: model.elements.filter(e => e.nodes.length >= 3).length };
const staticView = synthResults(model, { kind: 'static', label: 'DL' });
const otherView = synthResults(model, { kind: 'static', mode: 2, label: 'LL' });
const modalView = synthResults(model, { kind: 'modal', mode: 1, label: 'Mode 1' });
const utilisation = synthUtilisation(model);
out.payloadMb = +(JSON.stringify(staticView).length / 1048576).toFixed(1);
const display = (show, extra = {}) => ({ show, scale: 1, animate: false, format, ...extra });
const heapBefore = await heapMb();

// The window's own frame rate (nothing drawn): the ceiling of the rates below.
await frames(5);
const idleStart = await nextFrame();
await frames(60);
out.idleFps = +(60000 / (performance.now() - idleStart)).toFixed(1);

// ── First frame: as the editor loads a model (setModel, then the View picker's "all"). ──
let start = performance.now();
const viewer = createFemViewer(container, { theme: THEMES[params.get('theme') ?? 'dark'] });
viewer.setModel(model);
viewer.setVisibleElements(undefined);
const setModelSync = performance.now() - start;
await nextFrame();
const first = await nextFrame();
out.firstFrame = { setModelMs: ms(setModelSync), firstFrameMs: ms(first - start), heapModelMb: await heapMb() };

const internals = viewer;
const renderer = internals.renderer.three;
let renderCpu = [];
const render = renderer.render.bind(renderer);
renderer.render = (scene, camera) => {
	const t = performance.now();
	render(scene, camera);
	renderCpu.push(performance.now() - t);
};
const info = () => ({ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, lines: renderer.info.render.lines, geometries: renderer.info.memory.geometries, textures: renderer.info.memory.textures });

async function orbit(name, count = 180) {
	await frames(10);
	renderCpu = [];
	const times = [];
	let last = await nextFrame();
	for (let i = 0; i < count; i++) {
		internals.camera.controls.rotate(Math.PI / 90, 0, false);
		const now = await nextFrame();
		times.push(now - last);
		last = now;
	}
	const total = times.reduce((a, b) => a + b, 0);
	out[name] = { fps: +(1000 * count / total).toFixed(1), worstFrameMs: ms(Math.max(...times)), medianRenderCpuMs: +median(renderCpu).toFixed(2), ...info() };
}

async function timed(fn, settle = 1) {
	const t = performance.now();
	fn();
	const sync = performance.now() - t;
	let end;
	for (let i = 0; i < settle; i++) {
		end = await nextFrame();
	}
	return { syncMs: ms(sync), toFrameMs: ms(end - t) };
}

if (params.get('shots')) {
	// Screenshots for a before/after comparison: the model, then a few results (fixed camera).
	const shot = async name => {
		await frames(10);
		const taken = new Promise(resolve => window.benchShotTaken = resolve);
		console.log('BENCH_SHOT ' + name);
		await taken;
	};
	const theme = params.get('theme') ?? 'dark';
	await shot(`${theme}-model`);
	const beam = model.elements.find(e => e.name?.startsWith('B'));
	for (const [name, view, shown] of [
		['deformed', staticView, display('deformed')],
		['Mz-labels', staticView, display('Mz', { memberLabels: true })],
		['M11', staticView, display('M11')],
		['utilisation', staticView, display('utilisation', { utilisation })],
		['reactions', staticView, display('reactions')],
	]) {
		viewer.setResults(view, shown);
		await shot(`${theme}-${name}`);
	}
	// The mode shape animated: two moments of the oscillation.
	viewer.setResults(modalView, display('deformed', { animate: true }));
	await shot(`${theme}-mode-animated-a`);
	await new Promise(resolve => setTimeout(resolve, 500));
	await shot(`${theme}-mode-animated-b`);
	viewer.setResults(staticView, display('Mz'));
	viewer.setSelection({ kind: 'element', id: beam.id });
	await shot(`${theme}-Mz-selected`);
	viewer.setSelection(undefined);
	const zs = [...new Set(model.nodes.map(n => n.coords[2]))].sort((a, b) => a - b);
	const nodeZ = new Map(model.nodes.map(n => [n.id, n.coords[2]]));
	const level = zs[Math.floor(zs.length / 2)];
	viewer.setVisibleElements(new Set(model.elements.filter(e => e.nodes.every(n => nodeZ.get(n) === level)).map(e => e.id)));
	await viewer.setCameraView('top');
	viewer.setResults(staticView, display('Mz', { memberLabels: true }));
	await shot(`${theme}-storey-plan-Mz`);
	console.log('BENCH_RESULT {}');
	await new Promise(() => { });
}

await orbit('orbitModel');

// ── Result switches (each twice: cold, then warm). ──
const switches = [
	['deformed', staticView, display('deformed')],
	['Mz', staticView, display('Mz')],
	['Mz other case', otherView, display('Mz')],
	['Mz memberLabels', staticView, display('Mz', { memberLabels: true })],
	['M11 contour', staticView, display('M11')],
	['utilisation', staticView, display('utilisation', { utilisation })],
	['reactions', staticView, display('reactions')],
	['scale x2', staticView, display('reactions', { scale: 2 })],
	['mode 1', modalView, display('deformed')],
];
out.switch = {};
for (const pass of [0, 1]) {
	for (const [name, view, shown] of switches) {
		const result = await timed(() => viewer.setResults(view, shown));
		out.switch[name] = pass ? { ...out.switch[name], warm: result } : { cold: result };
	}
}
out.switch['none'] = { warm: await timed(() => viewer.setResults(undefined)) };
await frames(3);
out.switch.heapAfterMb = await heapMb();

// ── Frame rates under results. ──
viewer.setResults(staticView, display('Mz', { memberLabels: true }));
await orbit('orbitMemberLabels');
viewer.setResults(staticView, display('M11'));
await orbit('orbitContour');
viewer.setResults(modalView, display('deformed', { animate: true }));
await orbit('orbitModeAnimation');

// ── Selection under a diagram. ──
viewer.setResults(staticView, display('Mz'));
await frames(5);
const beam = model.elements.find(e => e.name?.startsWith('B'));
out.select = {
	select: await timed(() => viewer.setSelection({ kind: 'element', id: beam.id })),
	deselect: await timed(() => viewer.setSelection(undefined)),
};

// ── One storey isolated, and back. ──
const zs = [...new Set(model.nodes.map(n => n.coords[2]))].sort((a, b) => a - b);
const level = zs[Math.floor(zs.length / 2)];
const nodeZ = new Map(model.nodes.map(n => [n.id, n.coords[2]]));
const storey = new Set(model.elements.filter(e => e.nodes.every(n => nodeZ.get(n) === level)).map(e => e.id));
out.isolate = { storey: await timed(() => viewer.setVisibleElements(storey)) };
await orbit('orbitStorey', 90);
out.isolate.all = await timed(() => viewer.setVisibleElements(undefined));
out.isolate.allAgain = await timed(() => viewer.setVisibleElements(undefined));

// ── Theme switch. ──
out.theme = await timed(() => viewer.setTheme({ background: '#ffffff', member: '#0066bf' }));
viewer.setTheme({ background: '#1e1e1e', member: '#4fc1ff' });

// ── Memory and leaks: model switches, then a new viewer. ──
viewer.setResults(undefined);
await frames(3);
const gpuBefore = info();
for (let i = 0; i < 5; i++) {
	viewer.setModel({ ...model, nodes: [...model.nodes] });
	viewer.setResults(i % 2 ? staticView : modalView, display(i % 2 ? 'Mz' : 'deformed', { memberLabels: true }));
	await frames(2);
}
viewer.setResults(undefined);
await frames(3);
out.memory = { heapBeforeMb: heapBefore, heapWithViewerMb: await heapMb(), gpuBefore: { geometries: gpuBefore.geometries, textures: gpuBefore.textures }, gpuAfter5ModelSwitches: { geometries: info().geometries, textures: info().textures } };
viewer.dispose();
await frames(3);
out.memory.heapAfterDisposeMb = await heapMb();

console.log('BENCH_RESULT ' + JSON.stringify(out));
