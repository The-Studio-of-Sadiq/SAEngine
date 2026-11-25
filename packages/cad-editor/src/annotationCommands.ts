import { AcDbArc, AcDbCircle, AcDbEntity, AcDbLine, AcDbMLeader, AcDbMLeaderContentType, AcDbMText, AcDbText, AcDbTextHorizontalMode, AcDbTextStyleTableRecord, AcDbTextVerticalMode, AcGePoint3d } from '@mlightcad/data-model';
import { registerCommand, type CadCommandContext, type CadPoint3 } from './commands.js';
import { centerMarkSegments, tableGrid } from './annotationGeometry.js';
import { getCurrentTableStyle } from './stylesAuditCommands.js';

let rememberedHeight = 2.5;
let rememberedDimcen = 2.5;

export function getDrawingDimcen(db: any): number {
	const raw = db?.dimcen ??
		db?.header?.dimcen ??
		db?.header?.DIMCEN ??
		(typeof db?.getVariable === 'function' ? db.getVariable('DIMCEN') : undefined) ??
		(typeof db?.getSysVar === 'function' ? db.getSysVar('DIMCEN') : undefined) ??
		db?.tables?.dimStyleTable?.getAt?.(db.dimstyle)?.dimcen;
	if (typeof raw === 'number' && Number.isFinite(raw)) {
		rememberedDimcen = raw;
		return raw;
	}
	return rememberedDimcen;
}

const point = (p: CadPoint3) => new AcGePoint3d(p);
const makeText = (ctx: CadCommandContext, value: string, p: CadPoint3, height: number, rotation = 0, styleName?: string) => {
	const t = new AcDbText();
	t.textString = value;
	t.position = point(p);
	t.height = height;
	t.rotation = rotation;
	t.layer = ctx.database.native.clayer;
	t.styleName = styleName ?? ctx.database.native.textstyle;
	return t;
};

export async function textCommand(ctx: CadCommandContext): Promise<void> {
	let startPoint: CadPoint3 | undefined;
	let hmode = AcDbTextHorizontalMode.LEFT;
	let vmode = AcDbTextVerticalMode.BASELINE;
	let currentStyle = ctx.database.native.textstyle;

	const justificationKeywords = [
		'TL', 'TC', 'TR', 'ML', 'MC', 'MR', 'BL', 'BC', 'BR',
		'Left', 'Center', 'Right', 'Align', 'Middle', 'Fit',
	] as const;

	const modeMap: Record<string, [AcDbTextHorizontalMode, AcDbTextVerticalMode]> = {
		tl: [AcDbTextHorizontalMode.LEFT, AcDbTextVerticalMode.TOP],
		tc: [AcDbTextHorizontalMode.CENTER, AcDbTextVerticalMode.TOP],
		tr: [AcDbTextHorizontalMode.RIGHT, AcDbTextVerticalMode.TOP],
		ml: [AcDbTextHorizontalMode.LEFT, AcDbTextVerticalMode.MIDDLE],
		mc: [AcDbTextHorizontalMode.CENTER, AcDbTextVerticalMode.MIDDLE],
		mr: [AcDbTextHorizontalMode.RIGHT, AcDbTextVerticalMode.MIDDLE],
		bl: [AcDbTextHorizontalMode.LEFT, AcDbTextVerticalMode.BOTTOM],
		bc: [AcDbTextHorizontalMode.CENTER, AcDbTextVerticalMode.BOTTOM],
		br: [AcDbTextHorizontalMode.RIGHT, AcDbTextVerticalMode.BOTTOM],
		left: [AcDbTextHorizontalMode.LEFT, AcDbTextVerticalMode.BASELINE],
		center: [AcDbTextHorizontalMode.CENTER, AcDbTextVerticalMode.BASELINE],
		right: [AcDbTextHorizontalMode.RIGHT, AcDbTextVerticalMode.BASELINE],
		align: [AcDbTextHorizontalMode.ALIGNED, AcDbTextVerticalMode.BASELINE],
		middle: [AcDbTextHorizontalMode.MIDDLE, AcDbTextVerticalMode.MIDDLE],
		fit: [AcDbTextHorizontalMode.FIT, AcDbTextVerticalMode.BASELINE],
	};

	while (!startPoint) {
		if (typeof ctx.getPointPick === 'function') {
			const res = await ctx.getPointPick('Specify start point of text or [Justify/Style]:', {
				keywords: ['Justify', 'Style'],
			});
			if (res.status === 'cancel' || res.status === 'none') return;
			if (res.status === 'keyword') {
				const kw = res.keyword?.toLowerCase();
				if (kw === 'justify' || kw === 'j') {
					const just = await ctx.getKeyword(
						'Enter an option [TL/TC/TR/ML/MC/MR/BL/BC/BR/Left/Center/Right/Align/Middle/Fit] <Left>:',
						justificationKeywords,
						{ default: 'Left' },
					);
					const [h, v] = modeMap[just.toLowerCase()] ?? modeMap.left;
					hmode = h;
					vmode = v;
					startPoint = await ctx.getPoint('Specify justification point:');
					break;
				} else if (kw === 'style' || kw === 's') {
					const styleName = await ctx.getString('Enter style name:', { allowSpaces: false });
					if (!ctx.database.native.tables.textStyleTable.has(styleName)) {
						throw new Error(`Text style "${styleName}" does not exist`);
					}
					currentStyle = styleName;
					ctx.database.native.textstyle = styleName;
					continue;
				}
			} else if (res.status === 'ok' && res.point) {
				startPoint = res.point;
				break;
			}
		} else {
			startPoint = await ctx.getPoint('Specify start point of text or [Justify/Style]:');
			break;
		}
	}

	if (!startPoint) return;

	const styleRecord = ctx.database.native.tables.textStyleTable.has(currentStyle)
		? ctx.database.native.tables.textStyleTable.getAt(currentStyle)
		: undefined;
	let actualHeight = rememberedHeight;
	if (styleRecord && typeof styleRecord.textSize === 'number' && styleRecord.textSize > 0) {
		actualHeight = styleRecord.textSize;
	} else {
		const heightRaw = await ctx.getString(`Specify height <${rememberedHeight}>:`, {
			allowSpaces: false,
			allowEmpty: true,
			defaultValue: String(rememberedHeight),
		});
		const parsed = heightRaw.trim() === '' ? rememberedHeight : Number(heightRaw);
		if (!Number.isFinite(parsed) || parsed <= 0) throw new Error('Text height must be positive');
		actualHeight = parsed;
		rememberedHeight = actualHeight;
	}

	const rotationRaw = await ctx.getString('Specify rotation angle of text <0>:', {
		allowSpaces: false,
		allowEmpty: true,
		defaultValue: '0',
	});
	const degrees = rotationRaw.trim() === '' ? 0 : Number(rotationRaw);
	if (!Number.isFinite(degrees)) throw new Error('Invalid rotation angle');
	const rotation = degrees * Math.PI / 180;

	let lineCount = 0;
	while (true) {
		const value = await ctx.getString('Enter text:', { allowSpaces: true, allowEmpty: true });
		if (!value) break;

		const lineOffset = lineCount * 1.5 * actualHeight;
		const p: CadPoint3 = {
			x: startPoint.x + lineOffset * Math.sin(rotation),
			y: startPoint.y - lineOffset * Math.cos(rotation),
			z: startPoint.z,
		};
		const t = makeText(ctx, value, p, actualHeight, rotation, currentStyle);
		t.horizontalMode = hmode;
		t.verticalMode = vmode;
		if (hmode !== AcDbTextHorizontalMode.LEFT || vmode !== AcDbTextVerticalMode.BASELINE) {
			t.alignmentPoint = point(p);
		}
		ctx.database.add(t);
		lineCount++;
	}
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
	const db = ctx.database.native;
	const currentStyleName = db?.cmleaderstyle || 'Standard';
	const currentStyle = db?.objects?.mleaderStyle?.getAt?.(currentStyleName);
	const textHeight = (currentStyle && currentStyle.textHeight > 0) ? currentStyle.textHeight : rememberedHeight;
	const leader=new AcDbMLeader();
	leader.contentType = (currentStyle?.contentType !== undefined) ? currentStyle.contentType : AcDbMLeaderContentType.MTextContent;
	if (currentStyle?.objectId) leader.mleaderStyleId = currentStyle.objectId;
	if (currentStyle && currentStyle.arrowSize > 0) leader.arrowheadSize = currentStyle.arrowSize;
	if (currentStyle?.landingGap !== undefined && currentStyle.landingGap > 0) leader.landingGap = currentStyle.landingGap;
	if (currentStyle?.doglegLength !== undefined && currentStyle.doglegLength > 0) leader.doglegLength = currentStyle.doglegLength;
	if (currentStyle?.enableDogleg !== undefined) leader.doglegEnabled = currentStyle.enableDogleg;
	if (currentStyle?.enableLanding !== undefined) leader.landingEnabled = currentStyle.enableLanding;
	leader.addLeader({landingPoint:point(landing),leaderLines:[{vertices:[point(arrow),point(landing)]}]});
	leader.contents=content;
	leader.textLocation=landing;
	leader.textHeight=textHeight;
	leader.textStyleName=ctx.database.native.textstyle;
	ctx.database.add(leader);
}

export async function centerMarkCommand(ctx: CadCommandContext): Promise<void> {
	const e = await ctx.getEntity('Select circle or arc:');
	if (!(e instanceof AcDbCircle) && !(e instanceof AcDbArc)) throw new Error('Select a circle or arc');
	const center = e.center;
	const radius = e.radius;
	const size = getDrawingDimcen(ctx.database.native);
	const segs = centerMarkSegments(center, size, radius);
	const lines = segs.map(s => {
		const line = new AcDbLine(point(s.start), point(s.end));
		line.layer = ctx.database.native.clayer;
		return line;
	});
	ctx.database.add(lines);
}

export async function tableCommand(ctx: CadCommandContext): Promise<void> {
	const origin=await ctx.getPoint('Specify table insertion point:'); const rows=await ctx.getInteger('Number of rows:',{min:1}); const cols=await ctx.getInteger('Number of columns:',{min:1}); const rh=await ctx.getDouble('Row height:'); const cw=await ctx.getDouble('Column width:');
	const curStyle = getCurrentTableStyle(ctx.database.native);
	const textHeight = curStyle?.dataTextHeight ?? curStyle?.textHeight ?? rememberedHeight;
	const entities:AcDbEntity[]=tableGrid(rows,cols,rh,cw,origin).map(s=>new AcDbLine(point(s.start),point(s.end)));
	const header=await ctx.getKeyword('Add header row text?', ['Yes','No'],{default:'No'});
	if(header==='Yes') for(let c=0;c<cols;c++){const v=await ctx.getString(`Header column ${c+1}:`,{allowSpaces:true});const t=new AcDbMText();t.contents=v;t.location=new AcGePoint3d(origin.x+c*cw+cw*.1,origin.y-rh*.75,origin.z);t.height=textHeight;entities.push(t);}
	ctx.database.add(entities);
}

export function registerAnnotationCommands(): void {
	registerCommand('TEXT', textCommand, {aliases:['DTEXT','DT']}); registerCommand('TEXTEDIT',textEditCommand,{aliases:['DDEDIT','ED']}); registerCommand('STYLE',styleCommand,{aliases:['ST']}); registerCommand('MLEADER',mleaderCommand,{aliases:['MLD']}); registerCommand('CENTERMARK',centerMarkCommand,{aliases:['CM']}); registerCommand('TABLE',tableCommand,{aliases:['TB']});
}
