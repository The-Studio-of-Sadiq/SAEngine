/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { PROJECT_MENU } from '../../saengineProject/browser/projectMenu.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { PACKAGES_SHOW_COMMAND } from '../common/packageIndex.js';
import { PLANNED_CODE_PACK_EUROCODES, PLANNED_CODE_PACK_US } from '../common/plannedCodePacks.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { CodePacksEditor, IInstallCodePackArgs, INewCodePackArgs, IShowPackagesArgs } from './codePacksEditor.js';
import { CodePacksEditorInput, CodePacksEditorInputSerializer } from './codePacksEditorInput.js';
import { activeCodeName } from '../../../services/saengineProject/common/activeCodePack.js';

const category = localize2('saengine.category', "SAEngine");

Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(CodePacksEditor, CodePacksEditor.ID, localize('saengineCodePacksEditor', "SAEngine Packages")),
	[new SyncDescriptor(CodePacksEditorInput)]
);
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(CodePacksEditorInput.ID, CodePacksEditorInputSerializer);

async function openPage(accessor: ServicesAccessor): Promise<CodePacksEditor | undefined> {
	const pane = await accessor.get(IEditorService).openEditor(CodePacksEditorInput.instance, { pinned: true });
	return pane instanceof CodePacksEditor ? pane : undefined;
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PACKAGES_SHOW_COMMAND,
			title: localize2('saengine.packages.show', "Packages..."),
			category,
			icon: Codicon.package,
			f1: true,
			menu: { id: PROJECT_MENU, group: '1_project', order: 7 },
		});
	}

	/** `args` (optional): `{ tab: 'installed' | 'browse' | 'updates', kind }`. */
	override async run(accessor: ServicesAccessor, args?: IShowPackagesArgs): Promise<void> {
		(await openPage(accessor))?.show(args);
	}
});

// The page's earlier name: kept so links, keybindings and scripts that open Code Packs still work.
CommandsRegistry.registerCommand('saengine.codePacks.show', (accessor, args?: IShowPackagesArgs) => accessor.get(ICommandService).executeCommand(PACKAGES_SHOW_COMMAND, args));

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.codePacks.new',
			title: localize2('saengine.codePacks.new', "New Code Pack..."),
			category,
			f1: true,
		});
	}

	/** `args` (optional): `{ id, name, extends, scope }`, asked for when missing. */
	override async run(accessor: ServicesAccessor, args?: INewCodePackArgs): Promise<void> {
		await (await openPage(accessor))?.newPack(args);
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.codePacks.install',
			title: localize2('saengine.codePacks.install', "Install Package from File..."),
			category,
			f1: true,
		});
	}

	/** `args` (optional): `{ path, scope }`; without a path a folder or .zip is picked. */
	override async run(accessor: ServicesAccessor, args?: IInstallCodePackArgs): Promise<void> {
		await (await openPage(accessor))?.install(args);
	}
});

// Design codes other than BNBC 2020 are planned, not in this MVP (T42): each gets a page with its
// coverage, is listed on the Packages page and shows disabled in the New Project wizard. No
// tables, values or clause text of these codes are included.
registerPlannedFeature({
	id: PLANNED_CODE_PACK_US,
	part: 'settings',
	title: localize('codePacks.planned.us', "Code Pack: ACI 318-19 + ASCE 7-22 (US)"),
	summary: localize('codePacks.planned.usSummaryMaterials', "A design-code pack for projects designed to the US codes. Covered now, in the built-in pack aci318-asce7-22 (chosen in Project Settings or the New Project wizard): the loads of ASCE 7-22, structural concrete (ACI 318-19), structural steel (AISC 360-22, LRFD or ASD, and AISC 341-22), timber (NDS 2018, ASD or LRFD) and masonry (TMS 402-22 allowable stress and strength design); a steel moment or braced frame building can be generated. Planned: the geotechnical tables and the steel fire design (AISC 360-22 Appendix 4), which fall back to {0} or are not covered until then.", activeCodeName()),
	steps: [
		localize('codePacks.planned.us1Loads', "Choose ACI 318-19 + ASCE 7-22 as the project's design code in Project Settings or in the New Project wizard (built in: no install)."),
		localize('codePacks.planned.us2Lookup', "Enter the site's SDS, SD1, S1 and TL and the basic wind speed V from the ASCE Hazard Tool (Project Settings > Site), or look the seismic values up online by the site's coordinates from the USGS Seismic Design Web Services (opt-in: Look Up Hazard Values... in Project Settings > Site or the New Project wizard); a snow load where the site has one."),
		localize('codePacks.planned.us3', "Loads, combinations and design checks read their factors and limits from the pack instead of {0}.", activeCodeName()),
		localize('codePacks.planned.us4', "Reports cite the pack's sections; checks the pack does not cover stay marked as not covered."),
	],
	inputs: [
		{ label: localize('codePacks.planned.usRisk', "Risk category"), example: 'II' },
		{ label: localize('codePacks.planned.usSdc', "Seismic design category"), example: 'D' },
		{ label: localize('codePacks.planned.usSite', "Site class"), example: 'D' },
	],
	outputs: [
		localize('codePacks.planned.usOut1Materials', "Covered: loads and combinations (ASCE 7-22), concrete members and seismic detailing (ACI 318-19), steel members, connections and seismic systems (AISC 360-22, AISC 341-22), timber members and bolted or nailed joints (NDS 2018), masonry walls (TMS 402-22). Planned: the geotechnical tables, steel fire design"),
		localize('codePacks.planned.usOut2', "The same reports and drawings as {0}, citing ACI 318-19 and ASCE 7-22", activeCodeName()),
	],
	references: ['ACI 318-19 Building Code Requirements for Structural Concrete', 'ASCE/SEI 7-22 Minimum Design Loads and Associated Criteria for Buildings and Other Structures', 'ANSI/AISC 360-22 and 341-22', 'ANSI/AWC NDS-2018', 'TMS 402-22'],
});

registerPlannedFeature({
	id: PLANNED_CODE_PACK_EUROCODES,
	part: 'settings',
	title: localize('codePacks.planned.eurocodes', "Code Pack: Eurocodes with National Annexes"),
	summary: localize('codePacks.planned.eurocodesSummary', "The Eurocodes EN 1990 to EN 1998 as one base pack, and each country's National Annex as a small pack that extends it: the annex sets only the Nationally Determined Parameters and inherits everything else. Covered now, in the built-in pack Eurocodes (eurocodes) with the recommended values: the loads and seismic actions (EN 1990 combinations, EN 1991-1-1, -1-3, -1-4, -1-7 Annex D, EN 1998-1), the concrete design (EN 1992-1-1: members, slabs, stairs, walls, punching, slenderness, cracks and deflection, anchorage and laps; EN 1998-1 Section 5: DCM and DCH capacity design) and the geotechnical design (EN 1997-1: footings by the design approach, piles with the correlation factors). Steel and the other materials (EN 1993 to EN 1999) still come from {0}. National Annexes built in: United Kingdom (eurocodes-uk), Germany (eurocodes-de), Malaysia (eurocodes-my), Singapore (eurocodes-sg); the other countries' annexes are planned.", activeCodeName()),
	steps: [
		localize('codePacks.planned.eurocodes0', "Covered: choose Eurocodes (recommended values) in Project Settings or the New Project wizard; enter agR as Z and vb,0 as V (Location: Custom) and the terrain category."),
		localize('codePacks.planned.eurocodes1', "Covered: choose a built-in National Annex pack (UK, Germany, Malaysia, Singapore) in Project Settings or the New Project wizard; its towns give vb,0 (and agR), Site altitude and Snow zone give the altitude factor and sk where the annex has them."),
		localize('codePacks.planned.eurocodes2', "Install the National Annex pack of the country; it names the base pack in `extends`, the same mechanism a {0} office pack uses today.", activeCodeName()),
		localize('codePacks.planned.eurocodes3', "Choose the National Annex pack as the design code: its Nationally Determined Parameters override the base pack's recommended values, the rest comes from the base."),
		localize('codePacks.planned.eurocodes4', "Without a National Annex the base pack's recommended values apply, and reports say so."),
	],
	inputs: [
		{ label: localize('codePacks.planned.eurocodesAnnex', "National Annex"), example: localize('codePacks.planned.eurocodesAnnexExample', "by country") },
		{ label: localize('codePacks.planned.eurocodesConsequence', "Consequence class"), example: 'CC2' },
		{ label: localize('codePacks.planned.eurocodesDuctility', "Ductility class"), example: 'DCM' },
	],
	outputs: [
		localize('codePacks.planned.eurocodesOut1', "Coverage: actions and combinations, concrete and steel members, foundations, seismic design"),
		localize('codePacks.planned.eurocodesOut2', "Reports that name the National Annex used for every Nationally Determined Parameter"),
	],
	references: ['EN 1990 to EN 1998 (Eurocodes)', 'The National Annexes of each CEN member country'],
});

// Alpha 9 C9: the Indian Standards page left: the built-in is-codes pack covers the loads,
// concrete, foundations, steel (IS 800), masonry (IS 1905), timber (IS 883) and composite beams.
