/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/progressView.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { IntervalTimer, RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IProgress, IProgressStep } from '../../../../platform/progress/common/progress.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewDescriptorService, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { formatDuration, IJobHandle, IJobOptions, ISaengineJob, ISaengineJobsService, JobState, JobStepState, runningStep, SaengineJobs } from '../../../services/saengineProject/common/saengineJobs.js';
import { IStatusbarEntry, IStatusbarEntryAccessor, IStatusbarService, StatusbarAlignment } from '../../../services/statusbar/browser/statusbar.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';

/*
 * The one progress place of SAEngine's long jobs (saengineJobs.ts): one status bar item for the
 * job going (and, for a while, how the last one ended) and the Progress view in the panel with
 * the jobs, their steps and the follow-ups of the finished ones.
 */

export const PROGRESS_VIEW_CONTAINER_ID = 'workbench.panel.saengineProgress';
export const PROGRESS_VIEW_ID = 'saengine.progress';
export const SHOW_PROGRESS_COMMAND = 'saengine.showProgress';
const STATUS_ENTRY_ID = 'saengine.jobs.status';
/** How long the status bar item shows how the last job ended [ms]. */
const FINISHED_SHOWN_MS = 15_000;

//#region Service

class SaengineJobsService extends Disposable implements ISaengineJobsService {

	declare readonly _serviceBrand: undefined;

	private readonly model = this._register(new SaengineJobs());
	readonly onDidChange = this.model.onDidChange;
	constructor(@IViewsService private readonly viewsService: IViewsService) {
		super();
	}

	get jobs(): readonly ISaengineJob[] {
		return this.model.jobs;
	}

	start(options: IJobOptions): IJobHandle {
		return this.model.start(options);
	}

	run<T>(options: IJobOptions, task: (progress: IProgress<IProgressStep>, job: IJobHandle) => Promise<T>): Promise<T> {
		return this.model.run(options, task);
	}

	cancel(id: number): void {
		this.model.cancel(id);
	}

	async show(id?: number): Promise<void> {
		const view = await this.viewsService.openView<ProgressView>(PROGRESS_VIEW_ID, true);
		view?.reveal(id);
	}
}

registerSingleton(ISaengineJobsService, SaengineJobsService, InstantiationType.Delayed);

//#endregion

//#region Words and icons

function jobIcon(state: JobState): ThemeIcon {
	switch (state) {
		case 'running': return ThemeIcon.modify(Codicon.sync, 'spin');
		case 'done': return Codicon.passFilled;
		case 'warning': return Codicon.warning;
		case 'failed': return Codicon.error;
		case 'cancelled': return Codicon.debugStop;
	}
}

function stepIcon(state: JobStepState): ThemeIcon {
	switch (state) {
		case 'running': return ThemeIcon.modify(Codicon.loading, 'spin');
		case 'done': return Codicon.check;
		case 'warning': return Codicon.warning;
		case 'failed': return Codicon.error;
		case 'cancelled': return Codicon.debugStop;
		case 'skipped': return Codicon.dash;
		default: return Codicon.circleSmall;
	}
}

function jobStateLabel(state: JobState): string {
	switch (state) {
		case 'running': return localize('job.running', "running");
		case 'done': return localize('job.done', "done");
		case 'warning': return localize('job.warning', "done, with notes");
		case 'failed': return localize('job.failed', "failed");
		case 'cancelled': return localize('job.cancelled', "stopped");
	}
}

function stepStateLabel(state: JobStepState): string {
	switch (state) {
		case 'running': return localize('jobStep.running', "running");
		case 'done': return localize('jobStep.done', "done");
		case 'warning': return localize('jobStep.warning', "with notes");
		case 'failed': return localize('jobStep.failed', "failed");
		case 'cancelled': return localize('jobStep.cancelled', "stopped");
		case 'skipped': return localize('jobStep.skipped', "not run");
		default: return localize('jobStep.pending', "to do");
	}
}

/** The time of a job: so far while it runs, in total once it ended. */
function jobTime(job: ISaengineJob, now: number): string {
	return formatDuration(((job.ended ?? now) - job.started) / 1000);
}

//#endregion

//#region Status bar

/**
 * The one status bar item of the jobs: "Run All 6/11: design checks · 2:05" while one runs (with
 * "+1" for others), how the last one ended for a while after; click opens the Progress view.
 */
class JobsStatusContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.jobsStatus';

	private readonly entry = this._register(new MutableDisposable<IStatusbarEntryAccessor>());
	private readonly ticker = this._register(new IntervalTimer());
	private readonly hide = this._register(new RunOnceScheduler(() => this.update(), FINISHED_SHOWN_MS));

	constructor(
		@ISaengineJobsService private readonly jobsService: ISaengineJobsService,
		@IStatusbarService private readonly statusbarService: IStatusbarService,
	) {
		super();
		this._register(jobsService.onDidChange(() => this.update()));
		this.update();
	}

	private update(): void {
		const now = Date.now();
		const jobs = this.jobsService.jobs;
		const running = jobs.filter(job => job.state === 'running');
		const last = jobs.find(job => job.state !== 'running');
		let entry: IStatusbarEntry | undefined;
		if (running.length) {
			const job = running[running.length - 1];
			const step = runningStep(job);
			const planned = job.planned ? job.steps.length : undefined;
			let text = job.title;
			if (!step && job.detail) {
				text = localize('jobs.statusMessage', "{0}: {1}", job.title, job.detail);
			} else if (step) {
				text = planned
					? localize('jobs.statusStep', "{0} {1}/{2}: {3}", job.title, step.index + 1, planned, step.step.label)
					: localize('jobs.statusMessage', "{0}: {1}", job.title, step.step.label);
			}
			text = `${text} · ${jobTime(job, now)}`;
			if (running.length > 1) {
				text += ` (+${running.length - 1})`;
			}
			const lines = [text];
			if (step?.step.detail) {
				lines.push(step.step.detail);
			}
			lines.push(localize('jobs.statusClick', "Click to show the progress and the steps."));
			entry = {
				name: localize('jobs.statusName', "SAEngine Progress"),
				text: `$(sync~spin) ${text}`,
				ariaLabel: lines.join('. '),
				tooltip: lines.join('\n'),
				command: SHOW_PROGRESS_COMMAND,
			};
			this.ticker.cancelAndSet(() => this.update(), 1000);
			this.hide.cancel();
		} else {
			this.ticker.cancel();
			if (last?.ended !== undefined && now - last.ended < FINISHED_SHOWN_MS) {
				const text = localize('jobs.statusEnded', "{0}: {1}", last.title, jobStateLabel(last.state));
				entry = {
					name: localize('jobs.statusName', "SAEngine Progress"),
					text: `$(${jobIcon(last.state).id}) ${text}`,
					ariaLabel: last.message ? `${text}. ${last.message}` : text,
					tooltip: [text, last.message, localize('jobs.statusClick', "Click to show the progress and the steps.")].filter(Boolean).join('\n'),
					command: SHOW_PROGRESS_COMMAND,
				};
				this.hide.schedule(FINISHED_SHOWN_MS - (now - last.ended));
			}
		}
		if (!entry) {
			this.entry.clear();
		} else if (this.entry.value) {
			this.entry.value.update(entry);
		} else {
			this.entry.value = this.statusbarService.addEntry(entry, STATUS_ENTRY_ID, StatusbarAlignment.LEFT, -100);
		}
	}
}

registerWorkbenchContribution2(JobsStatusContribution.ID, JobsStatusContribution, WorkbenchPhase.AfterRestored);

//#endregion

//#region Progress view

export class ProgressView extends ViewPane {

	static readonly ID = PROGRESS_VIEW_ID;

	private list: HTMLElement | undefined;
	/** The rendered element of each job, by id. */
	private readonly items = new Map<number, HTMLElement>();
	private readonly rendered = this._register(new DisposableStore());
	private readonly scheduler = this._register(new RunOnceScheduler(() => this.renderJobs(), 100));
	private readonly ticker = this._register(new IntervalTimer());

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@ISaengineJobsService private readonly jobsService: ISaengineJobsService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this._register(jobsService.onDidChange(() => this.scheduler.schedule()));
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		this.list = append(container, $('.sa-progress-view'));
		this.list.setAttribute('role', 'list');
		this.list.setAttribute('aria-label', localize('progress.aria', "SAEngine jobs and their steps"));
		this.renderJobs();
	}

	/** Scrolls job `id` (else the newest) into view and focuses it. */
	reveal(id: number | undefined): void {
		this.renderJobs();
		const target = id !== undefined ? this.items.get(id) : this.items.values().next().value;
		target?.scrollIntoView({ block: 'nearest' });
		target?.focus();
	}

	private renderJobs(): void {
		const list = this.list;
		if (!list) {
			return;
		}
		this.rendered.clear();
		this.items.clear();
		clearNode(list);
		const now = Date.now();
		const jobs = this.jobsService.jobs;
		if (!jobs.length) {
			append(list, $('.sa-progress-empty', undefined, localize('progress.empty', "Long jobs (Run All, Design Reinforcement, drawings, the report, imports) show their progress and their steps here.")));
		}
		for (const job of jobs) {
			this.renderJob(list, job, now);
		}
		if (jobs.some(job => job.state === 'running')) {
			this.ticker.cancelAndSet(() => this.renderJobs(), 1000);
		} else {
			this.ticker.cancel();
		}
	}

	private renderJob(list: HTMLElement, job: ISaengineJob, now: number): void {
		const item = append(list, $(`.sa-progress-job.sa-job-${job.state}`));
		item.setAttribute('role', 'listitem');
		this.items.set(job.id, item);
		item.tabIndex = -1;
		const header = append(item, $('.sa-progress-job-header'));
		append(header, $(`span.sa-progress-icon${ThemeIcon.asCSSSelector(jobIcon(job.state))}`)).setAttribute('aria-hidden', 'true');
		append(header, $('span.sa-progress-title', undefined, job.title));
		append(header, $('span.sa-progress-meta', undefined, `${jobStateLabel(job.state)} · ${jobTime(job, now)}`));
		item.setAttribute('aria-label', localize('progress.jobAria', "{0}: {1}, {2}", job.title, jobStateLabel(job.state), jobTime(job, now)));
		if (job.state === 'running' && job.cancellable) {
			const stop = append(header, $('a.sa-progress-link', { role: 'button', tabindex: '0' }, localize('progress.stop', "Stop")));
			this.rendered.add(addDisposableListener(stop, EventType.CLICK, () => this.jobsService.cancel(job.id)));
			this.rendered.add(addDisposableListener(stop, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					this.jobsService.cancel(job.id);
				}
			}));
		}
		const message = job.message ?? job.detail;
		if (message) {
			append(item, $('.sa-progress-message', undefined, message));
		}
		if (job.actions.length) {
			const actions = append(item, $('.sa-progress-actions'));
			for (const action of job.actions) {
				const link = append(actions, $('a.sa-progress-link', { role: 'button', tabindex: '0' }, action.label));
				this.rendered.add(addDisposableListener(link, EventType.CLICK, () => action.run()));
				this.rendered.add(addDisposableListener(link, EventType.KEY_DOWN, e => {
					if (e.key === 'Enter' || e.key === ' ') {
						e.preventDefault();
						action.run();
					}
				}));
			}
		}
		if (job.steps.length) {
			const steps = append(item, $('ol.sa-progress-steps'));
			for (const step of job.steps) {
				const row = append(steps, $(`li.sa-progress-step.sa-step-${step.state}`));
				append(row, $(`span.sa-progress-icon${ThemeIcon.asCSSSelector(stepIcon(step.state))}`)).setAttribute('aria-hidden', 'true');
				append(row, $('span.sa-progress-step-label', undefined, step.label));
				const meta = [step.state !== 'done' && step.state !== 'running' ? stepStateLabel(step.state) : undefined, step.seconds !== undefined && step.seconds >= 1 ? formatDuration(step.seconds) : undefined].filter(Boolean).join(' · ');
				if (meta) {
					append(row, $('span.sa-progress-meta', undefined, meta));
				}
				if (step.detail) {
					append(row, $('div.sa-progress-step-detail', undefined, step.detail));
				}
				row.setAttribute('aria-label', [step.label, stepStateLabel(step.state), step.detail].filter(Boolean).join(', '));
			}
		}
	}
}

const progressViewIcon = registerIcon('saengine-progress-view-icon', Codicon.pulse, localize('progressViewIcon', "View icon of the SAEngine progress view."));

const progressContainer = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry).registerViewContainer({
	id: PROGRESS_VIEW_CONTAINER_ID,
	title: localize2('progress', "Progress"),
	icon: progressViewIcon,
	order: -1,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [PROGRESS_VIEW_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: PROGRESS_VIEW_CONTAINER_ID,
}, ViewContainerLocation.Panel, { doNotRegisterOpenCommand: true });

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViews([{
	id: PROGRESS_VIEW_ID,
	name: localize2('progress', "Progress"),
	containerIcon: progressViewIcon,
	ctorDescriptor: new SyncDescriptor(ProgressView),
	canToggleVisibility: false,
	canMoveView: true,
	order: 0,
}], progressContainer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: SHOW_PROGRESS_COMMAND,
			title: localize2('saengine.showProgress', "Show Progress"),
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
		});
	}

	override run(accessor: ServicesAccessor): Promise<void> {
		return accessor.get(ISaengineJobsService).show();
	}
});

//#endregion
