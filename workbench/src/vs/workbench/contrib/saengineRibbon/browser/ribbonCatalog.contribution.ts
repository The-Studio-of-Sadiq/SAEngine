/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * The ribbon catalog (owner, 2026-11-23: "do the visual properly"): every window and sub-window
 * gets the full set of tabs, groups and buttons an engineer expects. A button whose feature is
 * built (saengine.features) opens its input panel and runs it through `features/run`; the
 * others open a planned-feature page that says what the button will do. The data is generated
 * from scripts/ribbon/ribbon_catalog.json and features.json (ribbonCatalog.generated.ts).
 */

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { MenuRegistry } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { userPatterns } from '../../../services/saengineProject/common/loadPatterns.js';
import { joinPath } from '../../../../base/common/resources.js';
import { openEngineDataPanel } from '../../saengineProject/browser/engineDataPanelInput.js';
import { DataPanelRow, DataPanelValues, IDataPanelContext, IDataPanelFieldOption, IDataPanelResult, IDataPanelTable, registerEngineDataPanel } from '../../saengineProject/browser/engineDataPanelRegistry.js';
import { OPEN_PLANNED_FEATURE_COMMAND } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { CATALOG_GROUPS, ICatalogButton } from './ribbonCatalog.generated.js';
import { registerRibbonGroupLabel, registerRibbonItemHint, RIBBON_TABS } from './ribbonRegistry.js';

const CODICONS = Codicon as unknown as Readonly<Record<string, ThemeIcon | undefined>>;
const CATALOG_PREFIX = 'saengine.catalog.';

/** What `features/run` returns (saengine.features.result). */
interface IFeatureRunResult {
	readonly summary?: { readonly [key: string]: string | number | boolean | null };
	readonly tables?: readonly { readonly title: string; readonly columns: readonly { readonly key: string; readonly title: string }[]; readonly rows: readonly DataPanelRow[] }[];
	readonly notes?: readonly string[];
	readonly problems?: readonly string[];
	/** Files the feature wrote (an absolute path each), such as a strip view (#285). */
	readonly outputFiles?: readonly { readonly label: string; readonly path: string }[];
}

/** "loadKpa" -> "Load Kpa": a summary key as a label. */
function humanize(key: string): string {
	const words = key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ');
	return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatValue(value: string | number | boolean | null): string {
	if (value === null) {
		return '–';
	}
	if (typeof value === 'boolean') {
		return value ? localize('ribbonCatalog.yes', "Yes") : localize('ribbonCatalog.no', "No");
	}
	return typeof value === 'number' && !Number.isInteger(value) ? String(Number(value.toFixed(3))) : String(value);
}

function toPanelResult(raw: IFeatureRunResult): IDataPanelResult {
	const tables: IDataPanelTable[] = (raw.tables ?? []).map((table, index) => ({
		id: `t${index}`,
		title: table.title,
		columns: table.columns.map(column => ({ key: column.key, title: column.title })),
		rows: table.rows,
	}));
	return {
		metrics: Object.entries(raw.summary ?? {}).map(([key, value]) => ({ label: humanize(key), value: formatValue(value) })),
		tables,
		notes: raw.notes,
		problems: raw.problems,
		outputFiles: raw.outputFiles,
	};
}

/** A field that picks one of the built-in load cases (its options hold SD and Lr). */
function isCaseField(field: { readonly type: string; readonly options?: readonly { readonly value: string }[] }): boolean {
	return field.type === 'select' && !!field.options?.some(o => o.value === 'SD') && !!field.options.some(o => o.value === 'Lr');
}

/** Issue #301: the case pickers also offer the project's own load patterns (as saved). */
async function withProjectPatterns(context: IDataPanelContext, fields: readonly { readonly key: string; readonly type: string; readonly options?: readonly IDataPanelFieldOption[] }[]) {
	const root = context.project?.root;
	if (!root) {
		return undefined;
	}
	let patterns;
	try {
		patterns = userPatterns(JSON.parse((await context.fileService.readFile(joinPath(root, '02 Project Settings', 'project-settings.json'))).value.toString()));
	} catch {
		return undefined;
	}
	if (!patterns.length) {
		return undefined;
	}
	const options: { [key: string]: readonly IDataPanelFieldOption[] } = {};
	for (const field of fields) {
		if (isCaseField(field)) {
			options[field.key] = [...field.options!, ...patterns.map(p => ({ value: p.id, label: `${p.id}: ${p.name}` }))];
		}
	}
	return { options };
}

function registerFeaturePanel(button: ICatalogButton, part: string): void {
	const feature = button.feature!;
	const featureId = button.id.slice(CATALOG_PREFIX.length);
	const caseFields = feature.fields.some(isCaseField);
	registerEngineDataPanel({
		id: button.id,
		title: button.label,
		part,
		help: feature.help,
		icon: CODICONS[button.icon],
		fields: feature.fields.map(field => ({
			key: field.key,
			label: field.label,
			type: field.type,
			defaultValue: field.defaultValue,
			options: field.options,
			min: field.min,
			max: field.max,
			help: field.help,
		})),
		loadInitial: caseFields ? context => withProjectPatterns(context, feature.fields) : undefined,
		run: async (context, values: DataPanelValues) => toPanelResult(await context.engineRequest<IFeatureRunResult>('features/run', {
			id: featureId,
			projectRoot: context.project?.root.fsPath,
			values,
		})),
	});
	CommandsRegistry.registerCommand(button.id, accessor => openEngineDataPanel(accessor.get(IEditorService), button.id));
}

for (const group of CATALOG_GROUPS) {
	const tab = RIBBON_TABS.find(t => t.id === group.tab);
	if (!tab) {
		continue;
	}
	registerRibbonGroupLabel(group.key, group.label);
	group.buttons.forEach((button, index) => {
		if (button.feature) {
			registerFeaturePanel(button, group.part);
		} else if (button.planned) {
			const featureId = button.id.slice(CATALOG_PREFIX.length);
			registerPlannedFeature({ id: featureId, part: group.part, title: button.label, summary: button.description });
			CommandsRegistry.registerCommand(button.id, accessor => accessor.get(ICommandService).executeCommand(OPEN_PLANNED_FEATURE_COMMAND, featureId));
		}
		MenuRegistry.appendMenuItem(tab.menuId, {
			group: group.group,
			order: index + 1,
			command: {
				id: button.id,
				title: button.label,
				tooltip: button.description,
				icon: CODICONS[button.icon] ?? Codicon.circleOutline,
			},
		});
		registerRibbonItemHint(button.id, { size: button.size, label: button.label }, tab.menuId);
	});
}
