/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { dirname, joinPath } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';

/*
 * Soil-structure interaction in the FEM editor: when the analysis model stands on soil springs
 * (`08 FEM/ssi.json`, Project Settings → Analysis → Column supports), the properties panel shows
 * the springs and, once compared, the fixed-base model against the soil-spring one (periods,
 * base shear, storey drifts; `08 FEM/ssi-compare.json`).
 */

/** Desktop command deriving and running the fixed-base model and comparing it (`saengine.fem.ssi_compare`). */
export const SSI_COMPARE_COMMAND = 'saengine.fem.ssiCompare';
/** The springs beside the model (`saengine.fem.ssi.SsiResult.to_json`). */
export const SSI_SPRINGS_FILE = 'ssi.json';
/** The last comparison beside the model. */
export const SSI_COMPARE_FILE = 'ssi-compare.json';
/** The soil-spring model's results folder and the manifest its runs write last. */
const RESULTS_FOLDER = 'model.results';
const RESULTS_MANIFEST = 'manifest.json';

/**
 * Whether a comparison written at `compared` (modified time, ms) is out of date: the model or its
 * results are newer (derived or run again since), or one of them is missing. The Python side
 * (`saengine.fem.ssi_compare.comparison_stale`) applies the same test for the report.
 */
export function comparisonStale(compared: number | undefined, model: number | undefined, results: number | undefined): boolean {
	return compared === undefined || model === undefined || results === undefined || model > compared || results > compared;
}

/** One foundation's springs, in kN/m and kN·m/rad. */
export interface ISsiSpring {
	readonly foundation: string;
	readonly type: string;
	readonly columns: readonly string[];
	readonly k: readonly number[];
}

export interface ISsiSprings {
	readonly springs: readonly ISsiSpring[];
	readonly shearModulusRatio?: number;
	readonly fixedColumns: readonly string[];
	readonly notes: readonly string[];
}

export interface ISsiComparison extends ISsiSprings {
	readonly periods: readonly { readonly mode: number; readonly fixed: number; readonly ssi: number; readonly ratio: number }[];
	/** kN. */
	readonly baseShear: readonly { readonly case: string; readonly fixed: number; readonly ssi: number }[];
	/** Largest storey drift ratio of each lateral case. */
	readonly drift: readonly { readonly case: string; readonly fixed: number; readonly ssi: number }[];
	/** Every storey's drift ratio (level in m). */
	readonly storeyDrift: readonly { readonly case: string; readonly level: number; readonly fixed: number; readonly ssi: number }[];
	readonly computed?: string;
}

type JsonRecord = { readonly [key: string]: unknown };

function isRecord(value: unknown): value is JsonRecord {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function records(value: unknown): JsonRecord[] {
	return Array.isArray(value) ? value.filter(isRecord) : [];
}

function num(value: unknown): number {
	return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function strings(value: unknown): string[] {
	return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

const DOFS = ['Kx', 'Ky', 'Kz', 'Krx', 'Kry', 'Krz'] as const;

/** The springs of `ssi.json` (or of a comparison), read defensively. */
export function readSsiSprings(raw: unknown): ISsiSprings | undefined {
	if (!isRecord(raw) || !Array.isArray(raw.springs)) {
		return undefined;
	}
	return {
		springs: records(raw.springs).map(s => ({
			foundation: String(s.foundation ?? ''),
			type: String(s.type ?? ''),
			columns: strings(s.columns),
			k: DOFS.map(name => num(s[name])),
		})),
		shearModulusRatio: typeof raw.shearModulusRatio === 'number' ? raw.shearModulusRatio : undefined,
		fixedColumns: strings(raw.fixedColumns),
		notes: strings(raw.notes),
	};
}

/** A comparison of `saengine.fem.ssiCompare` (or `ssi-compare.json`), read defensively. */
export function readSsiComparison(raw: unknown): ISsiComparison | undefined {
	const springs = readSsiSprings(raw);
	if (!springs || !isRecord(raw) || !Array.isArray(raw.periods)) {
		return undefined;
	}
	return {
		...springs,
		periods: records(raw.periods).map(p => ({ mode: num(p.mode), fixed: num(p.fixed), ssi: num(p.ssi), ratio: num(p.ratio) })),
		baseShear: records(raw.baseShear).map(b => ({ case: String(b.case ?? ''), fixed: num(b.fixed), ssi: num(b.ssi) })),
		drift: records(raw.drift).map(d => ({ case: String(d.case ?? ''), fixed: num(d.fixed), ssi: num(d.ssi) })),
		storeyDrift: records(raw.storeyDrift).map(d => ({ case: String(d.case ?? ''), level: num(d.level), fixed: num(d.fixed), ssi: num(d.ssi) })),
		computed: typeof raw.computed === 'string' ? raw.computed : undefined,
	};
}

/** A drift ratio as engineers write it: "1/4950" (0 as "0"). */
export function formatDrift(ratio: number): string {
	const value = Math.abs(ratio);
	return value > 0 ? `1/${Math.round(1 / value)}` : '0';
}

/** A spring stiffness [kN/m or kN·m/rad] in a few significant figures: "1.23e+5". */
export function formatStiffness(value: number): string {
	return value >= 1e4 ? value.toExponential(2) : value.toFixed(0);
}

/** One table of the panel: a header row and value rows. */
function table(container: HTMLElement, head: readonly string[], rows: readonly (readonly string[])[], className = ''): void {
	const element = append(container, $(`table.fem-ssi-table${className ? `.${className}` : ''}`));
	const header = append(append(element, $('thead')), $('tr'));
	for (const cell of head) {
		append(header, $('th', undefined, cell));
	}
	const body = append(element, $('tbody'));
	for (const row of rows) {
		const tr = append(body, $('tr'));
		for (const cell of row) {
			append(tr, $('td', undefined, cell));
		}
	}
}

/**
 * The soil springs' part of the FEM editor's properties panel: follows the model's `ssi.json` and
 * `ssi-compare.json`, and runs the comparison on request.
 */
export class FemSsiPanel extends Disposable {

	private readonly watch = this._register(new DisposableStore());
	private readonly buttons = this._register(new DisposableStore());
	private resource: URI | undefined;
	private springs: ISsiSprings | undefined;
	private comparison: ISsiComparison | undefined;
	/** The comparison is older than the model or its results. */
	private stale = false;
	private comparing = false;
	private problem: string | undefined;
	private token = 0;

	constructor(
		private readonly onDidChange: () => void,
		private readonly commandService: ICommandService,
		private readonly fileService: IFileService,
		/** The project folder the model belongs to, for the comparison command. */
		private readonly projectRoot: (model: URI) => URI | undefined,
	) {
		super();
	}

	/** The model is on soil springs. */
	get applies(): boolean {
		return !!this.springs;
	}

	setResource(resource: URI | undefined): void {
		if (resource?.toString() === this.resource?.toString()) {
			return;
		}
		this.resource = resource;
		this.watch.clear();
		this.springs = undefined;
		this.comparison = undefined;
		this.stale = false;
		this.problem = undefined;
		this.token++;
		if (resource) {
			const folder = dirname(resource);
			const results = joinPath(folder, RESULTS_FOLDER);
			const watcher = this.fileService.createWatcher(folder, { recursive: false, excludes: [] });
			this.watch.add(watcher);
			this.watch.add(watcher.onDidChange(e => {
				if (e.contains(joinPath(folder, SSI_SPRINGS_FILE)) || e.contains(joinPath(folder, SSI_COMPARE_FILE)) || e.contains(resource) || e.contains(results)) {
					void this.load();
				}
			}));
			// The results' manifest, to tell when the comparison is older than the last run.
			const resultsWatcher = this.fileService.createWatcher(results, { recursive: false, excludes: [] });
			this.watch.add(resultsWatcher);
			this.watch.add(resultsWatcher.onDidChange(e => {
				if (e.contains(joinPath(results, RESULTS_MANIFEST))) {
					void this.load();
				}
			}));
			void this.load();
		}
	}

	private async modified(resource: URI): Promise<number | undefined> {
		try {
			return (await this.fileService.stat(resource)).mtime;
		} catch {
			return undefined;
		}
	}

	private async read(name: string): Promise<unknown> {
		if (!this.resource) {
			return undefined;
		}
		try {
			return JSON.parse((await this.fileService.readFile(joinPath(dirname(this.resource), name))).value.toString());
		} catch {
			return undefined;
		}
	}

	private async load(): Promise<void> {
		const token = ++this.token;
		const resource = this.resource;
		if (!resource) {
			return;
		}
		const folder = dirname(resource);
		const [springs, comparison, compared, model, results] = await Promise.all([
			this.read(SSI_SPRINGS_FILE), this.read(SSI_COMPARE_FILE),
			this.modified(joinPath(folder, SSI_COMPARE_FILE)), this.modified(resource), this.modified(joinPath(folder, RESULTS_FOLDER, RESULTS_MANIFEST)),
		]);
		if (token !== this.token) {
			return;
		}
		this.springs = readSsiSprings(springs);
		this.comparison = this.springs ? readSsiComparison(comparison) : undefined;
		this.stale = !!this.comparison && comparisonStale(compared, model, results);
		this.onDidChange();
	}

	/** Derives and runs the fixed-base model and compares it with the soil-spring run. */
	async compare(): Promise<void> {
		const root = this.resource && this.projectRoot(this.resource);
		if (!root || this.comparing) {
			return;
		}
		this.comparing = true;
		this.problem = undefined;
		this.onDidChange();
		try {
			const result = readSsiComparison(await this.commandService.executeCommand<unknown>(SSI_COMPARE_COMMAND, { projectRoot: root.fsPath }));
			if (result) {
				this.comparison = result;
				this.stale = false;
			} else {
				this.problem = localize('femSsi.unavailable', "The comparison is not available.");
			}
		} catch (error) {
			const text = error instanceof Error ? error.message : String(error);
			this.problem = localize('femSsi.failed', "The comparison failed: {0}", text.split(/\r?\n/)[0]);
		} finally {
			this.comparing = false;
			this.onDidChange();
		}
	}

	/** The section of the properties panel; nothing when the model is on fixed supports. */
	render(container: HTMLElement): void {
		this.buttons.clear();
		const springs = this.springs;
		if (!springs) {
			return;
		}
		const section = append(container, $('.fem-ssi'));
		append(section, $('.sa-props-heading', undefined, localize('femSsi.heading', "Soil Springs")));
		const comparison = this.comparison;
		if (comparison?.periods.length) {
			if (this.stale) {
				append(section, $('.sa-props-note.fem-ssi-problem', undefined, localize('femSsi.stale', "This comparison is older than the analysis model or its results: Compare Again to bring it up to date.")));
			}
			append(section, $('.fem-ssi-caption', undefined, localize('femSsi.periodsCaption', "Periods, fixed base and on soil springs")));
			table(section, [localize('femSsi.mode', "Mode"), localize('femSsi.fixed', "Fixed"), localize('femSsi.ssi', "Springs"), localize('femSsi.ratio', "T̃/T")],
				comparison.periods.slice(0, 6).map(p => [String(p.mode), localize('femSsi.seconds', "{0} s", p.fixed.toFixed(3)), localize('femSsi.seconds', "{0} s", p.ssi.toFixed(3)), p.ratio.toFixed(3)]));
			if (comparison.baseShear.length) {
				append(section, $('.fem-ssi-caption', undefined, localize('femSsi.shearCaption', "Base shear of the static cases")));
				table(section, [localize('femSsi.case', "Case"), localize('femSsi.fixed', "Fixed"), localize('femSsi.ssi', "Springs")],
					comparison.baseShear.map(b => [b.case, localize('femSsi.kN', "{0} kN", b.fixed.toFixed(1)), localize('femSsi.kN', "{0} kN", b.ssi.toFixed(1))]));
			}
			if (comparison.storeyDrift.length) {
				append(section, $('.fem-ssi-caption', undefined, localize('femSsi.driftCaption', "Storey drift ratios")));
				table(section, [localize('femSsi.case', "Case"), localize('femSsi.level', "Level"), localize('femSsi.fixed', "Fixed"), localize('femSsi.ssi', "Springs")],
					comparison.storeyDrift.map(d => [d.case, localize('femSsi.metres', "{0} m", d.level.toFixed(2)), formatDrift(d.fixed), formatDrift(d.ssi)]));
			}
			append(section, $('.sa-props-note', undefined, localize('femSsi.designNote', "The foundations of 9 Substructure are designed from the fixed-base run; the members from the run on springs.")));
		} else {
			append(section, $('.sa-props-note', undefined, localize('femSsi.notCompared', "Compare with a fixed-base run of the same model: periods, base shear and storey drifts.")));
		}
		if (this.problem) {
			append(section, $('.sa-props-note.fem-ssi-problem', undefined, this.problem));
		}
		const button = this.buttons.add(new Button(append(section, $('.fem-ssi-actions')), { ...defaultButtonStyles, secondary: !!comparison && !this.stale }));
		button.label = this.comparing
			? localize('femSsi.comparing', "Running the Fixed-Base Model...")
			: comparison ? localize('femSsi.compareAgain', "Compare Again") : localize('femSsi.compare', "Compare with Fixed Base");
		button.enabled = !this.comparing;
		this.buttons.add(button.onDidClick(() => void this.compare()));

		append(section, $('.fem-ssi-caption', undefined, springs.shearModulusRatio !== undefined
			? localize('femSsi.springsCaptionRatio', "Springs (kN/m, kN·m/rad), G/G0 = {0}", springs.shearModulusRatio.toFixed(2))
			: localize('femSsi.springsCaption', "Springs (kN/m, kN·m/rad)")));
		table(section, [localize('femSsi.foundation', "Foundation"), ...DOFS],
			springs.springs.map(s => [`${s.foundation} (${s.columns.join(', ')})`, ...s.k.map(formatStiffness)]), 'springs');
		if (springs.fixedColumns.length) {
			append(section, $('.sa-props-note', undefined, localize('femSsi.fixedColumns', "Fixed: {0}.", springs.fixedColumns.join(', '))));
		}
	}
}
