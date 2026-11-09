/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

// The three.js view of the web viewer export (alpha 9 L12). The exported index.html inlines the
// model and results as window.SAENGINE_DATA (saengine.exporters.web_viewer.model_data and
// results_data) and loads this bundle from beside it; when the bundle is missing, the page's own
// wireframe view runs instead.

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

type Point = [number, number, number];

interface Member { id: string; start: Point; end: Point; section: string; kind: string; parts?: string[] }
interface Plate { id: string; points: Point[] }
interface Section { designation?: string | null; objectType?: string | null }
interface ElementResult { utilisation?: number | null; ok?: boolean | null; governing?: string | null }
interface Data {
	model: { name: string; members: Member[]; plates: Plate[]; sections: Record<string, Section> };
	results?: { elements: Record<string, ElementResult>; summary?: { checked?: number; passed?: number; failed?: number } | null };
}

declare global {
	interface Window {
		SAENGINE_DATA?: Data;
		saengineViewer?: boolean;
		saengineViewerStarted?: boolean;
	}
}

const COLORS = { ok: 0x2e7d32, near: 0xc77700, fail: 0xc62828, none: 0x3b5b8c };

function resultOf(data: Data, member: Member): ElementResult | undefined {
	const elements = data.results?.elements ?? {};
	return elements[member.id] ?? (member.parts ?? []).map(p => elements[p]).find(Boolean);
}

function colorOf(result: ElementResult | undefined): number {
	if (!result || typeof result.utilisation !== 'number') {
		return COLORS.none;
	}
	return result.ok === false || result.utilisation > 1 ? COLORS.fail : result.utilisation > 0.9 ? COLORS.near : COLORS.ok;
}

/** SAEngine's Z up as three.js's Y up. */
function v(p: Point): THREE.Vector3 {
	return new THREE.Vector3(p[0], p[2], -p[1]);
}

function start(data: Data): void {
	const canvas = document.getElementById('view') as HTMLCanvasElement | null;
	if (!canvas) {
		return;
	}
	window.saengineViewer = true;
	window.saengineViewerStarted = true;
	const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
	const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
	renderer.setPixelRatio(window.devicePixelRatio || 1);
	const scene = new THREE.Scene();
	scene.background = new THREE.Color(dark ? 0x1b1c1e : 0xf7f7f5);
	const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
	const controls = new OrbitControls(camera, canvas);

	const pickables: { line: THREE.Line; member: Member }[] = [];
	for (const member of data.model.members) {
		const geometry = new THREE.BufferGeometry().setFromPoints([v(member.start), v(member.end)]);
		const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: colorOf(resultOf(data, member)) }));
		scene.add(line);
		pickables.push({ line, member });
	}
	const plates = new THREE.Group();
	for (const plate of data.model.plates) {
		if (plate.points.length < 3) {
			continue;
		}
		const positions: number[] = [];
		const p0 = v(plate.points[0]);
		for (let k = 1; k < plate.points.length - 1; k++) {
			for (const q of [p0, v(plate.points[k]), v(plate.points[k + 1])]) {
				positions.push(q.x, q.y, q.z);
			}
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
		plates.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: 0x888888, transparent: true, opacity: 0.15, side: THREE.DoubleSide, depthWrite: false })));
	}
	scene.add(plates);

	const box = new THREE.Box3().setFromObject(scene);
	const centre = box.getCenter(new THREE.Vector3());
	const size = Math.max(1, box.getSize(new THREE.Vector3()).length());
	function reset(): void {
		camera.position.copy(centre).add(new THREE.Vector3(size * 0.7, size * 0.5, size * 0.7));
		controls.target.copy(centre);
		controls.update();
	}
	reset();

	const summary = data.results?.summary;
	const summaryElement = document.getElementById('summary');
	if (summaryElement) {
		summaryElement.textContent = summary ? `Design: ${summary.checked ?? '?'} checked, ${summary.passed ?? '?'} pass, ${summary.failed ?? '?'} fail` : 'Model only (no design results).';
	}
	const info = document.getElementById('info');
	const raycaster = new THREE.Raycaster();
	raycaster.params.Line = { threshold: size / 300 };
	let down: { x: number; y: number } | undefined;
	canvas.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY }; });
	canvas.addEventListener('pointerup', e => {
		if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 3 || !info) {
			return;
		}
		const rect = canvas.getBoundingClientRect();
		raycaster.setFromCamera(new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1), camera);
		const hit = raycaster.intersectObjects(pickables.map(p => p.line))[0];
		const picked = hit && pickables.find(p => p.line === hit.object);
		if (!picked) {
			info.textContent = 'Drag to orbit, wheel to zoom, click a member.';
			return;
		}
		const section = data.model.sections[picked.member.section];
		const result = resultOf(data, picked.member);
		const utilisation = result && typeof result.utilisation === 'number' ? `${Math.round(result.utilisation * 100)} %` : '-';
		info.textContent = `${picked.member.id} (${picked.member.kind})\nSection: ${section?.designation || section?.objectType || picked.member.section}\n` +
			(result ? `Utilisation: ${utilisation}${result.governing ? ` (${result.governing})` : ''}` : 'Not checked');
	});
	document.getElementById('reset')?.addEventListener('click', reset);
	document.getElementById('plates')?.addEventListener('click', () => { plates.visible = !plates.visible; });

	function resize(): void {
		const width = window.innerWidth, height = window.innerHeight;
		renderer.setSize(width, height, false);
		camera.aspect = width / Math.max(1, height);
		camera.updateProjectionMatrix();
	}
	window.addEventListener('resize', resize);
	resize();
	renderer.setAnimationLoop(() => {
		controls.update();
		renderer.render(scene, camera);
	});
}

if (window.SAENGINE_DATA) {
	start(window.SAENGINE_DATA);
}
