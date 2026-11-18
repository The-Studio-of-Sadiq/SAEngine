import assert from 'node:assert/strict';
import { test } from 'node:test';
import * as esbuild from 'esbuild';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
async function load(){const outfile=path.join(await mkdtemp(path.join(tmpdir(),'cad-inquiry-')),'geom.mjs');await esbuild.build({stdin:{contents:await readFile('src/inquiryGeometry.ts','utf8'),sourcefile:'inquiryGeometry.ts',loader:'ts'},outfile,bundle:true,format:'esm',platform:'node',logLevel:'error'});return import(pathToFileURL(outfile).href);}
test('rectangle closed polyline area and perimeter',async()=>{const g=await load();assert.deepEqual(g.polylineMetrics([[0,0],[1000,0],[1000,500],[0,500]],[],true),{length:3000,area:500000});});
test('bulge one contributes exact semicircle area',async()=>{const g=await load();const m=g.polylineMetrics([[0,0],[100,0],[100,100],[0,100]],[1,0,0,0],true);assert.ok(Math.abs(m.area-(10000+Math.PI*2500/2))<1e-8);});
test('circle metrics radius 100',async()=>{const g=await load();assert.ok(Math.abs(g.circleMetrics(100).area-31415.9265359)<1e-5);assert.ok(Math.abs(g.circleMetrics(100).circumference-628.3185307)<1e-5);});
test('quarter arc length radius 100',async()=>{const g=await load();const a=g.arcFromBulge([100,0],[0,100],Math.tan(Math.PI/8));assert.ok(Math.abs(a.radius*Math.abs(a.sweep)-157.0796327)<1e-6);});
test('divide line into four intervals',async()=>{const g=await load();assert.deepEqual(g.divideCurve([{start:[0,0],end:[100,0]}],4),[[25,0],[50,0],[75,0]]);});
test('divide quarter arc into two intervals',async()=>{const g=await load();const pts=g.divideCurve([{start:[100,0],end:[0,100],bulge:Math.tan(Math.PI/8)}],2);assert.ok(Math.abs(pts[0][0]-Math.SQRT1_2*100)<1e-8);assert.ok(Math.abs(pts[0][1]-Math.SQRT1_2*100)<1e-8);});
test('measure line from start at spacing 30',async()=>{const g=await load();assert.deepEqual(g.measureCurve([{start:[0,0],end:[100,0]}],30),[[30,0],[60,0],[90,0]]);});
