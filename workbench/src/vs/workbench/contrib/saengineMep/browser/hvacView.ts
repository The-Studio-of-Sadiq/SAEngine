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
import { pathLength, staticListNote, storyFloorArea } from './mepRead.js';
import { resultSection, value } from './mepResults.js';
import {
	allCrossings, capacityUnit, DUCT_SHAPES, DUCT_SYSTEMS, ductCrossings, ductLetters, ductShapeLabel, ductSystemLabel, DuctSystem, ensureHvac, FACADES, HVAC_SYSTEMS, hvacOf, hvacStoryRow,
	hvacSystemLabel, IConstructions, IDuct, IHvacCity, IHvacReport, IHvacUse, IPlant, isFan, PLANT_KINDS, plantAsEquipment, plantKindLabel, plantLetters, PlantKind, riserInShaft, SHADINGS,
	shadingLabel,
} from './hvacDocument.js';

/*
 * The HVAC's Data view and properties panel in the MEP editor: the system and the design
 * conditions, the envelope, the storeys' use, the plant and the ducts as tables; one plant item
 * or duct in the properties panel. Built through the editor's form host (mepForm.ts).
 */

export interface IHvacTables {
	readonly cities: readonly IHvacCity[];
	readonly uses: readonly IHvacUse[];
	readonly constructions: IConstructions;
	readonly tablesFromBackend: boolean;
	readonly constructionsFromBackend: boolean;
}

export interface IHvacActions {
	addPlant(kind: PlantKind): void;
	drawDuct(system: DuctSystem): void;
	addRiserDuct(system: DuctSystem): void;
	proposePlant(): void;
}

const C = localize('hvacView.unit.c', "°C");
const WM2 = localize('hvacView.unit.wm2', "W/m²");
const WM2K = localize('hvacView.unit.wm2k', "W/m²K");

const H = {
	outdoorDB: { key: 'outdoorDB', label: localize('hvacView.f.outdoorDB', "Outdoor dry bulb"), unit: C, kind: 'number', min: 0, max: 60, title: localize('hvacView.f.outdoorDBTitle', "Override of the station's cooling design dry bulb (Table 8.2.2, 2 % column, Sec 2.12.2.1)") },
	outdoorWB: { key: 'outdoorWB', label: localize('hvacView.f.outdoorWB', "Outdoor wet bulb"), unit: C, kind: 'number', min: 0, max: 60, title: localize('hvacView.f.outdoorWBTitle', "Override of the mean coincident wet bulb (Table 8.2.2, 2 % column, Sec 2.12.2.1)") },
	indoorDB: { key: 'indoorDB', label: localize('hvacView.f.indoorDB', "Indoor dry bulb"), unit: C, kind: 'number', min: 0, max: 60, title: localize('hvacView.f.indoorDBTitle', "Inside design condition; empty for the backend's from Table 8.2.1") },
	indoorRH: { key: 'indoorRH', label: localize('hvacView.f.indoorRH', "Indoor humidity"), unit: '%', kind: 'number', min: 1, max: 99, title: localize('hvacView.f.indoorRHTitle', "Inside relative humidity; empty for the backend's from Table 8.2.1") },
	dailyRange: { key: 'dailyRange', label: localize('hvacView.f.dailyRange', "Daily range"), unit: C, kind: 'number', min: 0.1, title: localize('hvacView.f.dailyRangeTitle', "Mean daily range; empty for the station's (Table 8.2.2 column 14)") },
	uWall: { key: 'uWall', label: localize('hvacView.f.uWall', "Wall U"), unit: WM2K, kind: 'number', min: 0.01, title: localize('hvacView.f.uOverride', "Override of the construction's U-value") },
	uRoof: { key: 'uRoof', label: localize('hvacView.f.uRoof', "Roof U"), unit: WM2K, kind: 'number', min: 0.01, title: localize('hvacView.f.uOverride', "Override of the construction's U-value") },
	uGlazing: { key: 'uGlazing', label: localize('hvacView.f.uGlazing', "Glazing U"), unit: WM2K, kind: 'number', min: 0.01, title: localize('hvacView.f.uOverride', "Override of the construction's U-value") },
	shgc: { key: 'shgc', label: localize('hvacView.f.shgc', "Glazing SHGC"), kind: 'number', min: 0.01, max: 0.99, title: localize('hvacView.f.shgcTitle', "Solar heat gain coefficient of the glazing; empty for the construction's") },
	occupants: { key: 'occupants', label: localize('hvacView.f.occupants', "Occupants"), kind: 'integer', min: 0, width: 76, title: localize('hvacView.f.occupantsTitle', "Persons on the storey; empty for the default density of Table 8.2.3") },
	lighting: { key: 'lighting', label: localize('hvacView.f.lighting', "Lighting"), unit: WM2, kind: 'number', min: 0, width: 72 },
	equipment: { key: 'equipment', label: localize('hvacView.f.equipment', "Equipment"), unit: WM2, kind: 'number', min: 0, width: 72 },
	capacity: { key: 'capacity', label: localize('hvacView.f.capacity', "Capacity"), kind: 'number', min: 0.001, width: 76, title: localize('hvacView.f.capacityTitle', "Cooling in kW; airflow in m³/s for fans") },
	ductWidth: { key: 'width', label: localize('hvacView.f.ductWidth', "Width"), unit: UNIT_MM, kind: 'number', min: 1, width: 64 },
	ductHeight: { key: 'height', label: localize('hvacView.f.ductHeight', "Height"), unit: UNIT_MM, kind: 'number', min: 1, width: 64 },
	diameter: { key: 'diameter', label: localize('hvacView.f.diameter', "Diameter"), unit: UNIT_MM, kind: 'number', min: 1, width: 64 },
	flow: { key: 'flow', label: localize('hvacView.f.flow', "Airflow"), unit: localize('hvacView.unit.m3s', "m³/s"), kind: 'number', min: 0.001, width: 72, title: localize('hvacView.f.flowTitle', "Airflow it carries; empty for the backend's from the loads") },
} satisfies { [key: string]: IFieldSpec };

function wwrField(facade: string): IFieldSpec {
	return { key: facade, label: facade, kind: 'number', min: 0, max: 0.9, width: 48, title: localize('hvacView.f.wwrTitle', "Window-to-wall ratio of the {0} facade, 0 to 0.9; empty for the backend's default", facade) };
}

function cityOption(city: IHvacCity): { value: string; label: string } {
	return { value: city.key, label: city.db !== undefined && city.wb !== undefined ? localize('hvacView.cityOption', "{0} ({1} / {2} °C)", city.label, formatNumber(city.db, 2), formatNumber(city.wb, 2)) : city.label };
}

/** The HVAC's Data view. */
export function renderHvacData(view: HTMLElement, host: IMepFormHost, tables: IHvacTables, actions: IHvacActions, usedStation?: string): void {
	const document = host.document;
	const hvac = hvacOf(document);
	const h = () => ensureHvac(document);
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('hvacView.dataTitle', "HVAC set-up")));
	append(header, $('span.mep-view-subtitle', undefined, localize('hvacView.dataSubtitle', "The system and design conditions, the envelope and each storey's use (for the cooling load), the plant (its weight) and the ducts (their openings and shafts); sizes in mm, positions in m.")));

	// System and design conditions.
	const design = host.section(localize('hvacView.design', "System and design conditions"), undefined);
	const setting = settingsGrid(design);
	setting(localize('hvacView.f.system', "System"), host.selectInput(HVAC_SYSTEMS.map(s => ({ value: s, label: hvacSystemLabel(s) })), String(hvac?.system ?? ''), v => host.setOptional(h(), 'system', v), 'hvac.system', localize('hvacView.f.system', "System"), true));
	// Left empty, the backend takes the station nearest the site (Project Settings): name it rather than show a dash.
	const nearest = hvac?.design.city ? undefined : tables.cities.find(c => c.key === usedStation);
	const city = tables.cities.find(c => c.key === hvac?.design.city) ?? nearest;
	const emptyStation = nearest ? localize('hvacView.cityNearest', "{0} (nearest to the site)", nearest.label) : localize('hvacView.cityFromSite', "Nearest to the site (Project Settings)");
	const station = host.selectInput(tables.cities.map(cityOption), String(hvac?.design.city ?? ''), v => host.setOptional(h().design, 'city', v), 'hvac.design.city', localize('hvacView.f.city', "Station"), emptyStation);
	station.title = station.selectedOptions[0]?.textContent ?? '';
	setting(localize('hvacView.f.city', "Station"), station,
		undefined, localize('hvacView.f.cityTitle', "The nearest station of BNBC Table 8.2.2 (outside design conditions); its cooling dry bulb / mean coincident wet bulb at 2 % (Sec 2.12.2.1) in brackets"));
	const store = (target: () => { [key: string]: unknown }, key: string) => (v: number | string | undefined) => host.setField(target(), key, v);
	const placeholder = (n: number | undefined) => n === undefined ? localize('hvacView.default', "default") : formatNumber(n, 2);
	setting(H.outdoorDB.label, host.textInput(H.outdoorDB, hvac?.design.outdoorDB, store(() => h().design, 'outdoorDB'), 'hvac.design.outdoorDB', placeholder(city?.db)), H.outdoorDB.unit, H.outdoorDB.title);
	setting(H.outdoorWB.label, host.textInput(H.outdoorWB, hvac?.design.outdoorWB, store(() => h().design, 'outdoorWB'), 'hvac.design.outdoorWB', placeholder(city?.wb)), H.outdoorWB.unit, H.outdoorWB.title);
	setting(H.dailyRange.label, host.textInput(H.dailyRange, hvac?.design.dailyRange, store(() => h().design, 'dailyRange'), 'hvac.design.dailyRange', placeholder(city?.range)), H.dailyRange.unit, H.dailyRange.title);
	setting(H.indoorDB.label, host.textInput(H.indoorDB, hvac?.design.indoorDB, store(() => h().design, 'indoorDB'), 'hvac.design.indoorDB', localize('hvacView.code', "code")), H.indoorDB.unit, H.indoorDB.title);
	setting(H.indoorRH.label, host.textInput(H.indoorRH, hvac?.design.indoorRH, store(() => h().design, 'indoorRH'), 'hvac.design.indoorRH', localize('hvacView.code', "code")), H.indoorRH.unit, H.indoorRH.title);
	if (!tables.tablesFromBackend) {
		append(design, $('p.mep-note.plb-static-note', undefined, staticListNote(localize('hvacView.citiesWhat', "the stations of BNBC Table 8.2.2 and the uses of Table 8.2.3"))));
	}

	// Envelope.
	const envelope = host.section(localize('hvacView.envelope', "Envelope"), undefined);
	const envelopeSetting = settingsGrid(envelope);
	const constructionOptions = (list: readonly { key: string; label: string; u?: number }[]) => list.map(c => ({ value: c.key, label: c.u !== undefined ? localize('hvacView.consOption', "{0} (U {1})", c.label, formatNumber(c.u, 2)) : c.label }));
	const uPlaceholder = (list: readonly { key: string; u?: number }[], key: unknown) => {
		const u = list.find(c => c.key === key)?.u;
		return u === undefined ? localize('hvacView.construction', "construction") : formatNumber(u, 2);
	};
	const e = hvac?.envelope;
	envelopeSetting(localize('hvacView.f.wall', "Walls"), host.selectInput(constructionOptions(tables.constructions.wall), String(e?.wall ?? ''), v => host.setOptional(h().envelope, 'wall', v), 'hvac.envelope.wall', localize('hvacView.f.wall', "Walls"), true));
	envelopeSetting(H.uWall.label, host.textInput(H.uWall, e?.uWall, store(() => h().envelope, 'uWall'), 'hvac.envelope.uWall', uPlaceholder(tables.constructions.wall, e?.wall)), H.uWall.unit, H.uWall.title);
	envelopeSetting(localize('hvacView.f.roof', "Roof"), host.selectInput(constructionOptions(tables.constructions.roof), String(e?.roof ?? ''), v => host.setOptional(h().envelope, 'roof', v), 'hvac.envelope.roof', localize('hvacView.f.roof', "Roof"), true));
	envelopeSetting(H.uRoof.label, host.textInput(H.uRoof, e?.uRoof, store(() => h().envelope, 'uRoof'), 'hvac.envelope.uRoof', uPlaceholder(tables.constructions.roof, e?.roof)), H.uRoof.unit, H.uRoof.title);
	envelopeSetting(localize('hvacView.f.glazing', "Glazing"), host.selectInput(constructionOptions(tables.constructions.glazing), String(e?.glazing ?? ''), v => host.setOptional(h().envelope, 'glazing', v), 'hvac.envelope.glazing', localize('hvacView.f.glazing', "Glazing"), true));
	envelopeSetting(H.uGlazing.label, host.textInput(H.uGlazing, e?.uGlazing, store(() => h().envelope, 'uGlazing'), 'hvac.envelope.uGlazing', uPlaceholder(tables.constructions.glazing, e?.glazing)), H.uGlazing.unit, H.uGlazing.title);
	const shgc = tables.constructions.glazing.find(c => c.key === e?.glazing)?.shgc;
	envelopeSetting(H.shgc.label, host.textInput(H.shgc, e?.shgc, store(() => h().envelope, 'shgc'), 'hvac.envelope.shgc', shgc === undefined ? localize('hvacView.construction', "construction") : formatNumber(shgc, 2)), undefined, H.shgc.title);
	envelopeSetting(localize('hvacView.f.shading', "Shading"), host.selectInput(SHADINGS.map(s => ({ value: s, label: shadingLabel(s) })), String(e?.shading ?? ''), v => host.setOptional(h().envelope, 'shading', v), 'hvac.envelope.shading', localize('hvacView.f.shading', "Shading"), true),
		undefined, localize('hvacView.f.shadingTitle', "Overhangs correct the SHGC by Table 8.2.9(b)"));
	if (!tables.constructionsFromBackend) {
		append(envelope, $('p.mep-note.plb-static-note', undefined, localize('hvacView.staticConstructions', "Constructions: the names SAEngine starts from, without U-values; the backend's list (with its U-values and SHGC) replaces them when it is available. Give a U-value to override.")));
	}

	// Stories.
	const rows = hvac?.stories ?? [];
	const stories = host.section(localize('hvacView.stories', "Storeys"), rows.length);
	const table = append(append(stories, $('.mep-table-scroll')), $('table.mep-table'));
	const columns = [
		{ label: localize('hvacView.f.story', "Storey"), width: 110 }, { label: localize('hvacView.f.conditioned', "Air-conditioned"), width: 70 }, { label: localize('hvacView.f.use', "Use"), width: 250 },
		{ label: H.occupants.label, numeric: true, width: 76 }, { label: H.lighting.label, unit: WM2, numeric: true, width: 72 }, { label: H.equipment.label, unit: WM2, numeric: true, width: 72 },
		...FACADES.map(f => ({ label: localize('hvacView.f.wwr', "WWR {0}", f), numeric: true, width: 52 })), { label: localize('hvacView.f.area', "Floor"), unit: localize('hvacView.unit.m2', "m²"), numeric: true, width: 64 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	const useOptions = tables.uses.map(u => ({ value: u.key, label: u.perPerson !== undefined ? localize('hvacView.useOption', "{0} ({1} L/s per person)", u.label, formatNumber(u.perPerson, 2)) : u.label }));
	for (const storyId of storyRowIds(host.context, rows)) {
		const index = rows.findIndex(r => r.story === storyId);
		const row = rows[index];
		const tr = append(body, $(`tr.mep-row${row ? '' : '.plb-empty-row'}`));
		const path = (field: string) => index >= 0 ? `hvac.stories.${index}.${field}` : `hvac.new.${storyId}.${field}`;
		const target = () => hvacStoryRow(h(), storyId);
		append(tr, $('td', undefined, host.storyName(storyId)));
		append(append(tr, $('td.mep-check-cell')), host.checkbox(row?.conditioned === true, v => {
			target().conditioned = v;
			host.changed(true);
		}, localize('hvacView.f.conditionedOf', "{0} is air-conditioned", host.storyName(storyId))));
		append(append(tr, $('td')), host.selectInput(useOptions, String(row?.use ?? ''), v => host.setOptional(target(), 'use', v), path('use'), localize('hvacView.f.useOf', "Use of {0}", host.storyName(storyId)), true));
		for (const field of [H.occupants, H.lighting, H.equipment]) {
			append(append(tr, $('td')), host.textInput(field, row?.[field.key], v => host.setField(target(), field.key, v), path(field.key)));
		}
		for (const facade of FACADES) {
			append(append(tr, $('td')), host.textInput(wwrField(facade), row?.glazing?.[facade], v => {
				const r = target();
				r.glazing ??= {};
				host.setField(r.glazing, facade, v);
			}, path(`glazing.${facade}`)));
		}
		const area = storyFloorArea(host.context, storyId);
		append(tr, $('td.number.mep-muted-cell', undefined, area ? formatNumber(area, 0) : ''));
		if (row) {
			host.removeButton(tr, () => {
				h().stories.splice(index, 1);
				host.changed(true);
			});
		} else {
			append(tr, $('td'));
		}
	}

	renderPlantTable(host, actions);
	renderDuctTable(host, actions);
}

function storyCell(host: IMepFormHost, row: HTMLElement, current: string, store: (story: string) => void, key: string): void {
	append(append(row, $('td')), host.selectInput(host.storyOptions(), current, store, key, localize('hvacView.f.story', "Storey")));
}

function renderPlantTable(host: IMepFormHost, actions: IHvacActions): void {
	const plant = hvacOf(host.document)?.plant ?? [];
	const section = host.section(localize('hvacView.plant', "Plant"), plant.length, { label: localize('hvacView.proposePlant', "Propose Plant"), run: () => actions.proposePlant() });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('hvacView.f.kind', "Kind"), width: 160 }, { label: localize('hvacView.f.storyOn', "On"), width: 100 },
		{ label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true }, { label: F.length.label, unit: UNIT_MM, numeric: true }, { label: F.width.label, unit: UNIT_MM, numeric: true },
		{ label: H.capacity.label, numeric: true, width: 76 }, { label: F.operatingWeight.label, unit: UNIT_KN, numeric: true, width: 84 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	plant.forEach((p, index) => {
		const row = host.selectableRow(body, { kind: 'plant', index });
		const path = (field: string) => `hvac.plant.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, p.id, v => host.setField(p, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(PLANT_KINDS.map(k => ({ value: k, label: `${plantLetters(k)} · ${plantKindLabel(k)}` })), p.kind, v => {
			p.kind = v;
			host.changed(true);
		}, path('kind'), localize('hvacView.f.kind', "Kind")));
		storyCell(host, row, p.story, v => {
			p.story = v;
			host.followStory(v);
			host.changed(true);
		}, path('story'));
		for (const field of [F.x, F.y, F.length, F.width]) {
			append(append(row, $('td')), host.textInput(field, p[field.key], v => host.setField(p, field.key, v), path(field.key)));
		}
		const capacity = append(row, $('td'));
		append(capacity, host.textInput({ ...H.capacity, unit: capacityUnit(p.kind) }, p.capacity, v => host.setField(p, 'capacity', v), path('capacity')));
		append(append(row, $('td')), host.textInput(F.operatingWeight, p.operatingWeight, v => host.setField(p, 'operatingWeight', v), path('operatingWeight'), localize('hvacView.supplier', "supplier")));
		if (p.sized) {
			row.title = localize('hvacView.sizedTitle', "Proposed by SAEngine; edit it to the supplier's data");
			row.classList.add('plb-sized-row');
		}
		host.removeButton(row, () => {
			ensureHvac(host.document).plant.splice(index, 1);
			host.changed(true);
		});
	});
	if (!plant.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('hvacView.noPlant', "None yet. Add the outdoor units, chillers, cooling towers and AHUs from the toolbar, or let SAEngine propose them from the loads: their operating weights load the floors they stand on.")));
	}
}

function renderDuctTable(host: IMepFormHost, actions: IHvacActions): void {
	const document = host.document;
	const ducts = hvacOf(document)?.ducts ?? [];
	const section = host.section(localize('hvacView.ducts', "Ducts"), ducts.length, { label: localize('hvacView.drawSupply', "Draw Supply Duct"), run: () => actions.drawDuct('supply') });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('hvacView.f.ductSystem', "System"), width: 150 }, { label: localize('hvacView.f.shape', "Shape"), width: 110 },
		{ label: H.ductWidth.label, unit: UNIT_MM, numeric: true, width: 64 }, { label: H.ductHeight.label, unit: UNIT_MM, numeric: true, width: 64 }, { label: H.diameter.label, unit: UNIT_MM, numeric: true, width: 64 },
		{ label: localize('hvacView.f.storyRun', "Story"), width: 100 }, { label: F.bottom.label, unit: UNIT_MM, numeric: true, width: 80 }, { label: localize('hvacView.f.run', "Run"), width: 130 },
		{ label: H.flow.label, unit: H.flow.unit, numeric: true, width: 72 }, { label: localize('hvacView.f.beams', "Beams crossed"), width: 140 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	ducts.forEach((d, index) => {
		const row = host.selectableRow(body, { kind: 'duct', index });
		const path = (field: string) => `hvac.ducts.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, d.id, v => host.setField(d, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(DUCT_SYSTEMS.map(s => ({ value: s, label: `${ductLetters(s)} · ${ductSystemLabel(s)}` })), d.system, v => {
			d.system = v;
			host.changed(true);
		}, path('system'), localize('hvacView.f.ductSystem', "System")));
		append(append(row, $('td')), host.selectInput(DUCT_SHAPES.map(s => ({ value: s, label: ductShapeLabel(s) })), d.shape, v => setShape(host, d, v), path('shape'), localize('hvacView.f.shape', "Shape")));
		const round = d.shape === 'round';
		for (const [field, usable] of [[H.ductWidth, !round], [H.ductHeight, !round], [H.diameter, round]] as const) {
			const td = append(row, $('td'));
			if (usable) {
				append(td, host.textInput(field, d[field.key], v => host.setField(d, field.key, v), path(field.key)));
			} else {
				td.classList.add('mep-muted');
				td.textContent = '—';
			}
		}
		if (d.riser) {
			append(row, $('td.mep-muted-cell', undefined, localize('hvacView.riserSpan', "{0} to {1}", host.storyName(d.riser.fromStory), host.storyName(d.riser.toStory))));
			append(row, $('td.mep-muted', undefined, '—'));
			append(row, $('td.mep-muted-cell', undefined, riserInShaft(d, document) ? localize('hvacView.riserIn', "riser in {0}", riserInShaft(d, document)!) : localize('hvacView.riserFree', "riser, no shaft")));
		} else {
			storyCell(host, row, d.story, v => {
				d.story = v;
				host.followStory(v);
				host.changed(true);
			}, path('story'));
			append(append(row, $('td')), host.textInput(F.bottom, d.bottom, v => host.setField(d, 'bottom', v), path('bottom'), localize('hvacView.soffit', "soffit")));
			append(row, $('td.mep-muted-cell', undefined, localize('hvacView.runLength', "{0} points, {1} m", d.path.length, formatNumber(pathLength(d.path) / 1000, 2))));
		}
		append(append(row, $('td')), host.textInput(H.flow, d.flow, v => host.setField(d, 'flow', v), path('flow'), localize('hvacView.sized', "sized")));
		const crossings = ductCrossings(d, document, host.context);
		const crossed = append(row, $('td.mep-muted-cell'));
		crossed.textContent = crossings.map(c => c.opening ? `${c.beam} (${c.opening})` : localize('hvacView.beamNoOpening', "{0} (no opening)", c.beam)).join(', ');
		if (crossings.some(c => !c.opening)) {
			crossed.title = localize('hvacView.needsOpenings', "Crosses a beam without an opening: Add Duct Openings, or lower the duct below the beams");
			crossed.classList.add('band-warn');
		}
		host.removeButton(row, () => {
			ensureHvac(document).ducts.splice(index, 1);
			host.changed(true);
		});
	});
	if (!ducts.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('hvacView.noDucts', "None yet. Draw the main ducts in the plan (Draw Duct: click the points, double-click to end) and add the riser ducts in the shafts: where they cross the beams they need openings.")));
	}
}

function setShape(host: IMepFormHost, duct: IDuct, shape: string): void {
	if (duct.shape === shape) {
		return;
	}
	if (shape === 'round') {
		duct.diameter ??= Math.max(duct.width ?? 0, duct.height ?? 0) || 400;
		delete duct.width;
		delete duct.height;
	} else {
		duct.width ??= duct.diameter ?? 400;
		duct.height ??= duct.diameter ?? 300;
		delete duct.diameter;
	}
	duct.shape = shape;
	host.changed(true);
}

// ───────────────────────────── properties ─────────────────────────────

export function renderPlantProperties(panel: HTMLElement, host: IMepFormHost, plant: IPlant, index: number, report: IHvacReport | undefined): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `hvac.plant.${index}.${field}`;
	appendPropertyHeading(panel, localize('hvacView.plantHeading', "{0} {1}", plantKindLabel(plant.kind), plant.id));
	host.fieldRow(panel, F.id, plant.id, v => host.setField(plant, 'id', v), path('id'));
	host.propertyRow(panel, localize('hvacView.f.kind', "Kind"), host.selectInput(PLANT_KINDS.map(k => ({ value: k, label: plantKindLabel(k) })), plant.kind, v => {
		plant.kind = v;
		host.changed(true);
	}, path('kind'), localize('hvacView.f.kind', "Kind")));
	host.propertyRow(panel, localize('hvacView.f.storyOn', "On"), host.selectInput(host.storyOptions(), plant.story, v => {
		plant.story = v;
		host.followStory(v);
		host.changed(true);
	}, path('story'), localize('hvacView.f.storyOn', "On")));
	appendPropertyHeading(panel, localize('hvacView.placement', "Placement and size"));
	for (const field of [F.x, F.y, F.length, F.width, F.height]) {
		host.fieldRow(panel, field, plant[field.key], v => host.setField(plant, field.key, v), path(field.key));
	}
	appendPropertyHeading(panel, localize('hvacView.duty', "Duty and load"));
	host.fieldRow(panel, { ...H.capacity, unit: capacityUnit(plant.kind), title: isFan(plant.kind) ? localize('hvacView.f.airflowTitle', "Airflow of the fan") : localize('hvacView.f.coolingTitle', "Cooling capacity") }, plant.capacity, v => host.setField(plant, 'capacity', v), path('capacity'));
	host.fieldRow(panel, F.operatingWeight, plant.operatingWeight, v => host.setField(plant, 'operatingWeight', v), path('operatingWeight'), localize('hvacView.supplier', "supplier"));
	const pressure = equipmentPressure(plantAsEquipment(plant));
	if (plant.operatingWeight !== undefined && pressure !== undefined) {
		appendPropertyRow(panel, localize('hvacView.f.pressure', "Load over the footprint"), localize('hvacView.kpaValue', "{0} kPa", formatNumber(pressure, 2)));
	}
	const served = plant.serves?.length ? plant.serves.map(s => host.storyName(s)).join(', ') : localize('hvacView.servesAll', "the building");
	appendPropertyRow(panel, localize('hvacView.f.serves', "Serves"), served);
	if (plant.sized) {
		appendPropertyNote(panel, localize('hvacView.sizedNote', "Proposed by SAEngine from the loads: edit it to the supplier's data."));
	}
	appendPropertyNote(panel, localize('hvacView.plantLoadNote', "Its operating weight loads the floor through the equipment loads (Run All); a vibrating unit needs its mountings."));
	const result = report?.plant.find(p => p.id === plant.id);
	if (result) {
		appendPropertyHeading(panel, localize('hvacView.check', "Check"));
		if (result.required !== undefined) {
			appendPropertyRow(panel, localize('hvacView.f.required', "Required"), `${formatNumber(result.required, 1)}${result.unit ? ` ${result.unit}` : ''}`);
		}
		appendPropertyRow(panel, localize('hvacView.f.status', "Status"), $(`span.plb-pill.band-${result.status}`, undefined, result.status === 'fail' ? localize('hvacView.fails', "fails") : result.status === 'ok' ? localize('hvacView.ok', "ok") : '—'));
		if (result.note) {
			appendPropertyNote(panel, result.note);
		}
	}
}

export function renderDuctProperties(panel: HTMLElement, host: IMepFormHost, duct: IDuct, index: number, report: IHvacReport | undefined): void {
	const F = ITEM_FIELDS;
	const document = host.document;
	const path = (field: string) => `hvac.ducts.${index}.${field}`;
	appendPropertyHeading(panel, localize('hvacView.ductHeading', "{0} duct {1}", ductSystemLabel(duct.system), duct.id));
	host.fieldRow(panel, F.id, duct.id, v => host.setField(duct, 'id', v), path('id'));
	host.propertyRow(panel, localize('hvacView.f.ductSystem', "System"), host.selectInput(DUCT_SYSTEMS.map(s => ({ value: s, label: ductSystemLabel(s) })), duct.system, v => {
		duct.system = v;
		host.changed(true);
	}, path('system'), localize('hvacView.f.ductSystem', "System")));
	appendPropertyHeading(panel, localize('hvacView.section', "Section"));
	host.propertyRow(panel, localize('hvacView.f.shape', "Shape"), host.selectInput(DUCT_SHAPES.map(s => ({ value: s, label: ductShapeLabel(s) })), duct.shape, v => setShape(host, duct, v), path('shape'), localize('hvacView.f.shape', "Shape")));
	if (duct.shape === 'round') {
		host.fieldRow(panel, H.diameter, duct.diameter, v => host.setField(duct, 'diameter', v), path('diameter'));
	} else {
		host.fieldRow(panel, H.ductWidth, duct.width, v => host.setField(duct, 'width', v), path('width'));
		host.fieldRow(panel, H.ductHeight, duct.height, v => host.setField(duct, 'height', v), path('height'));
	}
	host.fieldRow(panel, H.flow, duct.flow, v => host.setField(duct, 'flow', v), path('flow'), localize('hvacView.sized', "sized"));
	appendPropertyHeading(panel, localize('hvacView.route', "Route"));
	if (duct.riser) {
		const riser = duct.riser;
		for (const end of ['fromStory', 'toStory'] as const) {
			const label = end === 'fromStory' ? localize('hvacView.f.from', "Starts at") : localize('hvacView.f.to', "Up to");
			host.propertyRow(panel, label, host.selectInput(host.storyOptions(), riser[end], v => {
				riser[end] = v;
				host.changed(true);
			}, path(`riser.${end}`), label));
		}
		host.propertyRow(panel, localize('hvacView.f.shaft', "Shaft"), host.selectInput(document.shafts.map(s => ({ value: s.id, label: s.id })), duct.shaft ?? '', v => host.setOptional(duct, 'shaft', v), path('shaft'), localize('hvacView.f.shaft', "Shaft"), true),
			undefined, localize('hvacView.f.shaftTitle', "The shaft it rises in; else it needs an opening through each floor"));
		host.propertyRow(panel, localize('hvacView.f.position', "Position"), host.pathInput(duct.path.slice(0, 1), p => {
			duct.path = p.slice(0, 1);
			host.changed(false);
		}, path('path'), localize('hvacView.f.position', "Position"), 1), F.x.unit, localize('hvacView.positionTitle', "x y in m; drag it in the plan to move it"));
		if (!riserInShaft(duct, document)) {
			appendPropertyNote(panel, localize('hvacView.riserNoShaft', "Not in a shaft: it needs an opening through each floor it passes (Add Duct Openings)."));
		}
	} else {
		host.propertyRow(panel, localize('hvacView.f.storyRun', "Story"), host.selectInput(host.storyOptions(), duct.story, v => {
			duct.story = v;
			host.followStory(v);
			host.changed(true);
		}, path('story'), localize('hvacView.f.storyRun', "Story")));
		host.fieldRow(panel, F.bottom, duct.bottom, v => host.setField(duct, 'bottom', v), path('bottom'), localize('hvacView.soffit', "soffit"));
		host.propertyRow(panel, localize('hvacView.f.path', "Path"), host.pathInput(duct.path, p => {
			duct.path = p;
			host.changed(false);
		}, path('path'), localize('hvacView.f.path', "Path"), 2), F.x.unit, localize('hvacView.pathTitle', "Points as x y in m, separated by semicolons; drag the duct in the plan to move it"));
		appendPropertyRow(panel, localize('hvacView.f.length', "Length"), localize('hvacView.mValue', "{0} m", formatNumber(pathLength(duct.path) / 1000, 2)));
		const crossings = ductCrossings(duct, document, host.context);
		appendPropertyHeading(panel, localize('hvacView.crossings', "Beams crossed ({0})", crossings.length));
		for (const c of crossings) {
			appendPropertyRow(panel, localize('hvacView.beam', "Beam {0}", c.beam), c.opening
				? localize('hvacView.throughOpening', "through {0}", c.opening)
				: $('span.band-warn.mep-util-value', undefined, localize('hvacView.needsOpening', "needs an opening, {0} m from its start", formatNumber(c.distance / 1000, 2))));
		}
		if (!crossings.length) {
			appendPropertyNote(panel, localize('hvacView.noCrossings', "It crosses no beam at its level."));
		}
	}
	const result = report?.ducts.find(d => d.id === duct.id);
	if (result) {
		appendPropertyHeading(panel, localize('hvacView.check', "Check"));
		if (result.load !== undefined) {
			appendPropertyRow(panel, H.flow.label, `${formatNumber(result.load, 2)} ${H.flow.unit}`);
		}
		if (result.velocity !== undefined) {
			appendPropertyRow(panel, localize('hvacView.f.velocity', "Velocity"), localize('hvacView.msValue', "{0} m/s", formatNumber(result.velocity, 1)));
		}
		if (result.size) {
			appendPropertyRow(panel, localize('hvacView.f.size', "Size"), result.size);
		}
		if (result.note) {
			appendPropertyNote(panel, result.note);
		}
	}
}

export function renderHvacSummaryProperties(panel: HTMLElement, host: IMepFormHost, report: IHvacReport | undefined): void {
	const hvac = hvacOf(host.document);
	const story = host.context.stories.find(s => s.id === host.story);
	if (story) {
		appendPropertyHeading(panel, story.name);
		const row = hvac?.stories.find(s => s.story === story.id);
		appendPropertyRow(panel, localize('hvacView.f.conditioned', "Air-conditioned"), row?.conditioned ? localize('hvacView.yes', "yes") : localize('hvacView.no', "no"));
		appendPropertyRow(panel, localize('hvacView.plant', "Plant"), String(hvac?.plant.filter(p => p.story === story.id).length ?? 0));
		const weight = (hvac?.plant ?? []).filter(p => p.story === story.id).reduce((s, p) => s + (p.operatingWeight ?? 0), 0);
		appendPropertyRow(panel, ITEM_FIELDS.operatingWeight.label, localize('hvacView.knValue', "{0} kN", formatNumber(weight, 1)));
		const result = report?.stories.find(s => s.story === story.id);
		if (result?.total !== undefined) {
			appendPropertyRow(panel, localize('hvacView.f.load', "Cooling load"), localize('hvacView.kwValue', "{0} kW", formatNumber(result.total, 1)));
		}
	}
	appendPropertyHeading(panel, localize('hvacView.summary', "HVAC"));
	appendPropertyRow(panel, localize('hvacView.f.system', "System"), hvac?.system ? hvacSystemLabel(String(hvac.system)) : '—');
	appendPropertyRow(panel, localize('hvacView.plant', "Plant"), String(hvac?.plant.length ?? 0));
	appendPropertyRow(panel, localize('hvacView.ducts', "Ducts"), String(hvac?.ducts.length ?? 0));
	const open = allCrossings(host.document, host.context).filter(c => !c.opening).length;
	appendPropertyRow(panel, localize('hvacView.f.openCrossings', "Beam crossings without an opening"), String(open));
	appendPropertyNote(panel, localize('hvacView.summaryNote', "Select a plant item or a duct in the plan to edit it here; the design conditions, envelope and storeys are in Data. Calculate Loads runs the cooling load."));
}

/** Without the backend: what the file says (floor areas, internal gains from the densities, plant weights). */
export function renderLocalHvac(view: HTMLElement, host: IMepFormHost): void {
	const hvac = hvacOf(host.document);
	if (!hvac) {
		return;
	}
	const section = resultSection(view, localize('hvacView.localTitle', "As set up"), localize('hvacView.localDetail', "from the file; the loads, sizes and checks come from the backend"));
	const table = append(section, $('table.mep-table.mep-result-table'));
	host.tableHead(table, [
		{ label: localize('hvacView.f.story', "Storey"), width: 130 }, { label: localize('hvacView.f.area', "Floor"), unit: localize('hvacView.unit.m2', "m²"), numeric: true, width: 80 },
		{ label: localize('hvacView.f.gains', "Lighting and equipment"), unit: localize('hvacView.unit.kw', "kW"), numeric: true, width: 120 },
		{ label: localize('hvacView.f.plantWeight', "Plant weight"), unit: UNIT_KN, numeric: true, width: 100 },
	]);
	const body = append(table, $('tbody'));
	const stories = new Set([...hvac.stories.map(s => s.story), ...hvac.plant.map(p => p.story)]);
	for (const story of host.context.stories.filter(s => stories.has(s.id)).reverse()) {
		const row = hvac.stories.find(s => s.story === story.id);
		const area = storyFloorArea(host.context, story.id);
		const gains = row ? ((row.lighting ?? 0) + (row.equipment ?? 0)) * area / 1000 : undefined;
		const weight = hvac.plant.filter(p => p.story === story.id).reduce((s, p) => s + (p.operatingWeight ?? 0), 0);
		const tr = append(body, $('tr'));
		append(tr, $('td', undefined, story.name));
		append(tr, $('td.number', undefined, value(area || undefined, 0)));
		append(tr, $('td.number', undefined, value(gains, 1)));
		append(tr, $('td.number', undefined, weight ? formatNumber(weight, 1) : ''));
	}
	const open = allCrossings(host.document, host.context).filter(c => !c.opening);
	if (open.length) {
		append(section, $('p.mep-note', undefined, localize('hvacView.localCrossings', "Beam crossings without an opening: {0}.", open.map(c => `${c.duct} × ${c.beam}`).join(', '))));
	}
}
