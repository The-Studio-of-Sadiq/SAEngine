/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/projectNavigator.css';
import './media/projectStageBar.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IDisposable, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IBannerService } from '../../../services/banner/browser/bannerService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaenginePartStatusService, nextStep } from '../../../services/saengineProject/common/partStatus.js';
import { IProjectStage, projectStages, StageAction, StageState, stageStateLabel } from '../../../services/saengineProject/common/projectStages.js';
import { ISaengineProject, ISaengineProjectService, projectParts } from '../../../services/saengineProject/common/saengineProject.js';
import { openPart, openPartSection, partName, stateText } from './projectParts.js';

/*
 * The project stage bar: one thin strip under the title bar with the project's stages in order
 * (Site & Soil, Model, Loads, Analysis, Design, Drawings · BOQ · Report), each with its state
 * from the part statuses (projectStages.ts). Clicking a stage opens its part; its tooltip says
 * what is out of date or failing and the next step. Shown while a project is open.
 */

/** Height of the strip [px]: fits 1366x768 under the title bar. */
const STAGE_BAR_HEIGHT = 28;

/** Commands of the next steps (registered by the analysis part; strings: no imports between the parts). */
const ACTION_COMMANDS: Record<StageAction, string> = {
	runAll: 'saengine.runAll',
	designReinforcement: 'saengine.fem.designReinforcement',
};

function actionLabel(action: StageAction): string {
	switch (action) {
		case 'runAll': return localize('stageBar.runAll', "Run All");
		case 'designReinforcement': return localize('stageBar.designReinforcement', "Design Reinforcement");
	}
}

function stateIcon(state: StageState): ThemeIcon {
	switch (state) {
		case 'done': return Codicon.passFilled;
		case 'inProgress': return Codicon.circleLargeFilled;
		case 'stale': return Codicon.history;
		case 'failed': return Codicon.error;
		default: return Codicon.circleLargeOutline;
	}
}

export class ProjectStageBar extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.projectStageBar';

	private readonly element = $('.sa-stage-bar');
	private readonly strip = this._register(new MutableDisposable<IDisposable>());
	private readonly rendered = this._register(new DisposableStore());
	private readonly scheduler = this._register(new RunOnceScheduler(() => this.render(), 50));
	private buttons: HTMLElement[] = [];
	/** The stage that keeps the keyboard focus position (roving tabindex). */
	private focusIndex = 0;

	constructor(
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IBannerService private readonly bannerService: IBannerService,
		@IHoverService private readonly hoverService: IHoverService,
		@IKeybindingService private readonly keybindingService: IKeybindingService,
		@ICommandService private readonly commandService: ICommandService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
	) {
		super();
		this.element.setAttribute('role', 'toolbar');
		this.element.setAttribute('aria-label', localize('stageBar.aria', "Project stages"));
		this._register(addDisposableListener(this.element, EventType.KEY_DOWN, e => this.onKeyDown(new StandardKeyboardEvent(e))));
		this._register(this.projectService.onDidChangeProject(() => this.scheduler.schedule()));
		this._register(this.statusService.onDidChange(() => this.scheduler.schedule()));
		this.render();
	}

	private render(): void {
		const project = this.projectService.project;
		const stages = project ? projectStages(this.statusService.statuses) : [];
		if (!project || !stages.length) {
			this.strip.clear();
			return;
		}
		const hadFocus = this.element.contains(this.element.ownerDocument.activeElement);
		this.rendered.clear();
		clearNode(this.element);
		const next = nextStep(this.statusService.statuses)?.status.part;
		const nextStage = next ? stages.find(stage => stage.state !== 'done' && stage.focus?.part === next) : undefined;
		this.buttons = stages.map((stage, index) => {
			if (index > 0) {
				append(this.element, $(`span.sa-stage-sep${ThemeIcon.asCSSSelector(Codicon.chevronRight)}`)).setAttribute('aria-hidden', 'true');
			}
			return this.renderStage(project, stage, stage === nextStage);
		});
		this.focusIndex = Math.min(this.focusIndex, this.buttons.length - 1);
		this.buttons.forEach((button, index) => button.tabIndex = index === this.focusIndex ? 0 : -1);
		if (hadFocus) {
			this.buttons[this.focusIndex]?.focus();
		}
		if (!this.strip.value) {
			this.strip.value = this.bannerService.showStrip(this.element, STAGE_BAR_HEIGHT);
		}
	}

	private renderStage(project: ISaengineProject, stage: IProjectStage, isNext: boolean): HTMLElement {
		const button = append(this.element, $<HTMLButtonElement>(`button.sa-stage.sa-stage-${stage.state}`));
		button.type = 'button';
		button.classList.toggle('sa-stage-next', isNext);
		append(button, $(`span.sa-stage-icon${ThemeIcon.asCSSSelector(stateIcon(stage.state))}`)).setAttribute('aria-hidden', 'true');
		append(button, $('span.sa-stage-label', undefined, stage.label));
		if (stage.state === 'failed' || stage.state === 'stale') {
			append(button, $('span.sa-stage-text', undefined, stage.focus ? stateText(stage.focus) : stageStateLabel(stage.state)));
		}
		const lines = this.describe(project, stage);
		button.setAttribute('aria-label', lines.join('. '));
		if (isNext) {
			button.setAttribute('aria-current', 'step');
		}
		this.rendered.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, lines.join('\n')));
		this.rendered.add(addDisposableListener(button, EventType.CLICK, () => void this.open(project, stage)));
		this.rendered.add(addDisposableListener(button, EventType.FOCUS, () => {
			this.focusIndex = this.buttons.indexOf(button);
			this.buttons.forEach(b => b.tabIndex = b === button ? 0 : -1);
		}));
		return button;
	}

	/** The tooltip: the stage and its state, the part that needs work and the next step. */
	private describe(project: ISaengineProject, stage: IProjectStage): string[] {
		const lines = [localize('stageBar.title', "{0}: {1}", stage.label, stageStateLabel(stage.state))];
		const focus = stage.focus;
		const part = focus && projectParts(project.type).find(p => p.id === focus.part);
		if (focus && part && stage.state !== 'notStarted' && stage.state !== 'done') {
			lines.push(localize('stageBar.part', "{0}: {1}", partName(part), stateText(focus)));
		}
		if (stage.waitsFor && stage.state !== 'stale') {
			lines.push(localize('stageBar.waits', "Waits for the analysis."));
		}
		if (stage.state !== 'done' && focus?.hint) {
			const action = stage.action;
			if (action) {
				const key = this.keybindingService.lookupKeybinding(ACTION_COMMANDS[action])?.getLabel();
				lines.push(key
					? localize('stageBar.nextWithKey', "Next: {0} ({1}, {2}).", focus.hint, actionLabel(action), key)
					: localize('stageBar.nextWith', "Next: {0} ({1}).", focus.hint, actionLabel(action)));
			} else {
				lines.push(localize('stageBar.next', "Next: {0}.", focus.hint));
			}
		}
		if (part) {
			lines.push(localize('stageBar.click', "Click to open {0}.", partName(part)));
		}
		return lines;
	}

	private async open(project: ISaengineProject, stage: IProjectStage): Promise<void> {
		const part = stage.focus && projectParts(project.type).find(p => p.id === stage.focus!.part);
		if (!part) {
			return;
		}
		if (stage.section) {
			await openPartSection(project, part, { id: stage.section, label: stage.label, sections: [stage.section] }, { editorService: this.editorService, commandService: this.commandService });
		} else {
			await openPart(project, part, { editorService: this.editorService, fileService: this.fileService, openerService: this.openerService, commandService: this.commandService });
		}
	}

	/** Left and Right (and Home, End) move between the stages; Enter and Space open one (the button's own). */
	private onKeyDown(event: StandardKeyboardEvent): void {
		const count = this.buttons.length;
		if (!count) {
			return;
		}
		let index: number | undefined;
		if (event.equals(KeyCode.RightArrow)) {
			index = (this.focusIndex + 1) % count;
		} else if (event.equals(KeyCode.LeftArrow)) {
			index = (this.focusIndex - 1 + count) % count;
		} else if (event.equals(KeyCode.Home)) {
			index = 0;
		} else if (event.equals(KeyCode.End)) {
			index = count - 1;
		}
		if (index !== undefined) {
			event.preventDefault();
			event.stopPropagation();
			this.buttons[index].focus();
		}
	}
}

registerWorkbenchContribution2(ProjectStageBar.ID, ProjectStageBar, WorkbenchPhase.AfterRestored);
