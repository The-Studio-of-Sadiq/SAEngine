/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { IProgress, IProgressStep } from '../../../../platform/progress/common/progress.js';

/*
 * One place for SAEngine's long jobs (Run All, Design Reinforcement, drawings, the report,
 * imports): each job reports its steps here, one status bar item shows the job going and the
 * Progress view lists the jobs with their steps. Notifications are kept for what needs a
 * decision and for errors; a job that went well ends in the Progress view, not in a toast.
 */

export type JobState = 'running' | 'done' | 'warning' | 'failed' | 'cancelled';
export type JobStepState = 'pending' | 'running' | 'done' | 'warning' | 'failed' | 'skipped' | 'cancelled';

export interface IJobStep {
	readonly label: string;
	readonly state: JobStepState;
	/** What the step is doing, or how it ended ("12 members designed", the error). */
	readonly detail?: string;
	/** How long it took [s], once it ended. */
	readonly seconds?: number;
}

/** A follow-up the finished job offers (Open Report, Show Results). */
export interface IJobAction {
	readonly label: string;
	run(): unknown;
}

export interface ISaengineJob {
	readonly id: number;
	readonly title: string;
	readonly state: JobState;
	/** Start and end [ms since the epoch]. */
	readonly started: number;
	readonly ended?: number;
	readonly steps: readonly IJobStep[];
	/** Whether the steps were known up front (counted "6/11"), or came with the progress messages. */
	readonly planned: boolean;
	/** What a job without steps is doing now ("Sheet S-03 (3 of 12)"). */
	readonly detail?: string;
	/** How it ended, in words. */
	readonly message?: string;
	readonly actions: readonly IJobAction[];
	/** Whether Stop can end it (while it runs). */
	readonly cancellable: boolean;
}

export interface IJobOptions {
	readonly title: string;
	/** The steps known up front (Run All's); without them each progress message adds a step. */
	readonly steps?: readonly string[];
	/** Stops the job (the Progress view's and the status bar's Stop). */
	readonly cancel?: () => void;
}

/** The job's side of a running job. */
export interface IJobHandle {
	readonly id: number;
	/** Messages as steps: each new message ends the running step and starts the next (withProgress's `report`). */
	readonly progress: IProgress<IProgressStep>;
	/** Starts step `index` of the planned steps (the running one ends done, unless it ended already). */
	startStep(index: number, detail?: string): void;
	/** What the running step (the job, when no step runs) is doing now. */
	report(detail: string | undefined): void;
	/** Ends step `index` as `state`. */
	endStep(index: number, state: JobStepState, detail?: string, seconds?: number): void;
	/** Ends the job; a running step ends as the job does. */
	end(state: Exclude<JobState, 'running'>, message?: string, actions?: readonly IJobAction[]): void;
}

export const ISaengineJobsService = createDecorator<ISaengineJobsService>('saengineJobsService');

export interface ISaengineJobsService {
	readonly _serviceBrand: undefined;

	/** The jobs of this window, the newest first: the running ones and the last finished ones. */
	readonly jobs: readonly ISaengineJob[];
	readonly onDidChange: Event<void>;

	start(options: IJobOptions): IJobHandle;

	/**
	 * Runs `task` as a job, the way `IProgressService.withProgress` runs it: its progress
	 * messages become steps. The job ends done when the task resolves and failed when it throws
	 * (the error is thrown on: the caller says what went wrong).
	 */
	run<T>(options: IJobOptions, task: (progress: IProgress<IProgressStep>, job: IJobHandle) => Promise<T>): Promise<T>;

	cancel(id: number): void;

	/** Opens the Progress view, on job `id` if given. */
	show(id?: number): Promise<void>;
}

/** How many finished jobs the list keeps. */
export const FINISHED_JOBS_KEPT = 10;

interface IMutableJob {
	id: number;
	title: string;
	state: JobState;
	started: number;
	ended?: number;
	steps: IJobStep[];
	readonly planned: boolean;
	detail?: string;
	message?: string;
	actions: readonly IJobAction[];
	cancel?: () => void;
	readonly cancellable: boolean;
}

/** The jobs and their steps, without the UI (the service and the tests share it). */
export class SaengineJobs extends Disposable {

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange = this._onDidChange.event;

	private readonly list: IMutableJob[] = [];
	private nextId = 1;

	constructor(private readonly now: () => number = Date.now) {
		super();
	}

	get jobs(): readonly ISaengineJob[] {
		return this.list;
	}

	start(options: IJobOptions): IJobHandle {
		const job: IMutableJob = {
			id: this.nextId++,
			title: options.title,
			state: 'running',
			started: this.now(),
			steps: (options.steps ?? []).map(label => ({ label, state: 'pending' })),
			planned: !!options.steps?.length,
			actions: [],
			cancel: options.cancel,
			cancellable: !!options.cancel,
		};
		this.list.unshift(job);
		this.prune();
		this._onDidChange.fire();

		const running = () => job.steps.findIndex(step => step.state === 'running');
		const set = (index: number, step: IJobStep) => {
			job.steps[index] = step;
			this._onDidChange.fire();
		};
		const handle: IJobHandle = {
			id: job.id,
			progress: {
				report: value => {
					if (job.state !== 'running' || !value.message) {
						return;
					}
					const current = running();
					if (current >= 0 && job.steps[current].label === value.message) {
						return;
					}
					if (current >= 0) {
						job.steps[current] = { ...job.steps[current], state: 'done' };
					}
					job.steps.push({ label: value.message, state: 'running' });
					this._onDidChange.fire();
				},
			},
			startStep: (index, detail) => {
				if (job.state !== 'running' || !job.steps[index]) {
					return;
				}
				const current = running();
				if (current >= 0 && current !== index) {
					job.steps[current] = { ...job.steps[current], state: 'done' };
				}
				set(index, { label: job.steps[index].label, state: 'running', detail });
			},
			report: detail => {
				if (job.state !== 'running') {
					return;
				}
				const current = running();
				if (current >= 0) {
					if (job.steps[current].detail !== detail) {
						set(current, { ...job.steps[current], detail });
					}
				} else if (job.detail !== detail) {
					job.detail = detail;
					this._onDidChange.fire();
				}
			},
			endStep: (index, state, detail, seconds) => {
				if (job.steps[index]) {
					set(index, { label: job.steps[index].label, state, detail, seconds });
				}
			},
			end: (state, message, actions) => {
				if (job.state !== 'running') {
					return;
				}
				const current = running();
				if (current >= 0) {
					job.steps[current] = { ...job.steps[current], state };
				}
				job.state = state;
				job.detail = undefined;
				job.ended = this.now();
				job.message = message;
				job.actions = actions ?? [];
				job.cancel = undefined;
				this.prune();
				this._onDidChange.fire();
			},
		};
		return handle;
	}

	async run<T>(options: IJobOptions, task: (progress: IProgress<IProgressStep>, job: IJobHandle) => Promise<T>): Promise<T> {
		const job = this.start(options);
		try {
			const result = await task(job.progress, job);
			job.end('done');
			return result;
		} catch (error) {
			job.end('failed', error instanceof Error ? error.message : String(error));
			throw error;
		}
	}

	cancel(id: number): void {
		const job = this.list.find(j => j.id === id);
		if (job?.state === 'running' && job.cancel) {
			job.cancel();
		}
	}

	/** Drops the oldest finished jobs beyond {@link FINISHED_JOBS_KEPT}. */
	private prune(): void {
		let finished = 0;
		for (let i = 0; i < this.list.length; i++) {
			if (this.list[i].state !== 'running' && ++finished > FINISHED_JOBS_KEPT) {
				this.list.splice(i--, 1);
			}
		}
	}
}

/** The running step of `job`, with its number (1-based) among the planned steps. */
export function runningStep(job: ISaengineJob): { readonly index: number; readonly step: IJobStep } | undefined {
	const index = job.steps.findIndex(step => step.state === 'running');
	return index >= 0 ? { index, step: job.steps[index] } : undefined;
}

/** "4:05" of seconds; "1:02:10" past an hour (Run All's times, the Progress view's). */
export function formatDuration(seconds: number): string {
	const total = Math.max(0, Math.round(seconds));
	const s = total % 60;
	const m = Math.floor(total / 60) % 60;
	const h = Math.floor(total / 3600);
	const pad = (n: number) => String(n).padStart(2, '0');
	return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
