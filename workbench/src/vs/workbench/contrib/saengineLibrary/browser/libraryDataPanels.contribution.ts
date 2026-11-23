/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, IDataPanelAction, IEngineDataPanelDescriptor, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';

const category = localize2('saengine.category', "SAEngine");
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

interface IJsonBag {
	readonly [key: string]: unknown;
}

function asBag(value: unknown): IJsonBag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as IJsonBag : {};
}

function asArray(value: unknown): readonly unknown[] {
	return Array.isArray(value) ? value : [];
}

function asStrings(value: unknown): string[] {
	return asArray(value).filter((v): v is string => typeof v === 'string' && !!v);
}

function str(value: unknown, fallback = ''): string {
	return typeof value === 'string' ? value : typeof value === 'number' || typeof value === 'boolean' ? String(value) : fallback;
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function formatScalar(value: unknown): string {
	if (value === null || value === undefined || value === '') {
		return '–';
	}
	if (typeof value === 'boolean') {
		return value ? 'Yes' : 'No';
	}
	if (typeof value === 'number') {
		// Engine floats (17.255999999999997) read as 17.256.
		return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
	}
	if (typeof value === 'string') {
		return value;
	}
	return JSON.stringify(value);
}

function registerLibraryPanel(descriptor: IEngineDataPanelDescriptor): void {
	registerEngineDataPanel(descriptor);
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: descriptor.id,
				title: { value: descriptor.title, original: descriptor.title },
				category,
				icon: descriptor.icon,
				f1: true,
				precondition: descriptor.requiresProject === false ? undefined : projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), descriptor.id);
		}
	});
}

function openMaterialsAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openMaterials',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showMaterials'),
	}];
}

function openObjectsAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openObjects',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showObjects'),
	}];
}

//#region Materials

registerLibraryPanel({
	id: 'saengine.library.materialSummary',
	title: localize('u6d.lib.mat.title', "Materials Properties & Plausibility"),
	part: 'library',
	icon: Codicon.beaker,
	help: localize('u6d.lib.mat.help', "Summarizes project materials with computed ACI concrete modulus Ec, modulus of rupture fr, and plausibility checks."),
	secondaryActions: openMaterialsAction(localize('u6d.lib.openMat', "Open Materials")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/materialSummary', { projectRoot: ctx.project!.root.fsPath }));
		const mats = asArray(raw.materials).map(asBag);
		const rows: DataPanelRow[] = mats.map(m => ({
			id: str(m.id),
			category: str(m.category),
			name: str(m.name),
			density: num(m.density) ?? '–',
			e: num(m.e) ?? '–',
			fc: num(m.fc) ?? '–',
			fy: num(m.fy) ?? '–',
			ecCalc: num(m.ecCalc) ?? '–',
			frCalc: num(m.frCalc) ?? '–',
			warnings: str(m.warnings, 'OK') === 'OK' ? 'Pass' : str(m.warnings),
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.mat.mCount', "Materials"), value: String(rows.length) },
				{ label: localize('u6d.lib.mat.mWarn', "Warnings"), value: String(rows.filter(r => r.warnings !== 'Pass').length) },
			],
			tables: [{
				id: 'materials',
				title: localize('u6d.lib.mat.tab', "Project Materials Summary"),
				columns: [
					{ key: 'id', title: localize('u6d.lib.mat.colId', "ID") },
					{ key: 'category', title: localize('u6d.lib.mat.colCat', "Category") },
					{ key: 'name', title: localize('u6d.lib.mat.colName', "Name") },
					{ key: 'density', title: localize('u6d.lib.mat.colDens', "Density [kg/m³]"), type: 'number', align: 'right' },
					{ key: 'e', title: localize('u6d.lib.mat.colE', "E [MPa]"), type: 'number', align: 'right' },
					{ key: 'fc', title: localize('u6d.lib.mat.colFc', "f'c [MPa]"), type: 'number', align: 'right' },
					{ key: 'fy', title: localize('u6d.lib.mat.colFy', "fy [MPa]"), type: 'number', align: 'right' },
					{ key: 'ecCalc', title: localize('u6d.lib.mat.colEc', "Calc Ec [MPa]"), type: 'number', align: 'right' },
					{ key: 'frCalc', title: localize('u6d.lib.mat.colFr', "fr [MPa]"), type: 'number', align: 'right' },
					{ key: 'warnings', title: localize('u6d.lib.mat.colWarn', "Check"), type: 'status' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.concreteCalc',
	title: localize('u6d.lib.conc.title', "Concrete Modulus & Nominal Mix Calculator"),
	part: 'library',
	icon: Codicon.symbolNumeric,
	help: localize('u6d.lib.conc.help', "Computes ACI 318 concrete modulus Ec = 4700√f'c, modulus of rupture fr = 0.62√f'c, and nominal concrete mix strength."),
	fields: [
		{ key: 'fc', label: localize('u6d.lib.conc.fc', "Concrete Strength f'c [MPa]"), type: 'number', defaultValue: 28, min: 5, max: 120 },
		{ key: 'mixRatio', label: localize('u6d.lib.conc.mix', "Nominal Mix Ratio (e.g. 1:2:4 or 1:1.5:3)"), type: 'text', defaultValue: '1:2:4' },
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('library/materialSummary', {
			projectRoot: ctx.project!.root.fsPath,
			fc: Number(values.fc) || 28,
			mixRatio: String(values.mixRatio || '1:2:4'),
		}));
		const calc = asBag(raw.calculator);
		const rows: DataPanelRow[] = [
			{ property: 'Cylinder Strength f\'c [MPa]', value: formatScalar(calc.fc) },
			{ property: 'Elastic Modulus Ec = 4700√f\'c [MPa]', value: formatScalar(calc.ecMpa) },
			{ property: 'Modulus of Rupture fr = 0.62√f\'c [MPa]', value: formatScalar(calc.frMpa) },
			{ property: `Nominal Mix (${str(calc.mixRatio, '1:2:4')}) Strength [MPa]`, value: formatScalar(calc.nominalMixFc) },
		];
		return {
			metrics: [
				{ label: localize('u6d.lib.conc.mEc', "Ec"), value: calc.ecMpa !== undefined ? `${str(calc.ecMpa)} MPa` : '–' },
				{ label: localize('u6d.lib.conc.mFr', "fr"), value: calc.frMpa !== undefined ? `${str(calc.frMpa)} MPa` : '–' },
				{ label: localize('u6d.lib.conc.mMix', "Nominal Mix f'c"), value: calc.nominalMixFc !== undefined && calc.nominalMixFc !== null ? `${str(calc.nominalMixFc)} MPa` : '–' },
			],
			tables: [{
				id: 'calc',
				title: localize('u6d.lib.conc.tab', "Concrete Mechanical Properties"),
				columns: [
					{ key: 'property', title: localize('u6d.lib.conc.colProp', "Property") },
					{ key: 'value', title: localize('u6d.lib.conc.colVal', "Value") },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Sections & Catalogues

registerLibraryPanel({
	id: 'saengine.library.designedSections',
	title: localize('u6d.lib.ds.title', "Designed Sections Inventory"),
	part: 'library',
	icon: Codicon.symbolRuler,
	help: localize('u6d.lib.ds.help', "Inventories all custom sections saved in 04 Objects/sections/*.json with region/bar counts, section area, moments of inertia and geometry checks."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/designedSections', {
			projectRoot: ctx.project!.root.fsPath,
			capacity: false,
		}));
		const secs = asArray(raw.sections).map(asBag);
		const rows: DataPanelRow[] = secs.map(s => ({
			id: str(s.id),
			regions: num(s.regions) ?? 0,
			bars: num(s.bars) ?? 0,
			areaMm2: num(s.areaMm2) ?? '–',
			ixMm4: num(s.ixMm4) ?? '–',
			iyMm4: num(s.iyMm4) ?? '–',
			status: str(s.status, 'Pass'),
			note: str(s.note, 'OK'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.ds.mCount', "Designed Sections"), value: String(rows.length) },
			],
			tables: [{
				id: 'sections',
				title: localize('u6d.lib.ds.tab', "Custom Designed Sections"),
				columns: [
					{ key: 'id', title: localize('u6d.lib.ds.colId', "Section ID") },
					{ key: 'regions', title: localize('u6d.lib.ds.colReg', "Regions"), type: 'number', align: 'right' },
					{ key: 'bars', title: localize('u6d.lib.ds.colBars', "Bars"), type: 'number', align: 'right' },
					{ key: 'areaMm2', title: localize('u6d.lib.ds.colA', "Area [mm²]"), type: 'number', align: 'right' },
					{ key: 'ixMm4', title: localize('u6d.lib.ds.colIx', "Ix [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'iyMm4', title: localize('u6d.lib.ds.colIy', "Iy [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'status', title: localize('u6d.lib.ds.colStat', "Status"), type: 'status' },
					{ key: 'note', title: localize('u6d.lib.ds.colNote', "Notes") },
				],
				rows,
				emptyMessage: localize('u6d.lib.ds.empty', "No custom sections saved in 04 Objects/sections yet."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.sectionCapacity',
	title: localize('u6d.lib.secCap.title', "Section Capacity (P-M & Moment-Curvature)"),
	part: 'library',
	icon: Codicon.graphLine,
	help: localize('u6d.lib.secCap.help', "Computes uniaxial P-Mx / P-My interaction diagrams and optional fibre moment-curvature M-κ curve for a designed section."),
	fields: [
		{ key: 'sectionId', label: localize('u6d.lib.secCap.id', "Designed Section"), type: 'select', defaultValue: '', options: [{ value: '', label: localize('u6d.lib.secCap.first', "First Section") }] },
		{ key: 'momentCurvature', label: localize('u6d.lib.secCap.mc', "Compute Moment-Curvature M-κ"), type: 'checkbox', defaultValue: true },
		{ key: 'axialKn', label: localize('u6d.lib.secCap.ax', "Axial Load for M-κ [kN]"), type: 'number', defaultValue: 0 },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const raw = asBag(await ctx.engineRequest('library/designedSections', {
			projectRoot: ctx.project.root.fsPath,
			capacity: false,
		}));
		const ids = asStrings(raw.availableSections);
		if (!ids.length) {
			return undefined;
		}
		return {
			options: { sectionId: ids.map(id => ({ value: id, label: id })) },
			values: { sectionId: ids[0] },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('library/designedSections', {
			projectRoot: ctx.project!.root.fsPath,
			sectionId: String(values.sectionId || '') || undefined,
			capacity: true,
			momentCurvature: Boolean(values.momentCurvature),
			axialKn: Number(values.axialKn) || 0,
		}));
		const analysis = asBag(raw.analysis);
		const props = asBag(analysis.properties);
		const uniaxial = asBag(analysis.uniaxial);
		const mc = asBag(analysis.momentCurvature);
		const propRows: DataPanelRow[] = Object.entries(props).map(([k, v]) => ({
			property: k,
			value: formatScalar(v),
		}));
		const xPts = asArray(asBag(uniaxial.x).points ?? uniaxial.x).map(asBag);
		const yPts = asArray(asBag(uniaxial.y).points ?? uniaxial.y).map(asBag);
		const interactRows: DataPanelRow[] = [
			...xPts.map(pt => ({ axis: 'Mx', p: num(pt.P ?? pt.p ?? pt.n) ?? 0, m: num(pt.M ?? pt.m ?? pt.mx) ?? 0 })),
			...yPts.map(pt => ({ axis: 'My', p: num(pt.P ?? pt.p ?? pt.n) ?? 0, m: num(pt.M ?? pt.m ?? pt.my) ?? 0 })),
		];
		const mcRows: DataPanelRow[] = asArray(mc.curve ?? mc.points).map(asBag).map(pt => ({
			kappa: num(pt.kappa ?? pt.k) ?? 0,
			moment: num(pt.moment ?? pt.m) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.secCap.mSec', "Section"), value: str(raw.sectionId, '–') },
				{ label: localize('u6d.lib.secCap.mKind', "Capacity Kind"), value: str(analysis.capacityKind, '–') },
				{ label: localize('u6d.lib.secCap.mMc', "M-κ Points"), value: String(mcRows.length) },
			],
			tables: [
				{
					id: 'props',
					title: localize('u6d.lib.secCap.propTab', "Section Properties"),
					columns: [
						{ key: 'property', title: localize('u6d.lib.secCap.colProp', "Property") },
						{ key: 'value', title: localize('u6d.lib.secCap.colVal', "Value") },
					],
					rows: propRows,
				},
				{
					id: 'pm',
					title: localize('u6d.lib.secCap.pmTab', "Uniaxial P-M Interaction"),
					columns: [
						{ key: 'axis', title: localize('u6d.lib.secCap.colAxis', "Axis") },
						{ key: 'p', title: localize('u6d.lib.secCap.colP', "Axial P"), type: 'number', align: 'right' },
						{ key: 'm', title: localize('u6d.lib.secCap.colM', "Moment M"), type: 'number', align: 'right' },
					],
					rows: interactRows,
				},
				{
					id: 'mc',
					title: localize('u6d.lib.secCap.mcTab', "Moment-Curvature Curve"),
					columns: [
						{ key: 'kappa', title: localize('u6d.lib.secCap.colKap', "Curvature κ"), type: 'number', align: 'right' },
						{ key: 'moment', title: localize('u6d.lib.secCap.colMom', "Moment M"), type: 'number', align: 'right' },
					],
					rows: mcRows,
				},
			],
			notes: [...asStrings(raw.notes), ...(analysis.capacityNote ? [str(analysis.capacityNote)] : [])],
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.steelCatalogue',
	title: localize('u6d.lib.steel.title', "Standard Rolled & Hollow Steel Sections"),
	part: 'library',
	icon: Codicon.library,
	requiresProject: false,
	help: localize('u6d.lib.steel.help', "Searchable catalogue of standard I, channel, tee, angle, RHS, CHS, bar and round steel sections with geometric properties."),
	fields: [
		{
			key: 'family',
			label: localize('u6d.lib.steel.fam', "Family Filter"),
			type: 'select',
			defaultValue: 'all',
			options: [
				{ value: 'all', label: localize('u6d.lib.steel.all', "All Families") },
				{ value: 'W', label: 'AISC W' },
				{ value: 'UB', label: 'BS UB' },
				{ value: 'UC', label: 'BS UC' },
				{ value: 'IPE', label: 'EN IPE' },
				{ value: 'HEA', label: 'EN HEA' },
				{ value: 'HEB', label: 'EN HEB' },
				{ value: 'RHS', label: 'RHS' },
				{ value: 'CHS', label: 'CHS' },
			],
		},
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('library/steelSections', {}));
		const all = asArray(raw.sections).map(asBag);
		const fam = String(values.family || 'all');
		const filtered = fam === 'all' ? all : all.filter(s => str(s.family).toUpperCase() === fam.toUpperCase() || str(s.name).toUpperCase().startsWith(fam.toUpperCase()));
		const rows: DataPanelRow[] = filtered.slice(0, 1000).map(s => ({
			name: str(s.name),
			family: str(s.family),
			shape: str(s.shape),
			mass: num(s.mass) ?? '–',
			area: num(s.area) ?? '–',
			ix: num(s.ix) ?? num(s.Ix) ?? '–',
			iy: num(s.iy) ?? num(s.Iy) ?? '–',
			sx: num(s.sx) ?? num(s.Zx) ?? '–',
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.steel.mTotal', "Catalogue Sections"), value: String(all.length) },
				{ label: localize('u6d.lib.steel.mShown', "Matching"), value: String(filtered.length) },
			],
			tables: [{
				id: 'steel',
				title: localize('u6d.lib.steel.tab', "Steel Sections Catalogue"),
				columns: [
					{ key: 'name', title: localize('u6d.lib.steel.colName', "Designation") },
					{ key: 'family', title: localize('u6d.lib.steel.colFam', "Family") },
					{ key: 'shape', title: localize('u6d.lib.steel.colShape', "Shape") },
					{ key: 'mass', title: localize('u6d.lib.steel.colMass', "Mass [kg/m]"), type: 'number', align: 'right' },
					{ key: 'area', title: localize('u6d.lib.steel.colArea', "Area [mm²]"), type: 'number', align: 'right' },
					{ key: 'ix', title: localize('u6d.lib.steel.colIx', "Ix [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'iy', title: localize('u6d.lib.steel.colIy', "Iy [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'sx', title: localize('u6d.lib.steel.colSx', "Zx / Sx [mm³]"), type: 'number', align: 'right' },
				],
				rows,
			}],
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.sheetPiles',
	title: localize('u6d.lib.sp.title', "Steel Sheet Pile Sections Catalogue"),
	part: 'library',
	icon: Codicon.layoutPanel,
	requiresProject: false,
	help: localize('u6d.lib.sp.help', "Nominal U and Z steel sheet pile section properties per metre of excavation wall (modulus W, inertia I and mass)."),
	fields: [
		{
			key: 'shape',
			label: localize('u6d.lib.sp.shape', "Profile Shape"),
			type: 'select',
			defaultValue: 'all',
			options: [
				{ value: 'all', label: localize('u6d.lib.sp.all', "All (U & Z)") },
				{ value: 'U', label: 'U Sections' },
				{ value: 'Z', label: 'Z Sections' },
			],
		},
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('library/sheetPiles', { shape: String(values.shape || 'all') }));
		const rows: DataPanelRow[] = asArray(raw.sections).map(asBag).map(s => ({
			name: str(s.name),
			shape: str(s.shape),
			widthMm: num(s.widthMm) ?? 0,
			heightMm: num(s.heightMm) ?? 0,
			wCm3PerM: num(s.wCm3PerM) ?? 0,
			iCm4PerM: num(s.iCm4PerM) ?? 0,
			massKgPerM2: num(s.massKgPerM2) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.sp.mCount', "Sections"), value: String(rows.length) },
			],
			tables: [{
				id: 'sheetPiles',
				title: localize('u6d.lib.sp.tab', "Sheet Pile Catalogue"),
				columns: [
					{ key: 'name', title: localize('u6d.lib.sp.colName', "Section") },
					{ key: 'shape', title: localize('u6d.lib.sp.colShape', "Shape") },
					{ key: 'widthMm', title: localize('u6d.lib.sp.colW', "Width [mm]"), type: 'number', align: 'right' },
					{ key: 'heightMm', title: localize('u6d.lib.sp.colH', "Height [mm]"), type: 'number', align: 'right' },
					{ key: 'wCm3PerM', title: localize('u6d.lib.sp.colMod', "W [cm³/m]"), type: 'number', align: 'right' },
					{ key: 'iCm4PerM', title: localize('u6d.lib.sp.colIn', "I [cm⁴/m]"), type: 'number', align: 'right' },
					{ key: 'massKgPerM2', title: localize('u6d.lib.sp.colMass', "Mass [kg/m²]"), type: 'number', align: 'right' },
				],
				rows,
			}],
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.profileProperties',
	title: localize('u6d.lib.prof.title', "Object Type Section Properties"),
	part: 'library',
	icon: Codicon.symbolField,
	help: localize('u6d.lib.prof.help', "Computes cross-sectional area, second moments of area (Ix, Iy), torsional constant J, radii of gyration and plastic moduli for all object types."),
	secondaryActions: openObjectsAction(localize('u6d.lib.openObj', "Open Object Types")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/objectSections', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asArray(raw.objects).map(asBag).map(o => ({
			id: str(o.id),
			kind: str(o.kind),
			shape: str(o.shape, '–'),
			areaMm2: num(o.areaMm2) ?? '–',
			ixMm4: num(o.ixMm4) ?? '–',
			iyMm4: num(o.iyMm4) ?? '–',
			jMm4: num(o.jMm4) ?? '–',
			rxMm: num(o.rxMm) ?? '–',
			ryMm: num(o.ryMm) ?? '–',
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.prof.mCount', "Object Types"), value: String(rows.length) },
			],
			tables: [{
				id: 'profiles',
				title: localize('u6d.lib.prof.tab', "Object Type Section Properties"),
				columns: [
					{ key: 'id', title: localize('u6d.lib.prof.colId', "Object Type") },
					{ key: 'kind', title: localize('u6d.lib.prof.colKind', "Kind") },
					{ key: 'shape', title: localize('u6d.lib.prof.colShape', "Profile") },
					{ key: 'areaMm2', title: localize('u6d.lib.prof.colA', "Area [mm²]"), type: 'number', align: 'right' },
					{ key: 'ixMm4', title: localize('u6d.lib.prof.colIx', "Ix [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'iyMm4', title: localize('u6d.lib.prof.colIy', "Iy [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'jMm4', title: localize('u6d.lib.prof.colJ', "J [mm⁴]"), type: 'number', align: 'right' },
					{ key: 'rxMm', title: localize('u6d.lib.prof.colRx', "rx [mm]"), type: 'number', align: 'right' },
					{ key: 'ryMm', title: localize('u6d.lib.prof.colRy', "ry [mm]"), type: 'number', align: 'right' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Object Types & Architectural Types

registerLibraryPanel({
	id: 'saengine.library.objectSchedule',
	title: localize('u6d.lib.objSched.title', "Object Types Summary"),
	part: 'library',
	icon: Codicon.symbolClass,
	help: localize('u6d.lib.objSched.help', "Summarizes all structural object types in 04 Objects/objects.json by kind, assigned material, profile shape and modifier overrides."),
	secondaryActions: openObjectsAction(localize('u6d.lib.openObj', "Open Object Types")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/objectSections', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asArray(raw.objects).map(asBag).map(o => ({
			id: str(o.id),
			kind: str(o.kind),
			material: str(o.material, '–'),
			shape: str(o.shape, '–'),
			modifiersCount: num(o.modifiersCount) ?? 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.os.mCount', "Object Types"), value: String(rows.length) },
				{ label: localize('u6d.lib.os.mMods', "With Modifiers"), value: String(rows.filter(r => (num(r.modifiersCount) ?? 0) > 0).length) },
			],
			tables: [{
				id: 'objectSchedule',
				title: localize('u6d.lib.os.tab', "Structural Object Types"),
				columns: [
					{ key: 'id', title: localize('u6d.lib.os.colId', "ID") },
					{ key: 'kind', title: localize('u6d.lib.os.colKind', "Kind") },
					{ key: 'material', title: localize('u6d.lib.os.colMat', "Material") },
					{ key: 'shape', title: localize('u6d.lib.os.colShape', "Profile") },
					{ key: 'modifiersCount', title: localize('u6d.lib.os.colMods', "Modifiers"), type: 'number', align: 'right' },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.archTypes',
	title: localize('u6d.lib.arch.title', "Architectural Types Browser"),
	part: 'library',
	icon: Codicon.typeHierarchy,
	help: localize('u6d.lib.arch.help', "Lists architectural wall, door, window, roof, ceiling and floor finish types with their instance counts."),
	fields: [
		{
			key: 'category',
			label: localize('u6d.lib.arch.cat', "Category"),
			type: 'select',
			defaultValue: 'all',
			options: [
				{ value: 'all', label: localize('u6d.lib.arch.all', "All Categories") },
				{ value: 'wallTypes', label: localize('u6d.lib.arch.walls', "Wall Types") },
				{ value: 'doorTypes', label: localize('u6d.lib.arch.doors', "Door Types") },
				{ value: 'windowTypes', label: localize('u6d.lib.arch.windows', "Window Types") },
				{ value: 'roofTypes', label: localize('u6d.lib.arch.roofs', "Roof Types") },
				{ value: 'flooringTypes', label: localize('u6d.lib.arch.flooring', "Flooring Types") },
				{ value: 'ceilingTypes', label: localize('u6d.lib.arch.ceiling', "Ceiling Types") },
			],
		},
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('library/archTypes', {
			projectRoot: ctx.project!.root.fsPath,
			category: String(values.category || 'all'),
		}));
		const rows: DataPanelRow[] = asArray(raw.types).map(asBag).map(t => ({
			category: str(t.category),
			id: str(t.id),
			name: str(t.name, str(t.id)),
			usages: num(t.usageCount) ?? num(t.usages) ?? 0,
			summary: str(t.summary, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.arch.mCount', "Types"), value: String(rows.length) },
			],
			tables: [{
				id: 'archTypes',
				title: localize('u6d.lib.arch.tab', "Architectural Types"),
				columns: [
					{ key: 'category', title: localize('u6d.lib.arch.colCat', "Category") },
					{ key: 'id', title: localize('u6d.lib.arch.colId', "ID") },
					{ key: 'name', title: localize('u6d.lib.arch.colName', "Name") },
					{ key: 'usages', title: localize('u6d.lib.arch.colUse', "Usages"), type: 'number', align: 'right' },
					{ key: 'summary', title: localize('u6d.lib.arch.colSum', "Summary") },
				],
				rows,
				emptyMessage: localize('u6d.lib.arch.empty', "No architectural types defined for this category."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.components',
	title: localize('u6d.lib.comp.title', "Parametric Component Library & Schedule"),
	part: 'library',
	icon: Codicon.extensions,
	help: localize('u6d.lib.comp.help', "Inspects starter architectural component types (furniture, fixtures, casework, equipment) and placed component counts."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/archTypes', { projectRoot: ctx.project!.root.fsPath }));
		const starter = asArray(raw.starterComponents).map(asBag);
		const sched = asBag(raw.componentSchedule);
		const placed = asArray(sched.items ?? sched.rows ?? sched.byType).map(asBag);
		const starterRows: DataPanelRow[] = starter.map(c => ({
			id: str(c.id),
			name: str(c.name, str(c.id)),
			category: str(c.category),
			widthMm: num(c.width) ?? num(c.defaultWidth) ?? '–',
			depthMm: num(c.depth) ?? num(c.defaultDepth) ?? '–',
		}));
		const placedRows: DataPanelRow[] = placed.map(p => ({
			type: str(p.type || p.id),
			category: str(p.category, '–'),
			room: str(p.room, '–'),
			story: str(p.story, '–'),
			count: num(p.count) ?? 1,
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.comp.mStarter', "Starter Components"), value: String(starterRows.length) },
				{ label: localize('u6d.lib.comp.mPlaced', "Placed Items"), value: String(placedRows.length) },
			],
			tables: [
				{
					id: 'starter',
					title: localize('u6d.lib.comp.startTab', "Starter Component Catalogue"),
					columns: [
						{ key: 'id', title: localize('u6d.lib.comp.colId', "ID") },
						{ key: 'name', title: localize('u6d.lib.comp.colName', "Name") },
						{ key: 'category', title: localize('u6d.lib.comp.colCat', "Category") },
						{ key: 'widthMm', title: localize('u6d.lib.comp.colW', "Width [mm]"), type: 'number', align: 'right' },
						{ key: 'depthMm', title: localize('u6d.lib.comp.colD', "Depth [mm]"), type: 'number', align: 'right' },
					],
					rows: starterRows,
				},
				{
					id: 'placed',
					title: localize('u6d.lib.comp.placedTab', "Placed Component Schedule"),
					columns: [
						{ key: 'type', title: localize('u6d.lib.comp.colPType', "Type") },
						{ key: 'category', title: localize('u6d.lib.comp.colPCat', "Category") },
						{ key: 'room', title: localize('u6d.lib.comp.colPRoom', "Room") },
						{ key: 'story', title: localize('u6d.lib.comp.colPStory', "Story") },
						{ key: 'count', title: localize('u6d.lib.comp.colPCount', "Count"), type: 'number', align: 'right' },
					],
					rows: placedRows,
					emptyMessage: localize('u6d.lib.comp.emptyPlaced', "No architectural components placed yet."),
				},
			],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.barSizes',
	title: localize('u6d.lib.bars.title', "Code Pack Rebar Sizes & Unit Masses"),
	part: 'library',
	icon: Codicon.listOrdered,
	help: localize('u6d.lib.bars.help', "Lists the active design code pack's permitted rebar diameters and nominal linear masses [kg/m]."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/materialSummary', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asArray(raw.barSizes).map(asBag).map(b => ({
			diameterMm: num(b.diameterMm) ?? 0,
			massKgPerM: num(b.massKgPerM) ?? 0,
			areaMm2: num(b.diameterMm) ? Number((Math.PI * Math.pow(num(b.diameterMm)!, 2) / 4).toFixed(1)) : 0,
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.bars.mCount', "Standard Sizes"), value: String(rows.length) },
			],
			tables: [{
				id: 'bars',
				title: localize('u6d.lib.bars.tab', "Standard Reinforcing Bar Sizes"),
				columns: [
					{ key: 'diameterMm', title: localize('u6d.lib.bars.colDia', "Diameter [mm]"), type: 'number', align: 'right' },
					{ key: 'areaMm2', title: localize('u6d.lib.bars.colArea', "Area [mm²]"), type: 'number', align: 'right' },
					{ key: 'massKgPerM', title: localize('u6d.lib.bars.colMass', "Mass [kg/m]"), type: 'number', align: 'right' },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

//#endregion

//#region Modifiers & Library Checks

registerLibraryPanel({
	id: 'saengine.library.modifiersAudit',
	title: localize('u6d.lib.mods.title', "Stiffness Modifiers Audit"),
	part: 'library',
	icon: Codicon.settings,
	help: localize('u6d.lib.mods.help', "Audits cracked-section stiffness modifiers (EI, EA, GJ) configured on object types and overridden per floor-plan member."),
	secondaryActions: openObjectsAction(localize('u6d.lib.openObj', "Open Object Types")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/objectSections', { projectRoot: ctx.project!.root.fsPath }));
		const mods = asArray(raw.modifiers).map(asBag);
		const rows: DataPanelRow[] = mods.map(m => ({
			target: str(m.target),
			scope: str(m.scope),
			kind: str(m.kind),
			values: Object.entries(m).filter(([k]) => !['target', 'scope', 'kind'].includes(k)).map(([k, v]) => `${k}=${formatScalar(v)}`).join(', '),
		}));
		return {
			metrics: [
				{ label: localize('u6d.lib.mods.mCount', "Modified Items"), value: String(rows.length) },
			],
			tables: [{
				id: 'modifiers',
				title: localize('u6d.lib.mods.tab', "Resolved Stiffness Modifiers"),
				columns: [
					{ key: 'target', title: localize('u6d.lib.mods.colTgt', "Object / Member") },
					{ key: 'scope', title: localize('u6d.lib.mods.colScope', "Scope") },
					{ key: 'kind', title: localize('u6d.lib.mods.colKind', "Type") },
					{ key: 'values', title: localize('u6d.lib.mods.colVals', "Factors") },
				],
				rows,
				emptyMessage: localize('u6d.lib.mods.empty', "No custom stiffness modifiers overridden; code defaults apply."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.checkAll',
	title: localize('u6d.lib.chk.title', "Validate Materials & Object Types"),
	part: 'library',
	icon: Codicon.checklist,
	help: localize('u6d.lib.chk.help', "Validates 03 Materials and 04 Objects schemas, cross-references and rebar/steel coverage warnings."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/validateAll', { projectRoot: ctx.project!.root.fsPath }));
		const rows: DataPanelRow[] = asArray(raw.findings).map(asBag).map(f => ({
			file: str(f.file),
			severity: str(f.severity, 'Error') === 'Error' ? 'Fail' : 'Warn',
			path: str(f.path, '–'),
			message: str(f.message),
		}));
		const errCount = rows.filter(r => r.severity === 'Fail').length;
		return {
			metrics: [
				{ label: localize('u6d.lib.chk.mErr', "Errors"), value: String(errCount), tone: errCount ? 'fail' : 'ok' },
				{ label: localize('u6d.lib.chk.mWarn', "Warnings"), value: String(rows.length - errCount), tone: rows.length - errCount ? 'warn' : 'ok' },
			],
			tables: [{
				id: 'findings',
				title: localize('u6d.lib.chk.tab', "Library Validation Findings"),
				columns: [
					{ key: 'file', title: localize('u6d.lib.chk.colFile', "Library") },
					{ key: 'severity', title: localize('u6d.lib.chk.colSev', "Severity"), type: 'status' },
					{ key: 'path', title: localize('u6d.lib.chk.colPath', "Path") },
					{ key: 'message', title: localize('u6d.lib.chk.colMsg', "Message") },
				],
				rows,
				emptyMessage: localize('u6d.lib.chk.clean', "Materials and object types pass all library checks."),
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerLibraryPanel({
	id: 'saengine.library.limits',
	title: localize('u6d.lib.lim.title', "Library Guardrail Rules"),
	part: 'library',
	icon: Codicon.law,
	help: localize('u6d.lib.lim.help', "Shows code pack guardrail limits enforced on 03 Materials and 04 Objects inputs."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/limits', { projectRoot: ctx.project!.root.fsPath }));
		const rules = asArray(raw.rules).map(asBag).filter(r => !r.kind || r.kind === 'materials' || r.kind === 'objects');
		const rows: DataPanelRow[] = [];
		for (const r of rules) {
			const id = str(r.id);
			const kind = str(r.kind, 'all');
			const field = str(r.what || asStrings(r.paths).join(', '), '–');
			const unit = str(r.unit, '–');
			for (const lim of asArray(r.block).map(asBag)) {
				rows.push({
					id,
					kind,
					field,
					level: 'Fail',
					min: formatScalar(lim.min),
					max: formatScalar(lim.max),
					unit,
					source: formatScalar(lim.source),
					message: str(lim.reason, '–'),
				});
			}
			for (const lim of asArray(r.warn).map(asBag)) {
				rows.push({
					id,
					kind,
					field,
					level: 'Warn',
					min: formatScalar(lim.min),
					max: formatScalar(lim.max),
					unit,
					source: formatScalar(lim.source),
					message: str(lim.reason, '–'),
				});
			}
		}
		return {
			metrics: [
				{ label: localize('u6d.lib.lim.mRules', "Library Rule Groups"), value: String(rules.length) },
				{ label: localize('u6d.lib.lim.mCount', "Active Limits"), value: String(rows.length) },
			],
			tables: [{
				id: 'limits',
				title: localize('u6d.lib.lim.tab', "Materials & Objects Guardrail Limits"),
				columns: [
					{ key: 'id', title: localize('u6d.set.guard.colId', "Rule ID") },
					{ key: 'kind', title: localize('u6d.set.guard.colKind', "File Kind") },
					{ key: 'field', title: localize('u6d.set.guard.colField', "Field") },
					{ key: 'level', title: localize('u6d.set.guard.colLevel', "Severity"), type: 'status' },
					{ key: 'min', title: localize('u6d.set.guard.colMin', "Min") },
					{ key: 'max', title: localize('u6d.set.guard.colMax', "Max") },
					{ key: 'unit', title: localize('u6d.set.guard.colUnit', "Unit") },
					{ key: 'source', title: localize('u6d.set.guard.colSource', "Source") },
					{ key: 'message', title: localize('u6d.set.guard.colMsg', "Reason") },
				],
				rows,
			}],
		};
	},
});

//#endregion
