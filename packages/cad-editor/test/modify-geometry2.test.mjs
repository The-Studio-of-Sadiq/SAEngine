import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

async function load() {
 const outfile=path.join(await mkdtemp(path.join(tmpdir(),'cad-geom2-')),'geom.mjs');
 await esbuild.build({stdin:{contents:await import('node:fs/promises').then(fs=>fs.readFile('src/modifyGeometry2.ts','utf8')),sourcefile:'modifyGeometry2.ts',loader:'ts'},outfile,bundle:true,format:'esm',platform:'node',logLevel:'error'});
 return import(pathToFileURL(outfile).href);
}
test('scale and reference factor',async()=>{const g=await load();assert.deepEqual(g.scalePoint([100,0],[0,0],2),[200,0]);assert.deepEqual(g.scalePoint([100,0],[0,0],2.5),[250,0]);});
test('polar 4 item array rotates each copied point',async()=>{const {polarArray}=await load();const a=polarArray([[100,0]],[0,0],4,360,true);assert.deepEqual([[100,0],...a.map(x=>x.point([100,0]))].map(p=>p.map(n=>Math.round(n)||0)),[[100,0],[0,100],[-100,0],[0,-100]]);});
test('rectangular 2 by 3 array offsets',async()=>{const {rectangularArray}=await load();assert.deepEqual(rectangularArray(['x'],2,3,50,100).map(x=>x.offset),[[100,0],[200,0],[0,50],[100,50],[200,50]]);});
test('break line into retained endpoints',async()=>{const {breakLine}=await load();assert.deepEqual(breakLine([0,0],[100,0],[30,0],[60,0]),[{start:[0,0],end:[30,0]},{start:[60,0],end:[100,0]}]);});
test('join touching lines',async()=>{const {joinLines}=await load();assert.deepEqual(joinLines({start:[0,0],end:[50,0]},{start:[50,0],end:[100,0]}),{start:[0,0],end:[100,0]});});
test('explode closed rectangle into four edges',async()=>{const {explodePolyline}=await load();assert.deepEqual(explodePolyline([[0,0],[10,0],[10,10],[0,10]],true).length,4);});
test('lengthen picked endpoint by delta',async()=>{const {lengthenLine}=await load();assert.deepEqual(lengthenLine([0,0],[100,0],20,[99,0]),{start:[0,0],end:[120,0]});});
test('stretch selected polyline vertex',async()=>{const {stretchPolyline}=await load();assert.deepEqual(stretchPolyline([[0,0],[100,0],[100,100]],p=>p[0]===100&&p[1]===100,[0,50]),[[0,0],[100,0],[100,150]]);});
test('align point with ninety degree rotation and translation',async()=>{const {alignPoint}=await load();assert.deepEqual(alignPoint([0,0],[0,0],90,[10,10]).map(n=>Math.round(n)),[10,10]);assert.deepEqual(alignPoint([100,0],[0,0],90,[10,10]).map(n=>Math.round(n)),[10,110]);});

test('polar array without rotation translates items instead of rotating', async () => {
	const { polarArray } = await load();
	const a = polarArray([[100, 0]], [0, 0], 4, 360, false);
	// Center [0,0], item reference [100,0].
	// At 90°: reference rotates to [0,100], offset is [-100, 100]. Point [100, 10] translates to [0, 110].
	// At 180°: reference rotates to [-100,0], offset is [-200, 0]. Point [100, 10] translates to [-100, 10].
	// At 270°: reference rotates to [0,-100], offset is [-100, -100]. Point [100, 10] translates to [0, -90].
	const pts = a.map(x => x.point([100, 10])).map(p => p.map(n => Math.round(n) || 0));
	assert.deepEqual(pts, [[0, 110], [-100, 10], [0, -90]]);
});

test('break circle removes counter-clockwise pick interval, retaining CCW arc from 2nd to 1st pick', async () => {
	const { breakCircle } = await load();
	// Circle r=100 at origin broken at [100,0] (0°) then [0,100] (90°).
	// AutoCAD removes CCW interval 0°->90°.
	// The remaining arc is CCW from second pick (90°) to first pick (0° / 360°), sweep 270°.
	const arc = breakCircle([0, 0], 100, [100, 0], [0, 100]);
	assert.deepEqual(arc, { center: [0, 0], radius: 100, startAngle: 90, endAngle: 0 });
});

test('break arc removes interval between picks', async () => {
	const { breakArc } = await load();
	// Semicircle 0° to 180° broken at [0,100] (90°) and [-70.71, 70.71] (135°).
	const parts = breakArc([0, 0], 100, 0, 180, [0, 100], [-70.7107, 70.7107]);
	assert.equal(parts.length, 2);
	assert.deepEqual(parts[0], { center: [0, 0], radius: 100, startAngle: 0, endAngle: 90 });
	assert.equal(Math.round(parts[1].startAngle), 135);
	assert.equal(parts[1].endAngle, 180);
});

test('break polyline splits open polyline into two polylines', async () => {
	const { breakPolyline } = await load();
	const parts = breakPolyline([[0, 0], [50, 0], [100, 0]], [25, 0], [75, 0]);
	assert.deepEqual(parts, [[[0, 0], [25, 0]], [[75, 0], [100, 0]]]);
});

test('explode polyline with bulge 1 yields semicircle arc', async () => {
	const { explodePolyline } = await load();
	// Polyline from [0,0] to [100,0] with bulge 1 (included angle 4*atan(1) = 180°).
	// Chord length 100, midpoint [50,0]. Sagitta h = 0 -> center [50,0], radius 50.
	// CCW from [0,0] (180°) to [100,0] (0°).
	const segs = explodePolyline([[0, 0], [100, 0]], false, [1]);
	assert.equal(segs.length, 1);
	assert.equal(segs[0].kind, 'arc');
	assert.deepEqual(segs[0].center.map(n => Math.round(n)), [50, 0]);
	assert.equal(Math.round(segs[0].radius), 50);
	assert.equal(Math.round(segs[0].startAngle), 180);
	assert.equal(Math.round(segs[0].endAngle), 0);
});

test('join touching line and arc produces polyline with bulge', async () => {
	const { arcToBulge } = await load();
	// Line [0,0]->[50,0] touches arc [50,0]->[100,0] with center [75,0].
	// Arc chord length 50, radius 25 -> semicircle, sweep 180°.
	// Bulge b = tan(180° / 4) = tan(45°) = 1.
	const b = arcToBulge([50, 0], [100, 0], [75, 0], true);
	assert.equal(Math.round(b * 1000) / 1000, 1);
});

test('join co-circular arcs touching end to end', async () => {
	const { joinArcs } = await load();
	// Arc 1 from 0° to 90°, Arc 2 from 90° to 180° on circle r=50 at origin.
	const merged = joinArcs(
		{ center: [0, 0], radius: 50, startAngle: 0, endAngle: 90 },
		{ center: [0, 0], radius: 50, startAngle: 90, endAngle: 180 },
	);
	assert.deepEqual(merged, { center: [0, 0], radius: 50, startAngle: 0, endAngle: 180 });
});

test('lengthen arc by delta or percent', async () => {
	const { lengthenArc } = await load();
	// Quarter circle r=100 from 0° to 90° (arc length = 100 * pi/2 = 50*pi).
	// Lengthen by delta = 10*pi (18°) picking near end [0, 100].
	const extEnd = lengthenArc([0, 0], 100, 0, 90, 10 * Math.PI, [0, 100]);
	assert.equal(Math.round(extEnd.endAngle), 108);
	assert.equal(extEnd.startAngle, 0);

	// Lengthen by delta = 10*pi picking near start [100, 0].
	const extStart = lengthenArc([0, 0], 100, 0, 90, 10 * Math.PI, [100, 0]);
	assert.equal(Math.round(extStart.startAngle), 342);
	assert.equal(extStart.endAngle, 90);
});
