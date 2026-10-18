/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { dirname, isEqual, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { mepModelStamp, sourceStamp } from '../../../services/saengineProject/common/partSources.js';
import { ISaengineProjectService, PROJECT_PARTS } from '../../../services/saengineProject/common/saengineProject.js';

/** Desktop command deriving the analysis model with the Python models (see `saengine.fem.derive`). */
const DERIVE_COMMAND = 'saengine.fem.derive';

/** The parts the analysis model is derived from, with the names the derivation records them under. */
export const DERIVATION_SOURCES: readonly { readonly part: string; readonly key: string; readonly label: string }[] = [
	{ part: 'bim', key: 'bim', label: localize('fem.source.bim', "Building Model") },
	{ part: 'settings', key: 'settings', label: localize('fem.source.settings', "Project Settings") },
	{ part: 'objects', key: 'objects', label: localize('fem.source.objects', "Object Types") },
	{ part: 'materials', key: 'materials', label: localize('fem.source.materials', "Materials") },
];

/**
 * The soil report, a source only of a model whose site class may come from it: the derivation
 * records its stamp (key `soil`) whenever the settings take the site class from the soil report,
 * so adding or changing boreholes later makes the model out of date.
 */
export const SOIL_DERIVATION_SOURCE = { part: 'soil', key: 'soil', label: localize('fem.source.soil', "Soil Report") } as const;

/**
 * Sources a model has only when they give it something: 7 MEP once it has equipment, openings or
 * shafts (their loads and holes), 9 Substructure when the column supports are soil springs (the
 * foundations). The derivation records their stamps then (keys `mep`, `substructure`).
 */
export const MEP_DERIVATION_SOURCE = { part: 'mep', key: 'mep', label: localize('fem.source.mep', "MEP") } as const;
export const SUBSTRUCTURE_DERIVATION_SOURCE = { part: 'substructure', key: 'substructure', label: localize('fem.source.substructure', "Substructure") } as const;

/** Every part the derivation may read: the sources above, the soil report, MEP and the substructure. */
export const DERIVATION_INPUTS: readonly string[] = [...DERIVATION_SOURCES.map(s => s.part), SOIL_DERIVATION_SOURCE.part, MEP_DERIVATION_SOURCE.part, SUBSTRUCTURE_DERIVATION_SOURCE.part];

interface IFemDerivation {
	readonly text?: string;
	readonly pushoverText?: string;
	readonly thermalText?: string;
	readonly ssiText?: string;
	readonly notes?: readonly string[];
	readonly summary?: { readonly [key: string]: number };
	readonly problems?: readonly string[];
}

/** The pushover model, derived beside the analysis model when the settings ask for pushovers. */
export const PUSHOVER_FILE = 'pushover.osmodel';
/** The temperature case's fixed-end forces, beside the model when the settings have the case T (`saengine.fem.thermal`). */
export const THERMAL_FILE = 'thermal.json';
/** The column bases' soil springs, beside the model when the supports are soil springs (`saengine.fem.ssi`). */
export const SSI_FILE = 'ssi.json';

/** Whether the MEP file `text` has anything the analysis model takes: equipment, openings or shafts. */
export function mepHasContent(text: string | undefined): boolean {
	try {
		const value = text ? JSON.parse(text) : undefined;
		const listed = (list: unknown) => Array.isArray(list) && list.length > 0;
		return typeof value === 'object' && value !== null && (['equipment', 'openings', 'shafts'].some(key => listed(value[key]))
			// The HVAC plant and the electrical equipment load the model as equipment too.
			|| listed(value.hvac?.plant) || listed(value.electrical?.equipment));
	} catch {
		return false;
	}
}

/** The main file of project part `id` (`08 FEM/model.osmodel`, ...). */
export function partFile(root: URI, id: string): URI {
	const part = PROJECT_PARTS.find(p => p.id === id)!;
	return joinPath(root, part.folder, part.mainFile!);
}

/** The source stamps recorded in a derived model's description ("Sources: bim=…; settings=…"). */
export function recordedSources(description: unknown): Map<string, string> {
	const sources = new Map<string, string>();
	const match = typeof description === 'string' ? /Sources: (?<list>.*)$/.exec(description) : null;
	for (const entry of match?.groups?.list.split(';') ?? []) {
		const [key, value] = entry.trim().split('=');
		if (key && value) {
			sources.set(key, value);
		}
	}
	return sources;
}

/** Whether the analysis model was derived, and from which sources it is out of date. */
export interface IFemDerivationState {
	/** The model records the sources it was derived from. */
	readonly derived: boolean;
	/** Labels of the sources changed since (a source whose text is unknown counts as changed). */
	readonly changed: readonly string[];
}

/** The derivation state of a model with `description`, given the current text of each source part. */
export function derivationState(description: unknown, texts: ReadonlyMap<string, string | undefined>): IFemDerivationState {
	const recorded = recordedSources(description);
	const changed = DERIVATION_SOURCES.filter(({ part, key }) => {
		const text = texts.get(part);
		return text === undefined || recorded.get(key) !== sourceStamp(text);
	}).map(c => c.label);
	// The soil report and the substructure count only when the model recorded them (its site
	// class could come from the soil report; soil springs stand on the substructure's foundations).
	for (const source of [SOIL_DERIVATION_SOURCE, SUBSTRUCTURE_DERIVATION_SOURCE]) {
		if (recorded.has(source.key)) {
			const text = texts.get(source.part);
			if (text === undefined || recorded.get(source.key) !== sourceStamp(text)) {
				changed.push(source.label);
			}
		}
	}
	// MEP counts once recorded, and once it has something for a model derived without it.
	const mep = MEP_DERIVATION_SOURCE;
	const mepText = texts.get(mep.part);
	if (recorded.has(mep.key) ? mepText === undefined || recorded.get(mep.key) !== mepModelStamp(mepText) : recorded.size > 0 && mepHasContent(mepText)) {
		changed.push(mep.label);
	}
	return { derived: recorded.size > 0, changed };
}

/** What deriving the analysis model gave: facts to show, notes to heed, or why it failed. */
export interface IFemDeriveOutcome {
	readonly ok: boolean;
	/** "Derived 120 nodes and 80 elements; base shear ..." (ok), or the problems (not ok). */
	readonly message: string;
	readonly notes: readonly string[];
}

/**
 * Derives the project's analysis model (and its pushover model) from the current texts of the
 * source parts and writes them to `08 FEM`. Shared by the FEM editor and Run All.
 */
export async function deriveAnalysisModel(commandService: ICommandService, fileService: IFileService, root: URI, texts: ReadonlyMap<string, string | undefined>): Promise<IFemDeriveOutcome> {
	const resource = partFile(root, 'fem');
	const [bimText, settingsText, objectsText, materialsText] = DERIVATION_SOURCES.map(s => texts.get(s.part));
	if (bimText === undefined || settingsText === undefined || objectsText === undefined || materialsText === undefined) {
		const missing = DERIVATION_SOURCES.filter(s => texts.get(s.part) === undefined).map(s => s.label);
		return { ok: false, message: localize('fem.deriveMissing', "{0} could not be read.", missing.join(', ')), notes: [] };
	}
	// The soil report's text from the caller, so the site class comes from the same text as the
	// state check; without it the backend reads `01 Soil Report` beside the model folder.
	const soilText = texts.get(SOIL_DERIVATION_SOURCE.part);
	const mepText = texts.get(MEP_DERIVATION_SOURCE.part);
	const substructureText = texts.get(SUBSTRUCTURE_DERIVATION_SOURCE.part);
	const result = await commandService.executeCommand<IFemDerivation>(DERIVE_COMMAND, {
		bimText, objectsText, materialsText, settingsText, modelFolder: dirname(resource).fsPath,
		...(soilText !== undefined ? { soilText } : {}),
		...(mepText !== undefined ? { mepText } : {}),
		...(substructureText !== undefined ? { substructureText } : {}),
	});
	if (!result?.text) {
		return { ok: false, message: (result?.problems ?? []).join('; '), notes: [] };
	}
	// Both models are derived together, whichever of them is open; the side files of the
	// temperature case and the soil springs are written with them, or removed.
	const folder = dirname(resource);
	const side = async (name: string, text: string | undefined) => {
		const file = joinPath(folder, name);
		if (text !== undefined) {
			await fileService.writeFile(file, VSBuffer.fromString(text));
		} else if (await fileService.exists(file)) {
			await fileService.del(file);
		}
	};
	await side(THERMAL_FILE, result.thermalText);
	await side(SSI_FILE, result.ssiText);
	await fileService.writeFile(resource, VSBuffer.fromString(result.text));
	if (result.pushoverText) {
		await fileService.writeFile(joinPath(folder, PUSHOVER_FILE), VSBuffer.fromString(result.pushoverText));
	}
	const summary = result.summary ?? {};
	return {
		ok: true,
		message: localize('fem.derived', "Derived {0} nodes and {1} elements; base shear {2} kN, seismic weight {3} kN.",
			summary.nodes ?? 0, summary.elements ?? 0, (summary.base_shear_kN ?? 0).toFixed(1), (summary.weight_kN ?? 0).toFixed(1)),
		notes: result.notes ?? [],
	};
}

/**
 * Where the project's analysis model (`08 FEM/model.osmodel`, and its pushover model
 * `pushover.osmodel`) comes from: whether its sources have changed since it was derived, and
 * deriving it again. The analysis model is never edited by hand: it is derived again on request.
 * The FEM editor shows this state in its toolbar ("Out of date" and Derive).
 */
export class FemDerivation extends Disposable {

	private readonly store = this._register(new DisposableStore());
	private readonly models = new Map<string, ITextModel>();
	private description: unknown;
	private resource: URI | undefined;
	private requested: URI | undefined;
	private _deriving = false;

	constructor(
		/** Called whenever the state changed (sources edited, derivation started or finished). */
		private readonly onDidChange: () => void,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
	) {
		super();
		// Editors restore before the project is detected: look again once it is.
		this._register(this.projectService.onDidChangeProject(() => void this.setResource(this.requested)));
	}

	/** Whether `resource` is the project's analysis model (or its pushover model). */
	get applies(): boolean {
		return !!this.resource;
	}

	get deriving(): boolean {
		return this._deriving;
	}

	/** The state, when the open file is the project's analysis model. */
	get state(): IFemDerivationState | undefined {
		if (!this.resource) {
			return undefined;
		}
		return derivationState(this.description, this.texts());
	}

	/** The current text of each derivation input (unsaved edits included). */
	private texts(): Map<string, string | undefined> {
		return new Map(DERIVATION_INPUTS.map(part => [part, this.models.get(part)?.getValue()]));
	}

	/** Follows the sources of `resource` when it is the project's analysis model. */
	async setResource(resource: URI | undefined): Promise<void> {
		this.requested = resource;
		this.store.clear();
		this.models.clear();
		const root = this.projectService.project?.root;
		const model = root && partFile(root, 'fem');
		this.resource = model && resource && (isEqual(resource, model) || isEqual(resource, joinPath(dirname(model), PUSHOVER_FILE))) ? resource : undefined;
		if (root && this.resource) {
			for (const part of DERIVATION_INPUTS) {
				try {
					const reference = await this.textModelService.createModelReference(partFile(root, part));
					this.store.add(reference);
					const source = reference.object.textEditorModel;
					this.models.set(part, source);
					this.store.add(source.onDidChangeContent(() => this.onDidChange()));
				} catch {
					// A missing part file shows as changed until it is restored.
				}
			}
		}
		this.onDidChange();
	}

	/** The model's description, holding the stamps of the sources it was derived from. */
	setDescription(description: unknown): void {
		this.description = description;
		this.onDidChange();
	}

	/** Derives the analysis model again from the current sources (unsaved edits included). */
	async derive(): Promise<IFemDeriveOutcome | undefined> {
		const root = this.projectService.project?.root;
		if (!root || !this.resource || this._deriving) {
			return undefined;
		}
		this._deriving = true;
		this.onDidChange();
		try {
			return await deriveAnalysisModel(this.commandService, this.fileService, root, this.texts());
		} catch (error) {
			return { ok: false, message: String(error), notes: [] };
		} finally {
			this._deriving = false;
			this.onDidChange();
		}
	}
}
