import { AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbMLeader, AcDbMLeaderContentType, AcDbMText, AcDbText, AcDbTextHorizontalMode, AcDbTextStyleTableRecord, AcDbTextVerticalMode, AcGePoint3d } from '@mlightcad/data-model';
import { registerCommand, type CadCommandContext, type CadPoint3 } from './commands.js';
import { centerMarkSegments, justifiedTextAnchor, tableGrid } from './annotationGeometry.js';

let rememberedHeight = 2.5;
const num = async (ctx: CadCommandContext, prompt: string, def?: number) => def;
const point = (p: CadPoint3) => new AcGePoint3d(p);
const makeText = (ctx: CadCommandContext, value: string, p: CadPoint3, height: number, rotation = 0) => {
	const t = new AcDbText(); t.textString=value; t.position=point(p); t.height=height; t.rotation=rotation; t.layer=ctx.database.native.clayer; t.styleName=ctx.database.native.textstyle; return t;
};

export async function textCommand(ctx: CadCommandContext): Promise<void> {
	const p = await ctx.getPoint('Specify start point:');
	const just=await ctx.getKeyword('Specify justification [Left/Center/Right/Aligned/Middle/Fit/Top/Bottom/MC]:',['Left','Center','Right','Aligned','Middle','Fit','Top','Bottom','MC'],{default:'Left'});
	const mode:Record<string,[AcDbTextHorizontalMode,AcDbTextVerticalMode]>={Left:[AcDbTextHorizontalMode.LEFT,AcDbTextVerticalMode.BASELINE],Center:[AcDbTextHorizontalMode.CENTER,AcDbTextVerticalMode.BASELINE],Right:[AcDbTextHorizontalMode.RIGHT,AcDbTextVerticalMode.BASELINE],Aligned:[AcDbTextHorizontalMode.ALIGNED,AcDbTextVerticalMode.BASELINE],Middle:[AcDbTextHorizontalMode.MIDDLE,AcDbTextVerticalMode.MIDDLE],Fit:[AcDbTextHorizontalMode.FIT,AcDbTextVerticalMode.BASELINE],Top:[AcDbTextHorizontalMode.LEFT,AcDbTextVerticalMode.TOP],Bottom:[AcDbTextHorizontalMode.LEFT,AcDbTextVerticalMode.BOTTOM],MC:[AcDbTextHorizontalMode.CENTER,AcDbTextVerticalMode.MIDDLE]};
	const [hmode,vmode]=mode[just]??mode.Left;
	const heightRaw=await ctx.getString(`Specify height <${rememberedHeight}>:`,{allowSpaces:false,defaultValue:String(rememberedHeight)});
	const actualHeight=Number(heightRaw); if(!Number.isFinite(actualHeight)||actualHeight<=0) throw new Error('Text height must be positive'); rememberedHeight=actualHeight;
	const rotationRaw=await ctx.getString('Specify rotation angle <0>:',{allowSpaces:false,defaultValue:'0'}); const degrees=Number(rotationRaw); if(!Number.isFinite(degrees)) throw new Error('Invalid rotation angle');
	const value=await ctx.getString('Enter text:',{allowSpaces:true});
	const t=makeText(ctx,value,p,actualHeight,degrees*Math.PI/180); t.horizontalMode=hmode; t.verticalMode=vmode; if(hmode!==AcDbTextHorizontalMode.LEFT||vmode!==AcDbTextVerticalMode.BASELINE)t.alignmentPoint=point(p); ctx.database.add(t);
}

export async function textEditCommand(ctx: CadCommandContext): Promise<void> {
	const entity=await ctx.getEntity('Select TEXT or MTEXT:');
	const content=await ctx.getString('Enter new text:',{allowSpaces:true});
	if (entity instanceof AcDbText) entity.textString=content;
	else if (entity instanceof AcDbMText) entity.contents=content;
	else throw new Error('Selected entity is not TEXT or MTEXT');
}

export async function styleCommand(ctx: CadCommandContext): Promise<void> {
	const name=await ctx.getString('Enter text style name:',{allowSpaces:false});
	const font=await ctx.getString('Enter font file or TrueType family:',{allowSpaces:true});
	const height=await ctx.getDouble('Specify fixed height (0 = variable):');
	const width=await ctx.getDouble('Specify width factor:');
	const oblique=await ctx.getDouble('Specify oblique angle in degrees:');
	const db=ctx.database.native;
	const record=new AcDbTextStyleTableRecord({name,fileName:font}); record.textSize=height; record.xScale=width; record.obliquingAngle=oblique*Math.PI/180;
	if(db.tables.textStyleTable.has(name)) db.tables.textStyleTable.remove(name); db.tables.textStyleTable.add(record); db.textstyle=name;
}

export async function mleaderCommand(ctx: CadCommandContext): Promise<void> {
	const arrow=await ctx.getPoint('Specify arrowhead location:'); const landing=await ctx.getPoint('Specify landing location:',{base:arrow}); const content=await ctx.getString('Enter multileader text:',{allowSpaces:true});
	const leader=new AcDbMLeader(); leader.contentType=AcDbMLeaderContentType.MTextContent; leader.addLeader({landingPoint:point(landing),leaderLines:[{vertices:[point(arrow),point(landing)]}]}); leader.contents=content; leader.textLocation=landing; leader.textHeight=rememberedHeight; leader.textStyleName=ctx.database.native.textstyle; ctx.database.add(leader);
}

export async function centerMarkCommand(ctx: CadCommandContext): Promise<void> {
	const e=await ctx.getEntity('Select circle or arc:');
	const curve=e as AcDbCircle|AcDbArc;
	if (!(e instanceof AcDbCircle) && !(e instanceof AcDbArc)) throw new Error('Select a circle or arc');
	const center=curve.center; const size=2.5;
	ctx.database.add(centerMarkSegments(center,size).map(s=>new AcDbLine(point(s.start),point(s.end))));
}

export async function tableCommand(ctx: CadCommandContext): Promise<void> {
	const origin=await ctx.getPoint('Specify table insertion point:'); const rows=await ctx.getInteger('Number of rows:',{min:1}); const cols=await ctx.getInteger('Number of columns:',{min:1}); const rh=await ctx.getDouble('Row height:'); const cw=await ctx.getDouble('Column width:');
	const entities:AcDbEntity[]=tableGrid(rows,cols,rh,cw,origin).map(s=>new AcDbLine(point(s.start),point(s.end)));
	const header=await ctx.getKeyword('Add header row text?', ['Yes','No'],{default:'No'});
	if(header==='Yes') for(let c=0;c<cols;c++){const v=await ctx.getString(`Header column ${c+1}:`,{allowSpaces:true});const t=new AcDbMText();t.contents=v;t.location=new AcGePoint3d(origin.x+c*cw+cw*.1,origin.y-rh*.75,origin.z);t.height=Math.min(rh*.5,rememberedHeight);entities.push(t);}
	ctx.database.add(entities);
}

export function registerAnnotationCommands(): void {
	registerCommand('TEXT', textCommand, {aliases:['DTEXT','DT']}); registerCommand('TEXTEDIT',textEditCommand,{aliases:['DDEDIT','ED']}); registerCommand('STYLE',styleCommand,{aliases:['ST']}); registerCommand('MLEADER',mleaderCommand,{aliases:['MLD']}); registerCommand('CENTERMARK',centerMarkCommand,{aliases:['CM']}); registerCommand('TABLE',tableCommand,{aliases:['TB']});
}
