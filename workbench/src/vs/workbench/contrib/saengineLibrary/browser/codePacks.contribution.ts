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
import { PLANNED_CODE_PACK_EUROCODES, PLANNED_CODE_PACK_INDIA, PLANNED_CODE_PACK_US } from '../common/plannedCodePacks.js';
import { registerPlannedFeature } from '../../../services/saengineProject/common/plannedFeatures.js';
import { CodePacksEditor, IInstallCodePackArgs, INewCodePackArgs, IShowPackagesArgs } from './codePacksEditor.js';
import { CodePacksEditorInput, CodePacksEditorInputSerializer } from './codePacksEditorInput.js';

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
// coverage, is listed on the Packages page and shows disabled in the New Building wizard. No
// tables, values or clause text of these codes are included.
registerPlannedFeature({
	id: PLANNED_CODE_PACK_US,
	part: 'settings',
	title: localize('codePacks.planned.us', "Code Pack: ACI 318-19 + ASCE 7-22 (US)"),
	summary: localize('codePacks.planned.usSummary', "A design-code pack for projects designed to the US codes: concrete design to ACI 318-19 with the loads and load combinations of ASCE 7-22, installed from the Packages page and chosen in Project Settings like BNBC 2020."),
	steps: [
		localize('codePacks.planned.us1', "Install the pack from the Packages page (a data package, signed and listed in the official index)."),
		localize('codePacks.planned.us2', "Choose it as the project's design code in Project Settings or in the New Building wizard."),
		localize('codePacks.planned.us3', "Loads, combinations and design checks read their factors and limits from the pack instead of BNBC 2020."),
		localize('codePacks.planned.us4', "Reports cite the pack's sections; checks the pack does not cover stay marked as not covered."),
	],
	inputs: [
		{ label: localize('codePacks.planned.usRisk', "Risk category"), example: 'II' },
		{ label: localize('codePacks.planned.usSdc', "Seismic design category"), example: 'D' },
		{ label: localize('codePacks.planned.usSite', "Site class"), example: 'D' },
	],
	outputs: [
		localize('codePacks.planned.usOut1', "Coverage: concrete members (beams, columns, slabs, walls, footings), seismic detailing, wind, seismic and gravity loads, load combinations"),
		localize('codePacks.planned.usOut2', "The same reports and drawings as BNBC 2020, citing ACI 318-19 and ASCE 7-22"),
	],
	references: ['ACI 318-19 Building Code Requirements for Structural Concrete', 'ASCE/SEI 7-22 Minimum Design Loads and Associated Criteria for Buildings and Other Structures'],
});

registerPlannedFeature({
	id: PLANNED_CODE_PACK_EUROCODES,
	part: 'settings',
	title: localize('codePacks.planned.eurocodes', "Code Pack: Eurocodes with National Annexes"),
	summary: localize('codePacks.planned.eurocodesSummary', "The Eurocodes EN 1990 to EN 1998 as one base pack, and each country's National Annex as a small pack that extends it: the annex sets only the Nationally Determined Parameters and inherits everything else."),
	steps: [
		localize('codePacks.planned.eurocodes1', "Install the Eurocodes base pack (EN 1990 basis, EN 1991 actions, EN 1992 concrete, EN 1993 steel, EN 1997 geotechnics, EN 1998 seismic)."),
		localize('codePacks.planned.eurocodes2', "Install the National Annex pack of the country; it names the base pack in `extends`, the same mechanism a BNBC office pack uses today."),
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

registerPlannedFeature({
	id: PLANNED_CODE_PACK_INDIA,
	part: 'settings',
	title: localize('codePacks.planned.india', "Code Pack: Indian Standards (IS)"),
	summary: localize('codePacks.planned.indiaSummary', "A design-code pack for projects designed to the Indian Standards: concrete to IS 456, seismic loads to IS 1893, steel to IS 800, other loads to IS 875 and ductile detailing to IS 13920."),
	steps: [
		localize('codePacks.planned.india1', "Install the pack from the Packages page."),
		localize('codePacks.planned.india2', "Choose it as the project's design code in Project Settings or in the New Building wizard."),
		localize('codePacks.planned.india3', "Loads, combinations, member design and detailing read the pack instead of BNBC 2020."),
	],
	inputs: [
		{ label: localize('codePacks.planned.indiaZone', "Seismic zone"), example: 'III' },
		{ label: localize('codePacks.planned.indiaSoil', "Soil type"), example: 'II' },
		{ label: localize('codePacks.planned.indiaImportance', "Importance factor"), example: localize('codePacks.planned.indiaImportanceExample', "by building use") },
	],
	outputs: [
		localize('codePacks.planned.indiaOut1', "Coverage: dead, live, wind and seismic loads, combinations, concrete and steel members, ductile detailing"),
		localize('codePacks.planned.indiaOut2', "The same reports and drawings as BNBC 2020, citing the IS clauses"),
	],
	references: ['IS 456:2000 Plain and Reinforced Concrete', 'IS 1893 (Part 1):2016 Earthquake Resistant Design', 'IS 800:2007 General Construction in Steel', 'IS 875 (Parts 1–5) Design Loads', 'IS 13920:2016 Ductile Design and Detailing'],
});
