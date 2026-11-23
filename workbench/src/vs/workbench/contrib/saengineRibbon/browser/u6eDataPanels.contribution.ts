/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import type { EngineMethod } from '../../../../platform/saengine/common/femSolver.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, IEngineDataPanelDescriptor, IDataPanelResult, IDataPanelTable, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';

const category = localize2('saengine.category', "SAEngine");
const projectOpen = ContextKeyExpr.has('saengineProjectOpen');

type U6ePanelPart = 'fem' | 'bim3d' | 'architecture' | 'documents' | 'studies' | 'output';

interface IU6ePanelDefinition {
	readonly id: string;
	readonly method: EngineMethod;
	readonly part: U6ePanelPart;
	readonly title: string;
	readonly autoRun?: boolean;
}

interface IJsonBag {
	readonly [key: string]: unknown;
}

function isBag(value: unknown): value is IJsonBag {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asBag(value: unknown): IJsonBag {
	return isBag(value) ? value : {};
}

function asArray(value: unknown): readonly unknown[] {
	return Array.isArray(value) ? value : [];
}

function formatValue(value: unknown): string {
	if (value === null || value === undefined || value === '') {
		return localize('u6e.panel.emptyValue', "–");
	}
	if (typeof value === 'boolean') {
		return value ? localize('u6e.panel.yes', "Yes") : localize('u6e.panel.no', "No");
	}
	if (typeof value === 'number') {
		if (!Number.isFinite(value)) {
			return localize('u6e.panel.emptyValue', "–");
		}
		return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
	}
	if (typeof value === 'string') {
		return value;
	}
	if (Array.isArray(value)) {
		return value.map(formatValue).join(', ');
	}
	if (isBag(value)) {
		return Object.entries(value).map(([key, item]) => `${key}: ${formatValue(item)}`).join('; ');
	}
	return String(value);
}

function humanizeKey(value: string): string {
	return value
		.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
		.replace(/[_-]+/g, ' ')
		.replace(/\b\w/g, first => first.toLocaleUpperCase());
}

function makeTable(key: string, values: readonly unknown[]): IDataPanelTable | undefined {
	if (!values.length) {
		return undefined;
	}

	const rows: DataPanelRow[] = values.map((value, index) => {
		const row: { [key: string]: string } = {};
		if (isBag(value)) {
			for (const [field, item] of Object.entries(value)) {
				row[field] = formatValue(item);
			}
		}
		if (!Object.keys(row).length) {
			row.item = String(index + 1);
			row.value = formatValue(value);
		}
		return row;
	});

	const keys = [...new Set(rows.flatMap(row => Object.keys(row)))];
	return {
		id: key,
		title: localize('u6e.panel.tableTitle', "{0}", humanizeKey(key)),
		columns: keys.map(column => ({
			key: column,
			title: localize('u6e.panel.columnTitle', "{0}", humanizeKey(column)),
		})),
		rows,
		emptyMessage: localize('u6e.panel.noRows', "No rows are available."),
	};
}

function panelResult(raw: IJsonBag): IDataPanelResult {
	const notes = asArray(raw.notes).filter((note): note is string => typeof note === 'string');
	if (raw.unavailable === true) {
		const shown = notes.length ? notes : [localize('u6e.panel.unavailable', "This feature is currently unavailable.")];
		return {
			metrics: [{ label: localize('u6e.panel.status', "Status"), value: localize('u6e.panel.notInPack', "Not in the active code pack"), tone: 'warn' }],
			tables: [notesTable(shown)],
			notes: shown,
		};
	}

	const summary = asBag(raw.summary);
	const metrics = Object.entries(summary).map(([key, value]) => ({
		label: localize('u6e.panel.metricLabel', "{0}", humanizeKey(key)),
		value: formatValue(value),
	}));
	const tables: IDataPanelTable[] = [];
	const details: DataPanelRow[] = [];
	for (const [key, value] of Object.entries(raw)) {
		if (key === 'summary' || key === 'notes' || key === 'unavailable') {
			continue;
		}
		if (Array.isArray(value)) {
			const table = makeTable(key, value);
			if (table) {
				tables.push(table);
			}
		} else if (isBag(value)) {
			for (const [field, item] of Object.entries(value)) {
				details.push({
					field: localize('u6e.panel.columnTitle', "{0}", humanizeKey(`${key}.${field}`)),
					value: formatValue(item),
				});
			}
		} else {
			details.push({
				field: localize('u6e.panel.columnTitle', "{0}", humanizeKey(key)),
				value: formatValue(value),
			});
		}
	}
	if (details.length) {
		tables.unshift({
			id: 'details',
			title: localize('u6e.panel.detailsTitle', "Details"),
			columns: [
				{ key: 'field', title: localize('u6e.panel.fieldTitle', "Field") },
				{ key: 'value', title: localize('u6e.panel.valueTitle', "Value") },
			],
			rows: details,
		});
	}
	if (notes.length) {
		// The panel shows only metrics and tables: the engine's notes get their own table.
		tables.push(notesTable(notes));
	}
	return { metrics, tables, notes };
}

function notesTable(notes: readonly string[]): IDataPanelTable {
	return {
		id: 'notes',
		title: localize('u6e.panel.notesTitle', "Notes"),
		columns: [{ key: 'note', title: localize('u6e.panel.noteTitle', "Note") }],
		rows: notes.map(note => ({ note })),
	};
}

function registerU6ePanel(definition: IU6ePanelDefinition): void {
	const id = `saengine.u6e.${definition.id}`;
	const descriptor: IEngineDataPanelDescriptor = {
		id,
		title: definition.title,
		part: definition.part,
		icon: Codicon.table,
		autoRun: definition.autoRun,
		help: localize('u6e.panel.help', "Runs {0} for the current project.", definition.title),
		run: async context => {
			const raw = asBag(await context.engineRequest(definition.method, { projectRoot: context.project!.root.fsPath }));
			return panelResult(raw);
		},
	};

	registerEngineDataPanel(descriptor);
	registerAction2(class extends Action2 {
		constructor() {
			super({
				id,
				title: { value: definition.title, original: definition.title },
				category,
				icon: Codicon.table,
				f1: true,
				precondition: projectOpen,
			});
		}

		override run(accessor: ServicesAccessor): Promise<unknown> {
			return openEngineDataPanel(accessor.get(IEditorService), id);
		}
	});
}

const panels: readonly IU6ePanelDefinition[] = [
	{ id: 'fem.notionalLoads', method: 'fem/notionalLoads', part: 'fem', title: localize('u6e.fem.notionalLoads', "Notional Loads") },
	{ id: 'fem.patternLive', method: 'fem/patternLive', part: 'fem', title: localize('u6e.fem.patternLive', "Pattern Live Loads") },
	{ id: 'fem.snowRainLoads', method: 'fem/snowRainLoads', part: 'fem', title: localize('u6e.fem.snowRainLoads', "Snow & Rain Loads") },
	{ id: 'fem.thermalLoads', method: 'fem/thermalLoads', part: 'fem', title: localize('u6e.fem.thermalLoads', "Thermal Loads") },
	{ id: 'fem.floodLoads', method: 'fem/floodLoads', part: 'fem', title: localize('u6e.fem.floodLoads', "Flood Loads") },
	{ id: 'fem.stairCraneLoads', method: 'fem/stairCraneLoads', part: 'fem', title: localize('u6e.fem.stairCraneLoads', "Stair & Crane Loads") },
	{ id: 'fem.loadCombinations', method: 'fem/loadCombinations', part: 'fem', title: localize('u6e.fem.loadCombinations', "Load Combinations Audit") },
	{ id: 'fem.spectralHazard', method: 'fem/spectralHazard', part: 'fem', title: localize('u6e.fem.spectralHazard', "Spectral Hazard") },
	{ id: 'fem.seismicSummary', method: 'fem/seismicSummary', part: 'fem', title: localize('u6e.fem.seismicSummary', "Seismic Summary") },
	{ id: 'fem.groundMotions', method: 'fem/groundMotions', part: 'fem', title: localize('u6e.fem.groundMotions', "Ground Motions") },
	{ id: 'fem.linearTimeHistory', method: 'fem/linearTimeHistory', part: 'fem', title: localize('u6e.fem.linearTimeHistory', "Linear Time History") },
	{ id: 'fem.irregularities', method: 'fem/irregularities', part: 'fem', title: localize('u6e.fem.irregularities', "Seismic Irregularities") },
	{ id: 'fem.torsionalEffects', method: 'fem/torsionalEffects', part: 'fem', title: localize('u6e.fem.torsionalEffects', "Torsional Effects") },
	{ id: 'fem.twoLevelSeismic', method: 'fem/twoLevelSeismic', part: 'fem', title: localize('u6e.fem.twoLevelSeismic', "Two-Level Seismic") },
	{ id: 'fem.floorSpectra', method: 'fem/floorSpectra', part: 'fem', title: localize('u6e.fem.floorSpectra', "Floor Spectra") },
	{ id: 'fem.isolationDampers', method: 'fem/isolationDampers', part: 'fem', title: localize('u6e.fem.isolationDampers', "Isolation & Dampers") },
	{ id: 'fem.windSpeedFactors', method: 'fem/windSpeedFactors', part: 'fem', title: localize('u6e.fem.windSpeedFactors', "Wind Speed Factors") },
	{ id: 'fem.gustResponse', method: 'fem/gustResponse', part: 'fem', title: localize('u6e.fem.gustResponse', "Gust Response") },
	{ id: 'fem.peakVelocityPressure', method: 'fem/peakVelocityPressure', part: 'fem', title: localize('u6e.fem.peakVelocityPressure', "Peak Velocity Pressure") },
	{ id: 'fem.localPressures', method: 'fem/localPressures', part: 'fem', title: localize('u6e.fem.localPressures', "Local Pressures") },
	{ id: 'fem.windComfort', method: 'fem/windComfort', part: 'fem', title: localize('u6e.fem.windComfort', "Wind Comfort") },
	{ id: 'fem.openStructures', method: 'fem/openStructures', part: 'fem', title: localize('u6e.fem.openStructures', "Open Structures") },
	{ id: 'fem.pushoverAnalysis', method: 'fem/pushoverAnalysis', part: 'fem', title: localize('u6e.fem.pushoverAnalysis', "Pushover Analysis") },
	{ id: 'fem.nonlinearHistory', method: 'fem/nonlinearHistory', part: 'fem', title: localize('u6e.fem.nonlinearHistory', "Nonlinear History") },
	{ id: 'fem.pDeltaBuckling', method: 'fem/pDeltaBuckling', part: 'fem', title: localize('u6e.fem.pDeltaBuckling', "P-Delta & Buckling") },
	{ id: 'fem.stagedConstruction', method: 'fem/stagedConstruction', part: 'fem', title: localize('u6e.fem.stagedConstruction', "Staged Construction") },
	{ id: 'fem.creepShrinkage', method: 'fem/creepShrinkage', part: 'fem', title: localize('u6e.fem.creepShrinkage', "Creep & Shrinkage") },
	{ id: 'fem.ssiSprings', method: 'fem/ssiSprings', part: 'fem', title: localize('u6e.fem.ssiSprings', "Soil-Structure Interaction") },
	{ id: 'fem.swayDrift', method: 'fem/swayDrift', part: 'fem', title: localize('u6e.fem.swayDrift', "Sway & Drift") },
	{ id: 'fem.floorVibration', method: 'fem/floorVibration', part: 'fem', title: localize('u6e.fem.floorVibration', "Floor Vibration") },
	{ id: 'fem.differentialSettlement', method: 'fem/differentialSettlement', part: 'fem', title: localize('u6e.fem.differentialSettlement', "Differential Settlement") },
	{ id: 'fem.punchingShear', method: 'fem/punchingShear', part: 'fem', title: localize('u6e.fem.punchingShear', "Punching Shear") },
	{ id: 'fem.deflectionCheck', method: 'fem/deflectionCheck', part: 'fem', title: localize('u6e.fem.deflectionCheck', "Deflection Check") },
	{ id: 'fem.crackControl', method: 'fem/crackControl', part: 'fem', title: localize('u6e.fem.crackControl', "Crack Control") },
	{ id: 'fem.torsionDesign', method: 'fem/torsionDesign', part: 'fem', title: localize('u6e.fem.torsionDesign', "Torsion Design") },
	{ id: 'fem.capacitySeismicDetailing', method: 'fem/capacitySeismicDetailing', part: 'fem', title: localize('u6e.fem.capacitySeismicDetailing', "Capacity & Seismic Detailing") },
	{ id: 'fem.fireSteelConnections', method: 'fem/fireSteelConnections', part: 'fem', title: localize('u6e.fem.fireSteelConnections', "Fire, Steel & Connections") },
	{ id: 'bim.syncStamps', method: 'bim/syncStamps', part: 'bim3d', title: localize('u6e.bim.syncStamps', "Model Sync Status") },
	{ id: 'bim.detailingModel', method: 'bim/detailingModel', part: 'bim3d', title: localize('u6e.bim.detailingModel', "Detailing Model Audit") },
	{ id: 'bim.rebarCages', method: 'bim/rebarCages', part: 'bim3d', title: localize('u6e.bim.rebarCages', "Rebar Cages") },
	{ id: 'bim.barBendingSchedule', method: 'bim/barBendingSchedule', part: 'bim3d', title: localize('u6e.bim.barBendingSchedule', "Bar Bending Schedule") },
	{ id: 'bim.ifcCheck', method: 'exports/structuralIfcCheck', part: 'bim3d', title: localize('u6e.bim.ifcCheck', "Structural IFC Check") },
	{ id: 'bim.studyDaylight', method: 'studies/daylightSolar', part: 'bim3d', title: localize('u6e.bim.studyDaylight', "Daylight & Solar Study") },
	{ id: 'bim.studyNoise', method: 'studies/noiseStudy', part: 'bim3d', title: localize('u6e.bim.studyNoise', "Noise Study") },
	{ id: 'bim.studyPhasing', method: 'studies/phasingSummary', part: 'bim3d', title: localize('u6e.bim.studyPhasing', "Phasing Summary") },
	{ id: 'bim.studySite', method: 'studies/plotPlanning', part: 'bim3d', title: localize('u6e.bim.studySite', "Plot Planning") },
	{ id: 'architecture.roomsCheck', method: 'architecture/roomsCheck', part: 'architecture', title: localize('u6e.arch.roomsCheck', "Rooms Check") },
	{ id: 'architecture.massingFloors', method: 'architecture/massingFloors', part: 'architecture', title: localize('u6e.arch.massingFloors', "Massing & Floors") },
	{ id: 'architecture.roofCeilingCurtain', method: 'architecture/roofCeilingCurtain', part: 'architecture', title: localize('u6e.arch.roofCeilingCurtain', "Roof, Ceiling & Curtain Wall") },
	{ id: 'architecture.pointCloudStatus', method: 'architecture/pointCloudStatus', part: 'architecture', title: localize('u6e.arch.pointCloudStatus', "Point Cloud Status") },
	{ id: 'architecture.ifcCheck', method: 'exports/structuralIfcCheck', part: 'architecture', title: localize('u6e.arch.ifcCheck', "Structural IFC Check") },
	{ id: 'architecture.daylight', method: 'office/daylight', part: 'architecture', title: localize('u6e.arch.daylight', "Daylight Study") },
	{ id: 'architecture.sun', method: 'office/sun', part: 'architecture', title: localize('u6e.arch.sun', "Solar Exposure") },
	{ id: 'architecture.noise', method: 'office/noise', part: 'architecture', title: localize('u6e.arch.noise', "Road Noise Study") },
	{ id: 'documents.drawingAutomation', method: 'documents/drawingAutomation', part: 'documents', title: localize('u6e.docs.drawingAutomation', "Drawing Automation Review") },
	{ id: 'documents.drawingList', method: 'drawings/list', part: 'documents', title: localize('u6e.docs.drawingList', "Drawing Inventory") },
	{ id: 'documents.sheetInventory', method: 'documents/sheetInventory', part: 'documents', title: localize('u6e.docs.sheetInventory', "Sheet Inventory") },
	{ id: 'documents.projectMetadata', method: 'documents/projectMetadata', part: 'documents', title: localize('u6e.docs.projectMetadata', "Project Metadata") },
	{ id: 'documents.clauseTraceability', method: 'documents/clauseTraceability', part: 'documents', title: localize('u6e.docs.clauseTraceability', "Clause Traceability") },
	{ id: 'documents.scheduleCategories', method: 'drawings/scheduleCategories', part: 'documents', title: localize('u6e.docs.scheduleCategories', "Schedule Categories") },
	{ id: 'documents.calculationPackage', method: 'documents/calculationPackage', part: 'documents', title: localize('u6e.docs.calculationPackage', "Calculation Package") },
	{ id: 'documents.worksheetInventory', method: 'worksheets/list', part: 'documents', title: localize('u6e.docs.worksheetInventory', "Worksheet Inventory") },
	{ id: 'studies.daylightSolar', method: 'studies/daylightSolar', part: 'studies', title: localize('u6e.studies.daylightSolar', "Daylight & Solar Study") },
	{ id: 'studies.noiseStudy', method: 'studies/noiseStudy', part: 'studies', title: localize('u6e.studies.noiseStudy', "Noise Study") },
	{ id: 'studies.phasingSummary', method: 'studies/phasingSummary', part: 'studies', title: localize('u6e.studies.phasingSummary', "Phasing Summary") },
	{ id: 'studies.plotPlanning', method: 'studies/plotPlanning', part: 'studies', title: localize('u6e.studies.plotPlanning', "Plot Planning") },
	{ id: 'studies.specialStructures', method: 'studies/specialStructures', part: 'studies', title: localize('u6e.studies.specialStructures', "Special Structures") },
	{ id: 'studies.batchCheck', method: 'studies/batchCheck', part: 'studies', title: localize('u6e.studies.batchCheck', "Batch Check") },
	{ id: 'studies.verificationStatus', method: 'studies/verificationStatus', part: 'studies', title: localize('u6e.studies.verificationStatus', "Verification Status") },
	{ id: 'studies.verificationCases', method: 'verification/cases', part: 'studies', title: localize('u6e.studies.verificationCases', "Verification Cases") },
	{ id: 'studies.verificationRun', method: 'verification/run', part: 'studies', title: localize('u6e.studies.verificationRun', "Verification Run"), autoRun: false },
	{ id: 'studies.terrain', method: 'office/terrainMesh', part: 'studies', title: localize('u6e.studies.terrain', "Terrain Mesh") },
	{ id: 'exports.formatMatrix', method: 'exports/formatMatrix', part: 'output', title: localize('u6e.exports.formatMatrix', "Export Format Matrix") },
	{ id: 'exports.fabricationPreview', method: 'exports/fabricationPreview', part: 'output', title: localize('u6e.exports.fabricationPreview', "Fabrication Preview") },
	{ id: 'exports.structuralIfcCheck', method: 'exports/structuralIfcCheck', part: 'output', title: localize('u6e.exports.structuralIfcCheck', "Structural IFC Check") },
	{ id: 'exports.archiveInspection', method: 'exports/archiveInspection', part: 'output', title: localize('u6e.exports.archiveInspection', "Archive Inspection") },
	{ id: 'exports.bbsReconciliation', method: 'exports/bbsReconciliation', part: 'output', title: localize('u6e.exports.bbsReconciliation', "Bar Schedule Reconciliation") },
];

for (const panel of panels) {
	registerU6ePanel(panel);
}
