/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { joinPath } from '../../../../base/common/resources.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, IDataPanelAction, IDataPanelContext, IEngineDataPanelDescriptor, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ISaengineProjectService, projectParts } from '../../../services/saengineProject/common/saengineProject.js';
import { openPartSection } from '../../saengineProject/browser/projectParts.js';

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

function registerSettingsPanel(descriptor: IEngineDataPanelDescriptor): void {
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

async function readSettingsText(ctx: IDataPanelContext): Promise<string> {
	if (!ctx.project) {
		return '{}';
	}
	try {
		const raw = await ctx.fileService.readFile(joinPath(ctx.project.root, '02 Project Settings', 'project-settings.json'));
		return raw.value.toString();
	} catch {
		return '{}';
	}
}

async function activePackId(ctx: IDataPanelContext): Promise<string> {
	try {
		const parsed = asBag(JSON.parse(await readSettingsText(ctx)));
		return str(parsed.codePack, 'bnbc-2020');
	} catch {
		return 'bnbc-2020';
	}
}

function openSettingsAction(label: string): readonly IDataPanelAction[] {
	return [{
		id: 'openSettingsEditor',
		label,
		icon: Codicon.goToFile,
		run: ctx => void ctx.commandService.executeCommand('saengine.project.showSettings'),
	}];
}

//#region Code & Packs

registerSettingsPanel({
	id: 'saengine.settings.codePackInfo',
	title: localize('u6d.set.packInfo.title', "Active Code Pack Details"),
	part: 'settings',
	icon: Codicon.book,
	help: localize('u6d.set.packInfo.help', "Inspects the active design code pack manifest, edition, normative sources, clauses and covered areas."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const packId = await activePackId(ctx);
		const raw = asBag(await ctx.engineRequest('codes/show', {
			id: packId,
			root: ctx.project!.root.fsPath,
		}));
		const sources = asArray(raw.sources).map(asBag);
		const clauses = asBag(raw.clauses);
		const infoRows: DataPanelRow[] = [
			{ property: localize('u6d.set.packInfo.id', "Pack ID"), value: str(raw.id, packId) },
			{ property: localize('u6d.set.packInfo.name', "Name"), value: str(raw.name, '–') },
			{ property: localize('u6d.set.packInfo.edition', "Edition"), value: str(raw.edition, '–') },
			{ property: localize('u6d.set.packInfo.version', "Version"), value: str(raw.version, '–') },
			{ property: localize('u6d.set.packInfo.author', "Author"), value: str(raw.author, '–') },
			{ property: localize('u6d.set.packInfo.licence', "Licence"), value: str(raw.licence, '–') },
			{ property: localize('u6d.set.packInfo.desc', "Description"), value: str(raw.description, '–') },
		];
		const sourceRows: DataPanelRow[] = sources.map(s => ({
			id: str(s.id),
			title: str(s.title),
			url: str(s.url, '–'),
		}));
		const clauseRows: DataPanelRow[] = Object.entries(clauses).map(([table, ref]) => ({
			table,
			clause: formatScalar(ref),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.packInfo.mId', "Active Pack"), value: str(raw.id, packId) },
				{ label: localize('u6d.set.packInfo.mSrc', "Sources"), value: String(sourceRows.length) },
				{ label: localize('u6d.set.packInfo.mClauses', "Clauses"), value: String(clauseRows.length) },
			],
			tables: [
				{
					id: 'info',
					title: localize('u6d.set.packInfo.tab', "Pack Metadata"),
					columns: [
						{ key: 'property', title: localize('u6d.set.packInfo.colProp', "Property") },
						{ key: 'value', title: localize('u6d.set.packInfo.colVal', "Value") },
					],
					rows: infoRows,
				},
				{
					id: 'sources',
					title: localize('u6d.set.packInfo.srcTab', "Normative Sources"),
					columns: [
						{ key: 'id', title: localize('u6d.set.packInfo.colSId', "ID") },
						{ key: 'title', title: localize('u6d.set.packInfo.colSTit', "Title") },
						{ key: 'url', title: localize('u6d.set.packInfo.colSUrl', "Reference / URL") },
					],
					rows: sourceRows,
				},
				{
					id: 'clauses',
					title: localize('u6d.set.packInfo.clsTab', "Table Clauses"),
					columns: [
						{ key: 'table', title: localize('u6d.set.packInfo.colCTbl', "Table") },
						{ key: 'clause', title: localize('u6d.set.packInfo.colCRef', "Clause") },
					],
					rows: clauseRows,
				},
			],
			problems: asStrings(raw.problems),
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.installedPacks',
	title: localize('u6d.set.installed.title', "Installed Code Packs & Packages"),
	part: 'settings',
	icon: Codicon.package,
	help: localize('u6d.set.installed.help', "Lists all built-in, user-installed and project-local code packs, structure templates and building templates."),
	run: async ctx => {
		const rawList = await ctx.engineRequest('codes/list', { root: ctx.project!.root.fsPath, kind: 'all' });
		const packs = asArray(rawList).map(asBag);
		const rows: DataPanelRow[] = packs.map(p => ({
			id: str(p.id),
			name: str(p.name),
			kind: str(p.kind, 'designCode'),
			scope: str(p.scope, 'builtIn'),
			version: str(p.version, '–'),
			extendsPack: str(p.extends, '–'),
			trusted: p.trusted ? 'Pass' : 'Neutral',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.installed.mTot', "Packages"), value: String(rows.length) },
				{ label: localize('u6d.set.installed.mDesign', "Design Codes"), value: String(rows.filter(r => r.kind === 'designCode').length) },
			],
			tables: [{
				id: 'packs',
				title: localize('u6d.set.installed.tab', "Installed Packages"),
				columns: [
					{ key: 'id', title: localize('u6d.set.installed.colId', "ID") },
					{ key: 'name', title: localize('u6d.set.installed.colName', "Name") },
					{ key: 'kind', title: localize('u6d.set.installed.colKind', "Kind") },
					{ key: 'scope', title: localize('u6d.set.installed.colScope', "Scope") },
					{ key: 'version', title: localize('u6d.set.installed.colVer', "Version") },
					{ key: 'extendsPack', title: localize('u6d.set.installed.colExt', "Extends") },
				],
				rows,
			}],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.packTemplates',
	title: localize('u6d.set.templates.title', "Building & Structure Package Templates"),
	part: 'settings',
	icon: Codicon.files,
	help: localize('u6d.set.templates.help', "Lists installed building specifications and full project archive templates contributed by packages."),
	fields: [
		{
			key: 'kind',
			label: localize('u6d.set.templates.kind', "Template Kind"),
			type: 'select',
			defaultValue: 'buildingTemplate',
			options: [
				{ value: 'buildingTemplate', label: localize('u6d.set.templates.bldg', "Building Templates") },
				{ value: 'structureTemplate', label: localize('u6d.set.templates.struct', "Structure Presets") },
			],
		},
	],
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('codes/templates', {
			kind: String(values.kind || 'buildingTemplate'),
			root: ctx.project!.root.fsPath,
		}));
		const specs = asArray(raw.specs ?? raw.presets ?? raw.templates).map(asBag);
		const archives = asArray(raw.archives).map(asBag);
		const specRows: DataPanelRow[] = specs.map(s => ({
			id: str(s.id || s.name),
			package: str(s.package, '–'),
			name: str(s.name || s.title),
			description: str(s.description, '–'),
		}));
		const archRows: DataPanelRow[] = archives.map(a => ({
			id: str(a.id || a.name),
			package: str(a.package, '–'),
			path: str(a.path, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.templates.mSpecs', "Specs / Presets"), value: String(specRows.length) },
				{ label: localize('u6d.set.templates.mArch', "Archives"), value: String(archRows.length) },
			],
			tables: [
				{
					id: 'specs',
					title: localize('u6d.set.templates.specsTab', "Package Presets & Specifications"),
					columns: [
						{ key: 'id', title: localize('u6d.set.templates.colId', "ID") },
						{ key: 'package', title: localize('u6d.set.templates.colPkg', "Package") },
						{ key: 'name', title: localize('u6d.set.templates.colName', "Name") },
						{ key: 'description', title: localize('u6d.set.templates.colDesc', "Description") },
					],
					rows: specRows,
				},
				{
					id: 'archives',
					title: localize('u6d.set.templates.archTab', "Template Archives"),
					columns: [
						{ key: 'id', title: localize('u6d.set.templates.colAId', "ID") },
						{ key: 'package', title: localize('u6d.set.templates.colAPkg', "Package") },
						{ key: 'path', title: localize('u6d.set.templates.colAPath', "Path") },
					],
					rows: archRows,
				},
			],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.trustAudit',
	title: localize('u6d.set.trust.title', "Package Hooks & Hazard Lookup Trust"),
	part: 'settings',
	icon: Codicon.shield,
	help: localize('u6d.set.trust.help', "Audits trust status for package Python hooks and online hazard lookup endpoints, and updates trust when requested."),
	fields: [
		{ key: 'packId', label: localize('u6d.set.trust.packId', "Pack ID to update (optional)"), type: 'text', defaultValue: '', placeholder: localize('u6d.set.trust.ph', "Leave blank to only inspect") },
		{ key: 'what', label: localize('u6d.set.trust.what', "Trust Scope"), type: 'select', defaultValue: 'hooks', options: [{ value: 'hooks', label: localize('u6d.set.trust.hooks', "Python Hooks") }, { value: 'lookup', label: localize('u6d.set.trust.lookup', "Hazard Lookup Services") }] },
		{ key: 'trusted', label: localize('u6d.set.trust.trusted', "Mark selected pack as trusted"), type: 'checkbox', defaultValue: true },
	],
	run: async (ctx, values) => {
		const target = String(values.packId || '').trim();
		const notes: string[] = [];
		const problems: string[] = [];
		if (target) {
			const res = asBag(await ctx.engineRequest('codes/trust', {
				id: target,
				trusted: Boolean(values.trusted),
				root: ctx.project!.root.fsPath,
				...(values.what === 'lookup' ? { what: 'lookup' } : {}),
			}));
			if (res.message) {
				problems.push(str(res.message));
			} else {
				notes.push(localize('u6d.set.trust.updated', "Updated trust for {0}.", target));
			}
		}
		const rawList = await ctx.engineRequest('codes/list', { root: ctx.project!.root.fsPath, kind: 'all' });
		const rows: DataPanelRow[] = asArray(rawList).map(asBag).map(p => ({
			id: str(p.id),
			kind: str(p.kind, 'designCode'),
			scope: str(p.scope, 'builtIn'),
			hasHooks: p.hasHooks ? 'Yes' : 'No',
			hooksTrusted: p.trusted ? 'Pass' : (p.hasHooks ? 'Warn' : 'OK'),
			lookupTrusted: p.lookupTrusted ? 'Pass' : 'OK',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.trust.mTotal', "Packages"), value: String(rows.length) },
				{ label: localize('u6d.set.trust.mHooks', "With Python Hooks"), value: String(rows.filter(r => r.hasHooks === 'Yes').length) },
			],
			tables: [{
				id: 'trust',
				title: localize('u6d.set.trust.tab', "Package Trust Matrix"),
				columns: [
					{ key: 'id', title: localize('u6d.set.trust.colId', "Pack ID") },
					{ key: 'kind', title: localize('u6d.set.trust.colKind', "Kind") },
					{ key: 'scope', title: localize('u6d.set.trust.colScope', "Scope") },
					{ key: 'hasHooks', title: localize('u6d.set.trust.colHasHooks', "Hooks") },
					{ key: 'hooksTrusted', title: localize('u6d.set.trust.colHookTrust', "Hooks Trust"), type: 'status' },
					{ key: 'lookupTrusted', title: localize('u6d.set.trust.colLookupTrust', "Lookup Trust"), type: 'status' },
				],
				rows,
			}],
			notes,
			problems,
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.validatePack',
	title: localize('u6d.set.valPack.title', "Validate Code Pack Folder"),
	part: 'settings',
	icon: Codicon.checklist,
	help: localize('u6d.set.valPack.help', "Validates a code pack directory against table schemas, inheritance rules and authoring checks."),
	fields: [
		{ key: 'path', label: localize('u6d.set.valPack.path', "Code Pack Folder"), type: 'folder', defaultValue: '' },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const packId = await activePackId(ctx);
		const info = asBag(await ctx.engineRequest('codes/show', { id: packId, root: ctx.project.root.fsPath }));
		return info.path ? { values: { path: str(info.path) } } : undefined;
	},
	run: async (ctx, values) => {
		const path = String(values.path || '').trim();
		if (!path) {
			return { tables: [], problems: [localize('u6d.set.valPack.pick', "Select a code pack folder to validate.")] };
		}
		const raw = asBag(await ctx.engineRequest('codes/validate', { path, root: ctx.project!.root.fsPath }));
		const probs = asArray(raw.problems).map(asBag);
		const rows: DataPanelRow[] = probs.map(p => ({
			severity: str(p.severity, 'warning') === 'error' ? 'Fail' : 'Warn',
			table: str(p.table, '–'),
			message: str(p.message),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.valPack.mPack', "Pack"), value: str(raw.id, '–') },
				{ label: localize('u6d.set.valPack.mCount', "Findings"), value: String(rows.length), tone: rows.some(r => r.severity === 'Fail') ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'findings',
				title: localize('u6d.set.valPack.tab', "Pack Validation Findings"),
				columns: [
					{ key: 'severity', title: localize('u6d.set.valPack.colSev', "Severity"), type: 'status' },
					{ key: 'table', title: localize('u6d.set.valPack.colTbl', "Table") },
					{ key: 'message', title: localize('u6d.set.valPack.colMsg', "Message") },
				],
				rows,
				emptyMessage: localize('u6d.set.valPack.clean', "No validation errors or warnings found in this pack."),
			}],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.diffPacks',
	title: localize('u6d.set.diff.title', "Compare Code Packs"),
	part: 'settings',
	icon: Codicon.diff,
	help: localize('u6d.set.diff.help', "Compares every resolved code table and parameter between two installed code packs side by side."),
	fields: [
		{ key: 'packA', label: localize('u6d.set.diff.a', "Base Pack (A)"), type: 'select', defaultValue: 'bnbc-2020', options: [{ value: 'bnbc-2020', label: 'bnbc-2020' }] },
		{ key: 'packB', label: localize('u6d.set.diff.b', "Compare Pack (B)"), type: 'select', defaultValue: 'eurocodes', options: [{ value: 'eurocodes', label: 'eurocodes' }] },
	],
	loadInitial: async ctx => {
		const rawList = await ctx.engineRequest('codes/list', { root: ctx.project?.root.fsPath, kind: 'designCode' });
		const opts = asArray(rawList).map(asBag).map(p => ({ value: str(p.id), label: `${str(p.id)} — ${str(p.name)}` }));
		if (!opts.length) {
			return undefined;
		}
		return {
			options: { packA: opts, packB: opts },
			values: { packA: opts[0].value, packB: opts[Math.min(1, opts.length - 1)].value },
		};
	},
	run: async (ctx, values) => {
		const raw = asBag(await ctx.engineRequest('codes/diff', {
			packA: String(values.packA || 'bnbc-2020'),
			packB: String(values.packB || 'eurocodes'),
			projectRoot: ctx.project!.root.fsPath,
		}));
		const diffs = asArray(raw.differences).map(asBag);
		const rows: DataPanelRow[] = diffs.map(d => ({
			table: str(d.table),
			path: str(d.path),
			kind: str(d.kind),
			a: formatScalar(d.a),
			b: formatScalar(d.b),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.diff.mA', "Pack A"), value: str(raw.packA) },
				{ label: localize('u6d.set.diff.mB', "Pack B"), value: str(raw.packB) },
				{ label: localize('u6d.set.diff.mCount', "Differences"), value: String(raw.count ?? rows.length) },
			],
			tables: [{
				id: 'diffs',
				title: localize('u6d.set.diff.tab', "Resolved Table Differences"),
				columns: [
					{ key: 'table', title: localize('u6d.set.diff.colTbl', "Table") },
					{ key: 'path', title: localize('u6d.set.diff.colPath', "Path") },
					{ key: 'kind', title: localize('u6d.set.diff.colKind', "Change"), type: 'status' },
					{ key: 'a', title: localize('u6d.set.diff.colA', "Pack A") },
					{ key: 'b', title: localize('u6d.set.diff.colB', "Pack B") },
				],
				rows,
				emptyMessage: localize('u6d.set.diff.same', "No differences between these two packs."),
			}],
			problems: asStrings(raw.problems),
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.checkTemplate',
	title: localize('u6d.set.chkTpl.title', "Check Template Archive (.civil)"),
	part: 'settings',
	icon: Codicon.archive,
	autoRun: false,
	runLabel: localize('u6d.set.chkTpl.run', "Check Archive"),
	help: localize('u6d.set.chkTpl.help', "Inspects a .civil project archive for template readiness, forbidden files and schema problems before publishing."),
	fields: [
		{ key: 'path', label: localize('u6d.set.chkTpl.path', "Archive (.civil)"), type: 'file', defaultValue: '', filters: [{ name: 'SAEngine Archive', extensions: ['civil'] }] },
		{ key: 'author', label: localize('u6d.set.chkTpl.author', "Author (optional)"), type: 'text', defaultValue: '' },
	],
	run: async (ctx, values) => {
		const path = String(values.path || '').trim();
		if (!path) {
			return { tables: [], problems: [localize('u6d.set.chkTpl.pick', "Select a .civil template archive to inspect.")] };
		}
		const raw = asBag(await ctx.engineRequest('codes/checkTemplate', {
			path,
			author: String(values.author || ''),
		}));
		const rows: DataPanelRow[] = asArray(raw.problems).map(asBag).map(p => ({
			severity: str(p.severity, 'error') === 'error' ? 'Fail' : 'Warn',
			message: str(p.message),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.chkTpl.mOk', "Template Status"), value: raw.ok ? 'Valid' : 'Issues Found', tone: raw.ok ? 'ok' : 'fail' },
				{ label: localize('u6d.set.chkTpl.mCount', "Findings"), value: String(rows.length) },
			],
			tables: [{
				id: 'findings',
				title: localize('u6d.set.chkTpl.tab', "Template Archive Findings"),
				columns: [
					{ key: 'severity', title: localize('u6d.set.chkTpl.colSev', "Severity"), type: 'status' },
					{ key: 'message', title: localize('u6d.set.chkTpl.colMsg', "Message") },
				],
				rows,
				emptyMessage: localize('u6d.set.chkTpl.clean', "Archive passes all template checks."),
			}],
		};
	},
});

//#endregion

//#region Loads & Combinations

registerSettingsPanel({
	id: 'saengine.settings.areaLoads',
	title: localize('u6d.set.areaLoads.title', "Code Area Loads Audit"),
	part: 'settings',
	icon: Codicon.layers,
	help: localize('u6d.set.areaLoads.help', "Compares project area loads (dead/superimposed/live) against the active code pack occupancy defaults."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/areaLoads', {
			settingsText,
			root: ctx.project!.root.fsPath,
		}));
		const changed = new Set(asStrings(raw.changed));
		const rows: DataPanelRow[] = asArray(raw.areaLoads).map(asBag).map(a => ({
			id: str(a.id),
			use: str(a.use, '–'),
			dead: num(a.dead) ?? 0,
			live: num(a.live) ?? 0,
			differs: changed.has(str(a.id)) ? 'Changed' : 'Pass',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.al.mPack', "Code Pack"), value: str(raw.name || raw.id, '–') },
				{ label: localize('u6d.set.al.mCount', "Area Load Sets"), value: String(rows.length) },
				{ label: localize('u6d.set.al.mFrom', "Matches Pack"), value: raw.fromPack ? 'Yes' : `${changed.size} modified`, tone: raw.fromPack ? 'ok' : 'warn' },
			],
			tables: [{
				id: 'areaLoads',
				title: localize('u6d.set.al.tab', "Area Loads vs Code Pack"),
				columns: [
					{ key: 'id', title: localize('u6d.set.al.colId', "ID") },
					{ key: 'use', title: localize('u6d.set.al.colUse', "Occupancy Use") },
					{ key: 'dead', title: localize('u6d.set.al.colDead', "SDL [kPa]"), type: 'number', align: 'right' },
					{ key: 'live', title: localize('u6d.set.al.colLive', "Live [kPa]"), type: 'number', align: 'right' },
					{ key: 'differs', title: localize('u6d.set.al.colStatus', "Status"), type: 'status' },
				],
				rows,
			}],
			problems: raw.message ? [str(raw.message)] : [],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.packChoices',
	title: localize('u6d.set.choices.title', "Code Pack Occupancies & Structural Systems"),
	part: 'settings',
	icon: Codicon.listFlat,
	help: localize('u6d.set.choices.help', "Lists every occupancy, structural framing system, site class and town defined by the active code pack."),
	run: async ctx => {
		const packId = await activePackId(ctx);
		const raw = asBag(await ctx.engineRequest('codes/choices', {
			id: packId,
			root: ctx.project!.root.fsPath,
		}));
		const choices = asBag(raw.choices);
		const rows: DataPanelRow[] = [];
		for (const [group, items] of Object.entries(choices)) {
			for (const entry of asArray(items).map(asBag)) {
				rows.push({
					category: group,
					id: str(entry.id),
					label: str(entry.label || entry.name || entry.id),
				});
			}
		}
		return {
			metrics: [
				{ label: localize('u6d.set.ch.mPack', "Code Pack"), value: str(raw.name || packId) },
				{ label: localize('u6d.set.ch.mEntries', "Available Choices"), value: String(rows.length) },
			],
			tables: [{
				id: 'choices',
				title: localize('u6d.set.ch.tab', "Code Pack Enumerated Choices"),
				columns: [
					{ key: 'category', title: localize('u6d.set.ch.colCat', "Category") },
					{ key: 'id', title: localize('u6d.set.ch.colId', "ID") },
					{ key: 'label', title: localize('u6d.set.ch.colLbl', "Description") },
				],
				rows,
			}],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.combinationsPreview',
	title: localize('u6d.set.combos.title', "Code Load Combinations Generator"),
	part: 'settings',
	icon: Codicon.symbolOperator,
	help: localize('u6d.set.combos.help', "Previews all code-generated strength load combinations for the active settings (including thermal, settlement and creep/shrinkage if enabled)."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/combinations', {
			settingsText,
			root: ctx.project!.root.fsPath,
		}));
		const combos = asArray(raw.combinations).map(asBag);
		const rows: DataPanelRow[] = combos.map(c => ({
			name: str(c.name || c.id),
			factors: Object.entries(asBag(c.factors)).map(([k, v]) => `${formatScalar(v)} ${k}`).join(' + ') || formatScalar(c.formula),
			kind: str(c.kind, 'strength'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.cmb.mPack', "Code Pack"), value: str(raw.name || raw.id, '–') },
				{ label: localize('u6d.set.cmb.mCount', "Combinations"), value: String(rows.length) },
				{ label: localize('u6d.set.cmb.mMatch', "Matches Settings"), value: raw.fromPack ? 'Yes' : 'Customized', tone: raw.fromPack ? 'ok' : 'warn' },
			],
			tables: [{
				id: 'combos',
				title: localize('u6d.set.cmb.tab', "Generated Strength Combinations"),
				columns: [
					{ key: 'name', title: localize('u6d.set.cmb.colName', "Combination") },
					{ key: 'factors', title: localize('u6d.set.cmb.colFac', "Load Factors") },
					{ key: 'kind', title: localize('u6d.set.cmb.colKind', "Limit State") },
				],
				rows,
			}],
			problems: raw.message ? [str(raw.message)] : [],
		};
	},
});

//#endregion

//#region Seismic & Wind Hazard

registerSettingsPanel({
	id: 'saengine.settings.hazardSummary',
	title: localize('u6d.set.haz.title', "Derived Seismic & Wind Parameters"),
	part: 'settings',
	icon: Codicon.pulse,
	help: localize('u6d.set.haz.help', "Reports all derived seismic coefficients (Z, Fa, Fv, SDS, SD1, SDC, R, Ω0, Cd) and wind parameters (V, Kd, Kzt, exposure)."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('settings/hazardSummary', { projectRoot: ctx.project!.root.fsPath }));
		const der = asBag(raw.derived);
		const sources = asBag(raw.sources);
		const siteSrc = asBag(sources.site);
		const rows: DataPanelRow[] = [
			...Object.entries(der).map(([k, v]) => ({ parameter: k, value: formatScalar(v) })),
			...(siteSrc.label ? [{ parameter: 'Resolved Site Class', value: str(siteSrc.label) }] : []),
		];
		return {
			metrics: [
				{ label: localize('u6d.set.haz.mZ', "Seismic Z"), value: formatScalar(der.Z) },
				{ label: localize('u6d.set.haz.mSdc', "SDC"), value: str(der.SDC || der.sdc, '–') },
				{ label: localize('u6d.set.haz.mV', "Wind Speed V"), value: der.V !== undefined ? `${formatScalar(der.V)} m/s` : '–' },
			],
			tables: [{
				id: 'derived',
				title: localize('u6d.set.haz.tab', "Derived Site & Hazard Parameters"),
				columns: [
					{ key: 'parameter', title: localize('u6d.set.haz.colParam', "Parameter") },
					{ key: 'value', title: localize('u6d.set.haz.colVal', "Value") },
				],
				rows,
			}],
			notes: asStrings(raw.notes),
			problems: asStrings(raw.problems),
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.townCatalogue',
	title: localize('u6d.set.towns.title', "Code Pack Towns & Hazard Catalogue"),
	part: 'settings',
	icon: Codicon.globe,
	help: localize('u6d.set.towns.help', "Searchable table of cities and towns defined in the active code pack with their mapped seismic zone coefficients and basic wind speeds."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('settings/towns', { projectRoot: ctx.project!.root.fsPath }));
		const towns = asArray(raw.towns).map(asBag);
		const rows: DataPanelRow[] = towns.map(t => ({
			id: str(t.id),
			name: str(t.name || t.label || t.id),
			zone: str(t.zone || t.seismicZone, '–'),
			z: num(t.Z) ?? num(t.z) ?? '–',
			v: num(t.V) ?? num(t.v) ?? '–',
			lat: num(t.latitude) ?? '–',
			lon: num(t.longitude) ?? '–',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.towns.mCount', "Towns"), value: String(rows.length) },
			],
			tables: [{
				id: 'towns',
				title: localize('u6d.set.towns.tab', "Hazard Table by Town"),
				columns: [
					{ key: 'name', title: localize('u6d.set.towns.colName', "Town") },
					{ key: 'zone', title: localize('u6d.set.towns.colZone', "Zone") },
					{ key: 'z', title: localize('u6d.set.towns.colZ', "Z"), type: 'number', align: 'right' },
					{ key: 'v', title: localize('u6d.set.towns.colV', "Wind V [m/s]"), type: 'number', align: 'right' },
					{ key: 'lat', title: localize('u6d.set.towns.colLat', "Latitude"), type: 'number', align: 'right' },
					{ key: 'lon', title: localize('u6d.set.towns.colLon', "Longitude"), type: 'number', align: 'right' },
				],
				rows,
			}],
			problems: asStrings(raw.problems),
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.hazardOffers',
	title: localize('u6d.set.offers.title', "Online Hazard Providers (Offline Preview)"),
	part: 'settings',
	icon: Codicon.cloudDownload,
	help: localize('u6d.set.offers.help', "Shows online hazard services configured for the active code pack and exact coordinates/queries without making a network request."),
	run: async ctx => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('hazard/offers', {
			settingsText,
			root: ctx.project!.root.fsPath,
		}));
		const providers = asArray(raw.providers).map(asBag);
		const coords = asBag(raw.coordinates);
		const rows: DataPanelRow[] = providers.map(p => ({
			id: str(p.id),
			service: str(p.service),
			host: str(p.host, '–'),
			url: str(p.url, '–'),
			status: p.problem ? 'Warn' : 'OK',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.off.mPack', "Code Pack"), value: str(raw.codePack, '–') },
				{ label: localize('u6d.set.off.mProv', "Providers"), value: String(rows.length) },
				{ label: localize('u6d.set.off.mCoords', "Coordinates"), value: coords.latitude !== undefined ? `${str(coords.latitude)}, ${str(coords.longitude)}` : 'Not set' },
			],
			tables: [{
				id: 'providers',
				title: localize('u6d.set.off.tab', "Configured Hazard Lookup Providers"),
				columns: [
					{ key: 'id', title: localize('u6d.set.off.colId', "Provider") },
					{ key: 'service', title: localize('u6d.set.off.colSvc', "Service") },
					{ key: 'host', title: localize('u6d.set.off.colHost', "Host") },
					{ key: 'url', title: localize('u6d.set.off.colUrl', "Query URL") },
					{ key: 'status', title: localize('u6d.set.off.colStat', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.set.off.empty', "Active code pack does not define online hazard lookup providers."),
			}],
			notes: raw.manualNote ? [str(raw.manualNote)] : [],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.hazardLookup',
	title: localize('u6d.set.lookup.title', "Fetch Online Hazard Values"),
	part: 'settings',
	icon: Codicon.globe,
	autoRun: false,
	runLabel: localize('u6d.set.lookup.run', "Fetch Hazard Values"),
	help: localize('u6d.set.lookup.help', "Opt-in query to a code pack hazard web service (such as USGS) sending only site coordinates and code parameters."),
	fields: [
		{ key: 'provider', label: localize('u6d.set.lookup.prov', "Provider ID"), type: 'text', defaultValue: 'usgs-asce7-22' },
		{ key: 'latitude', label: localize('u6d.set.lookup.lat', "Latitude [°] (blank = from project)"), type: 'text', defaultValue: '' },
		{ key: 'longitude', label: localize('u6d.set.lookup.lon', "Longitude [°] (blank = from project)"), type: 'text', defaultValue: '' },
		{ key: 'consent', label: localize('u6d.set.lookup.consent', "Send coordinates to external hazard provider"), type: 'checkbox', defaultValue: false },
	],
	run: async (ctx, values) => {
		const settingsText = await readSettingsText(ctx);
		const latTxt = String(values.latitude || '').trim();
		const lonTxt = String(values.longitude || '').trim();
		const raw = asBag(await ctx.engineRequest('hazard/lookup', {
			settingsText,
			provider: String(values.provider || ''),
			consent: Boolean(values.consent),
			root: ctx.project!.root.fsPath,
			...(latTxt && Number.isFinite(Number(latTxt)) ? { latitude: Number(latTxt) } : {}),
			...(lonTxt && Number.isFinite(Number(lonTxt)) ? { longitude: Number(lonTxt) } : {}),
		}));
		const vals = asArray(raw.values).map(asBag);
		const rows: DataPanelRow[] = vals.map(v => ({
			target: str(v.target),
			label: str(v.label, str(v.target)),
			value: formatScalar(v.value),
			unit: str(v.unit, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.lookup.mOk', "Lookup Status"), value: raw.ok ? 'Success' : str(raw.code, 'Refused'), tone: raw.ok ? 'ok' : 'warn' },
				{ label: localize('u6d.set.lookup.mVals', "Values"), value: String(rows.length) },
			],
			tables: [{
				id: 'values',
				title: localize('u6d.set.lookup.tab', "Retrieved Hazard Parameters"),
				columns: [
					{ key: 'target', title: localize('u6d.set.lookup.colTgt', "Setting Path") },
					{ key: 'label', title: localize('u6d.set.lookup.colLbl', "Parameter") },
					{ key: 'value', title: localize('u6d.set.lookup.colVal', "Value") },
					{ key: 'unit', title: localize('u6d.set.lookup.colUnit', "Unit") },
				],
				rows,
			}],
			problems: raw.message ? [str(raw.message)] : [],
		};
	},
});

//#endregion

//#region Checks & Conformance

registerSettingsPanel({
	id: 'saengine.settings.validateAll',
	title: localize('u6d.set.valAll.title', "Validate All Project Parts"),
	part: 'settings',
	icon: Codicon.checkAll,
	help: localize('u6d.set.valAll.help', "Runs cross-part schema and engineering validation across every file of the project (Soil through Exports)."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('project/validateAll', { projectRoot: ctx.project!.root.fsPath }));
		const summary = asBag(raw.summary);
		const parts = asArray(raw.parts).map(asBag);
		const probs = asArray(raw.problems).map(asBag);
		const partRows: DataPanelRow[] = parts.map(p => ({
			part: str(p.part),
			file: str(p.file, '–'),
			state: str(p.state, 'ok') === 'ok' ? 'Pass' : str(p.state),
			errors: num(p.errors) ?? 0,
			problemsCount: asArray(p.problems).length,
		}));
		const probRows: DataPanelRow[] = probs.map(p => ({
			part: str(p.part),
			severity: str(p.severity) === 'error' ? 'Fail' : 'Warn',
			path: str(p.path, '–'),
			message: str(p.message),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.valAll.mParts', "Parts OK"), value: `${str(summary.ok, '0')}/${str(summary.parts, String(partRows.length))}` },
				{ label: localize('u6d.set.valAll.mErr', "Errors"), value: String(summary.errors ?? 0), tone: (num(summary.errors) ?? 0) > 0 ? 'fail' : 'ok' },
				{ label: localize('u6d.set.valAll.mWarn', "Warnings"), value: String(summary.warnings ?? 0), tone: (num(summary.warnings) ?? 0) > 0 ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'parts',
					title: localize('u6d.set.valAll.partsTab', "Project Parts Readiness"),
					columns: [
						{ key: 'part', title: localize('u6d.set.valAll.colPart', "Part") },
						{ key: 'file', title: localize('u6d.set.valAll.colFile', "File") },
						{ key: 'state', title: localize('u6d.set.valAll.colState', "State"), type: 'status' },
						{ key: 'errors', title: localize('u6d.set.valAll.colErrs', "Errors"), type: 'number', align: 'right' },
						{ key: 'problemsCount', title: localize('u6d.set.valAll.colProbs', "Findings"), type: 'number', align: 'right' },
					],
					rows: partRows,
				},
				{
					id: 'problems',
					title: localize('u6d.set.valAll.probsTab', "All Project Findings"),
					columns: [
						{ key: 'part', title: localize('u6d.set.valAll.colPPart', "Part") },
						{ key: 'severity', title: localize('u6d.set.valAll.colPSev', "Severity"), type: 'status' },
						{ key: 'path', title: localize('u6d.set.valAll.colPPath', "Path") },
						{ key: 'message', title: localize('u6d.set.valAll.colPMsg', "Message") },
					],
					rows: probRows,
					emptyMessage: localize('u6d.set.valAll.clean', "Every project part validates with zero issues."),
				},
			],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.checkSettings',
	title: localize('u6d.set.chkSet.title', "Check Project Settings"),
	part: 'settings',
	icon: Codicon.pass,
	help: localize('u6d.set.chkSet.help', "Validates 02 Project Settings/project-settings.json against schema constraints and active code pack rules."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const text = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('library/check', {
			kind: 'settings',
			text,
			projectRoot: ctx.project!.root.fsPath,
		}));
		const probs = asArray(raw.problems).map(asBag);
		const rows: DataPanelRow[] = probs.map(p => ({
			path: str(p.path, '–'),
			message: str(p.message),
			status: 'Fail',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.chkSet.mStat', "Settings Check"), value: rows.length ? `${rows.length} issue(s)` : 'Valid', tone: rows.length ? 'fail' : 'ok' },
			],
			tables: [{
				id: 'problems',
				title: localize('u6d.set.chkSet.tab', "Project Settings Validation"),
				columns: [
					{ key: 'path', title: localize('u6d.set.chkSet.colPath', "Field Path") },
					{ key: 'message', title: localize('u6d.set.chkSet.colMsg', "Message") },
					{ key: 'status', title: localize('u6d.set.chkSet.colStat', "Status"), type: 'status' },
				],
				rows,
				emptyMessage: localize('u6d.set.chkSet.clean', "Project settings passed all validation checks."),
			}],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.conformance',
	title: localize('u6d.set.conf.title', "Code Pack Conformance Audit"),
	part: 'settings',
	icon: Codicon.verified,
	help: localize('u6d.set.conf.help', "Runs all 7 conformance checks on the active code pack: loads, covers, sources, clause ownership, actions, bar sizes and verification."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('codes/conformance', { projectRoot: ctx.project!.root.fsPath }));
		const findings = asArray(raw.findings).map(asBag);
		const rows: DataPanelRow[] = findings.map(f => ({
			check: str(f.check),
			level: str(f.level) === 'error' ? 'Fail' : 'Warn',
			table: str(f.table, '–'),
			message: str(f.message),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.conf.mPack', "Code Pack"), value: str(raw.packName || raw.packId, '–') },
				{ label: localize('u6d.set.conf.mErr', "Errors"), value: String(raw.errorCount ?? 0), tone: (num(raw.errorCount) ?? 0) > 0 ? 'fail' : 'ok' },
				{ label: localize('u6d.set.conf.mWarn', "Warnings"), value: String(raw.warningCount ?? 0), tone: (num(raw.warningCount) ?? 0) > 0 ? 'warn' : 'ok' },
			],
			tables: [{
				id: 'findings',
				title: localize('u6d.set.conf.tab', "Conformance Findings"),
				columns: [
					{ key: 'check', title: localize('u6d.set.conf.colChk', "Check") },
					{ key: 'level', title: localize('u6d.set.conf.colLvl', "Level"), type: 'status' },
					{ key: 'table', title: localize('u6d.set.conf.colTbl', "Table") },
					{ key: 'message', title: localize('u6d.set.conf.colMsg', "Message") },
				],
				rows,
				emptyMessage: localize('u6d.set.conf.clean', "Code pack conforms across all 7 checks with zero remarks."),
			}],
			problems: asStrings(raw.problems),
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.guardrails',
	title: localize('u6d.set.guard.title', "Code Pack Input Guardrail Limits"),
	part: 'settings',
	icon: Codicon.law,
	help: localize('u6d.set.guard.help', "Inspects active engineering guardrail limits (blocks and warnings) derived from the project's code pack."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('library/limits', { projectRoot: ctx.project!.root.fsPath }));
		const rules = asArray(raw.rules).map(asBag);
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
				{ label: localize('u6d.set.guard.mRules', "Rule Groups"), value: String(rules.length) },
				{ label: localize('u6d.set.guard.mCount', "Active Limits"), value: String(rows.length) },
			],
			tables: [{
				id: 'rules',
				title: localize('u6d.set.guard.tab', "Input Guardrail Limits"),
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

//#region Overrides & Code Values

registerSettingsPanel({
	id: 'saengine.settings.codeValues',
	title: localize('u6d.set.vals.title', "Browse Code Pack Tables"),
	part: 'settings',
	icon: Codicon.table,
	help: localize('u6d.set.vals.help', "Browse every parameter inside the active code pack's tables (after applying project overrides)."),
	fields: [
		{ key: 'table', label: localize('u6d.set.vals.tbl', "Code Table"), type: 'select', defaultValue: 'concrete', options: [{ value: 'concrete', label: 'Concrete' }] },
	],
	loadInitial: async ctx => {
		if (!ctx.project) {
			return undefined;
		}
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/values', {
			settingsText,
			root: ctx.project.root.fsPath,
		}));
		const tbls = asArray(raw.tables).map(asBag);
		if (!tbls.length) {
			return undefined;
		}
		return {
			options: { table: tbls.map(t => ({ value: str(t.name), label: `${str(t.title || t.name)} (${str(t.section)})` })) },
			values: { table: str(tbls[0].name) },
		};
	},
	run: async (ctx, values) => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/values', {
			settingsText,
			root: ctx.project!.root.fsPath,
			table: String(values.table || 'concrete'),
		}));
		const rows: DataPanelRow[] = asArray(raw.rows).map(asBag).map(r => ({
			path: str(r.path),
			name: str(r.name || r.label || r.path),
			value: formatScalar(r.value),
			unit: str(r.unit, '–'),
			clause: str(r.clause, '–'),
			overridden: r.overridden ? 'Changed' : 'OK',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.vals.mPack', "Code Pack"), value: str(raw.name || raw.id, '–') },
				{ label: localize('u6d.set.vals.mRows', "Parameters"), value: String(rows.length) },
			],
			tables: [{
				id: 'rows',
				title: localize('u6d.set.vals.tab', "Code Table Values"),
				columns: [
					{ key: 'path', title: localize('u6d.set.vals.colPath', "Path") },
					{ key: 'name', title: localize('u6d.set.vals.colName', "Parameter") },
					{ key: 'value', title: localize('u6d.set.vals.colVal', "Value") },
					{ key: 'unit', title: localize('u6d.set.vals.colUnit', "Unit") },
					{ key: 'clause', title: localize('u6d.set.vals.colClause', "Clause") },
					{ key: 'overridden', title: localize('u6d.set.vals.colOver', "Status"), type: 'status' },
				],
				rows,
			}],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.activeOverrides',
	title: localize('u6d.set.over.title', "Project Code Overrides Audit"),
	part: 'settings',
	icon: Codicon.edit,
	help: localize('u6d.set.over.help', "Lists every project override of a code pack parameter, comparing the pack default with the overridden value and flagging invalid overrides."),
	secondaryActions: openSettingsAction(localize('u6d.set.openSettings', "Open Project Settings")),
	run: async ctx => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/values', {
			settingsText,
			root: ctx.project!.root.fsPath,
		}));
		const overrides = asArray(raw.overrides).map(asBag).map(o => ({
			path: str(o.path),
			name: str(o.name || o.path),
			packValue: formatScalar(o.packValue),
			value: formatScalar(o.value),
			unit: str(o.unit, '–'),
			clause: str(o.clause, '–'),
		}));
		const probs = asArray(raw.problems).map(asBag).map(p => ({
			path: str(p.path),
			message: str(p.message),
			packValue: formatScalar(p.packValue),
			status: 'Fail',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.over.mCount', "Active Overrides"), value: String(overrides.length) },
				{ label: localize('u6d.set.over.mBad', "Refused Overrides"), value: String(probs.length), tone: probs.length ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'overrides',
					title: localize('u6d.set.over.tab', "Applied Code Overrides"),
					columns: [
						{ key: 'path', title: localize('u6d.set.over.colPath', "Path") },
						{ key: 'name', title: localize('u6d.set.over.colName', "Parameter") },
						{ key: 'packValue', title: localize('u6d.set.over.colDef', "Pack Default") },
						{ key: 'value', title: localize('u6d.set.over.colVal', "Override Value") },
						{ key: 'unit', title: localize('u6d.set.over.colUnit', "Unit") },
						{ key: 'clause', title: localize('u6d.set.over.colClause', "Clause") },
					],
					rows: overrides,
					emptyMessage: localize('u6d.set.over.empty', "No code pack parameter overrides defined in this project."),
				},
				{
					id: 'problems',
					title: localize('u6d.set.over.probTab', "Refused Overrides"),
					columns: [
						{ key: 'path', title: localize('u6d.set.over.colPPath', "Path") },
						{ key: 'message', title: localize('u6d.set.over.colPMsg', "Reason") },
						{ key: 'packValue', title: localize('u6d.set.over.colPDef', "Fallback Value") },
						{ key: 'status', title: localize('u6d.set.over.colPStat', "Status"), type: 'status' },
					],
					rows: probs,
					emptyMessage: localize('u6d.set.over.noProbs', "All overrides are valid."),
				},
			],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.packFallbacks',
	title: localize('u6d.set.fall.title', "Generic Practice Fallbacks & Uncovered Areas"),
	part: 'settings',
	icon: Codicon.info,
	help: localize('u6d.set.fall.help', "Reports tables missing from the active code pack and generic SAEngine practice values substituted where the code is silent."),
	run: async ctx => {
		const settingsText = await readSettingsText(ctx);
		const raw = asBag(await ctx.engineRequest('codes/values', {
			settingsText,
			root: ctx.project!.root.fsPath,
		}));
		const falls = asArray(raw.fallbacks).map(asBag).map(f => ({
			path: str(f.path),
			value: formatScalar(f.value),
			note: str(f.note, '–'),
		}));
		const missing = asStrings(raw.missing).map(m => ({
			area: m,
			status: 'Warn',
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.fall.mFall', "Practice Fallbacks"), value: String(falls.length) },
				{ label: localize('u6d.set.fall.mMiss', "Uncovered Tables"), value: String(missing.length), tone: missing.length ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'fallbacks',
					title: localize('u6d.set.fall.tab', "Generic Practice Values Used"),
					columns: [
						{ key: 'path', title: localize('u6d.set.fall.colPath', "Path") },
						{ key: 'value', title: localize('u6d.set.fall.colVal', "Value") },
						{ key: 'note', title: localize('u6d.set.fall.colNote', "Note") },
					],
					rows: falls,
					emptyMessage: localize('u6d.set.fall.empty', "No generic practice fallbacks active."),
				},
				{
					id: 'missing',
					title: localize('u6d.set.fall.missTab', "Uncovered Code Tables"),
					columns: [
						{ key: 'area', title: localize('u6d.set.fall.colArea', "Table / Area") },
						{ key: 'status', title: localize('u6d.set.fall.colStat', "Status"), type: 'status' },
					],
					rows: missing,
					emptyMessage: localize('u6d.set.fall.noMiss', "All tables are covered by the active pack chain."),
				},
			],
		};
	},
});

registerSettingsPanel({
	id: 'saengine.settings.codedGeometry',
	title: localize('u6d.set.coded.title', "Coded Structure Templates"),
	part: 'settings',
	icon: Codicon.symbolStructure,
	help: localize('u6d.set.coded.help', "Lists parametric coded structure templates provided by installed structureTemplate packages."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('codes/templates', {
			kind: 'structureTemplate',
			root: ctx.project!.root.fsPath,
		}));
		const items = asArray(raw.presets ?? raw.templates ?? raw.coded).map(asBag);
		const rows: DataPanelRow[] = items.map(it => ({
			id: str(it.id || it.name),
			package: str(it.package, '–'),
			file: str(it.file, '–'),
			description: str(it.description, '–'),
		}));
		return {
			metrics: [
				{ label: localize('u6d.set.coded.mCount', "Coded Presets"), value: String(rows.length) },
			],
			tables: [{
				id: 'presets',
				title: localize('u6d.set.coded.tab', "Installed Structure Template Presets"),
				columns: [
					{ key: 'id', title: localize('u6d.set.coded.colId', "ID") },
					{ key: 'package', title: localize('u6d.set.coded.colPkg', "Package") },
					{ key: 'file', title: localize('u6d.set.coded.colFile', "Template File") },
					{ key: 'description', title: localize('u6d.set.coded.colDesc', "Description") },
				],
				rows,
				emptyMessage: localize('u6d.set.coded.empty', "No structure template presets installed."),
			}],
		};
	},
});

//#endregion

//#region Load patterns (issue #301)

/** Load Patterns...: Project Settings at its Load Patterns page (the project's own load cases). */
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.settings.loadPatterns',
			title: localize2('set.loadPatterns', "Load Patterns..."),
			category,
			icon: Codicon.symbolEnum,
			f1: true,
			precondition: projectOpen,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		const project = accessor.get(ISaengineProjectService).project;
		const editorService = accessor.get(IEditorService);
		const commandService = accessor.get(ICommandService);
		const part = project && projectParts(project.type).find(p => p.id === 'settings');
		if (project && part) {
			await openPartSection(project, part, { id: 'loadPatterns', label: localize('set.loadPatternsPage', "Load Patterns"), sections: ['loadPatterns'] }, { editorService, commandService });
		}
	}
});

//#endregion
