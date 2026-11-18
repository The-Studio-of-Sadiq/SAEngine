import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
import * as esbuild from 'esbuild';

async function loadGeometry(){
	const outfile=path.join(await mkdtemp(path.join(tmpdir(),'cad-annotation-')),'geometry.mjs');
	await esbuild.build({stdin:{contents:await readFile('src/annotationGeometry.ts','utf8'),sourcefile:'annotationGeometry.ts',loader:'ts'},outfile,bundle:true,format:'esm',platform:'node',logLevel:'error'});
	return import(pathToFileURL(outfile).href);
}
async function loadModel(){
	const outfile=path.join(await mkdtemp(path.join(tmpdir(),'cad-annotation-')),'model.mjs');
	const source=path.resolve('node_modules/@mlightcad/data-model/lib/index.js');
	await esbuild.build({entryPoints:[source],outfile,bundle:true,format:'esm',platform:'node',logLevel:'error',define:{define:'undefined'},packages:'external'});
	return import(pathToFileURL(outfile).href);
}

test('annotation placement helpers use expected rotated anchor and grid coordinates', async()=>{
	const {justifiedTextAnchor,centerMarkSegments,tableGrid}=await loadGeometry();
	const a=justifiedTextAnchor({x:0,y:0,z:0},10,2,'center','middle',Math.PI/2);
	assert.ok(Math.abs(a.x-1)<1e-9 && Math.abs(a.y+5)<1e-9); // rotate (-5,-1) by 90 degrees
	assert.deepEqual(centerMarkSegments({x:0,y:0,z:0},2.5),[
		{start:{x:-1.25,y:0,z:0},end:{x:1.25,y:0,z:0}}, {start:{x:0,y:-1.25,z:0},end:{x:0,y:1.25,z:0}},
	]);
	assert.deepEqual(tableGrid(3,2,10,5,{x:0,y:0,z:0}),[
		{start:{x:0,y:0,z:0},end:{x:10,y:0,z:0}},{start:{x:0,y:-10,z:0},end:{x:10,y:-10,z:0}},{start:{x:0,y:-20,z:0},end:{x:10,y:-20,z:0}},{start:{x:0,y:-30,z:0},end:{x:10,y:-30,z:0}},
		{start:{x:0,y:0,z:0},end:{x:0,y:-30,z:0}},{start:{x:5,y:0,z:0},end:{x:5,y:-30,z:0}},{start:{x:10,y:0,z:0},end:{x:10,y:-30,z:0}},
	]);
});

test('TEXT, MTEXT, style, and MLEADER survive DXF round trip',async()=>{
	const {AcDbDatabase,AcDbFileType,AcDbText,AcDbMText,AcDbMLeader,AcDbTextStyleTableRecord,AcGePoint3d,AcDbMLeaderContentType}=await loadModel();
	const db=new AcDbDatabase(); db.ensureTextStyleDefaults();
	db.tables.textStyleTable.add(new AcDbTextStyleTableRecord({name:'P10',fileName:'Arial',textSize:0,xScale:1,obliquingAngle:0}));
	const text=new AcDbText();text.textString='hello text';text.position=new AcGePoint3d(1,2,0);text.height=2.5;text.styleName='P10';
	const mt=new AcDbMText();mt.contents='hello\\Pmultiline';mt.location=new AcGePoint3d(3,4,0);mt.height=2.5;mt.styleName='P10';
	const ml=new AcDbMLeader();ml.contentType=AcDbMLeaderContentType.MTextContent;ml.addLeader({leaderLines:[{vertices:[new AcGePoint3d(0,0,0),new AcGePoint3d(2,0,0)]}]});ml.contents='leader text';ml.textLocation=new AcGePoint3d(2,0,0);ml.textStyleName='P10';
	db.tables.blockTable.modelSpace.appendEntity([text,mt,ml]);
	const out=db.dxfOut(undefined,6);const dxf=typeof out==='string'?out:new TextDecoder().decode(out);
	const reopened=new AcDbDatabase();await reopened.read(dxf,{readOnly:false},AcDbFileType.DXF);
	const entities=reopened.tables.blockTable.modelSpace.newIterator().toArray();
	assert.equal(entities.find(e=>e instanceof AcDbText)?.textString,'hello text');
	assert.equal(entities.find(e=>e instanceof AcDbMText)?.contents,'hello\\Pmultiline');
	assert.ok(reopened.tables.textStyleTable.has('P10'));
	assert.equal(entities.find(e=>e instanceof AcDbMLeader)?.contents,'leader text');
});
