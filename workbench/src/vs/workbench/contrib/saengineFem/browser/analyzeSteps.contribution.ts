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
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, IDataPanelContext, IEngineDataPanelDescriptor, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';
import { openPart } from '../../saengineProject/browser/projectParts.js';

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

function registerAnalyzePanel(descriptor: IEngineDataPanelDescriptor): void {
	registerEngineDataPanel(descriptor);
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id: descriptor.id,
				title: { value: descriptor.title, original: descriptor.title },
				category,
				icon: descriptor.icon,
				f1: true,
				precondition: projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), descriptor.id);
		}
	});
}

function registerRunStepPanel(id: string, step: 'derive' | 'analyse' | 'design', title: string, help: string, icon: typeof Codicon.play, followUpLabel: string, followUpCommand: string): void {
	const openFollowUp = async (c: IDataPanelContext): Promise<void> => {
		if (followUpCommand === 'openFem') {
			const femPart = partById('fem');
			if (c.project && femPart) {
				await openPart(c.project, femPart, {
					editorService: c.editorService,
					fileService: c.fileService,
					openerService: c.openerService,
					commandService: c.commandService,
				});
			}
			return;
		}
		await c.commandService.executeCommand(followUpCommand);
	};

	registerAnalyzePanel({
		id,
		title,
		part: 'fem',
		icon,
		help,
		autoRun: false,
		runLabel: title,
		secondaryActions: [{
			id: 'followUp',
			label: followUpLabel,
			icon: Codicon.goToFile,
			run: c => openFollowUp(c),
		}],
		run: async ctx => {
			const outcome = await ctx.actionsService.run([{ action: 'run.step', params: { step } }], { apply: true });
			const first = outcome.results[0];
			const problems: string[] = [];
			if (!outcome.ok && first) {
				for (const p of first.problems) {
					problems.push(p.part ? `${p.part}: ${p.reason}` : p.reason);
				}
			}
			const rows: DataPanelRow[] = [
				{
					step,
					status: outcome.ok ? 'Pass' : 'Fail',
					message: first?.message ?? '',
					filesWritten: outcome.written.join(', ') || '–',
				},
			];
			for (const w of first?.warnings ?? []) {
				rows.push({ step, status: 'Warning', message: w, filesWritten: '–' });
			}
			const dataBag = asBag(first?.data);
			for (const [k, v] of Object.entries(dataBag)) {
				rows.push({
					step: k,
					status: 'OK',
					message: typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v),
					filesWritten: '–',
				});
			}
			return {
				metrics: [
					{ label: localize('u3.step.name', "Step"), value: step },
					{ label: localize('u3.step.result', "Status"), value: outcome.ok ? localize('u3.ok', "Passed") : localize('u3.fail', "Failed"), tone: outcome.ok ? 'ok' : 'fail' },
					{ label: localize('u3.step.written', "Written Files"), value: String(outcome.written.length) },
				],
				tables: [{
					id: 'step',
					title: localize('u3.step.table', "Step Output"),
					columns: [
						{ key: 'step', title: localize('u3.col.step', "Step / Key") },
						{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
						{ key: 'message', title: localize('u3.col.message', "Details") },
						{ key: 'filesWritten', title: localize('u3.col.written', "Written Files") },
					],
					rows,
				}],
				primaryAction: {
					id: 'openTarget',
					label: followUpLabel,
					icon: Codicon.goToFile,
					run: () => openFollowUp(ctx),
				},
				notes: asStrings(first?.warnings),
				problems,
			};
		},
	});
}

registerRunStepPanel(
	'saengine.analyze.runDerive',
	'derive',
	localize('u3.derive.title', "Derive Analysis Model Only"),
	localize('u3.derive.help', "Derives 08 FEM/model.osmodel from 06 BIM, 02 Project Settings, 03 Materials and 04 Objects without running the solver."),
	Codicon.symbolStructure,
	localize('u3.derive.openFem', "Open FEM Model"),
	'openFem',
);

registerRunStepPanel(
	'saengine.analyze.runAnalyse',
	'analyse',
	localize('u3.analyse.title', "Run Structural Analysis Only"),
	localize('u3.analyse.help', "Runs the derived 08 FEM/model.osmodel through OpenSees without advancing to reinforcement design, substructure or drawings."),
	Codicon.runAll,
	localize('u3.analyse.openTables', "Open Result Tables"),
	'saengine.showTables',
);

registerRunStepPanel(
	'saengine.analyze.runDesign',
	'design',
	localize('u3.designStep.title', "Run Member Design Checks Only"),
	localize('u3.designStep.help', "Runs code member design checks on the existing analysis results and computes required steel."),
	Codicon.symbolRuler,
	localize('u3.designStep.openChecks', "Open Design Checks"),
	'saengine.analyze.checkProject',
);

registerAnalyzePanel({
	id: 'saengine.analyze.checkProject',
	title: localize('u3.checkProj.title', "Check Project (Member & Code Checks)"),
	part: 'fem',
	icon: Codicon.checklist,
	help: localize('u3.checkProj.help', "Summarizes every part's readiness and lists failing (or all) structural member & seismic building checks from the latest design run."),
	fields: [
		{ key: 'onlyFailing', label: localize('u3.checkProj.onlyFailing', "Show failing checks only"), type: 'checkbox', defaultValue: true },
	],
	run: async (ctx, values) => {
		const summaryOutcome = await ctx.actionsService.run([{ action: 'results.summary', params: {} }], { apply: false });
		const sumData = asBag(summaryOutcome.results[0]?.data);
		const parts = asArray(sumData.parts).map(asBag);
		const partRows: DataPanelRow[] = parts.map(p => ({
			part: str(p.part),
			state: str(p.state),
			detail: str(p.detail || p.reason || ''),
		}));

		const checksOutcome = await ctx.actionsService.run([{ action: 'checks.list', params: { failing: Boolean(values.onlyFailing), limit: 500 } }], { apply: false });
		const checksFirst = checksOutcome.results[0];
		const problems: string[] = [];
		const notes: string[] = [];
		if (!checksOutcome.ok && checksFirst) {
			notes.push(checksFirst.problems.map(p => p.reason).join('; '));
		}
		const checksData = asBag(checksFirst?.data);
		const members = asArray(checksData.members).map(asBag);
		const memberRows: DataPanelRow[] = members.map(m => ({
			id: str(m.id),
			type: str(m.type),
			status: str(m.status, 'Pass'),
			utilisation: num(m.utilisation) ?? '–',
			governing: str(m.governing, '–'),
			failingChecks: asStrings(m.failing).join(', ') || '–',
		}));
		const buildingRows: DataPanelRow[] = asArray(checksData.building).map(asBag).map(b => ({
			check: str(b.name),
			utilisation: num(b.utilisation) ?? '–',
			status: b.ok === false ? 'Fail' : 'Pass',
			note: str(b.note),
		}));

		const failingMembers = members.filter(m => str(m.status).toLowerCase().includes('fail')).length;
		const emptyState = !members.length && !checksOutcome.ok ? {
			title: localize('u3.checkProj.emptyTitle', "Run member design first"),
			text: localize('u3.checkProj.emptyText', "No design checks exist yet; run the structural design step to check members and seismic drift."),
			action: {
				id: 'runDesign',
				label: localize('u3.checkProj.runDesign', "Run Design Checks"),
				icon: Codicon.play,
				run: () => void openEngineDataPanel(ctx.editorService, 'saengine.analyze.runDesign'),
			},
		} : undefined;

		return {
			metrics: [
				{ label: localize('u3.checkProj.membersListed', "Member Checks"), value: String(memberRows.length), tone: failingMembers ? 'warn' : 'ok' },
				{ label: localize('u3.checkProj.buildingChecks', "Building Checks"), value: String(buildingRows.length) },
				{ label: localize('u3.checkProj.parts', "Project Parts"), value: String(partRows.length) },
			],
			tables: [
				{
					id: 'members',
					title: localize('u3.checkProj.membersTab', "Member Design Checks"),
					columns: [
						{ key: 'id', title: localize('u3.col.member', "Member") },
						{ key: 'type', title: localize('u3.col.type', "Type") },
						{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
						{ key: 'utilisation', title: localize('u3.col.util', "Utilisation"), type: 'number', align: 'right' },
						{ key: 'governing', title: localize('u3.col.governing', "Governing Check") },
						{ key: 'failingChecks', title: localize('u3.col.failingChecks', "Failing Checks") },
					],
					rows: memberRows,
					emptyMessage: localize('u3.checkProj.noFailing', "All checked members pass under the current filter."),
				},
				{
					id: 'building',
					title: localize('u3.checkProj.buildingTab', "Seismic / Building Checks"),
					columns: [
						{ key: 'check', title: localize('u3.col.check', "Check") },
						{ key: 'utilisation', title: localize('u3.col.util', "Utilisation"), type: 'number', align: 'right' },
						{ key: 'status', title: localize('u3.col.status', "Status"), type: 'status' },
						{ key: 'note', title: localize('u3.col.note', "Note") },
					],
					rows: buildingRows,
				},
				{
					id: 'parts',
					title: localize('u3.checkProj.partsTab', "Project Part States"),
					columns: [
						{ key: 'part', title: localize('u3.col.part', "Part") },
						{ key: 'state', title: localize('u3.col.state', "State"), type: 'status' },
						{ key: 'detail', title: localize('u3.col.details', "Details") },
					],
					rows: partRows,
				},
			],
			notes,
			problems,
			emptyState,
		};
	},
});

registerAnalyzePanel({
	id: 'saengine.analyze.validateProject',
	title: localize('u3.validate.title', "Validate Project Schemas & Rules"),
	part: 'fem',
	icon: Codicon.pass,
	help: localize('u3.validate.help', "Validates every part file in the project against its JSON schema, Pydantic model, cross-part references, plot setbacks and FEM model schema."),
	run: async ctx => {
		const raw = asBag(await ctx.engineRequest('project/validateAll', {
			projectRoot: ctx.project!.root.fsPath,
		}));
		const summary = asBag(raw.summary);
		const parts = asArray(raw.parts).map(asBag);
		const partRows: DataPanelRow[] = parts.map(p => {
			const probs = asArray(p.problems);
			return {
				part: str(p.part),
				file: str(p.file, '–'),
				state: str(p.state),
				problemCount: probs.length,
			};
		});
		const problemRows: DataPanelRow[] = asArray(raw.problems).map(asBag).map(p => ({
			part: str(p.part),
			file: str(p.file, '–'),
			severity: str(p.severity, 'error'),
			path: str(p.path, '–'),
			message: str(p.message),
		}));
		const errors = num(summary.errors) ?? 0;
		const warnings = num(summary.warnings) ?? 0;
		return {
			metrics: [
				{ label: localize('u3.validate.overall', "Validation"), value: raw.ok ? localize('u3.pass', "Valid") : localize('u3.invalid', "Problems Found"), tone: raw.ok ? 'ok' : 'fail' },
				{ label: localize('u3.validate.errors', "Errors"), value: String(errors), tone: errors ? 'fail' : 'ok' },
				{ label: localize('u3.validate.warnings', "Warnings"), value: String(warnings), tone: warnings ? 'warn' : 'ok' },
			],
			tables: [
				{
					id: 'parts',
					title: localize('u3.validate.partsTab', "Project Parts"),
					columns: [
						{ key: 'part', title: localize('u3.col.part', "Part") },
						{ key: 'file', title: localize('u3.col.file', "File") },
						{ key: 'state', title: localize('u3.col.state', "State"), type: 'status' },
						{ key: 'problemCount', title: localize('u3.col.issues', "Issues"), type: 'number', align: 'right' },
					],
					rows: partRows,
				},
				{
					id: 'problems',
					title: localize('u3.validate.problemsTab', "Validation Problems"),
					columns: [
						{ key: 'part', title: localize('u3.col.part', "Part") },
						{ key: 'severity', title: localize('u3.col.severity', "Severity"), type: 'status' },
						{ key: 'path', title: localize('u3.col.fieldPath', "Field / Item") },
						{ key: 'message', title: localize('u3.col.problemMessage', "Message") },
					],
					rows: problemRows,
					emptyMessage: localize('u3.validate.clean', "No validation errors or warnings in any project part."),
				},
			],
			primaryAction: partById('fem') ? {
				id: 'openFem',
				label: localize('u3.derive.openFem', "Open FEM Model"),
				icon: Codicon.symbolStructure,
				run: async c => {
					const p = partById('fem');
					if (c.project && p) {
						await openPart(c.project, p, {
							editorService: c.editorService,
							fileService: c.fileService,
							openerService: c.openerService,
							commandService: c.commandService,
						});
					}
				},
			} : undefined,
		};
	},
});
