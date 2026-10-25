/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { localize } from '../../../../nls.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow } from '../../saengineProject/browser/editorFrame.js';
import { formatNumber, IFieldSpec } from '../../saengineSoil/browser/soilDocument.js';
import { IMepFormHost, ITEM_FIELDS, settingsGrid, storyRowIds, UNIT_KN, UNIT_MM } from './mepForm.js';
import { storyFloorArea } from './mepRead.js';
import { IOccupancy, ITank } from './plumbingDocument.js';
import {
	CEILINGS, CONSTRUCTIONS, CORRIDORS, ensureFire, FIRE_HAZARDS, FIRE_PUMP_DUTIES, FIRE_RISER_SYSTEMS, fireChoiceLabel, fireOf, firePumpLabel, firePumpLetters, fireRiserLabel, fireRiserLetters,
	fireStatusLabel, fireStoryRow, FireRiserSystem, hazardLabel, HOSES, IFirePump, IFireReport, IFireRiser, PIPE_MATERIALS, PUMP_TYPES, STANDBYS, STORAGES,
} from './fireDocument.js';

/*
 * The fire protection's Data view and properties panel in the MEP editor: the building and the
 * water supply settings, each storey's use (which decides the systems), the risers, pump sets
 * and fire tanks as tables; one item in the properties panel. Built through the editor's form
 * host (mepForm.ts).
 */

export interface IFireActions {
	addRiser(system: FireRiserSystem): void;
	propose(): void;
}

const M2 = localize('fireView.unit.m2', "m²");
const LPM = localize('fireView.unit.lpm', "l/min");
const KW = localize('fireView.unit.kw', "kW");

const E = {
	area: { key: 'area', label: localize('fireView.f.area', "Floor area"), unit: M2, kind: 'number', min: 0.001, width: 76, title: localize('fireView.f.areaTitle', "Gross floor area; empty: the story's slabs") },
	undivided: { key: 'undivided', label: localize('fireView.f.undivided', "Undivided"), unit: M2, kind: 'number', min: 0.001, width: 76, title: localize('fireView.f.undividedTitle', "Largest single effective undivided space; empty: the floor area") },
	dwellingUnits: { key: 'dwellingUnits', label: localize('fireView.f.units', "Dwelling units"), kind: 'number', min: 0, title: localize('fireView.f.unitsTitle', "Flats: 30 or more need a fire protection plan (Sec 5.1.6(c))") },
	occupantLoad: { key: 'occupantLoad', label: localize('fireView.f.occupants', "Occupant load"), kind: 'number', min: 0, title: localize('fireView.f.occupantsTitle', "Industry G1: above 150 the protection is performance based (Sec 5.9.1)") },
	falseCeiling: { key: 'falseCeiling', label: localize('fireView.f.falseCeiling', "Under one false ceiling"), unit: M2, kind: 'number', min: 0, title: localize('fireView.f.falseCeilingTitle', "Offices: above 500 m² an automatic alarm above and below it (Sec 5.7(ix))") },
	fireEngineWeight: { key: 'fireEngineWeight', label: localize('fireView.f.engine', "Fire engine"), unit: UNIT_KN, kind: 'number', min: 0.001, title: localize('fireView.f.engineTitle', "Gross weight of the local fire engine; empty: 160 kN (from memory, to be checked)") },
	diameter: { key: 'diameter', label: localize('fireView.f.diameter', "DN"), unit: UNIT_MM, kind: 'number', min: 1, width: 64, title: localize('fireView.f.diameterTitle', "Nominal size; empty: sized by the hydraulic calculation") },
	flow: { key: 'flow', label: localize('fireView.f.flow', "Flow"), unit: LPM, kind: 'number', min: 0.001, width: 72 },
	head: { key: 'head', label: localize('fireView.f.head', "Head"), unit: localize('fireView.unit.m', "m"), kind: 'number', min: 0.001, width: 64 },
	power: { key: 'power', label: localize('fireView.f.power', "Motor"), unit: KW, kind: 'number', min: 0.001, width: 64 },
	tankLength: { key: 'length', label: localize('fireView.f.tankLength', "Length"), unit: UNIT_MM, kind: 'number', min: 1, width: 72, title: localize('fireView.f.tankLengthTitle', "Inside, along X") },
	tankWidth: { key: 'width', label: localize('fireView.f.tankWidth', "Width"), unit: UNIT_MM, kind: 'number', min: 1, width: 72, title: localize('fireView.f.tankWidthTitle', "Inside, along Y") },
	waterDepth: { key: 'waterDepth', label: localize('fireView.f.waterDepth', "Water depth"), unit: UNIT_MM, kind: 'number', min: 1, width: 72 },
} satisfies { [key: string]: IFieldSpec };

function options(values: readonly string[]): { value: string; label: string }[] {
	return values.map(v => ({ value: v, label: fireChoiceLabel(v) }));
}

/** A tri-state choice: as Part 4 requires (empty), yes or no. */
function triState(host: IMepFormHost, current: boolean | undefined, store: (value: boolean | undefined) => void, key: string, label: string): HTMLSelectElement {
	return host.selectInput([
		{ value: '', label: localize('fireView.asRequired', "As Part 4 requires") },
		{ value: 'yes', label: localize('fireView.yes', "Yes") },
		{ value: 'no', label: localize('fireView.no', "No") },
	], current === undefined ? '' : current ? 'yes' : 'no', v => store(v === '' ? undefined : v === 'yes'), key, label);
}

export function renderFireData(view: HTMLElement, host: IMepFormHost, occupancies: readonly IOccupancy[], actions: IFireActions): void {
	const document = host.document;
	const fire = fireOf(document);
	const f = () => ensureFire(document);
	const header = append(view, $('.mep-view-header'));
	append(header, $('span.mep-view-title', undefined, localize('fireView.dataTitle', "Fire protection set-up")));
	append(header, $('span.mep-view-subtitle', undefined, localize('fireView.dataSubtitle', "Each storey's use decides the systems BNBC 2020 Part 4 requires; the risers, pump sets and fire tanks carry their sleeves and weights into the structure. Sizes in mm, positions in m.")));

	// Building and supply.
	const settings = host.section(localize('fireView.settings', "Building and water supply"), undefined);
	const setting = settingsGrid(settings);
	const choice = (target: () => { [key: string]: unknown }, key: string, values: readonly string[], label: string, current: unknown, title?: string) =>
		setting(label, host.selectInput(options(values), String(current ?? ''), v => host.setOptional(target(), key, v), `fire.${key}`, label, true), undefined, title);
	choice(() => f().building, 'construction', CONSTRUCTIONS, localize('fireView.f.construction', "Construction"), fire?.building.construction, localize('fireView.f.constructionTitle', "Sec 5.2: any other than Type I-A needs performance based fire protection"));
	choice(() => f().building, 'corridor', CORRIDORS, localize('fireView.f.corridor', "Corridor"), fire?.building.corridor, localize('fireView.f.corridorTitle', "Hostels, hotels and schools (Sec 5.3.3, 5.3.4, 5.4)"));
	for (const field of [E.dwellingUnits, E.occupantLoad, E.falseCeiling]) {
		setting(field.label, host.textInput(field, fire?.building[field.key], v => host.setField(f().building, field.key, v), `fire.building.${field.key}`), field.unit, field.title);
	}
	setting(localize('fireView.f.hydrant', "Hydrant system"), triState(host, fire?.hydrant, v => {
		if (v === undefined) {
			delete f().hydrant;
		} else {
			f().hydrant = v;
		}
		host.changed(true);
	}, 'fire.hydrant', localize('fireView.f.hydrant', "Hydrant system")), undefined, localize('fireView.f.hydrantTitle', "Where Part 4 allows 'portable extinguishers or hydrants', Yes chooses hydrants"));
	setting(localize('fireView.f.detection', "Automatic detection"), triState(host, fire?.detection, v => {
		if (v === undefined) {
			delete f().detection;
		} else {
			f().detection = v;
		}
		host.changed(true);
	}, 'fire.detection', localize('fireView.f.detection', "Automatic detection")));
	choice(() => f().supply, 'hose', HOSES, localize('fireView.f.hose', "Hose"), fire?.supply.hose, localize('fireView.f.hoseTitle', "300 kPa at the outlet; first-aid hose 200 kPa (Sec 4.2.3.3)"));
	choice(() => f().supply, 'material', PIPE_MATERIALS, localize('fireView.f.material', "Pipe"), fire?.supply.material);
	choice(() => f().supply, 'storage', STORAGES, localize('fireView.f.storage', "Fire water"), fire?.supply.storage, localize('fireView.f.storageTitle', "Kept for fire fighting only (Sec 4.2.3.7)"));
	choice(() => f().supply, 'pumpType', PUMP_TYPES, localize('fireView.f.pumpType', "Pump type"), fire?.supply.pumpType, localize('fireView.f.pumpTypeTitle', "Centrifugal pumps need a flooded suction (Sec 4.2.2.5)"));
	choice(() => f().supply, 'standby', STANDBYS, localize('fireView.f.standby', "Standby pump"), fire?.supply.standby);
	setting(localize('fireView.f.engineOnCover', "Fire engine on the tank"), host.yesNo(fire?.supply.fireEngineOnCover === true, v => {
		f().supply.fireEngineOnCover = v;
		host.changed(true);
	}, 'fire.supply.fireEngineOnCover', localize('fireView.f.engineOnCover', "Fire engine on the tank")), undefined, localize('fireView.f.engineOnCoverTitle', "No space beside the ground tank: its cover carries the fire engine (Sec 4.2.3.8)"));
	setting(E.fireEngineWeight.label, host.textInput(E.fireEngineWeight, fire?.supply.fireEngineWeight, v => host.setField(f().supply, 'fireEngineWeight', v), 'fire.supply.fireEngineWeight'), E.fireEngineWeight.unit, E.fireEngineWeight.title);

	// Stories.
	const rows = fire?.stories ?? [];
	const stories = host.section(localize('fireView.stories', "Use by storey"), rows.length);
	const table = append(append(stories, $('.mep-table-scroll')), $('table.mep-table'));
	const columns = [
		{ label: localize('fireView.f.story', "Storey"), width: 110 }, { label: localize('fireView.f.occupancy', "Use (Part 3 group)"), width: 300 },
		{ label: E.area.label, unit: M2, numeric: true, width: 76 }, { label: E.undivided.label, unit: M2, numeric: true, width: 76 },
		{ label: localize('fireView.f.hazard', "Hazard"), width: 160 }, { label: localize('fireView.f.sprinklered', "Sprinklers"), width: 140 },
		{ label: localize('fireView.f.slabs', "Slabs"), unit: M2, numeric: true, width: 64 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	const occupancyOptions = occupancies.map(o => ({ value: o.key, label: o.source ? `${o.label} (${o.source.split(' ').pop()})` : o.label }));
	for (const storyId of storyRowIds(host.context, rows)) {
		const index = rows.findIndex(r => r.story === storyId);
		const row = rows[index];
		const tr = append(body, $(`tr.mep-row${row ? '' : '.plb-empty-row'}`));
		const path = (field: string) => index >= 0 ? `fire.stories.${index}.${field}` : `fire.new.${storyId}.${field}`;
		const target = () => fireStoryRow(f(), storyId);
		append(tr, $('td', undefined, host.storyName(storyId)));
		append(append(tr, $('td')), host.selectInput(occupancyOptions, String(row?.occupancy ?? ''), v => host.setOptional(target(), 'occupancy', v), path('occupancy'), localize('fireView.f.occupancyOf', "Use of {0}", host.storyName(storyId)), true));
		for (const field of [E.area, E.undivided]) {
			append(append(tr, $('td')), host.textInput(field, row?.[field.key], v => host.setField(target(), field.key, v), path(field.key)));
		}
		append(append(tr, $('td')), host.selectInput(FIRE_HAZARDS.map(h => ({ value: h, label: hazardLabel(h) })), String(row?.hazard ?? ''), v => host.setOptional(target(), 'hazard', v), path('hazard'), localize('fireView.f.hazard', "Hazard"), true));
		append(append(tr, $('td')), triState(host, row?.sprinklered, v => {
			const r = target();
			if (v === undefined) {
				delete r.sprinklered;
			} else {
				r.sprinklered = v;
			}
			host.changed(true);
		}, path('sprinklered'), localize('fireView.f.sprinklered', "Sprinklers")));
		const area = storyFloorArea(host.context, storyId);
		append(tr, $('td.number.mep-muted-cell', undefined, area ? formatNumber(area, 0) : ''));
		if (row) {
			host.removeButton(tr, () => {
				f().stories.splice(index, 1);
				host.changed(true);
			});
		} else {
			append(tr, $('td'));
		}
	}
	append(stories, $('p.mep-note', undefined, localize('fireView.storiesNote', "Give the occupied storeys' use: the hazard follows Table 4.4.1 by the Part 3 group unless chosen; sprinklers where Part 4 requires them unless chosen.")));

	renderRiserTable(host, actions);
	renderPumpTable(host, actions);
	renderTankTable(host, actions);
}

function renderRiserTable(host: IMepFormHost, actions: IFireActions): void {
	const document = host.document;
	const risers = fireOf(document)?.risers ?? [];
	const section = host.section(localize('fireView.risers', "Risers"), risers.length, { label: localize('fireView.addStandpipe', "Add Standpipe"), run: () => actions.addRiser('standpipe') });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('fireView.f.system', "System"), width: 240 }, { label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true },
		{ label: E.diameter.label, unit: UNIT_MM, numeric: true, width: 64 }, { label: localize('fireView.f.from', "Starts at"), width: 110 }, { label: localize('fireView.f.to', "Up to"), width: 110 },
		{ label: localize('fireView.f.shaft', "Shaft"), width: 80 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	risers.forEach((r, index) => {
		const row = host.selectableRow(body, { kind: 'fireRiser', index });
		const path = (field: string) => `fire.risers.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, r.id, v => host.setField(r, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(FIRE_RISER_SYSTEMS.map(s => ({ value: s, label: `${fireRiserLetters(s)} · ${fireRiserLabel(s)}` })), r.system, v => {
			r.system = v;
			host.changed(true);
		}, path('system'), localize('fireView.f.system', "System")));
		for (const field of [F.x, F.y, E.diameter]) {
			append(append(row, $('td')), host.textInput(field, r[field.key], v => host.setField(r, field.key, v), path(field.key)));
		}
		for (const end of ['fromStory', 'toStory'] as const) {
			append(append(row, $('td')), host.selectInput(host.storyOptions(), r[end], v => {
				r[end] = v;
				host.changed(true);
			}, path(end), end === 'fromStory' ? localize('fireView.f.from', "Starts at") : localize('fireView.f.to', "Up to")));
		}
		append(append(row, $('td')), host.selectInput(document.shafts.map(s => ({ value: s.id, label: s.id })), r.shaft ?? '', v => host.setOptional(r, 'shaft', v), path('shaft'), localize('fireView.f.shaft', "Shaft"), true));
		host.removeButton(row, () => {
			ensureFire(document).risers.splice(index, 1);
			host.changed(true);
		});
	});
	if (!risers.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('fireView.noRisers', "None yet. Add the standpipes at the stair landings (one for each 1000 m² of floor, Table 4.4.1) and the sprinkler risers: each needs a sleeve through the floors it passes outside a shaft.")));
	}
}

function renderPumpTable(host: IMepFormHost, actions: IFireActions): void {
	const document = host.document;
	const pumps = fireOf(document)?.pumps ?? [];
	const section = host.section(localize('fireView.pumps', "Pump sets"), pumps.length, { label: localize('fireView.propose', "Propose Pumps and Tank"), run: () => actions.propose() });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('fireView.f.duty', "Duty"), width: 200 }, { label: localize('fireView.f.storyOn', "Story"), width: 110 },
		{ label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true },
		{ label: E.flow.label, unit: LPM, numeric: true, width: 72 }, { label: E.head.label, unit: E.head.unit, numeric: true, width: 64 }, { label: E.power.label, unit: KW, numeric: true, width: 64 },
		{ label: F.operatingWeight.label, unit: UNIT_KN, numeric: true, width: 84 }, { label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	pumps.forEach((p, index) => {
		const row = host.selectableRow(body, { kind: 'firePump', index });
		const path = (field: string) => `fire.pumps.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, p.id, v => host.setField(p, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput(FIRE_PUMP_DUTIES.map(d => ({ value: d, label: `${firePumpLetters(d)} · ${firePumpLabel(d)}` })), p.duty, v => {
			p.duty = v;
			host.changed(true);
		}, path('duty'), localize('fireView.f.duty', "Duty")));
		append(append(row, $('td')), host.selectInput(host.storyOptions(), p.story, v => {
			p.story = v;
			host.changed(true);
		}, path('story'), localize('fireView.f.storyOn', "Story")));
		for (const field of [F.x, F.y, E.flow, E.head, E.power, F.operatingWeight]) {
			append(append(row, $('td')), host.textInput(field, p[field.key], v => host.setField(p, field.key, v), path(field.key)));
		}
		host.removeButton(row, () => {
			ensureFire(document).pumps.splice(index, 1);
			host.changed(true);
		});
	});
	if (!pumps.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('fireView.noPumps', "None yet. Propose sizes the main, standby and jockey pumps from the hydraulic calculation (Table 4.4.2); their weights load the floor they stand on.")));
	}
}

function renderTankTable(host: IMepFormHost, actions: IFireActions): void {
	const document = host.document;
	const tanks = fireOf(document)?.tanks ?? [];
	const section = host.section(localize('fireView.tanks', "Fire tanks"), tanks.length, { label: localize('fireView.propose', "Propose Pumps and Tank"), run: () => actions.propose() });
	const table = append(append(section, $('.mep-table-scroll')), $('table.mep-table'));
	const F = ITEM_FIELDS;
	const columns = [
		{ label: F.id.label, width: 64 }, { label: localize('fireView.f.kind', "Kind"), width: 150 }, { label: localize('fireView.f.storyOn', "Story"), width: 110 },
		{ label: F.x.label, unit: F.x.unit, numeric: true }, { label: F.y.label, unit: F.y.unit, numeric: true },
		{ label: E.tankLength.label, unit: UNIT_MM, numeric: true, width: 72 }, { label: E.tankWidth.label, unit: UNIT_MM, numeric: true, width: 72 }, { label: E.waterDepth.label, unit: UNIT_MM, numeric: true, width: 72 },
		{ label: '', width: 28 },
	];
	host.tableHead(table, columns);
	const body = append(table, $('tbody'));
	tanks.forEach((t, index) => {
		const row = host.selectableRow(body, { kind: 'fireTank', index });
		const path = (field: string) => `fire.tanks.${index}.${field}`;
		append(append(row, $('td')), host.textInput(F.id, t.id, v => host.setField(t, 'id', v), path('id')));
		append(append(row, $('td')), host.selectInput([
			{ value: 'underground', label: localize('fireView.underground', "Underground reservoir") },
			{ value: 'overhead', label: localize('fireView.overhead', "Overhead tank") },
		], t.kind, v => {
			t.kind = v;
			if (v === 'underground') {
				t.story = null;
			} else if (!t.story) {
				t.story = host.story ?? host.context.stories[host.context.stories.length - 1]?.id ?? null;
			}
			host.changed(true);
		}, path('kind'), localize('fireView.f.kind', "Kind")));
		append(append(row, $('td')), t.kind === 'overhead' ? host.selectInput(host.storyOptions(), t.story ?? '', v => {
			t.story = v;
			host.changed(true);
		}, path('story'), localize('fireView.f.storyOn', "Story")) : $('span.mep-muted', undefined, localize('fireView.inGround', "in the ground")));
		for (const field of [F.x, F.y, E.tankLength, E.tankWidth, E.waterDepth]) {
			append(append(row, $('td')), host.textInput(field, t[field.key], v => host.setField(t, field.key, v), path(field.key)));
		}
		host.removeButton(row, () => {
			ensureFire(document).tanks.splice(index, 1);
			host.changed(true);
		});
	});
	if (!tanks.length) {
		append(append(body, $('tr')), $('td.mep-muted', { colspan: String(columns.length) }, localize('fireView.noTanks', "None yet. Propose sizes the reservoir from the flows and durations of Table 4.4.1; it is designed as an RC tank, and an overhead one loads its floor.")));
	}
}

export function renderFireRiserProperties(panel: HTMLElement, host: IMepFormHost, riser: IFireRiser, index: number): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `fire.risers.${index}.${field}`;
	appendPropertyHeading(panel, localize('fireView.riserHeading', "{0} {1}", fireRiserLabel(riser.system), riser.id));
	host.fieldRow(panel, F.id, riser.id, v => host.setField(riser, 'id', v), path('id'));
	host.propertyRow(panel, localize('fireView.f.system', "System"), host.selectInput(FIRE_RISER_SYSTEMS.map(s => ({ value: s, label: fireRiserLabel(s) })), riser.system, v => {
		riser.system = v;
		host.changed(true);
	}, path('system'), localize('fireView.f.system', "System")));
	for (const field of [F.x, F.y, E.diameter]) {
		host.fieldRow(panel, field, riser[field.key], v => host.setField(riser, field.key, v), path(field.key));
	}
	for (const end of ['fromStory', 'toStory'] as const) {
		const label = end === 'fromStory' ? localize('fireView.f.from', "Starts at") : localize('fireView.f.to', "Up to");
		host.propertyRow(panel, label, host.selectInput(host.storyOptions(), riser[end], v => {
			riser[end] = v;
			host.changed(true);
		}, path(end), label));
	}
	host.propertyRow(panel, localize('fireView.f.shaft', "Shaft"), host.selectInput(host.document.shafts.map(s => ({ value: s.id, label: s.id })), riser.shaft ?? '', v => host.setOptional(riser, 'shaft', v), path('shaft'), localize('fireView.f.shaft', "Shaft"), true));
	appendPropertyNote(panel, localize('fireView.riserNote', "A wet riser is at least 100 mm (Sec 4.2.4); its supports carry the water-filled pipe + 110 kg (Sec 4.2.3.13). Add Sleeves proposes the sleeves through the floors it passes outside a shaft."));
}

export function renderFirePumpProperties(panel: HTMLElement, host: IMepFormHost, pump: IFirePump, index: number): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `fire.pumps.${index}.${field}`;
	appendPropertyHeading(panel, localize('fireView.pumpHeading', "{0} {1}", firePumpLabel(pump.duty), pump.id));
	host.fieldRow(panel, F.id, pump.id, v => host.setField(pump, 'id', v), path('id'));
	host.propertyRow(panel, localize('fireView.f.storyOn', "Story"), host.selectInput(host.storyOptions(), pump.story, v => {
		pump.story = v;
		host.followStory(v);
		host.changed(true);
	}, path('story'), localize('fireView.f.storyOn', "Story")));
	for (const field of [F.x, F.y, F.length, F.width, F.height, E.flow, E.head, E.power, F.operatingWeight]) {
		host.fieldRow(panel, field, pump[field.key], v => host.setField(pump, field.key, v), path(field.key));
	}
	appendPropertyNote(panel, pump.operatingWeight === undefined
		? localize('fireView.pumpTypical', "No weight given: the analysis takes a typical set of its power (from memory); give the selected set's data. A pump vibrates (impact).")
		: localize('fireView.pumpNote', "Its weight loads the floor it stands on, once, with impact (it vibrates)."));
}

export function renderFireTankProperties(panel: HTMLElement, host: IMepFormHost, tank: ITank, index: number): void {
	const F = ITEM_FIELDS;
	const path = (field: string) => `fire.tanks.${index}.${field}`;
	appendPropertyHeading(panel, localize('fireView.tankHeading', "Fire tank {0}", tank.id));
	host.fieldRow(panel, F.id, tank.id, v => host.setField(tank, 'id', v), path('id'));
	for (const field of [F.x, F.y, E.tankLength, E.tankWidth, E.waterDepth]) {
		host.fieldRow(panel, field, tank[field.key], v => host.setField(tank, field.key, v), path(field.key));
	}
	appendPropertyNote(panel, tank.kind === 'overhead'
		? localize('fireView.tankOverheadNote', "Designed as the plumbing tanks; its weight with the water loads its floor once.")
		: localize('fireView.tankGroundNote', "Designed as the plumbing tanks; it stands on the ground. Easily reached by the fire engine, else its cover carries it (Sec 4.2.3.8)."));
}

export function renderFireSummaryProperties(panel: HTMLElement, host: IMepFormHost, report: IFireReport | undefined): void {
	const fire = fireOf(host.document);
	appendPropertyHeading(panel, localize('fireView.summary', "Fire protection"));
	if (report) {
		for (const s of report.systems) {
			appendPropertyRow(panel, s.label, fireStatusLabel(s.status));
		}
		if (report.demand?.volume) {
			appendPropertyRow(panel, localize('fireView.reservoir', "Reservoir"), localize('fireView.m3Value', "{0} m³", formatNumber(report.demand.volume, 1)));
		}
	}
	appendPropertyRow(panel, localize('fireView.risers', "Risers"), String(fire?.risers.length ?? 0));
	appendPropertyRow(panel, localize('fireView.pumps', "Pump sets"), String(fire?.pumps.length ?? 0));
	appendPropertyRow(panel, localize('fireView.tanks', "Fire tanks"), String(fire?.tanks.length ?? 0));
	appendPropertyNote(panel, localize('fireView.summaryNote', "Select a riser, pump or tank in the plan to edit it here; the storeys' use and the supply are in Data."));
}
