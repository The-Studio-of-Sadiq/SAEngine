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
