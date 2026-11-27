/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Size Steel Members (issue #286): the lightest catalogue section per steel member group that
 * passes every strength and serviceability check, analysis and design iterated until the
 * sections stop changing (engine `design/steelSizing`). The panel proposes; nothing changes
 * until the engineer applies all groups or the ones listed (action `design.steel.apply`: one
 * undo step in the object types, and the building model when members move to new types).
 */

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Severity } from '../../../../platform/notification/common/notification.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, DataPanelValues, IDataPanelContext, IEngineDataPanelDescriptor, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';

export const SIZE_STEEL_MEMBERS_ID = 'saengine.fem.sizeSteelMembers';

interface IJsonBag {
	readonly [key: string]: unknown;
}

function asBag(value: unknown): IJsonBag {
	return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as IJsonBag : {};
}

function asArray(value: unknown): readonly unknown[] {
	return Array.isArray(value) ? value : [];
}

function str(value: unknown, fallback = ''): string {
	return typeof value === 'string' ? value : typeof value === 'number' ? String(value) : fallback;
}

function num(value: unknown): number | undefined {
	return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function list(value: unknown): string[] {
	return String(value ?? '').split(',').map(s => s.trim()).filter(s => !!s);
}

/** The sizing options of the panel's fields (engine `SizingOptions.from_dict`). */
export function sizingOptions(values: DataPanelValues): { [key: string]: unknown } {
	const depth = (v: unknown) => typeof v === 'number' && v > 0 ? v : null;
	const candidates = list(values.candidates);
	const types = list(values.types);
	return {
		maxIterations: typeof values.maxIterations === 'number' ? values.maxIterations : 5,
		sameSection: values.sameSection !== false,
		minDepth: depth(values.minDepth),
		maxDepth: depth(values.maxDepth),
		...(candidates.length ? { candidates } : {}),
		...(types.length ? { types } : {}),
	};
}

/** A group's status as the table says it. */
export function statusText(status: string): string {
	switch (status) {
		case 'ok': return localize('steelSizing.statusResize', "Resize");
		case 'unchanged': return localize('steelSizing.statusUnchanged', "Unchanged");
		case 'tooSmall': return localize('steelSizing.statusTooSmall', "No section passes");
		default: return status;
	}
}

/** The last proposal of this window, by project root: what Apply applies. */
const proposals = new Map<string, IJsonBag>();

async function applyProposal(ctx: IDataPanelContext, groups: readonly string[] | 'all'): Promise<void> {
	const root = ctx.project?.root.fsPath;
	const proposal = root ? proposals.get(root) : undefined;
	if (!proposal) {
		ctx.notificationService.notify({ severity: Severity.Info, message: localize('steelSizing.runFirst', "Run Size Steel Members first: there is no proposal to apply.") });
		return;
	}
	if (groups !== 'all' && !groups.length) {
		ctx.notificationService.notify({ severity: Severity.Info, message: localize('steelSizing.noneListed', "List the types to apply in 'Apply selected' (comma separated).") });
		return;
	}
	const outcome = await ctx.actionsService.run([{ action: 'design.steel.apply', params: { proposal, groups } }], { apply: true });
	const first = outcome.results[0];
	if (!outcome.ok) {
		const why = first ? [first.message, ...first.problems.map(p => p.reason)].filter(s => !!s).join('; ') : '';
		ctx.notificationService.notify({ severity: Severity.Error, message: localize('steelSizing.applyFailed', "The sections were not applied: {0}", why) });
		return;
	}
	ctx.notificationService.notify({ severity: Severity.Info, message: first?.message ?? localize('steelSizing.applied', "Sections applied.") });
}

const descriptor: IEngineDataPanelDescriptor = {
	id: SIZE_STEEL_MEMBERS_ID,
	title: localize('steelSizing.title', "Size Steel Members"),
	part: 'fem',
	icon: Codicon.symbolStructure,
	help: localize('steelSizing.help', "Proposes the lightest catalogue section for each steel beam, column and brace type that passes every strength and deflection check under the design combinations, analysing and designing again until the sections stop changing. Needs the current analysis results. Nothing changes until you apply."),
	autoRun: false,
	runLabel: localize('steelSizing.run', "Size Steel Members"),
	fields: [
		{ key: 'maxIterations', label: localize('steelSizing.maxIterations', "Maximum iterations (analyses)"), type: 'number', defaultValue: 5, min: 1, max: 20, step: '1' },
		{ key: 'sameSection', label: localize('steelSizing.sameSection', "Same section for every member of a type"), type: 'checkbox', defaultValue: true, help: localize('steelSizing.sameSectionHelp', "Off: each member gets its own lightest section; members whose sections differ move to new types when applied.") },
		{ key: 'candidates', label: localize('steelSizing.candidates', "Candidate sections or families"), type: 'text', defaultValue: '', placeholder: localize('steelSizing.candidatesHint', "blank: each type's own family; e.g. IPE, HEB 200, HEB 220") },
		{ key: 'minDepth', label: localize('steelSizing.minDepth', "Least depth [mm] (0: none)"), type: 'number', defaultValue: 0, min: 0, step: '10' },
		{ key: 'maxDepth', label: localize('steelSizing.maxDepth', "Greatest depth [mm] (0: none)"), type: 'number', defaultValue: 0, min: 0, step: '10' },
		{ key: 'types', label: localize('steelSizing.types', "Types to size"), type: 'text', defaultValue: '', placeholder: localize('steelSizing.typesHint', "blank: every steel type; e.g. B1, C1") },
		{ key: 'applyGroups', label: localize('steelSizing.applyGroups', "Apply selected (types)"), type: 'text', defaultValue: '', placeholder: localize('steelSizing.applyGroupsHint', "filled with the types to resize after a run; edit to choose") },
	],
	secondaryActions: [
		{
			id: 'applyAll',
			label: localize('steelSizing.applyAll', "Apply All"),
			icon: Codicon.checkAll,
			run: ctx => applyProposal(ctx, 'all'),
		},
		{
			id: 'applySelected',
			label: localize('steelSizing.applySelected', "Apply Selected"),
			icon: Codicon.check,
			run: (ctx, values) => applyProposal(ctx, list(values.applyGroups)),
		},
	],
	run: async (ctx, values) => {
		const root = ctx.project?.root.fsPath;
		if (!root) {
			return { tables: [], problems: [localize('steelSizing.noProject', "Open a project first.")] };
		}
		const raw = asBag(await ctx.engineRequest('design/steelSizing', { projectRoot: root, options: sizingOptions(values) }));
		if (typeof raw.error === 'string') {
			proposals.delete(root);
			return { tables: [], problems: [raw.error] };
		}
		proposals.set(root, raw);
		const groups = asArray(raw.groups).map(asBag);
		const rows: DataPanelRow[] = groups.map(g => ({
			group: str(g.group),
			type: str(g.type),
			members: asArray(g.members).length,
			current: str(g.currentSection, '–'),
			currentMass: num(g.currentMass),
			before: num(g.currentUtilisation),
			proposed: str(g.proposedSection, '–'),
			proposedMass: num(g.proposedMass),
			after: num(g.proposedUtilisation),
			governing: str(g.governingCheck, '–'),
			status: statusText(str(g.status)),
		}));
		const history: DataPanelRow[] = asArray(raw.history).map(asBag).map(h => ({
			iteration: num(h.iteration),
			changed: asArray(h.changed).map(c => str(c)).join(', ') || '–',
			maxUtilisation: num(h.maxUtilisation),
		}));
		const newTypes: DataPanelRow[] = asArray(raw.newTypes).map(asBag).map(n => ({
			type: str(n.type),
			from: str(n.from),
			section: str(asBag(n.proposed).section, '–'),
			members: asArray(n.members).map(m => str(m)).join(', '),
		}));
		const resized = asArray(raw.types).map(asBag).filter(t => t.status === 'ok').map(t => str(t.type));
		const tooSmall = groups.filter(g => g.status === 'tooSmall').length;
		const converged = raw.converged === true;
		return {
			metrics: [
				{ label: localize('steelSizing.mConverged', "Converged"), value: converged ? localize('steelSizing.yes', "Yes") : localize('steelSizing.no', "No"), tone: converged ? 'ok' : 'warn' },
				{ label: localize('steelSizing.mIterations', "Iterations"), value: String(num(raw.iterations) ?? 0) },
				{ label: localize('steelSizing.mResized', "Types to resize"), value: String(resized.length) },
				{ label: localize('steelSizing.mTooSmall', "No section passes"), value: String(tooSmall), tone: tooSmall ? 'fail' : 'ok' },
			],
			tables: [
				{
					id: 'proposal',
					title: localize('steelSizing.tProposal', "Proposed sections (utilisation before → after)"),
					columns: [
						{ key: 'group', title: localize('steelSizing.cGroup', "Group") },
						{ key: 'type', title: localize('steelSizing.cType', "Type") },
						{ key: 'members', title: localize('steelSizing.cMembers', "Members"), type: 'number', align: 'right' },
						{ key: 'current', title: localize('steelSizing.cCurrent', "Current") },
						{ key: 'currentMass', title: localize('steelSizing.cCurrentMass', "kg/m"), type: 'number', align: 'right' },
						{ key: 'before', title: localize('steelSizing.cBefore', "Utilisation before"), type: 'number', align: 'right' },
						{ key: 'proposed', title: localize('steelSizing.cProposed', "Proposed") },
						{ key: 'proposedMass', title: localize('steelSizing.cProposedMass', "kg/m"), type: 'number', align: 'right' },
						{ key: 'after', title: localize('steelSizing.cAfter', "Utilisation after"), type: 'number', align: 'right' },
						{ key: 'governing', title: localize('steelSizing.cGoverning', "Governing check") },
						{ key: 'status', title: localize('steelSizing.cStatus', "Status") },
					],
					rows,
					emptyMessage: localize('steelSizing.empty', "No steel beam, column or brace types in the analysis."),
				},
				{
					id: 'history',
					title: localize('steelSizing.tHistory', "Iterations"),
					columns: [
						{ key: 'iteration', title: localize('steelSizing.cIteration', "Iteration"), type: 'number', align: 'right' },
						{ key: 'changed', title: localize('steelSizing.cChanged', "Sections changed") },
						{ key: 'maxUtilisation', title: localize('steelSizing.cMaxU', "Largest utilisation"), type: 'number', align: 'right' },
					],
					rows: history,
				},
				...(newTypes.length ? [{
					id: 'newTypes',
					title: localize('steelSizing.tNewTypes', "New types (members sized on their own)"),
					columns: [
						{ key: 'type', title: localize('steelSizing.cNewType', "New type") },
						{ key: 'from', title: localize('steelSizing.cFrom', "From") },
						{ key: 'section', title: localize('steelSizing.cSection', "Section") },
						{ key: 'members', title: localize('steelSizing.cMemberIds', "Members") },
					],
					rows: newTypes,
				}] : []),
			],
			notes: asArray(raw.notes).map(n => str(n)).filter(n => !!n),
			problems: asArray(raw.warnings).map(w => str(w)).filter(w => !!w),
			updatedValues: { applyGroups: [...resized, ...newTypes.map(n => str(n.type))].join(', ') },
			statusText: converged
				? localize('steelSizing.statusConverged', "Converged in {0} iteration(s). Review the table, then Apply All or Apply Selected.", String(num(raw.iterations) ?? 0))
				: localize('steelSizing.statusNotConverged', "Not converged: see the problems before applying."),
			statusSeverity: converged ? 'info' : 'warning',
		};
	},
};

registerEngineDataPanel(descriptor);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SIZE_STEEL_MEMBERS_ID,
			title: localize2('steelSizing.command', "Size Steel Members"),
			category: localize2('saengine.category', "SAEngine"),
			icon: Codicon.symbolStructure,
			f1: true,
			precondition: ContextKeyExpr.has('saengineProjectOpen'),
		});
	}

	override run(accessor: ServicesAccessor): Promise<unknown> {
		return openEngineDataPanel(accessor.get(IEditorService), SIZE_STEEL_MEMBERS_ID);
	}
});
