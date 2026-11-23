/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * The ribbon catalog (owner, 2026-11-23: "do the visual properly"): every window and sub-window
 * gets the full set of tabs, groups and buttons an engineer expects. A button whose feature
 * exists runs it; the others open a planned-feature page that says what the button will do.
 * The data is generated from scripts/ribbon/ribbon_catalog.json (ribbonCatalog.generated.ts).
 */

import { Codicon } from '../../../../base/common/codicons.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { MenuRegistry } from '../../../../platform/actions/common/actions.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { OPEN_PLANNED_FEATURE_COMMAND } from '../../saengineProject/browser/plannedFeatureEditor.js';
import { CATALOG_GROUPS } from './ribbonCatalog.generated.js';
import { registerRibbonGroupLabel, registerRibbonItemHint, RIBBON_TABS } from './ribbonRegistry.js';

const CODICONS = Codicon as unknown as Readonly<Record<string, ThemeIcon | undefined>>;
const PLANNED_PREFIX = 'saengine.catalog.';

for (const group of CATALOG_GROUPS) {
	const tab = RIBBON_TABS.find(t => t.id === group.tab);
	if (!tab) {
		continue;
	}
	registerRibbonGroupLabel(group.key, group.label);
	group.buttons.forEach((button, index) => {
		if (button.planned) {
			const featureId = button.id.slice(PLANNED_PREFIX.length);
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
