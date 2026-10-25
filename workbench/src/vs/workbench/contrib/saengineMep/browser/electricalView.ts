/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow } from '../../saengineProject/browser/editorFrame.js';
import { formatNumber, IFieldSpec } from '../../saengineSoil/browser/soilDocument.js';
import { equipmentPressure } from './mepDocument.js';
import { IMepFormHost, ITEM_FIELDS, settingsGrid, storyRowIds, UNIT_KN, UNIT_MM } from './mepForm.js';
import { pathLength, roofStory, staticListNote, storyFloorArea } from './mepRead.js';
import { resultSection, value } from './mepResults.js';
import {
	connectedLoads, DOWN_CONDUCTORS, downConductorsLabel, EARTHINGS, earthingLabel, ELEC_KINDS, ELEC_RISER_KINDS, elecKindLabel, ElecKind, elecLetters, ElecRiserKind, elecStoryRow, electricalOf,
	ensureElectrical, IElecEquipment, IElecRiser, IElectricalReport, IElecUse, ITray, LIGHTNING_LEVELS, loadBreakdownText, ratingUnit, riserKindLabel, riserLetters, sourceOf, VOLTAGES, voltageLabel,
} from './electricalDocument.js';

/*
 * The electrical services' Data view and properties panel in the MEP editor: the supply, the
 * storeys' loads, the lightning protection, the equipment, risers and trays as tables; one item
 * in the properties panel. Built through the editor's form host (mepForm.ts).
 */

export interface IElectricalActions {
	addEquipment(kind: ElecKind): void;
	addRiser(kind: ElecRiserKind): void;
	drawTray(): void;
	proposeEquipment(): void;
}

const WM2 = localize('elecView.unit.wm2', "W/m²");
const KW = localize('elecView.unit.kw', "kW");

const E = {
	utility: { key: 'utility', label: localize('elecView.f.utility', "Utility"), kind: 'text', title: localize('elecView.f.utilityTitle', "The supply authority (DESCO, DPDC, REB...)") },
	lighting: { key: 'lighting', label: localize('elecView.f.lighting', "Lighting"), unit: WM2, kind: 'number', min: 0, width: 72 },
	power: { key: 'power', label: localize('elecView.f.power', "Power"), unit: WM2, kind: 'number', min: 0, width: 72, title: localize('elecView.f.powerTitle', "Socket outlets and small power, air-conditioning included") },
	other: { key: 'other', label: localize('elecView.f.other', "Other"), unit: KW, kind: 'number', min: 0, width: 72, title: localize('elecView.f.otherTitle', "Lifts, pumps and other loads of the storey") },
	rating: { key: 'rating', label: localize('elecView.f.rating', "Rating"), kind: 'number', min: 0.001, width: 76 },
	riserWidth: { key: 'width', label: localize('elecView.f.riserWidth', "Width"), unit: UNIT_MM, kind: 'number', min: 1, width: 64, title: localize('elecView.f.riserWidthTitle', "Plan size along x") },
	riserDepth: { key: 'depth', label: localize('elecView.f.riserDepth', "Depth"), unit: UNIT_MM, kind: 'number', min: 1, width: 64, title: localize('elecView.f.riserDepthTitle', "Plan size along y") },
	trayWidth: { key: 'width', label: localize('elecView.f.trayWidth', "Width"), unit: UNIT_MM, kind: 'number', min: 1, required: true, width: 64 },
	trayHeight: { key: 'height', label: localize('elecView.f.trayHeight', "Height"), unit: UNIT_MM, kind: 'number', min: 1, required: true, width: 64 },
} satisfies { [key: string]: IFieldSpec };

function useOption(use: IElecUse): { value: string; label: string } {
	return { value: use.key, label: use.nonAc !== undefined ? localize('elecView.useOption', "{0} ({1} / {2} W/m²)", use.label, use.nonAc, use.ac ?? '—') : use.label };
}

export function renderElectricalData(view: HTMLElement, host: IMepFormHost, uses: readonly IElecUse[], usesFromBackend: boolean, actions: IElectricalActions, report?: IElectricalReport): void {
	const document = host.document;
	const electrical = electricalOf(document);
	const e = () => ensureElectrical(document);
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('elecView.dataTitle', "Electrical set-up")));
	append(header, $('span.mep-view-subtitle', undefined, localize('elecView.dataSubtitle', "The supply and each storey's loads (for the substation, generator and their rooms), the lightning protection through the structure, and the equipment, risers and trays (their weights and openings); sizes in mm, positions in m.")));

	// Supply.
	const supply = host.section(localize('elecView.supply', "Supply"), undefined);
	const setting = settingsGrid(supply);
	setting(localize('elecView.f.voltage', "Supply voltage"), host.selectInput(VOLTAGES.map(v => ({ value: v, label: voltageLabel(v) })), String(electrical?.supply.voltage ?? ''), v => host.setOptional(e().supply, 'voltage', v), 'electrical.supply.voltage', localize('elecView.f.voltage', "Supply voltage"), true));
	setting(E.utility.label, host.textInput(E.utility, electrical?.supply.utility, v => host.setField(e().supply, 'utility', v), 'electrical.supply.utility'), undefined, E.utility.title);
	setting(localize('elecView.f.generator', "Standby generator"), host.yesNo(electrical?.supply.generator === true, v => {
		e().supply.generator = v;
		host.changed(true);
	}, 'electrical.supply.generator', localize('elecView.f.generator', "Standby generator")));
	setting(localize('elecView.f.ups', "UPS"), host.yesNo(electrical?.supply.ups === true, v => {
		e().supply.ups = v;
		host.changed(true);
	}, 'electrical.supply.ups', localize('elecView.f.ups', "UPS")));

	// Stories.
	const rows = electrical?.stories ?? [];
	const stories = host.section(localize('elecView.stories', "Loads by storey"), rows.length);
	if (!usesFromBackend) {
		append(stories, $('p.mep-note.plb-static-note', undefined, staticListNote(localize('elecView.usesWhat', "the occupancies of BNBC Table 8.1.17"))));
	}
	const table = append(append(stories, $('.mep-table-scroll')), $('table.mep-table'));
	const columns = [
		{ label: localize('elecView.f.story', "Storey"), width: 110 }, { label: localize('elecView.f.use', "Occupancy"), width: 300 },
		{ label: E.lighting.label, unit: WM2, numeric: true, width: 72 }, { label: E.power.label, unit: WM2, numeric: true, width: 72 }, { label: E.other.label, unit: KW, numeric: true, width: 72 },
		{ label: localize('elecView.f.area', "Floor"), unit: localize('elecView.unit.m2', "m²"), numeric: true, width: 64 },
		{ label: localize('elecView.f.used', "Used"), unit: WM2, numeric: true, width: 64, title: localize('elecView.f.usedTitle', "The unit load the backend uses: lighting + power, at least the minimum of BNBC Table 8.1.17, plus the A/C share") },
		{ label: localize('elecView.f.connected', "Connected"), unit: KW, numeric: true, width: 80 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	// The backend's figures where it has answered (the defaults it applied, the unit load it used); the entered densities otherwise.
	const computed = new Map((report?.stories ?? []).map(s => [s.story, s]));
	const loads = new Map(connectedLoads(document, host.context).map(l => [l.story, l]));
	for (const storyId of storyRowIds(host.context, rows)) {
		const index = rows.findIndex(r => r.story === storyId);
		const row = rows[index];
		const result = computed.get(storyId);
		const tr = append(body, $(`tr.mep-row${row ? '' : '.plb-empty-row'}`));
		const path = (field: string) => index >= 0 ? `electrical.stories.${index}.${field}` : `electrical.new.${storyId}.${field}`;
		const target = () => elecStoryRow(e(), storyId);
		append(tr, $('td', undefined, host.storyName(storyId)));
		const defaultUse = result && result.useSource !== 'entered' && result.useLabel ? localize('elecView.useDefault', "{0} (building use, Project Settings)", result.useLabel) : true;
		const select = append(append(tr, $('td')), host.selectInput(uses.map(useOption), String(row?.use ?? ''), v => host.setOptional(target(), 'use', v), path('use'), localize('elecView.f.useOf', "Occupancy of {0}", host.storyName(storyId)), defaultUse));
		select.title = select.selectedOptions[0]?.textContent ?? '';
		for (const field of [E.lighting, E.power, E.other]) {
			// A blank lighting or power shows what the backend put in its place (the rest of the Table 8.1.17 density).
			const derived = field === E.lighting ? result?.lighting : field === E.power ? result?.power : undefined;
			const placeholder = row?.[field.key] === undefined && derived !== undefined ? formatNumber(derived, 1) : undefined;
			const input = append(append(tr, $('td')), host.textInput(field, row?.[field.key], v => host.setField(target(), field.key, v), path(field.key), placeholder));
			if (placeholder && !input.title) {
				input.title = localize('elecView.derivedTitle', "Blank: {0} W/m² used (the rest of the BNBC Table 8.1.17 density after the other one)", placeholder);
			}
		}
		const area = result?.area ?? storyFloorArea(host.context, storyId);
		append(tr, $('td.number.mep-muted-cell', undefined, area ? formatNumber(area, 0) : ''));
		const used = append(tr, $('td.number.mep-muted-cell', undefined, value(result?.density, 1)));
		if (result?.breakdown.length) {
			used.title = loadBreakdownText(result);
		}
		const connected = result ? result.connected : loads.get(storyId)?.total || undefined;
		append(tr, $('td.number.mep-muted-cell', undefined, value(connected, 1)));
		if (row) {
			host.removeButton(tr, () => {
				e().stories.splice(index, 1);
				host.changed(true);
			});
		} else {
			append(tr, $('td'));
		}
	}
	append(stories, $('p.mep-note', undefined, report
		? localize('elecView.loadsNote', "BNBC 2020 Part 8 Table 8.1.17 (Sec 1.3.2.5) gives one minimum density for the lighting and the power together, and a higher one with air conditioning. A blank occupancy takes the building use of Project Settings; a blank lighting or power takes the rest of the table's density (shown in grey). Hover Used for the breakdown; Results lists it by storey.")
		: localize('elecView.loadsNoteLocal', "Connected shows the densities you entered only. The BNBC Table 8.1.17 minimums, the building-use default and the A/C share are applied by the backend; open Results to compute them.")));

	// Lightning protection.
	const lightning = host.section(localize('elecView.lightning', "Lightning protection"), undefined);
	const lps = settingsGrid(lightning);
	const l = electrical?.lightning;
	lps(localize('elecView.f.lpsEnabled', "Protected"), host.yesNo(l?.enabled === true, v => {
		e().lightning.enabled = v;
		host.changed(true);
	}, 'electrical.lightning.enabled', localize('elecView.f.lpsEnabled', "Protected")));
	lps(localize('elecView.f.level', "Protection level"), host.selectInput(LIGHTNING_LEVELS.map(v => ({ value: v, label: v })), String(l?.level ?? ''), v => host.setOptional(e().lightning, 'level', v), 'electrical.lightning.level', localize('elecView.f.level', "Protection level"), true),
		undefined, localize('elecView.f.levelTitle', "Empty: from the backend's risk assessment"));
	lps(localize('elecView.f.downConductors', "Down conductors"), host.selectInput(DOWN_CONDUCTORS.map(v => ({ value: v, label: downConductorsLabel(v) })), String(l?.downConductors ?? ''), v => host.setOptional(e().lightning, 'downConductors', v), 'electrical.lightning.downConductors', localize('elecView.f.downConductors', "Down conductors"), true));
	lps(localize('elecView.f.earthing', "Earthing"), host.selectInput(EARTHINGS.map(v => ({ value: v, label: earthingLabel(v) })), String(l?.earthing ?? ''), v => host.setOptional(e().lightning, 'earthing', v), 'electrical.lightning.earthing', localize('elecView.f.earthing', "Earthing"), true));
	const roof = roofStory(host.context);
	append(lightning, $('p.mep-note', undefined, l?.airTerminals?.length
		? localize('elecView.terminalsGiven', "{0} air terminals given (edit them as text); the down-conductor columns come from the backend and show on the plans of {1} and {2}.", l.airTerminals.length, roof?.name ?? '', host.context.stories[0]?.name ?? '')
		: localize('elecView.terminalsProposed', "The air terminals, the mesh and the down-conductor columns are proposed by the backend; they show on the plans of {0} (roof) and {1}.", roof?.name ?? '', host.context.stories[0]?.name ?? '')));

	renderEquipmentTable(host, actions);
	renderRiserTable(host, actions);
	renderTrayTable(host, actions);
}

function renderEquipmentTable(host: IMepFormHost, actions: IElectricalActions): void {
	const list = electricalOf(host.document)?.equipment ?? [];
	const section = host.section(localize('elecView.equipment', "Equipment"), list.length, { label: localize('elecView.propose', "Propose Equipment"), run: () => actions.proposeEquipment() });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('elecView.f.kind', "Kind"), width: 170 }, { label: localize('elecView.f.storyOn', "On"), width: 100 },
		{ label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true }, { label: F.length.label, unit: UNIT_MM, numeric: true }, { label: F.width.label, unit: UNIT_MM, numeric: true },
		{ label: E.rating.label, numeric: true, width: 76 }, { label: F.operatingWeight.label, unit: UNIT_KN, numeric: true, width: 84 }, { label: localize('elecView.f.vibrating', "Vibrating"), width: 64 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	list.forEach((item, index) => {
		const row = host.selectableRow(body, { kind: 'elecEquipment', index });
		const path = (field: string) => `electrical.equipment.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, item.id, v => host.setField(item, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(ELEC_KINDS.map(k => ({ value: k, label: `${elecLetters(k)} · ${elecKindLabel(k)}` })), item.kind, v => {
			item.kind = v;
			host.changed(true);
		}, path('kind'), localize('elecView.f.kind', "Kind")));
		append(append(row, $('td')), host.selectInput(host.storyOptions(), item.story, v => {
			item.story = v;
			host.followStory(v);
			host.changed(true);
		}, path('story'), localize('elecView.f.storyOn', "On")));
		for (const field of [F.x, F.y, F.length, F.width]) {
			append(append(row, $('td')), host.textInput(field, item[field.key], v => host.setField(item, field.key, v), path(field.key)));
		}
		append(append(row, $('td')), host.textInput({ ...E.rating, unit: ratingUnit(item.kind) }, item.rating, v => host.setField(item, 'rating', v), path('rating')));
		append(append(row, $('td')), host.textInput(F.operatingWeight, item.operatingWeight, v => host.setField(item, 'operatingWeight', v), path('operatingWeight'), localize('elecView.supplier', "supplier")));
		append(append(row, $('td.mep-check-cell')), host.checkbox(!!item.vibrating, v => {
			if (v) {
				item.vibrating = true;
			} else {
				delete item.vibrating;
			}
			host.changed(true);
		}, localize('elecView.f.vibrating', "Vibrating")));
		host.removeButton(row, () => {
			ensureElectrical(host.document).equipment.splice(index, 1);
			host.changed(true);
		});
	});
	if (!list.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('elecView.noEquipment', "None yet. Add the transformer, switchgear, generator and its fuel tank from the toolbar, or let SAEngine propose them from the demand: their weights load the floors, the generator vibrates.")));
	}
}

function renderRiserTable(host: IMepFormHost, actions: IElectricalActions): void {
	const document = host.document;
	const risers = electricalOf(document)?.risers ?? [];
	const section = host.section(localize('elecView.risers', "Risers"), risers.length, { label: localize('elecView.addBusbar', "Add Busbar Riser"), run: () => actions.addRiser('busbar') });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('elecView.f.riserKind', "Kind"), width: 200 }, { label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true },
		{ label: E.riserWidth.label, unit: UNIT_MM, numeric: true, width: 64 }, { label: E.riserDepth.label, unit: UNIT_MM, numeric: true, width: 64 },
		{ label: localize('elecView.f.from', "Starts at"), width: 110 }, { label: localize('elecView.f.to', "Up to"), width: 110 }, { label: localize('elecView.f.shaft', "Shaft"), width: 80 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	risers.forEach((r, index) => {
		const row = host.selectableRow(body, { kind: 'elecRiser', index });
		const path = (field: string) => `electrical.risers.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, r.id, v => host.setField(r, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(ELEC_RISER_KINDS.map(k => ({ value: k, label: `${riserLetters(k)} · ${riserKindLabel(k)}` })), r.kind, v => {
			r.kind = v;
			host.changed(true);
		}, path('kind'), localize('elecView.f.riserKind', "Kind")));
		for (const field of [F.x, F.y, E.riserWidth, E.riserDepth]) {
			append(append(row, $('td')), host.textInput(field, r[field.key], v => host.setField(r, field.key, v), path(field.key)));
		}
		for (const end of ['fromStory', 'toStory'] as const) {
			append(append(row, $('td')), host.selectInput(host.storyOptions(), r[end], v => {
				r[end] = v;
				host.changed(true);
			}, path(end), end === 'fromStory' ? localize('elecView.f.from', "Starts at") : localize('elecView.f.to', "Up to")));
		}
		append(append(row, $('td')), host.selectInput(document.shafts.map(s => ({ value: s.id, label: s.id })), r.shaft ?? '', v => host.setOptional(r, 'shaft', v), path('shaft'), localize('elecView.f.shaft', "Shaft"), true));
		host.removeButton(row, () => {
			ensureElectrical(document).risers.splice(index, 1);
			host.changed(true);
		});
	});
	if (!risers.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('elecView.noRisers', "None yet. Add the busbar rising mains and the riser trays (in the electrical shaft): each needs an opening or a shaft through the floors it passes.")));
	}
}

function renderTrayTable(host: IMepFormHost, actions: IElectricalActions): void {
	const trays = electricalOf(host.document)?.trays ?? [];
	const section = host.section(localize('elecView.trays', "Cable trays"), trays.length, { label: localize('elecView.drawTray', "Draw Tray"), run: () => actions.drawTray() });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('elecView.f.storyRun', "Story"), width: 110 }, { label: E.trayWidth.label, unit: UNIT_MM, numeric: true, width: 64 },
		{ label: E.trayHeight.label, unit: UNIT_MM, numeric: true, width: 64 }, { label: F.bottom.label, unit: UNIT_MM, numeric: true, width: 80 }, { label: localize('elecView.f.run', "Run"), width: 130 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	trays.forEach((t, index) => {
		const row = host.selectableRow(body, { kind: 'tray', index });
		const path = (field: string) => `electrical.trays.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, t.id, v => host.setField(t, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(host.storyOptions(), t.story, v => {
			t.story = v;
			host.followStory(v);
			host.changed(true);
		}, path('story'), localize('elecView.f.storyRun', "Story")));
		for (const field of [E.trayWidth, E.trayHeight]) {
			append(append(row, $('td')), host.textInput(field, t[field.key], v => host.setField(t, field.key, v), path(field.key)));
		}
		append(append(row, $('td')), host.textInput(F.bottom, t.bottom, v => host.setField(t, 'bottom', v), path('bottom'), localize('elecView.soffit', "soffit")));
		append(row, $('td.mep-muted-cell', undefined, localize('elecView.runLength', "{0} points, {1} m", t.path.length, formatNumber(pathLength(t.path) / 1000, 2))));
		host.removeButton(row, () => {
			ensureElectrical(host.document).trays.splice(index, 1);
			host.changed(true);
		});
	});
	if (!trays.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('elecView.noTrays', "None yet. Draw the main cable trays in the plan (Draw Tray: click the points, double-click to end).")));
	}
}

// ───────────────────────────── properties ─────────────────────────────

export function renderElecEquipmentProperties(panel: HTMLElement, host: IMepFormHost, item: IElecEquipment, index: number, report: IElectricalReport | undefined): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `electrical.equipment.${index}.${field}`;
	appendPropertyHeading(panel, localize('elecView.equipmentHeading', "{0} {1}", elecKindLabel(item.kind), item.id));
	host.fieldRow(panel, F.id, item.id, v => host.setField(item, 'id', v), path('id'));
	host.propertyRow(panel, localize('elecView.f.kind', "Kind"), host.selectInput(ELEC_KINDS.map(k => ({ value: k, label: elecKindLabel(k) })), item.kind, v => {
		item.kind = v;
		host.changed(true);
	}, path('kind'), localize('elecView.f.kind', "Kind")));
	host.propertyRow(panel, localize('elecView.f.storyOn', "On"), host.selectInput(host.storyOptions(), item.story, v => {
		item.story = v;
		host.followStory(v);
		host.changed(true);
	}, path('story'), localize('elecView.f.storyOn', "On")));
	appendPropertyHeading(panel, localize('elecView.placement', "Placement and size"));
	for (const field of [F.x, F.y, F.length, F.width, F.height]) {
		host.fieldRow(panel, field, item[field.key], v => host.setField(item, field.key, v), path(field.key));
	}
	appendPropertyHeading(panel, localize('elecView.ratingLoad', "Rating and load"));
	host.fieldRow(panel, { ...E.rating, unit: ratingUnit(item.kind) }, item.rating, v => host.setField(item, 'rating', v), path('rating'));
	host.fieldRow(panel, F.operatingWeight, item.operatingWeight, v => host.setField(item, 'operatingWeight', v), path('operatingWeight'), localize('elecView.supplier', "supplier"));
	host.propertyRow(panel, localize('elecView.f.vibrating', "Vibrating"), host.yesNo(!!item.vibrating, v => {
		if (v) {
			item.vibrating = true;
		} else {
			delete item.vibrating;
		}
		host.changed(true);
	}, path('vibrating'), localize('elecView.f.vibrating', "Vibrating")), undefined, localize('elecView.f.vibratingTitle', "A generator (reciprocating engine): the backend reports it for the floor's vibration and the mountings"));
	const pressure = equipmentPressure({ id: item.id, kind: 'other', story: item.story, x: item.x, y: item.y, length: item.length ?? 1000, width: item.width ?? 1000, operatingWeight: item.operatingWeight ?? 0 });
	if (item.operatingWeight !== undefined && pressure !== undefined) {
		appendPropertyRow(panel, localize('elecView.f.pressure', "Load over the footprint"), localize('elecView.kpaValue', "{0} kPa", formatNumber(pressure, 2)));
	}
	if (item.sized) {
		appendPropertyNote(panel, localize('elecView.sizedNote', "Proposed by SAEngine from the demand: edit it to the supplier's data."));
	}
	const source = sourceOf(report, item);
	if (source) {
		appendPropertyHeading(panel, localize('elecView.check', "Check"));
		if (source.required !== undefined) {
			appendPropertyRow(panel, localize('elecView.f.required', "Required"), `${formatNumber(source.required, 0)} ${source.unit ?? ratingUnit(item.kind)}`);
		}
		appendPropertyRow(panel, localize('elecView.f.status', "Status"), $(`span.plb-pill.band-${source.status}`, undefined, source.status === 'fail' ? localize('elecView.fails', "fails") : source.status === 'ok' ? localize('elecView.ok', "ok") : '—'));
		if (source.note) {
			appendPropertyNote(panel, source.note);
		}
	}
}

export function renderElecRiserProperties(panel: HTMLElement, host: IMepFormHost, riser: IElecRiser, index: number): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `electrical.risers.${index}.${field}`;
	appendPropertyHeading(panel, localize('elecView.riserHeading', "{0} {1}", riserKindLabel(riser.kind), riser.id));
	host.fieldRow(panel, F.id, riser.id, v => host.setField(riser, 'id', v), path('id'));
	host.propertyRow(panel, localize('elecView.f.riserKind', "Kind"), host.selectInput(ELEC_RISER_KINDS.map(k => ({ value: k, label: riserKindLabel(k) })), riser.kind, v => {
		riser.kind = v;
		host.changed(true);
	}, path('kind'), localize('elecView.f.riserKind', "Kind")));
	for (const field of [F.x, F.y, E.riserWidth, E.riserDepth]) {
		host.fieldRow(panel, field, riser[field.key], v => host.setField(riser, field.key, v), path(field.key));
	}
	for (const end of ['fromStory', 'toStory'] as const) {
		const label = end === 'fromStory' ? localize('elecView.f.from', "Starts at") : localize('elecView.f.to', "Up to");
		host.propertyRow(panel, label, host.selectInput(host.storyOptions(), riser[end], v => {
			riser[end] = v;
			host.changed(true);
		}, path(end), label));
	}
	host.propertyRow(panel, localize('elecView.f.shaft', "Shaft"), host.selectInput(host.document.shafts.map(s => ({ value: s.id, label: s.id })), riser.shaft ?? '', v => host.setOptional(riser, 'shaft', v), path('shaft'), localize('elecView.f.shaft', "Shaft"), true),
		undefined, localize('elecView.f.shaftTitle', "The shaft it rises in; else it needs an opening through each floor"));
	appendPropertyNote(panel, localize('elecView.riserNote', "Add Openings proposes the openings it needs through the floors it passes outside a shaft."));
}

export function renderTrayProperties(panel: HTMLElement, host: IMepFormHost, tray: ITray, index: number): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `electrical.trays.${index}.${field}`;
	appendPropertyHeading(panel, localize('elecView.trayHeading', "Cable tray {0}", tray.id));
	host.fieldRow(panel, F.id, tray.id, v => host.setField(tray, 'id', v), path('id'));
	host.propertyRow(panel, localize('elecView.f.storyRun', "Story"), host.selectInput(host.storyOptions(), tray.story, v => {
		tray.story = v;
		host.followStory(v);
		host.changed(true);
	}, path('story'), localize('elecView.f.storyRun', "Story")));
	host.fieldRow(panel, E.trayWidth, tray.width, v => host.setField(tray, 'width', v), path('width'));
	host.fieldRow(panel, E.trayHeight, tray.height, v => host.setField(tray, 'height', v), path('height'));
	host.fieldRow(panel, F.bottom, tray.bottom, v => host.setField(tray, 'bottom', v), path('bottom'), localize('elecView.soffit', "soffit"));
	host.propertyRow(panel, localize('elecView.f.path', "Path"), host.pathInput(tray.path, p => {
		tray.path = p;
		host.changed(false);
	}, path('path'), localize('elecView.f.path', "Path"), 2), F.x.unit, localize('elecView.pathTitle', "Points as x y in m, separated by semicolons; drag the tray in the plan to move it"));
	appendPropertyRow(panel, localize('elecView.f.length', "Length"), localize('elecView.mValue', "{0} m", formatNumber(pathLength(tray.path) / 1000, 2)));
}

export function renderElectricalSummaryProperties(panel: HTMLElement, host: IMepFormHost, report: IElectricalReport | undefined): void {
	const electrical = electricalOf(host.document);
	const story = host.context.stories.find(s => s.id === host.story);
	if (story) {
		appendPropertyHeading(panel, story.name);
		const onStory = electrical?.equipment.filter(e => e.story === story.id) ?? [];
		appendPropertyRow(panel, localize('elecView.equipment', "Equipment"), String(onStory.length));
		appendPropertyRow(panel, ITEM_FIELDS.operatingWeight.label, localize('elecView.knValue', "{0} kN", formatNumber(onStory.reduce((s, e) => s + (e.operatingWeight ?? 0), 0), 1)));
		const row = report?.stories.find(s => s.story === story.id);
		if (row?.kva !== undefined) {
			appendPropertyRow(panel, localize('elecView.f.demand', "Demand"), localize('elecView.kvaValue', "{0} kVA", formatNumber(row.kva, 0)));
		}
	}
	appendPropertyHeading(panel, localize('elecView.summary', "Electrical"));
	appendPropertyRow(panel, localize('elecView.f.voltage', "Supply voltage"), electrical?.supply.voltage ? voltageLabel(String(electrical.supply.voltage)) : '—');
	appendPropertyRow(panel, localize('elecView.equipment', "Equipment"), String(electrical?.equipment.length ?? 0));
	appendPropertyRow(panel, localize('elecView.risers', "Risers"), String(electrical?.risers.length ?? 0));
	appendPropertyRow(panel, localize('elecView.trays', "Cable trays"), String(electrical?.trays.length ?? 0));
	appendPropertyRow(panel, localize('elecView.lightning', "Lightning protection"), electrical?.lightning.enabled
		? electrical.lightning.level ? localize('elecView.levelValue', "level {0}", String(electrical.lightning.level)) : localize('elecView.yes', "yes")
		: localize('elecView.no', "no"));
	if (report?.lightning?.downConductors.length) {
		appendPropertyRow(panel, localize('elecView.f.downColumns', "Down-conductor columns"), report.lightning.downConductors.map(d => d.column).join(', '));
	}
	appendPropertyNote(panel, localize('elecView.summaryNote', "Select an equipment, a riser or a tray in the plan to edit it here; the supply, the storeys' loads and the lightning protection are in Data."));
}

/** Without the backend: the connected loads from the densities (no diversity) and the equipment weights. */
export function renderLocalElectrical(view: HTMLElement, host: IMepFormHost): void {
	const electrical = electricalOf(host.document);
	if (!electrical) {
		return;
	}
	const section = resultSection(view, localize('elecView.localTitle', "As set up"), localize('elecView.localDetail', "connected loads from your densities over the floor areas, without diversity; the demand, sizes and checks come from the backend"));
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('elecView.f.story', "Storey"), width: 130 }, { label: localize('elecView.f.area', "Floor"), unit: localize('elecView.unit.m2', "m²"), numeric: true, width: 80 },
		{ label: localize('elecView.f.connected', "Connected"), unit: KW, numeric: true, width: 90 }, { label: localize('elecView.f.equipmentWeight', "Equipment weight"), unit: UNIT_KN, numeric: true, width: 110 },
	]);
	const body = append(table, $('tbody'));
	const loads = new Map(connectedLoads(host.document, host.context).map(l => [l.story, l]));
	const stories = new Set([...loads.keys(), ...electrical.equipment.map(e => e.story)]);
	for (const story of host.context.stories.filter(s => stories.has(s.id)).reverse()) {
		const load = loads.get(story.id);
		const weight = electrical.equipment.filter(e => e.story === story.id).reduce((s, e) => s + (e.operatingWeight ?? 0), 0);
		const tr = append(body, $('tr'));
		append(tr, $('td', undefined, story.name));
		append(tr, $('td.number', undefined, value(load?.area || undefined, 0)));
		append(tr, $('td.number', undefined, value(load?.total, 1)));
		append(tr, $('td.number', undefined, weight ? formatNumber(weight, 1) : ''));
	}
}
