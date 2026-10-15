/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { FemResultDisplay, FemResultQuantity, FemSelection, FemValueQuantity } from '@saengine/fem-viewer';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IFemResultEntry, IFemResultList, IFemResultView } from '../../../../platform/saengine/common/femSolver.js';
import { defaultButtonStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';

/** Desktop commands reading a run's results with the Python backend (see `saengine.fem.resultList`). */
const LIST_COMMAND = 'saengine.fem.resultList';
const VIEW_COMMAND = 'saengine.fem.resultView';

/** The folder a model's analysis results are written to (`model.osmodel` -> `model.results`). */
export function resultsFolder(model: URI): URI {
	return joinPath(dirname(model), `${basename(model).replace(/\.osmodel$/i, '')}.results`);
}

type Show = FemResultQuantity | 'none';

interface IShowOption {
	readonly show: Show;
	readonly label: string;
}

const MODEL_ONLY: IShowOption = { show: 'none', label: localize('femResults.modelOnly', "Model Only") };
const STATIC_OPTIONS: readonly IShowOption[] = [
	MODEL_ONLY,
	{ show: 'deformed', label: localize('femResults.deformed', "Deflected Shape") },
	{ show: 'reactions', label: localize('femResults.reactions', "Support Reactions") },
	{ show: 'N', label: localize('femResults.axial', "Axial Force N") },
	{ show: 'Vy', label: localize('femResults.shearY', "Shear Force Vy") },
	{ show: 'Vz', label: localize('femResults.shearZ', "Shear Force Vz") },
	{ show: 'T', label: localize('femResults.torsion', "Torsion T") },
	{ show: 'My', label: localize('femResults.momentY', "Moment My") },
	{ show: 'Mz', label: localize('femResults.momentZ', "Moment Mz") },
];
/** Shell section forces per unit length, offered when the model has shells. */
const SHELL_OPTIONS: readonly IShowOption[] = [
	{ show: 'M11', label: localize('femResults.m11', "Shell Moment M11") },
	{ show: 'M22', label: localize('femResults.m22', "Shell Moment M22") },
	{ show: 'M12', label: localize('femResults.m12', "Shell Twisting Moment M12") },
	{ show: 'N11', label: localize('femResults.n11', "Shell Membrane Force N11") },
	{ show: 'N22', label: localize('femResults.n22', "Shell Membrane Force N22") },
	{ show: 'N12', label: localize('femResults.n12', "Shell Membrane Shear N12") },
	{ show: 'Q13', label: localize('femResults.q13', "Shell Transverse Shear Q13") },
	{ show: 'Q23', label: localize('femResults.q23', "Shell Transverse Shear Q23") },
];
const SHELL_COMPONENTS: readonly Show[] = ['N11', 'N22', 'N12', 'M11', 'M22', 'M12', 'Q13', 'Q23'];
const MODAL_OPTIONS: readonly IShowOption[] = [
	MODEL_ONLY,
	{ show: 'deformed', label: localize('femResults.modeShape', "Mode Shape") },
];
const COMPONENTS: readonly Show[] = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'];

/** Steps of the scale multiplier offered by the − and + buttons. */
const SCALES = [0.25, 0.5, 1, 2, 4, 8, 16];

type Quantity = FemValueQuantity;

/**
 * Values in the units the user reads: SAEngine models are in SI (m, N), shown as mm, kN and
 * kN·m. Models in other units show their own values.
 */
export function resultFormatter(units: string | undefined): (quantity: Quantity, value: number) => string {
	if (units?.startsWith('SI')) {
		return (quantity, value) => {
			switch (quantity) {
				case 'length': return localize('femResults.mm', "{0} mm", (value * 1000).toFixed(2));
				case 'force': return localize('femResults.kN', "{0} kN", (value / 1000).toFixed(1));
				case 'moment': return localize('femResults.kNm', "{0} kN·m", (value / 1000).toFixed(1));
				case 'forcePerLength': return localize('femResults.kNperM', "{0} kN/m", (value / 1000).toFixed(1));
				case 'momentPerLength': return localize('femResults.kNmPerM', "{0} kN·m/m", (value / 1000).toFixed(2));
			}
		};
	}
	return (_quantity, value) => Number(value.toPrecision(4)).toString();
}

/**
 * Below the analysis model's derivation bar: which result of the last run to show in 3D
 * (a case, a load combination of the project settings, or a mode), what to show of it (deflected
 * shape, a force diagram, the reactions), at which scale, and the values that matter.
 */
export class FemResultsBar extends Disposable {

	private readonly element: HTMLElement;
	private readonly resultPicker: SelectBox;
	private readonly modePicker: SelectBox;
	private readonly showPicker: SelectBox;
	private readonly modeContainer: HTMLElement;
	private readonly scaleLabel: HTMLElement;
	private readonly animateButton: Button;
	private readonly info: HTMLElement;
	private readonly watch = this._register(new DisposableStore());
	private readonly resultsWatch = this._register(new MutableDisposable());
	private readonly reload = this._register(new RunOnceScheduler(() => void this.load(), 400));

	private resource: URI | undefined;
	private format = resultFormatter(undefined);
	private list: IFemResultList = { results: [], stale: false };
	private key: string | undefined;
	private mode = 1;
	private show: Show = 'deformed';
	private scale = 1;
	private animate = true;
	private view: IFemResultView | undefined;
	private selection: FemSelection | undefined;
	private readonly views = new Map<string, IFemResultView>();
	private request = 0;

	constructor(
		container: HTMLElement,
		private readonly onDidChangeHeight: () => void,
		/** Draws a result in the 3D view; undefined shows the model alone. */
		private readonly onDidChangeDisplay: (view: IFemResultView | undefined, display: FemResultDisplay | undefined) => void,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IContextViewService contextViewService: IContextViewService,
	) {
		super();
		this.element = append(container, $('.fem-results'));
		const group = (className: string) => append(this.element, $(`.fem-results-group.${className}`));

		const results = group('result');
		append(results, $('span.fem-results-label', undefined, localize('femResults.result', "Result")));
		this.resultPicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.resultAria', "Analysis result shown") }));
		this.resultPicker.render(append(results, $('.fem-results-select.result')));
		this._register(this.resultPicker.onDidSelect(({ index }) => {
			this.key = this.list.results[index]?.key;
			this.mode = 1;
			void this.showResult();
		}));

		this.modeContainer = group('mode');
		append(this.modeContainer, $('span.fem-results-label', undefined, localize('femResults.mode', "Mode")));
		this.modePicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.modeAria', "Mode shown") }));
		this.modePicker.render(append(this.modeContainer, $('.fem-results-select.mode')));
		this._register(this.modePicker.onDidSelect(({ index }) => {
			this.mode = index + 1;
			void this.showResult();
		}));

		const show = group('show');
		append(show, $('span.fem-results-label', undefined, localize('femResults.show', "Show")));
		this.showPicker = this._register(new SelectBox([], 0, contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femResults.showAria', "What to show of the result") }));
		this.showPicker.render(append(show, $('.fem-results-select.show')));
		this._register(this.showPicker.onDidSelect(({ index }) => {
			this.show = this.showOptions()[index]?.show ?? 'none';
			this.render();
		}));

		const scale = group('scale');
		const button = (icon: ThemeIcon, title: string, run: () => void) => {
			const b = this._register(new Button(scale, { ...defaultButtonStyles, secondary: true, supportIcons: true, title }));
			b.label = `$(${icon.id})`;
			this._register(b.onDidClick(run));
			return b;
		};
		button(Codicon.remove, localize('femResults.smaller', "Draw Smaller"), () => this.step(-1));
		this.scaleLabel = append(scale, $('span.fem-results-scale'));
		button(Codicon.add, localize('femResults.larger', "Draw Larger"), () => this.step(1));
		this.animateButton = button(Codicon.debugPause, localize('femResults.animate', "Animate the Mode Shape"), () => {
			this.animate = !this.animate;
			this.render();
		});

		this.info = append(this.element, $('span.fem-results-info'));
	}

	/** Follows the results of `resource` when it is an analysis model (`.osmodel`). */
	setResource(resource: URI | undefined, units: string | undefined): void {
		this.format = resultFormatter(units);
		if (resource?.toString() === this.resource?.toString()) {
			this.render();
			return;
		}
		this.resource = resource;
		this.watch.clear();
		this.resultsWatch.clear();
		this.list = { results: [], stale: false };
		this.key = undefined;
		this.views.clear();
		this.view = undefined;
		if (resource) {
			// A run deletes and writes again the results folder beside the model: watch the model's
			// folder for it, and the results folder for its manifest (written last).
			const results = resultsFolder(resource);
			const watchResults = () => {
				const store = new DisposableStore();
				const watcher = store.add(this.fileService.createWatcher(results, { recursive: false, excludes: [] }));
				store.add(watcher.onDidChange(e => {
					if (e.contains(joinPath(results, 'manifest.json'))) {
						this.reload.schedule();
					}
				}));
				this.resultsWatch.value = store;
			};
			const watcher = this.fileService.createWatcher(dirname(resource), { recursive: false, excludes: [] });
			this.watch.add(watcher);
			this.watch.add(watcher.onDidChange(e => {
				if (e.contains(results)) {
					watchResults();
					this.reload.schedule();
				} else if (e.contains(resource)) {
					this.reload.schedule();
				}
			}));
			watchResults();
			void this.load();
		} else {
			this.render();
		}
	}

	setSelection(selection: FemSelection | undefined): void {
		this.selection = selection;
		this.renderInfo();
	}

	private async load(): Promise<void> {
		const resource = this.resource;
		if (!resource) {
			return;
		}
		let list: IFemResultList;
		try {
			list = await this.commandService.executeCommand<IFemResultList>(LIST_COMMAND, resource) ?? { results: [], stale: false };
		} catch {
			list = { results: [], stale: false }; // no backend, or no run yet
		}
		if (resource !== this.resource) {
			return;
		}
		this.list = list;
		this.views.clear();
		if (!list.results.some(r => r.key === this.key)) {
			this.key = list.results[0]?.key;
			this.mode = 1;
		}
		await this.showResult();
	}

	private get entry(): IFemResultEntry | undefined {
		return this.list.results.find(r => r.key === this.key);
	}

	private showOptions(): readonly IShowOption[] {
		if (this.entry?.kind === 'modal') {
			return MODAL_OPTIONS;
		}
		return this.view?.shells?.length ? [...STATIC_OPTIONS, ...SHELL_OPTIONS] : STATIC_OPTIONS;
	}

	private async showResult(): Promise<void> {
		const resource = this.resource;
		const entry = this.entry;
		if (!resource || !entry) {
			this.view = undefined;
			this.render();
			return;
		}
		const id = `${entry.key}/${entry.kind === 'modal' ? this.mode : 0}`;
		let view = this.views.get(id);
		if (!view) {
			const request = ++this.request;
			try {
				view = await this.commandService.executeCommand<IFemResultView>(VIEW_COMMAND, resource, entry.key, entry.kind === 'modal' ? this.mode : undefined);
			} catch (error) {
				this.view = undefined;
				this.render(localize('femResults.failed', "The result could not be read: {0}", String(error)));
				return;
			}
			if (request !== this.request || resource !== this.resource) {
				return;
			}
			if (view) {
				this.views.set(id, view);
			}
		}
		this.view = view;
		if (!this.showOptions().some(o => o.show === this.show)) {
			this.show = 'deformed';
		}
		this.render();
	}

	private step(direction: number): void {
		const index = SCALES.indexOf(this.scale);
		this.scale = SCALES[Math.max(0, Math.min(SCALES.length - 1, index + direction))];
		this.render();
	}

	private render(problem?: string): void {
		const entry = this.entry;
		this.element.classList.toggle('visible', !!entry);
		if (entry) {
			this.resultPicker.setOptions(this.list.results.map<ISelectOptionItem>(r => ({ text: r.label })), this.list.results.indexOf(entry));
			const modal = entry.kind === 'modal';
			this.modeContainer.classList.toggle('hidden', !modal);
			if (modal) {
				const modes = entry.modes ?? [];
				this.modePicker.setOptions(modes.map<ISelectOptionItem>(m => ({
					text: m.period === null ? String(m.number) : localize('femResults.modeOption', "{0} (T = {1} s)", m.number, m.period.toFixed(3)),
				})), Math.max(0, this.mode - 1));
			}
			const options = this.showOptions();
			this.showPicker.setOptions(options.map<ISelectOptionItem>(o => ({ text: o.label })), Math.max(0, options.findIndex(o => o.show === this.show)));
			this.scaleLabel.textContent = `×${this.scale}`;
			const animatable = modal && this.show === 'deformed';
			this.animateButton.element.classList.toggle('hidden', !animatable);
			this.animateButton.label = `$(${(this.animate ? Codicon.debugPause : Codicon.play).id})`;
		}
		const view = this.view;
		this.onDidChangeDisplay(
			view && this.show !== 'none' ? view : undefined,
			view && this.show !== 'none' ? { show: this.show, scale: this.scale, animate: this.animate, format: this.format } : undefined,
		);
		this.renderInfo(problem);
		this.onDidChangeHeight();
	}

	private renderInfo(problem?: string): void {
		clearNode(this.info);
		if (!this.entry) {
			return;
		}
		if (problem) {
			append(this.info, $(`span${ThemeIcon.asCSSSelector(Codicon.error)}`));
			append(this.info, $('span', undefined, problem));
			return;
		}
		if (this.list.stale) {
			append(this.info, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`));
			append(this.info, $('span', undefined, localize('femResults.stale', "The model changed after this analysis ran: run the analysis again.")));
			return;
		}
		const shellComponent = SHELL_COMPONENTS.indexOf(this.show);
		const values = shellComponent >= 0 ? (this.view?.shells ?? []).flatMap(s => s.forces ? [s.forces[shellComponent]] : []) : [];
		if (values.length) {
			// The contour's scale, lowest (blue) to highest (red), as the 3D view colours it.
			const quantity: Quantity = shellComponent >= 3 && shellComponent < 6 ? 'momentPerLength' : 'forcePerLength';
			append(this.info, $('span', undefined, this.format(quantity, Math.min(...values))));
			append(this.info, $('span.fem-results-scale-bar'));
			append(this.info, $('span', undefined, this.format(quantity, Math.max(...values))));
			append(this.info, $('span', undefined, localize('femResults.shellAxes', "Local 1 runs along X on slabs and along the wall on walls.")));
			return;
		}
		const text = this.describe();
		if (text) {
			append(this.info, $('span', undefined, text));
		}
	}

	/** The values that matter for what is shown, or for the selected node or element. */
	private describe(): string | undefined {
		const view = this.view;
		if (!view) {
			return undefined;
		}
		const format = this.format;
		const selection = this.selection;
		if (view.kind === 'modal') {
			return undefined;
		}
		if (selection?.kind === 'node') {
			const node = view.nodes.find(n => n[0] === selection.id);
			const reaction = view.reactions.find(r => r[0] === selection.id);
			const parts = [];
			if (node) {
				parts.push(localize('femResults.nodeDisplacement', "Node {0}: displacement x {1}, y {2}, z {3}", selection.id, format('length', node[1]), format('length', node[2]), format('length', node[3])));
			}
			if (reaction) {
				parts.push(localize('femResults.nodeReaction', "reaction Fx {0}, Fy {1}, Fz {2}", format('force', reaction[1]), format('force', reaction[2]), format('force', reaction[3])));
			}
			return parts.join('; ');
		}
		const component = COMPONENTS.indexOf(this.show);
		const quantity: Quantity = component >= 0 && component < 3 ? 'force' : 'moment';
		if (selection?.kind === 'element' && component >= 0) {
			const element = view.elements.find(e => e.id === selection.id);
			const values = element?.forces?.map(f => f[component]);
			if (element && values?.length) {
				return localize('femResults.elementRange', "{0}: {1} from {2} to {3} (end i {4}, end j {5})", element.name, this.show,
					format(quantity, Math.min(...values)), format(quantity, Math.max(...values)),
					format(quantity, values[0]), format(quantity, values[values.length - 1]));
			}
		}
		switch (this.show) {
			case 'deformed': {
				let largest: readonly number[] | undefined;
				for (const node of view.nodes) {
					if (!largest || Math.hypot(node[1], node[2], node[3]) > Math.hypot(largest[1], largest[2], largest[3])) {
						largest = node;
					}
				}
				return largest && localize('femResults.largestDisplacement', "Largest displacement {0} at node {1} (x {2}, y {3}, z {4}).",
					format('length', Math.hypot(largest[1], largest[2], largest[3])), largest[0], format('length', largest[1]), format('length', largest[2]), format('length', largest[3]));
			}
			case 'reactions': {
				const total = [1, 2, 3].map(i => view.reactions.reduce((sum, r) => sum + r[i], 0));
				return localize('femResults.totalReaction', "Total reaction: Fx {0}, Fy {1}, Fz {2}.", format('force', total[0]), format('force', total[1]), format('force', total[2]));
			}
			case 'none':
				return undefined;
			default: {
				let largest: { value: number; name: string } | undefined;
				for (const element of view.elements) {
					for (const forces of element.forces ?? []) {
						if (!largest || Math.abs(forces[component]) > Math.abs(largest.value)) {
							largest = { value: forces[component], name: element.name };
						}
					}
				}
				return largest && localize('femResults.largestForce', "Largest {0}: {1} in {2}. Select an element for its values.", this.show, format(quantity, largest.value), largest.name);
			}
		}
	}
}
