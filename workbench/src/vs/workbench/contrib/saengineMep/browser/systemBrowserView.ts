/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, EventType } from '../../../../base/browser/dom.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { formatNumber } from '../../saengineSoil/browser/soilDocument.js';
import { isRecord, optionalNumber, optionalString, records, strings } from './mepRead.js';
import { resultSection, tiles } from './mepResults.js';

/*
 * The MEP System Browser (Revit-parity R8): logical networks grouped by classification ->
 * system -> elements, with flow/load totals, critical path length, and connectivity warnings.
 * Clicking an element or warning selects it in the MEP plan/coordination view.
 */

export const MEP_SYSTEMS_COMMAND = 'saengine.mep.systems';

export interface ISystemElementInfo {
	readonly id: string;
	readonly kind: string;
	readonly discipline: string;
	readonly story?: string;
	readonly domain: string;
	readonly classification: string;
	readonly isSource: boolean;
	readonly isTerminal: boolean;
	readonly flow?: number;
	readonly fixtureUnits?: number;
	readonly load?: number;
}

export interface ISystemItem {
	readonly id: string;
	readonly name: string;
	readonly classification: string;
	readonly classificationLabel: string;
	readonly domain: string;
	readonly sources: readonly string[];
	readonly elements: readonly string[];
	readonly elementCount: number;
	readonly airFlowLps?: number;
	readonly waterFlowLps?: number;
	readonly fixtureUnits?: number;
	readonly electricalLoadKw?: number;
	readonly criticalPathLength: number;
	readonly warnings: number;
}

export interface ISystemIssue {
	readonly id: string;
	readonly kind: string;
	readonly severity: 'error' | 'warning';
	readonly message: string;
	readonly elements: readonly string[];
	readonly story?: string;
	readonly point?: readonly number[];
	readonly system?: string;
	readonly classification?: string;
}

export interface ISystemsReport {
	readonly systems: readonly ISystemItem[];
	readonly issues: readonly ISystemIssue[];
	readonly elements: { readonly [id: string]: ISystemElementInfo };
	readonly unassigned: readonly string[];
	readonly summary: {
		readonly systems: number;
		readonly elements: number;
		readonly connectors: number;
		readonly connections: number;
		readonly issues: number;
	};
}

export interface ISystemBrowserState {
	readonly report: ISystemsReport | undefined;
	readonly state: 'idle' | 'computing' | 'ok' | 'missing' | 'error';
	readonly error?: string;
	filter: string;
	readonly selectedId?: string;
}

export interface ISystemBrowserActions {
	recompute(): void;
	exportBcf(): void;
	selectElement(elementId: string, story?: string): void;
	rerender(): void;
}

export function classificationLabel(classification: string): string {
	switch (classification) {
		case 'supplyAir': return localize('sys.cls.supplyAir', "Supply air");
		case 'returnAir': return localize('sys.cls.returnAir', "Return air");
		case 'exhaustAir': return localize('sys.cls.exhaustAir', "Exhaust air");
		case 'freshAir': return localize('sys.cls.freshAir', "Fresh air");
		case 'kitchenExhaust': return localize('sys.cls.kitchenExhaust', "Kitchen exhaust");
		case 'smokeExtract': return localize('sys.cls.smokeExtract', "Smoke extract");
		case 'chilledWater': return localize('sys.cls.chilledWater', "Chilled water");
		case 'condenserWater': return localize('sys.cls.condenserWater', "Condenser water");
		case 'domesticColdWater': return localize('sys.cls.domesticColdWater', "Domestic cold water");
		case 'domesticHotWater': return localize('sys.cls.domesticHotWater', "Domestic hot water");
		case 'sanitary': return localize('sys.cls.sanitary', "Sanitary");
		case 'vent': return localize('sys.cls.vent', "Vent");
		case 'stormWater': return localize('sys.cls.stormWater', "Storm water");
		case 'fireProtection': return localize('sys.cls.fireProtection', "Fire protection");
		case 'power': return localize('sys.cls.power', "Power circuit");
		case 'cableTray': return localize('sys.cls.cableTray', "Cable tray");
		default: return classification;
	}
}

export function readSystemsReport(value: unknown): ISystemsReport | undefined {
	if (!isRecord(value) || !Array.isArray(value.systems)) {
		return undefined;
	}
	const systems: ISystemItem[] = records<Record<string, unknown>>(value.systems).map(s => ({
		id: String(s.id ?? ''),
		name: String(s.name ?? ''),
		classification: String(s.classification ?? ''),
		classificationLabel: String(s.classificationLabel ?? s.classification ?? ''),
		domain: String(s.domain ?? ''),
		sources: strings(s.sources),
		elements: strings(s.elements),
		elementCount: Number(s.elementCount ?? 0),
		airFlowLps: optionalNumber(s.airFlowLps),
		waterFlowLps: optionalNumber(s.waterFlowLps),
		fixtureUnits: optionalNumber(s.fixtureUnits),
		electricalLoadKw: optionalNumber(s.electricalLoadKw),
		criticalPathLength: Number(s.criticalPathLength ?? 0),
		warnings: Number(s.warnings ?? 0),
	}));
	const issues: ISystemIssue[] = records<Record<string, unknown>>(value.issues).map(i => ({
		id: String(i.id ?? ''),
		kind: String(i.kind ?? ''),
		severity: i.severity === 'error' ? 'error' : 'warning',
		message: String(i.message ?? ''),
		elements: strings(i.elements),
		story: optionalString(i.story),
		point: Array.isArray(i.point) ? i.point.filter((n): n is number => typeof n === 'number') : undefined,
		system: optionalString(i.system),
		classification: optionalString(i.classification),
	}));
	const elements: { [id: string]: ISystemElementInfo } = {};
	if (isRecord(value.elements)) {
		for (const [id, raw] of Object.entries(value.elements)) {
			if (!isRecord(raw)) {
				continue;
			}
			elements[id] = {
				id: String(raw.id ?? id),
				kind: String(raw.kind ?? ''),
				discipline: String(raw.discipline ?? ''),
				story: optionalString(raw.story),
				domain: String(raw.domain ?? ''),
				classification: String(raw.classification ?? ''),
				isSource: !!raw.isSource,
				isTerminal: !!raw.isTerminal,
				flow: optionalNumber(raw.flow),
				fixtureUnits: optionalNumber(raw.fixtureUnits),
				load: optionalNumber(raw.load),
			};
		}
	}
	const summaryRaw = isRecord(value.summary) ? value.summary : {};
	return {
		systems,
		issues,
		elements,
		unassigned: strings(value.unassigned),
		summary: {
			systems: Number(summaryRaw.systems ?? systems.length),
			elements: Number(summaryRaw.elements ?? Object.keys(elements).length),
			connectors: Number(summaryRaw.connectors ?? 0),
			connections: Number(summaryRaw.connections ?? 0),
			issues: Number(summaryRaw.issues ?? issues.length),
		},
	};
}

function systemMetricsText(sys: ISystemItem): string {
	const parts: string[] = [];
	if (sys.airFlowLps !== undefined) {
		parts.push(localize('sys.airFlow', "{0} L/s", formatNumber(sys.airFlowLps, 1)));
	}
	if (sys.waterFlowLps !== undefined) {
		parts.push(localize('sys.waterFlow', "{0} L/s", formatNumber(sys.waterFlowLps, 2)));
	}
	if (sys.fixtureUnits !== undefined) {
		parts.push(localize('sys.fu', "{0} FU", formatNumber(sys.fixtureUnits, 1)));
	}
	if (sys.electricalLoadKw !== undefined) {
		parts.push(localize('sys.kw', "{0} kW", formatNumber(sys.electricalLoadKw, 1)));
	}
	if (sys.criticalPathLength > 0) {
		parts.push(localize('sys.critPath', "critical {0} m", formatNumber(sys.criticalPathLength, 1)));
	}
	parts.push(localize('sys.elemCount', "{0} elements", sys.elementCount));
	return parts.join(' · ');
}

function elementMetaText(info: ISystemElementInfo | undefined): string {
	if (!info) {
		return '';
	}
	const parts = [info.kind];
	if (info.story) {
		parts.push(info.story);
	}
	if (info.flow !== undefined) {
		parts.push(`${formatNumber(info.flow, 1)} L/s`);
	}
	if (info.fixtureUnits !== undefined) {
		parts.push(`${formatNumber(info.fixtureUnits, 1)} FU`);
	}
	if (info.load !== undefined) {
		parts.push(`${formatNumber(info.load, 1)} kW`);
	}
	return parts.join(' · ');
}

/** Renders the MEP System Browser view (tree by classification -> system -> elements + warnings). */
export function renderSystemBrowser(
	view: HTMLElement,
	browser: ISystemBrowserState,
	actions: ISystemBrowserActions,
	disposables: DisposableStore,
): void {
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('sys.title', "System Browser")));
	append(header, $('span.mep-view-subtitle', undefined, localize('sys.subtitle', "Logical MEP networks from connectors, system totals and connectivity checks. Click an element to select it in the plan.")));

	if (browser.state !== 'ok' || !browser.report) {
		const box = append(view, $('.mep-results-state'));
		const computing = browser.state === 'computing' || browser.state === 'idle';
		const icon = computing ? ThemeIcon.modify(Codicon.loading, 'spin') : browser.state === 'error' ? Codicon.warning : Codicon.debugDisconnect;
		append(box, $(`span.mep-results-state-icon${ThemeIcon.asCSSSelector(icon)}`));
		append(box, $('.mep-results-state-title', undefined, computing
			? localize('sys.computing', "Building MEP systems...")
			: browser.state === 'error' ? localize('sys.failed', "The MEP systems could not be checked")
				: localize('sys.missing', "Backend not available")));
		append(box, $('.mep-results-state-text', undefined, browser.state === 'error'
			? (browser.error ?? '')
			: localize('sys.missingText', "The System Browser derives connectors and network graphs in the SAEngine Python backend.")));
		return;
	}

	const report = browser.report;
	const bar = append(view, $('.coord-actions.sys-toolbar'));
	const checkBtn = append(bar, $<HTMLButtonElement>('button.mep-add', { type: 'button' }));
	append(checkBtn, $(ThemeIcon.asCSSSelector(Codicon.refresh)));
	append(checkBtn, $('span', undefined, localize('sys.refresh', "Check Systems")));
	disposables.add(addDisposableListener(checkBtn, EventType.CLICK, () => actions.recompute()));

	if (report.issues.length) {
		const bcfBtn = append(bar, $<HTMLButtonElement>('button.mep-add', { type: 'button', title: localize('sys.exportBcfTitle', "Add system connectivity warnings to Coordination issues and export BCF 3.0") }));
		append(bcfBtn, $(ThemeIcon.asCSSSelector(Codicon.export)));
		append(bcfBtn, $('span', undefined, localize('sys.exportBcf', "Export Warnings to BCF")));
		disposables.add(addDisposableListener(bcfBtn, EventType.CLICK, () => actions.exportBcf()));
	}

	const filterLabel = append(bar, $('label.sys-filter'));
	append(filterLabel, $('span', undefined, localize('sys.filterLabel', "Classification")));
	const select = append(filterLabel, $<HTMLSelectElement>('select.mep-select', { 'aria-label': localize('sys.filterAria', "Filter by system classification") }));
	const classifications = Array.from(new Set([
		...report.systems.map(s => s.classification),
		...report.issues.map(i => i.classification).filter((c): c is string => !!c),
	]));
	append(select, $<HTMLOptionElement>('option', { value: '' }, localize('sys.filterAll', "All classifications"))).selected = !browser.filter;
	for (const cls of classifications) {
		const opt = append(select, $<HTMLOptionElement>('option', { value: cls }, classificationLabel(cls)));
		opt.selected = browser.filter === cls;
	}
	disposables.add(addDisposableListener(select, EventType.CHANGE, () => {
		browser.filter = select.value;
		actions.rerender();
	}));

	const tile = tiles(view);
	tile(String(report.summary.systems), localize('sys.tileSystems', "systems"));
	tile(String(report.summary.elements), localize('sys.tileElements', "MEP elements"));
	tile(String(report.summary.connections), localize('sys.tileConnections', "connections"));
	tile(String(report.summary.issues), localize('sys.tileIssues', "warnings"), report.summary.issues > 0 ? 'warn' : 'ok');

	const filteredSystems = report.systems.filter(s => !browser.filter || s.classification === browser.filter);
	const treeSection = resultSection(view, localize('sys.treeTitle', "Systems"), localize('sys.treeCount', "{0} shown", filteredSystems.length));
	if (!filteredSystems.length) {
		append(treeSection, $('p.mep-note', undefined, localize('sys.noSystems', "No MEP systems found for this filter. Add plant/equipment and connect ducts, pipes or cable trays.")));
	} else {
		const byClass = new Map<string, ISystemItem[]>();
		for (const sys of filteredSystems) {
			const group = byClass.get(sys.classification) ?? [];
			group.push(sys);
			byClass.set(sys.classification, group);
		}
		const rootTree = append(treeSection, $('.sys-tree'));
		for (const [cls, group] of byClass) {
			const clsDetails = append(rootTree, $<HTMLDetailsElement>('details.sys-group', { open: '' }));
			const clsSummary = append(clsDetails, $('summary.sys-group-header'));
			append(clsSummary, $('span.sys-group-name', undefined, classificationLabel(cls)));
			append(clsSummary, $('span.sys-badge', undefined, String(group.length)));
			for (const sys of group) {
				const sysDetails = append(clsDetails, $<HTMLDetailsElement>('details.sys-node', { open: '' }));
				const sysSummary = append(sysDetails, $('summary.sys-node-header'));
				append(sysSummary, $('span.sys-node-name', undefined, sys.name));
				append(sysSummary, $('span.sys-node-meta', undefined, systemMetricsText(sys)));
				if (sys.warnings > 0) {
					append(sysSummary, $('span.plb-pill.band-warn', undefined, localize('sys.warningsPill', "{0} warn", sys.warnings)));
				}
				const elemList = append(sysDetails, $('ul.sys-elements'));
				for (const eid of sys.elements) {
					const info = report.elements[eid];
					const li = append(elemList, $(`li.sys-element${browser.selectedId === eid ? '.selected' : ''}`));
					const btn = append(li, $<HTMLButtonElement>('button.sys-element-btn', { type: 'button' }));
					append(btn, $(ThemeIcon.asCSSSelector(info?.isSource ? Codicon.symbolMethod : info?.isTerminal ? Codicon.circleFilled : Codicon.symbolVariable)));
					append(btn, $('span.sys-element-id', undefined, eid));
					append(btn, $('span.sys-element-meta', undefined, elementMetaText(info)));
					disposables.add(addDisposableListener(btn, EventType.CLICK, () => actions.selectElement(eid, info?.story)));
				}
			}
		}
	}

	const filteredIssues = report.issues.filter(i => !browser.filter || i.classification === browser.filter);
	const issueSection = resultSection(view, localize('sys.issuesTitle', "Connectivity checks"), String(filteredIssues.length));
	if (!filteredIssues.length) {
		append(issueSection, $('p.mep-note', undefined, localize('sys.noIssues', "All connectors are connected with matching sizes, flow directions and classifications.")));
	} else {
		const list = append(issueSection, $('ul.sys-issues'));
		for (const issue of filteredIssues) {
			const li = append(list, $('li.sys-issue'));
			append(li, $(`span.plb-pill.band-${issue.severity === 'error' ? 'fail' : 'warn'}`, undefined, issue.kind));
			const targetId = issue.elements[0];
			if (targetId) {
				const btn = append(li, $<HTMLButtonElement>('button.mep-link.sys-issue-link', { type: 'button' }, issue.message));
				disposables.add(addDisposableListener(btn, EventType.CLICK, () => actions.selectElement(targetId, issue.story)));
			} else {
				append(li, $('span', undefined, issue.message));
			}
		}
	}
}
