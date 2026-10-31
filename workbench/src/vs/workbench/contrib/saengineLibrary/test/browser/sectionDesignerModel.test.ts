/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';
import { signedArea } from '../../../../../platform/saengine/common/geometry.js';
import {
	barsAlongEdges, barsLine, barsRing, cleanProperties, formatNumber, hitTest, interactionCurve, IUniaxial, moveSelection, newSection,
	offsetRing, parseSection, pointInRegion, propertyRows, rectangle, regionArea, sameRegions, serializeSection, snapPoint, TEMPLATE_DEFAULTS, templateBars, templateFields,
	templateProblem, templateRegions,
} from '../../browser/sectionDesignerModel.js';

suite('SAEngine - Section Designer model', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('templates have the areas of their hand formulas', () => {
		const area = (kind: Parameters<typeof templateRegions>[0], params = TEMPLATE_DEFAULTS[kind]) =>
			templateRegions(kind, params, 'C30').reduce((sum, r) => sum + regionArea(r), 0);
		assert.strictEqual(area('rectangle'), 400 * 600);
		assert.strictEqual(area('L'), 600 * 250 + (600 - 250) * 250);
		assert.strictEqual(area('T'), 900 * 250 + (600 - 250) * 250);
		assert.strictEqual(area('C'), 900 * 250 + 2 * (600 - 250) * 250);
		assert.strictEqual(area('box'), 2000 * 2000 - 1500 * 1500);
		// Core: the box less its hollow and the door opening through the front wall.
		assert.strictEqual(area('core'), 3000 * 2500 - 2500 * 2000 - 1000 * 250);
		assert.strictEqual(area('I'), 2 * 300 * 16 + 10 * (500 - 32));
		assert.ok(Math.abs(area('circle') - Math.PI * 300 * 300) / (Math.PI * 300 * 300) < 0.003);
		// Outlines are anticlockwise, so the backend and the offsets agree on the inside.
		for (const kind of ['rectangle', 'L', 'T', 'C', 'core'] as const) {
			assert.ok(signedArea(templateRegions(kind, TEMPLATE_DEFAULTS[kind], 'C30')[0].outline) > 0, kind);
		}
	});

	test('offset rings move every edge into the material', () => {
		assert.deepStrictEqual(offsetRing(rectangle(400, 600), 50), [[-150, -250], [150, -250], [150, 250], [-150, 250]]);
		// Clockwise input gives the same ring.
		assert.deepStrictEqual(offsetRing([...rectangle(400, 600)].reverse(), 50).sort(), offsetRing(rectangle(400, 600), 50).sort());
		// A hole grows into the concrete around it.
		assert.deepStrictEqual(offsetRing(rectangle(200, 200), 50, true), [[-150, -150], [150, -150], [150, 150], [-150, 150]]);
		// The re-entrant corner of an L moves diagonally away from the notch.
		const l = templateRegions('L', { b: 600, h: 600, t: 250 }, 'C30')[0].outline;
		assert.deepStrictEqual(offsetRing(l, 50)[3], [-300 + 250 - 50, -300 + 250 - 50]);
	});

	test('bars along the edges keep the cover and the spacing', () => {
		const region = templateRegions('rectangle', { b: 400, h: 600, t: 0 }, 'C30')[0];
		const bars = barsAlongEdges(region, 60, 20, 200);
		// 280 x 480 between the bar centres: 2 bars per short face, 3 per long face, corners shared.
		assert.strictEqual(bars.length, 10);
		assert.ok(bars.every(b => Math.abs(b.x) <= 140 + 1e-9 && Math.abs(b.y) <= 240 + 1e-9));
		assert.ok(bars.some(b => b.x === -140 && b.y === -240));
		// A box gets bars on its inner faces too, all in the concrete.
		const box = templateRegions('box', { b: 2000, h: 2000, t: 250 }, 'C30')[0];
		const boxBars = barsAlongEdges(box, 60, 16, 300);
		assert.ok(boxBars.length > 40);
		assert.ok(boxBars.every(b => pointInRegion([b.x, b.y], box)));
		// Outer faces 1000 - 60 from the centre, inner faces 750 + 60.
		assert.ok(boxBars.some(b => Math.abs(b.x) === 940) && boxBars.some(b => Math.abs(b.x) === 810), 'bars on both faces');
	});

	test('bars between corners line up with the corner bars of the parallel face (L template)', () => {
		const region = templateRegions('L', TEMPLATE_DEFAULTS.L, 'C30')[0];
		const bars = barsAlongEdges(region, 70, 20, 150);
		// Bar centres on (-230, ±230), (230, -230), (230, -120), (-120, -120), (-120, 230). The
		// outer leg face x = -230 divides into 115 mm steps; its bar near the inner corner's row
		// (y = -115) moves onto that row (y = -120).
		assert.ok(bars.some(b => b.x === -230 && b.y === -120));
		assert.ok(!bars.some(b => b.y === -115));
		assert.ok(bars.every(b => pointInRegion([b.x, b.y], region)));
	});

	test('L, T and C template bars pair across each leg at no more than the spacing', () => {
		const bars = templateBars('L', TEMPLATE_DEFAULTS.L, 70, 20, 150)!;
		const region = templateRegions('L', TEMPLATE_DEFAULTS.L, 'C30')[0];
		assert.ok(bars.every(b => pointInRegion([b.x, b.y], region)));
		// The horizontal leg: every bar on its outer face (y = -230) has a partner on its inner face (y = -120).
		const outer = bars.filter(b => b.y === -230).map(b => b.x).sort((a, b) => a - b);
		assert.deepStrictEqual(bars.filter(b => b.y === -120).map(b => b.x).sort((a, b) => a - b), outer);
		// The re-entrant corner bar, and even steps of no more than 150 mm along the leg.
		assert.ok(bars.some(b => b.x === -120 && b.y === -120));
		const steps = outer.slice(1).map((x, i) => x - outer[i]);
		assert.ok(steps.every(s => s <= 150 && s >= 100), steps.join());
		assert.strictEqual(templateBars('rectangle', TEMPLATE_DEFAULTS.rectangle, 70, 20, 150), undefined);
		for (const kind of ['T', 'C'] as const) {
			const shape = templateRegions(kind, TEMPLATE_DEFAULTS[kind], 'C30')[0];
			assert.ok(templateBars(kind, TEMPLATE_DEFAULTS[kind], 70, 20, 150)!.every(b => pointInRegion([b.x, b.y], shape)), kind);
		}
	});

	test('template dimensions: fields, checks and recognising the template', () => {
		assert.deepStrictEqual(templateFields('L').map(f => f.key), ['b', 'h', 't']);
		assert.deepStrictEqual(templateFields('I').map(f => f.key), ['b', 'h', 't', 'tf']);
		assert.deepStrictEqual(templateFields('circle').map(f => f.key), ['b']);
		assert.strictEqual(templateProblem('L', { b: 600, h: 600, t: 250 }), undefined);
		assert.ok(templateProblem('L', { b: 600, h: 600, t: 700 }));
		assert.ok(templateProblem('box', { b: 400, h: 400, t: 250 }));
		assert.ok(templateProblem('rectangle', { b: 0, h: 600, t: 0 }));
		const a = templateRegions('T', TEMPLATE_DEFAULTS.T, 'C30');
		assert.ok(sameRegions(a, templateRegions('T', TEMPLATE_DEFAULTS.T, 'C30')));
		assert.ok(!sameRegions(a, templateRegions('T', { ...TEMPLATE_DEFAULTS.T, b: 1000 }, 'C30')));
		assert.ok(!sameRegions(a, templateRegions('T', TEMPLATE_DEFAULTS.T, 'C40')));
	});

	test('round-off in the properties of a symmetric section is shown as 0', () => {
		const properties = {
			referenceMaterial: 'C30', E: 25700, area: 250000, cx: 24.15e-15, cy: -10.79e-15, ixx: 5.2e9, iyy: 5.2e9, ixy: 3e-4, i11: 5.2e9, i22: 5.2e9, principalAngle: 1e-12,
			rx: 144, ry: 144, sxTop: 2e7, sxBottom: 2e7, syRight: 2e7, syLeft: 2e7, zx: null, zy: null, j: 8e9, cw: 1e12, asx: 2e5, asy: 2e5,
			scx: 1e-13, scy: 0, massPerLength: 600, barArea: 0, barRatio: 0,
		};
		const clean = cleanProperties(properties);
		assert.deepStrictEqual([clean.cx, clean.cy, clean.scx, clean.ixy, clean.principalAngle], [0, 0, 0, 0, 0]);
		assert.strictEqual(propertyRows(properties).find(r => r.label === 'x̄')?.value, '0');
		// A real offset (an L's centroid) is kept.
		assert.strictEqual(cleanProperties({ ...properties, cx: 84.5 }).cx, 84.5);
		// The numerically solved shear centre's noise (-15e-6 mm) is 0 too.
		assert.strictEqual(cleanProperties({ ...properties, scx: -15e-6 }).scx, 0);
	});

	test('lines and rings of bars', () => {
		assert.deepStrictEqual(barsLine([0, 0], [300, 0], 4, 16).map(b => b.x), [0, 100, 200, 300]);
		const ring = barsRing([0, 0], 200, 8, 20);
		assert.strictEqual(ring.length, 8);
		assert.ok(ring.every(b => Math.abs(Math.hypot(b.x, b.y) - 200) < 1e-3));
	});

	test('snapping, hit testing and moving', () => {
		assert.deepStrictEqual(snapPoint([37, -62], 25), [25, -50]);
		const section = newSection('S1', 'C30', 'B420');
		assert.strictEqual(section.bars.length, 8);
		const bar = section.bars[0];
		assert.deepStrictEqual(hitTest(section, [bar.x + 3, bar.y], 2), { kind: 'bar', index: 0 });
		assert.deepStrictEqual(hitTest(section, [0, 0], 2), { kind: 'region', index: 0 });
		assert.strictEqual(hitTest(section, [1000, 0], 2), undefined);
		moveSelection(section, { kind: 'region', index: 0 }, 25, 0);
		assert.deepStrictEqual(section.regions[0].outline[0], [-225, -250]);
	});

	test('the file round-trips and shows points on one line', () => {
		const section = newSection('C-L1', 'C27.6', 'B420DWR');
		section.regions = templateRegions('core', TEMPLATE_DEFAULTS.core, 'C27.6');
		section.regions[0].holes.push(rectangle(100, 100, 0, 900));
		const text = serializeSection(section);
		assert.ok(text.includes('[-1500, -1250]'), text);
		assert.ok(text.endsWith('}\n'));
		const parsed = parseSection(text);
		assert.ok(parsed.ok);
		assert.deepStrictEqual(parsed.section, section);
		assert.strictEqual(parseSection('{"schema": "saengine.objects/1"}').ok, false);
		assert.strictEqual(parseSection('{"regions": [{"outline": [[0]], "material": "C"}]}').ok, false);
		assert.strictEqual(parseSection('not json').ok, false);
	});

	test('numbers, ticks and property rows', () => {
		assert.strictEqual(formatNumber(237500), '237.5 × 10³');
		assert.strictEqual(formatNumber(6648163377.19), '6.648 × 10⁹');
		assert.strictEqual(formatNumber(235.526), '235.5');
		assert.strictEqual(formatNumber(null), '—');
		const rows = propertyRows({
			referenceMaterial: 'C30', E: 25700, area: 237500, cx: 235.5, cy: 235.5, ixx: 6.6e9, iyy: 6.6e9, ixy: -2.9e9, i11: 9.5e9, i22: 3.7e9, principalAngle: -135,
			rx: 167, ry: 167, sxTop: 1.8e7, sxBottom: 2.8e7, syRight: 1.8e7, syLeft: 2.8e7, zx: null, zy: null, j: 4.4e9, cw: 5.6e13, asx: 1.5e5, asy: 1.5e5,
			scx: 157, scy: 157, massPerLength: 570, barArea: 0, barRatio: 0,
		});
		assert.ok(rows.some(r => r.label === 'A' && r.unit === 'mm²'));
		assert.ok(!rows.some(r => r.label === 'Zx'), 'no plastic moduli for composite sections');
	});

	test('interaction curves are closed, in kNÂ·m and kN', () => {
		const diagram: IUniaxial = {
			axis: 'x', phiPnMax: 3.7e6, phiTension: 1.1e6, p0: 7.1e6, points: [
				{ P: -1.2e6, M: 0, phiP: -1.1e6, phiM: 0, phi: 0.9, epsT: null },
				{ P: 0, M: 3.3e8, phiP: 0, phiM: 3.0e8, phi: 0.9, epsT: 0.01 },
				{ P: 7.1e6, M: 0, phiP: 3.7e6, phiM: 0, phi: 0.65, epsT: -0.003 },
				{ P: 0, M: -3.3e8, phiP: 0, phiM: -3.0e8, phi: 0.9, epsT: 0.01 },
			],
		};
		assert.deepStrictEqual(interactionCurve(diagram, false), [[0, -1200], [330, 0], [0, 7100], [-330, 0], [0, -1200]]);
		assert.deepStrictEqual(interactionCurve(diagram, true), [[0, -1100], [300, 0], [0, 3700], [-300, 0], [0, -1100]]);
		assert.deepStrictEqual(interactionCurve({ ...diagram, points: [] }, true), []);
	});
});
