/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femDesignProposal.css';
import { $, append, clearNode, Dimension } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { ISelectOptionItem, SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { Checkbox } from '../../../../base/browser/ui/toggle/toggle.js';
import { Action, Separator } from '../../../../base/common/actions.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IntervalTimer } from '../../../../base/common/async.js';
import { DisposableStore, IReference } from '../../../../base/common/lifecycle.js';
import { basename, dirname, joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultCheckboxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IUndoRedoService, UndoRedoGroup } from '../../../../platform/undoRedo/common/undoRedo.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { partById } from '../../../services/saengineProject/common/saengineProject.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { IWorkingCopyService } from '../../../services/workingCopy/common/workingCopyService.js';
import { EditorFrame, IEditorFrameStatus } from '../../saengineProject/browser/editorFrame.js';
import { saveProjectEdits } from '../../saengineProject/browser/projectEdits.js';
import { DESIGN_APPLY_COMMAND, DESIGN_PROPOSAL_COMMAND, designArguments, IFemDesignReport, runDesign } from './femDesign.js';
import { countFailing, describeBeforeAfter, describeChange, describeCheckCounts, describeFailing, describeSteelProposal, describeWaitStep, DesignProposalMode, IDesignWaitStep, DesignProposalModel, IDesignProposalRow, IDesignProposalTexts, IFemDesignApplyResult, IFailingItem, IFemDesignProposal, failingItems, notFixedBy, proposalEdits } from './femDesignProposal.js';
import { FemDesignProposalInput } from './femDesignProposalInput.js';
import { errorSummary } from './femResultsBar.js';

const MODES: readonly { readonly mode: DesignProposalMode; readonly label: string }[] = [
	{ mode: 'byType', label: localize('femProposal.byType', "Keep Shared Types") },
	{ mode: 'splitTypes', label: localize('femProposal.splitTypes', "Split into New Types") },
];

/** "Apply Proposal (2 Types)": the label of Apply with the rows included. */
function applyLabel(included: number): string {
	return included === 0 ? localize('femProposal.apply', "Apply Proposal")
		: included === 1 ? localize('femProposal.applyOne', "Apply Proposal (1 Type)")
			: localize('femProposal.applyCount', "Apply Proposal ({0} Types)", included);
}

/** Why the checks were not run again after an apply (or its undo). */
function notSavedText(unsaved: readonly URI[]): string {
	return localize('femProposal.notSaved', "{0} could not be saved: the design checks were not run again. Save the files, then Propose Again.", unsaved.map(file => basename(file)).join(', '));
}

/** What the last apply did, for the banner over the rows (and its Undo). */
interface IAppliedState {
	readonly before: IFemDesignReport | undefined;
	after: IFemDesignReport | undefined;
	readonly changes: readonly string[];
	/** The files edited, with their models' version right after the edit (Undo needs them unchanged). */
	readonly edited: readonly { readonly resource: URI; readonly version: number }[];
	undone: boolean;
	problem?: string;
}

/** A step of the work the page waits for, and since when. */
interface IWaitStep extends IDesignWaitStep {
	readonly since: number;
}

/**
 * Design Reinforcement: the bars proposed for each object type from the steel its members
 * require (the backend's `saengine.design.proposal`), current against proposed, with the member
 * that governs and those over-designed. The engineer picks the rows (and whether members keep
 * sharing their types) and applies them: one undoable edit of 04 Objects (and 06 BIM when types
 * are split), saved, then the design checks run again for the before/after counts.
 */
export class FemDesignProposalEditor extends EditorPane {

	static readonly ID = FemDesignProposalInput.EDITOR_ID;

	private frame!: EditorFrame;
	private scrollable!: DomScrollableElement;
	private list!: HTMLElement;
	private modePicker!: SelectBox;
	private readonly model = new DesignProposalModel();
	private before: IFemDesignReport | undefined;
	private loading = false;
	private applying = false;
	private problem: string | undefined;
	/** The engineer stopped waiting: a note, not an error. */
	private stopped = false;
	private applied: IAppliedState | undefined;
	private request = 0;
	/** What the page waits for, step k of n, and since when (N-X4 of usability walk 2: minutes of a blank page). */
	private step: IWaitStep | undefined;
	private readonly ticker = this._register(new IntervalTimer());

	private readonly renderStore = this._register(new DisposableStore());
	/** The text models of the files an apply edits, held while the page is open so their undo stays. */
	private readonly references = this._register(new DisposableStore());
	private readonly modelReferences = new Map<string, IReference<IResolvedTextEditorModel>>();

	private readonly applyAction = this._register(new Action('saengine.fem.proposal.apply', localize('femProposal.apply', "Apply Proposal"), ThemeIcon.asClassName(Codicon.check), false, () => this.apply()));
	private readonly refreshAction = this._register(new Action('saengine.fem.proposal.refresh', localize('femProposal.refresh', "Propose Again"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.reload()));
	private readonly stopAction = this._register(new Action('saengine.fem.proposal.stop', localize('femProposal.stop', "Stop Waiting"), ThemeIcon.asClassName(Codicon.debugStop), false, async () => this.stopWaiting()));
	private readonly includeAllAction = this._register(new Action('saengine.fem.proposal.includeAll', localize('femProposal.includeAll', "Include All Changes"), undefined, true, async () => this.includeAll(true)));
	private readonly includeNoneAction = this._register(new Action('saengine.fem.proposal.includeNone', localize('femProposal.includeNone', "Include None"), undefined, true, async () => this.includeAll(false)));
	private readonly openObjectsAction = this._register(new Action('saengine.fem.proposal.openObjects', localize('femProposal.openObjects', "Open Object Types"), undefined, true, () => this.openObjects()));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@IFileService private readonly fileService: IFileService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IUndoRedoService private readonly undoRedoService: IUndoRedoService,
		@IWorkingCopyService private readonly workingCopyService: IWorkingCopyService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(FemDesignProposalEditor.ID, group, telemetryService, themeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FemDesignProposalEditor.ID,
			ariaLabel: localize('femProposal.toolbar', "Design Reinforcement"),
		}));
		this.frame.element.classList.add('saengine-fem-proposal-editor');
		this.frame.setTitle(localize('femProposal.title', "Design Reinforcement"));
		this.frame.setHelp(localize('femProposal.help', "Bars proposed for each object type from the steel its members require under the load combinations of the last analysis run. Keep Shared Types designs each type for its most demanding member; Split into New Types moves members that need much less to new types with lighter bars. Apply changes 04 Objects (06 BIM and 05 Floor Plan for a split) in one edit that Undo reverts. Foundations are designed in 9 Substructure."));
		const mode = append(this.frame.controlsSlot, $('.fem-proposal-mode'));
		append(mode, $('span.sa-frame-label', undefined, localize('femProposal.mode', "Types")));
		this.modePicker = this._register(new SelectBox(MODES.map<ISelectOptionItem>(m => ({ text: m.label })), 0, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('femProposal.modeAria', "How members share object types") }));
		this.modePicker.render(append(mode, $('.fem-proposal-select')));
		this._register(this.modePicker.onDidSelect(({ index }) => this.setMode(MODES[index]?.mode ?? 'byType')));
		this.frame.setActions([this.applyAction, this.refreshAction, this.stopAction], [this.includeAllAction, this.includeNoneAction, new Separator(), this.openObjectsAction]);
		this.list = $('.fem-proposal-list');
		this.scrollable = this._register(new DomScrollableElement(this.list, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('fem-proposal-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
	}

	override async setInput(input: FemDesignProposalInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		const changed = !this.input || !input.matches(this.input);
		await super.setInput(input, options, context, token);
		if (changed) {
			this.references.clear();
			this.modelReferences.clear();
			this.applied = undefined;
			void this.reload();
		}
	}

	override clearInput(): void {
		this.request++;
		this.step = undefined;
		this.ticker.cancel();
		this.references.clear();
		this.modelReferences.clear();
		this.renderStore.clear();
		this.model.clear();
		this.applied = undefined;
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.list.focus();
	}

	/** The analysis model whose last run the proposal is made from. */
	private get resource(): URI | undefined {
		return (this.input as FemDesignProposalInput | undefined)?.model;
	}

	/** The project's file of `part` (the model is `<root>/08 FEM/model.osmodel`). */
	private partFile(model: URI, part: 'objects' | 'bim' | 'floorPlan'): URI {
		const info = partById(part);
		return joinPath(dirname(dirname(model)), info?.folder ?? '', info?.mainFile ?? '');
	}

	// ───────────────────────────── loading ─────────────────────────────

	/** Forgets the proposals and asks again for the mode shown, with the current checks' counts. */
	private async reload(): Promise<void> {
		const model = this.resource;
		if (!model) {
			return;
		}
		this.model.clear();
		this.problem = undefined;
		this.stopped = false;
		if (!CommandsRegistry.getCommand(DESIGN_PROPOSAL_COMMAND)) {
			this.render();
			return;
		}
		const request = ++this.request;
		this.loading = true;
		this.setStep({ index: 1, count: 2, text: localize('femProposal.stepSave', "Saving the project files") });
		// The backend reads the files on disk: save what the engineer sees first (as Run All does).
		const unsaved = await saveProjectEdits(this.workingCopyService, dirname(dirname(model)));
		if (request !== this.request) {
			return;
		}
		if (unsaved.length) {
			// Proposing from the files on disk would propose for bars the engineer has changed since.
			this.problem = localize('femProposal.saveFailed', "No bars were proposed: {0} could not be saved first.", unsaved.map(file => basename(file)).join(', '));
			this.loading = false;
			this.setStep(undefined);
			return;
		}
		this.setStep({ index: 2, count: 2, text: localize('femProposal.stepPropose', "Checking the bars now and proposing bars from the required steel") });
		const [before] = await Promise.all([
			runDesign(this.commandService, model).catch(() => undefined),
			this.fetch(this.model.mode, request),
		]);
		if (request !== this.request) {
			return;
		}
		this.before = before;
		this.model.setChecks(before);
		this.loading = false;
		this.setStep(undefined);
	}

	/** Shows `step` (undefined: none) and keeps its clock running while there is one. */
	private setStep(step: IDesignWaitStep | undefined): void {
		this.step = step && { ...step, since: Date.now() };
		if (step) {
			this.ticker.cancelAndSet(() => this.frame.setStatus(this.status()), 1000);
		} else {
			this.ticker.cancel();
		}
		this.render();
	}

	/**
	 * Gives the page back while the engine works on: its answer is no longer waited for (an
	 * apply not yet written leaves the files as they were; one written keeps its Undo). The
	 * engine keeps the proposal it finishes, so Propose Again shows it at once.
	 */
	private stopWaiting(): void {
		if (!this.loading && !this.applying) {
			return;
		}
		this.request++;
		this.loading = false;
		this.applying = false;
		this.stopped = true;
		this.problem = localize('femProposal.stopped', "Stopped waiting. The engine finishes in the background and keeps the proposal: Propose Again shows it once it is done.");
		this.setStep(undefined);
	}

	/** Asks for the proposal of `mode` once. */
	private async fetch(mode: DesignProposalMode, request: number): Promise<void> {
		const model = this.resource;
		if (!model || this.model.has(mode)) {
			return;
		}
		try {
			const proposal = await this.commandService.executeCommand<IFemDesignProposal>(DESIGN_PROPOSAL_COMMAND, { ...designArguments(model), mode });
			if (request === this.request && proposal) {
				this.model.setProposal(mode, proposal);
			}
		} catch (error) {
			if (request === this.request) {
				this.problem = localize('femProposal.failed', "No bars could be proposed: {0}", errorSummary(error));
			}
		}
	}

	private async setMode(mode: DesignProposalMode): Promise<void> {
		if (mode === this.model.mode) {
			return;
		}
		this.model.mode = mode;
		this.problem = undefined;
		this.stopped = false;
		if (!this.model.has(mode) && CommandsRegistry.getCommand(DESIGN_PROPOSAL_COMMAND)) {
			const request = ++this.request;
			this.loading = true;
			this.setStep({ index: 1, count: 1, text: localize('femProposal.stepMode', "Proposing bars for \"{0}\"", MODES.find(m => m.mode === mode)?.label ?? mode) });
			await this.fetch(mode, request);
			if (request !== this.request) {
				return;
			}
			this.loading = false;
			this.setStep(undefined);
			return;
		}
		this.render();
	}

	private includeAll(included: boolean): void {
		this.model.setAllIncluded(included);
		this.render();
	}

	private async openObjects(): Promise<void> {
		const model = this.resource;
		if (model) {
			await this.editorService.openEditor({ resource: this.partFile(model, 'objects'), options: { pinned: true } });
		}
	}

	// ───────────────────────────── apply and undo ─────────────────────────────

	/** Saves the files; returns those that could not be saved (still dirty after the save). */
	private async save(resources: readonly URI[]): Promise<URI[]> {
		const unsaved: URI[] = [];
		for (const resource of resources) {
			let saved: URI | undefined;
			try {
				saved = await this.textFileService.save(resource);
			} catch {
				saved = undefined;
			}
			if (!saved || this.textFileService.isDirty(resource)) {
				unsaved.push(resource);
			}
		}
		return unsaved;
	}

	private async textModel(resource: URI): Promise<IResolvedTextEditorModel> {
		const key = resource.toString();
		let reference = this.modelReferences.get(key);
		if (!reference) {
			reference = await this.textModelService.createModelReference(resource);
			this.references.add(reference);
			this.modelReferences.set(key, reference);
		}
		return reference.object;
	}

	/**
	 * Applies the rows included: the backend writes the new object types (and building model),
	 * which replace the files' text in one undo group, are saved, and are checked again.
	 */
	private async apply(): Promise<void> {
		const model = this.resource;
		const proposal = this.model.applyRequest();
		if (!model || !proposal || this.applying || !CommandsRegistry.getCommand(DESIGN_APPLY_COMMAND)) {
			return;
		}
		const request = this.request;
		this.applying = true;
		this.problem = undefined;
		this.stopped = false;
		this.setStep({ index: 1, count: 4, text: localize('femProposal.stepWrite', "Writing the bars into the object types") });
		try {
			// The files the backend edits: the object types always; the building model and the
			// floor plan its members come from (members moved to new types).
			const parts = ['objects', 'bim', 'floorPlan'] as const;
			const models = new Map<typeof parts[number], { resource: URI; model: ITextModel }>();
			for (const part of parts) {
				const resource = this.partFile(model, part);
				if (part === 'objects' || await this.fileService.exists(resource)) {
					models.set(part, { resource, model: (await this.textModel(resource)).textEditorModel });
				}
			}
			const current: IDesignProposalTexts = {
				objectsText: models.get('objects')!.model.getValue(),
				bimText: models.get('bim')?.model.getValue(),
				floorPlanText: models.get('floorPlan')?.model.getValue(),
			};
			const result = await this.commandService.executeCommand<IFemDesignApplyResult>(DESIGN_APPLY_COMMAND, {
				objectsText: current.objectsText,
				bimText: current.bimText ?? null,
				...(current.floorPlanText !== undefined ? { floorPlanText: current.floorPlanText } : {}),
				proposal,
			});
			if (request !== this.request) {
				// Stopped waiting before anything was edited: the files stay as they were.
				return;
			}
			if (!result) {
				throw new Error(localize('femProposal.applyNothing', "the backend returned nothing"));
			}
			const edits = proposalEdits(current, result);
			// One undo group over every file: Undo in any of them reverts them all.
			const group = new UndoRedoGroup();
			const edited: { resource: URI; version: number }[] = [];
			for (const part of parts) {
				const text = edits[part];
				const target = models.get(part);
				if (text === undefined || !target) {
					continue;
				}
				target.model.pushStackElement();
				target.model.pushEditOperations([], [{ range: target.model.getFullModelRange(), text }], () => null, group);
				target.model.pushStackElement();
				edited.push({ resource: target.resource, version: target.model.getAlternativeVersionId() });
			}
			const changes = (result.changes ?? []).map(describeChange).filter(c => !!c);
			const before = this.before;
			this.setStep({ index: 2, count: 4, text: localize('femProposal.stepSaveApplied', "Saving the edited files") });
			const unsaved = await this.save(edited.map(file => file.resource));
			// Kept even if the engineer stops waiting from here on: the files are edited, Undo stays.
			const applied: IAppliedState = { before, after: undefined, changes, edited, undone: false };
			this.applied = applied;
			if (request !== this.request) {
				return;
			}
			if (unsaved.length) {
				// The checks read the files on disk: checking now would count the old bars.
				applied.problem = notSavedText(unsaved);
				this.model.clear();
				return;
			}
			this.setStep({ index: 3, count: 4, text: localize('femProposal.stepCheck', "Checking the members again with the new bars") });
			const after = edited.length ? await runDesign(this.commandService, model).catch(() => undefined) : before;
			if (request !== this.request) {
				return;
			}
			applied.after = after;
			this.before = after;
			this.model.setChecks(after);
			// The bars changed: propose again from them (the rows now show what was applied).
			this.model.clear();
			this.setStep({ index: 4, count: 4, text: localize('femProposal.stepProposeAgain', "Proposing again from the new bars") });
			await this.fetch(this.model.mode, request);
		} catch (error) {
			if (request === this.request) {
				this.problem = localize('femProposal.applyFailed', "The proposal could not be applied: {0}", errorSummary(error));
			}
		} finally {
			if (request === this.request) {
				this.applying = false;
				this.setStep(undefined);
			}
		}
	}

	/** Whether the files are as the last apply left them (else Undo would revert later edits too). */
	private canUndo(applied: IAppliedState): boolean {
		return !applied.undone && applied.edited.length > 0 && applied.edited.every(file => {
			const reference = this.modelReferences.get(file.resource.toString());
			return reference?.object.textEditorModel.getAlternativeVersionId() === file.version && this.undoRedoService.canUndo(file.resource);
		});
	}

	/** Undoes the last apply in both files, saves them and checks again. */
	private async undo(): Promise<void> {
		const model = this.resource;
		const applied = this.applied;
		if (!model || !applied || !this.canUndo(applied)) {
			return;
		}
		const request = this.request;
		this.applying = true;
		this.setStep({ index: 1, count: 3, text: localize('femProposal.stepUndo', "Undoing the apply and saving the files") });
		try {
			// One undo: the group undoes the other file's edit too.
			await this.undoRedoService.undo(applied.edited[0].resource);
			const unsaved = await this.save(applied.edited.map(file => file.resource));
			if (request !== this.request) {
				return;
			}
			applied.undone = true;
			if (unsaved.length) {
				applied.after = undefined;
				applied.problem = notSavedText(unsaved);
				this.model.clear();
				return;
			}
			this.setStep({ index: 2, count: 3, text: localize('femProposal.stepCheckUndone', "Checking the members again with the bars before") });
			const after = await runDesign(this.commandService, model).catch(() => undefined);
			if (request !== this.request) {
				return;
			}
			applied.after = after;
			this.before = after;
			this.model.setChecks(after);
			this.model.clear();
			this.setStep({ index: 3, count: 3, text: localize('femProposal.stepProposeAgain', "Proposing again from the new bars") });
			await this.fetch(this.model.mode, request);
		} catch (error) {
			applied.problem = localize('femProposal.undoFailed', "The apply could not be undone: {0}", errorSummary(error));
		} finally {
			if (request === this.request) {
				this.applying = false;
				this.setStep(undefined);
			}
		}
	}

	// ───────────────────────────── rendering ─────────────────────────────

	private render(): void {
		this.renderStore.clear();
		clearNode(this.list);
		const available = !!CommandsRegistry.getCommand(DESIGN_PROPOSAL_COMMAND);
		const rows = this.model.rows();
		const included = rows.filter(r => r.included).length;
		this.applyAction.enabled = available && !!CommandsRegistry.getCommand(DESIGN_APPLY_COMMAND) && included > 0 && !this.applying && !this.loading;
		this.applyAction.label = applyLabel(included);
		this.refreshAction.enabled = available && !this.applying && !this.loading;
		this.stopAction.enabled = this.applying || this.loading;
		this.includeAllAction.enabled = this.includeNoneAction.enabled = rows.length > 0 && !this.applying;
		this.modePicker.select(Math.max(0, MODES.findIndex(m => m.mode === this.model.mode)));
		this.modePicker.setEnabled(available && !this.applying);
		if (this.loading || this.applying) {
			this.frame.showProgress();
		} else {
			this.frame.hideProgress();
		}

		if (!available) {
			this.frame.setEmpty({
				icon: Codicon.symbolRuler,
				title: localize('femProposal.unavailableTitle', "Design Reinforcement is not available"),
				text: localize('femProposal.unavailable', "This version's backend does not propose bars yet. The design checks still check the bars entered in 04 Objects."),
			});
			this.frame.setStatus(undefined);
			this.scrollable.scanDomNode();
			return;
		}
		const proposal = this.model.proposal;
		// Without a proposal, the banner of an apply still shows (with its Undo) while the page
		// checks and proposes again, and when the files could not be saved.
		if (!proposal && !this.loading && !this.applying && !this.applied) {
			this.frame.setEmpty({
				icon: Codicon.symbolRuler,
				title: localize('femProposal.noneTitle', "No proposal"),
				text: this.problem ?? localize('femProposal.none', "Run the analysis first: bars are proposed from its results."),
				actions: [{ label: localize('femProposal.refresh', "Propose Again"), icon: Codicon.refresh, run: () => void this.reload() }],
			});
			this.frame.setStatus(this.problem ? this.status() : undefined);
			this.scrollable.scanDomNode();
			return;
		}
		if (!proposal && this.loading && !this.applied) {
			// Not a blank page while the engine works: what it does, and how to stop waiting.
			this.frame.setEmpty({
				icon: Codicon.loading,
				title: localize('femProposal.loadingTitle', "Proposing bars"),
				text: this.step?.text ?? localize('femProposal.loading', "Proposing bars from the required steel..."),
				actions: [{ label: localize('femProposal.stop', "Stop Waiting"), icon: Codicon.debugStop, run: () => this.stopWaiting() }],
			});
			this.frame.setStatus(this.status());
			this.scrollable.scanDomNode();
			return;
		}
		this.frame.setEmpty(undefined);

		this.renderApplied();
		for (const warning of this.model.generalWarnings()) {
			append(this.list, $('.fem-proposal-warning', undefined, warning));
		}
		for (const note of this.model.generalNotes()) {
			append(this.list, $('.fem-proposal-note', undefined, note));
		}
		if (proposal) {
			this.renderHeader(rows, included);
			if (!rows.length) {
				append(this.list, $('.fem-proposal-note', undefined, localize('femProposal.noTypes', "There are no reinforced-concrete object types with checked members.")));
			}
			for (const row of rows) {
				this.renderRow(row);
			}
		}
		this.frame.setStatus(this.status());
		this.scrollable.scanDomNode();
	}

	private status(): IEditorFrameStatus | undefined {
		if ((this.applying || this.loading) && this.step) {
			return { busy: true, text: describeWaitStep(this.step, Date.now() - this.step.since) };
		}
		if (this.applying) {
			return { busy: true, text: localize('femProposal.applying', "Applying the proposal and checking the members again...") };
		}
		if (this.loading) {
			return { busy: true, text: localize('femProposal.loading', "Proposing bars from the required steel...") };
		}
		if (this.problem) {
			return { severity: this.stopped ? 'info' : 'error', text: this.problem };
		}
		const rows = this.model.rows();
		const changed = rows.filter(r => r.changed).length;
		const included = rows.filter(r => r.included).length;
		return {
			text: localize('femProposal.statusCounts', "{0} of {1} types change, {2} included.", changed, rows.length, included),
		};
	}

	/** The line over the rows: the checks now, and the Apply button. */
	private renderHeader(rows: readonly IDesignProposalRow[], included: number): void {
		const header = append(this.list, $('.fem-proposal-header'));
		const text = append(header, $('.fem-proposal-header-text'));
		append(text, $('.fem-proposal-header-title', undefined, this.model.mode === 'splitTypes'
			? localize('femProposal.headerSplit', "Bars per type, members that need much less moved to new types")
			: localize('femProposal.headerByType', "Bars per type, for its most demanding member")));
		if (this.before) {
			append(text, $('.fem-proposal-header-detail', undefined, localize('femProposal.now', "Design checks now: {0}.", describeCheckCounts(this.before))));
			// From the rows (N-X5 of usability walk 2: "bars are proposed" for a type whose row
			// proposed none).
			const noBars = this.before.summary.noBars ?? [];
			const withoutBars = noBars.filter(type => rows.some(r => r.type === type && r.tooSmall && !r.included));
			const proposed = noBars.filter(type => !withoutBars.includes(type));
			if (proposed.length) {
				append(text, $('.fem-proposal-header-detail', undefined, localize('femProposal.noBarsYet', "Not checked for want of bars: {0}. Bars are proposed for them below.", proposed.join(', '))));
			}
			if (withoutBars.length) {
				append(text, $('.fem-proposal-header-detail.warn', undefined, localize('femProposal.noBarsNone', "Not checked for want of bars, and no bars proposed: {0}. See their rows for the section to try.", withoutBars.join(', '))));
			}
		}
		const button = this.renderStore.add(new Button(header, { ...defaultButtonStyles, supportIcons: true }));
		button.label = `$(${Codicon.check.id}) ${applyLabel(included)}`;
		button.enabled = this.applyAction.enabled;
		this.renderStore.add(button.onDidClick(() => void this.apply()));
		// What the bars proposed leave failing (X4 of the usability walk: "nothing to change"
		// while every joint and a beam failed).
		const left = notFixedBy(rows, this.before);
		if (!rows.some(r => r.changed)) {
			if (left.length) {
				this.renderFailing(this.list, localize('femProposal.noBarFix', "No change of bars is proposed, but these still fail: {0}. Bars do not fix them: change the section, the material or the layout.", countFailing(left)), left);
			} else {
				append(this.list, $('.fem-proposal-note', undefined, localize('femProposal.allFine', "The bars of every type already provide the steel required: nothing to change.")));
			}
		} else if (left.length) {
			this.renderFailing(this.list, localize('femProposal.notFixed', "Not fixed by the rows included: {0}.", countFailing(left)), left);
		}
	}

	/** A warning with the failing items counted, their ids under a disclosure (N-X21 of usability walk 2). */
	private renderFailing(container: HTMLElement, text: string, items: readonly IFailingItem[]): void {
		const warning = append(container, $('.fem-proposal-warning'));
		const details = append(warning, $('details.fem-proposal-disclosure'));
		append(details, $('summary', undefined, text));
		append(details, $('.fem-proposal-ids', undefined, describeFailing(items)));
	}

	/** The banner of the last apply: the checks before and after, what changed, and Undo. */
	private renderApplied(): void {
		const applied = this.applied;
		if (!applied) {
			return;
		}
		// Applied is a success; what still fails is a warning inside it (N-X21 of usability walk 2).
		const ok = !!applied.after && !applied.problem;
		const banner = append(this.list, $(`.fem-proposal-applied${ok ? '.pass' : ''}${applied.undone ? '.undone' : ''}`));
		const head = append(banner, $('.fem-proposal-applied-head'));
		append(head, $('span.fem-proposal-applied-title', undefined, applied.undone
			? localize('femProposal.undone', "Apply undone")
			: localize('femProposal.applied', "Proposal applied")));
		if (applied.after) {
			append(head, $('span.fem-proposal-applied-counts', undefined, applied.undone
				? describeCheckCounts(applied.after)
				: describeBeforeAfter(applied.before, applied.after)));
		}
		if (!applied.undone) {
			for (const change of applied.changes) {
				append(banner, $('.fem-proposal-applied-change', undefined, change));
			}
			const failing = failingItems(applied.after);
			if (failing.length) {
				this.renderFailing(banner, localize('femProposal.stillFailing', "Still failing: {0}.", countFailing(failing)), failing);
			}
			if (this.canUndo(applied)) {
				const undo = this.renderStore.add(new Button(banner, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
				undo.label = `$(${Codicon.discard.id}) ${localize('femProposal.undo', "Undo Apply")}`;
				undo.enabled = !this.applying;
				this.renderStore.add(undo.onDidClick(() => void this.undo()));
			} else if (applied.edited.length) {
				append(banner, $('.fem-proposal-applied-change', undefined, localize('femProposal.undoInFiles', "The files changed since: undo in 04 Objects (Ctrl+Z) instead.")));
			}
		}
		if (applied.problem) {
			append(banner, $('.fem-proposal-warning', undefined, applied.problem));
		}
	}

	private renderRow(row: IDesignProposalRow): void {
		const element = append(this.list, $(`.fem-proposal-row${row.changed ? '' : '.unchanged'}${row.tooSmall ? '.too-small' : ''}${row.included ? '.included' : ''}`));
		const toggle = append(element, $('.fem-proposal-toggle'));
		const title = row.blocked
			? localize('femProposal.blockedRow', "{0} cannot be applied as the rows stand", row.type)
			: row.strengthBars
				? localize('femProposal.strengthRow', "Apply the bars the strength of {0} needs anyway (its joints still fail)", row.type)
				: row.changed
				? localize('femProposal.includeRow', "Include {0}", row.type)
				: row.tooSmall
					? row.steel
						? localize('femProposal.tooSmallSteelRow', "No {0} section makes {1} work", row.steel.family, row.type)
						: localize('femProposal.tooSmallRow', "No bars make {0} work", row.type)
					: row.steel
						? localize('femProposal.unchangedSteelRow', "{0} keeps its section", row.type)
						: localize('femProposal.unchangedRow', "{0} keeps its bars", row.type);
		const checkbox = this.renderStore.add(new Checkbox(title, row.included, defaultCheckboxStyles));
		toggle.appendChild(checkbox.domNode);
		if (!row.changed || row.blocked || this.applying) {
			checkbox.disable();
		}
		this.renderStore.add(checkbox.onChange(() => {
			this.model.setIncluded(row.key, checkbox.checked);
			this.render();
		}));

		const body = append(element, $('.fem-proposal-body'));
		const head = append(body, $('.fem-proposal-type'));
		append(head, $('span.fem-proposal-type-id', undefined, row.type));
		if (row.name && row.name !== row.type) {
			append(head, $('span.fem-proposal-type-name', undefined, row.name));
		}
		if (row.steel) {
			append(head, $('span.fem-proposal-badge.muted', undefined, localize('femProposal.steelBadge', "steel, {0}", row.steel.family)));
		}
		if (row.from) {
			append(head, $('span.fem-proposal-badge', undefined, localize('femProposal.newFrom', "new, from {0}", row.from)));
		} else if (row.tooSmall) {
			append(head, $('span.fem-proposal-badge.warn', undefined, row.steel
				? localize('femProposal.noSteelBadge', "no section of the family passes")
				: localize('femProposal.tooSmallBadge', "section too small")));
		} else if (!row.changed) {
			append(head, $('span.fem-proposal-badge.muted', undefined, localize('femProposal.noChange', "no change")));
		}

		const bars = append(body, $('.fem-proposal-bars'));
		append(bars, $('span.fem-proposal-current', undefined, row.current));
		if (row.changed) {
			append(bars, $(`span.fem-proposal-arrow${ThemeIcon.asCSSSelector(Codicon.arrowRight)}`, { 'aria-label': localize('femProposal.to', "to") }));
			append(bars, $('span.fem-proposal-proposed', undefined, row.proposed));
		}

		const facts: string[] = [];
		if (row.governingMember) {
			facts.push(localize('femProposal.governing', "governed by {0}", row.governingMember));
		}
		if (row.members.length) {
			facts.push(row.members.length === 1
				? localize('femProposal.oneMember', "1 member")
				: localize('femProposal.members', "{0} members", row.members.length));
		}
		if (facts.length) {
			append(body, $('.fem-proposal-facts', { title: row.members.join(', ') }, facts.join(' · ')));
		}
		const steelFacts = row.steel && describeSteelProposal(row.steel);
		if (steelFacts) {
			append(body, $('.fem-proposal-facts', undefined, steelFacts));
		}
		if (row.strengthBars) {
			append(body, $('.fem-proposal-facts', undefined, row.included
				? localize('femProposal.strengthIncluded', "Included: these bars are applied, but its joints still fail joint shear until the section grows.")
				: localize('femProposal.strengthOffer', "Tick to apply the bars its strength needs anyway; its joints still fail joint shear until the section grows.")));
		}
		if (row.overDesigned.length) {
			// A count, the ids under a disclosure (N-X21 of usability walk 2: a wall of member ids).
			const details = append(body, $('details.fem-proposal-disclosure.fem-proposal-facts'));
			append(details, $('summary', undefined, row.overDesigned.length === 1
				? localize('femProposal.overDesignedOne', "1 member over-designed with these bars")
				: localize('femProposal.overDesignedMany', "{0} members over-designed with these bars", row.overDesigned.length)));
			append(details, $('.fem-proposal-ids', undefined, row.overDesigned.join(', ')));
		}
		for (const warning of row.warnings) {
			append(body, $('.fem-proposal-warning', undefined, warning));
		}
		if (row.notes.length) {
			append(body, $('.fem-proposal-notes', undefined, row.notes.join('; ')));
		}
	}
}

