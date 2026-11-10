/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/officeTools.css';
import { $, addDisposableListener, append, clearNode, EventType, getWindow } from '../../../../base/browser/dom.js';
import { Action, IAction, Separator, SubmenuAction } from '../../../../base/common/actions.js';
import { VSBuffer } from '../../../../base/common/buffer.js';
import { Disposable, DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IFileDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { addDays, bimExtents, daysBetween, elementDates, ElementDates, ISchedule, OFFICE_REQUEST_COMMAND, parsePhasing, PHASING_FILE, phaseStates, PhaseState, SCHEDULE_FILE } from './officeModel.js';

/**
 * Alpha 9 L11: what the BIM view's studies call on the viewer (`@saengine/fem-viewer`'s
 * BuildingViewer from this alpha on). Optional, so the editor works with a viewer built before
 * them: a method the loaded viewer lacks is skipped.
 */
export interface IBuildingStudyViewer {
	setRenderPreset?(preset: RenderPreset): Promise<void>;
	setSun?(direction: readonly number[] | undefined): void;
	setWalkMode?(on: boolean): Promise<void>;
	exportStill?(options?: { readonly scale?: number; readonly supersample?: number }): Promise<Blob>;
	setProjectFrame?(min: readonly number[], max: readonly number[]): void;
	setTerrain?(points: readonly number[] | undefined, triangles?: readonly number[]): void;
	setConstruction?(dates: ElementDates | undefined, day: string | undefined): Promise<void>;
	setPhaseStates?(states: { readonly [element: string]: PhaseState } | undefined): Promise<void>;
}

export type RenderPreset = 'standard' | 'daylight' | 'overcast' | 'dusk' | 'clay';

const PRESETS: readonly [RenderPreset, string][] = [
	['standard', localize('bimStudies.preset.standard', "Standard")],
	['daylight', localize('bimStudies.preset.daylight', "Daylight (sun and shadows)")],
	['overcast', localize('bimStudies.preset.overcast', "Overcast")],
	['dusk', localize('bimStudies.preset.dusk', "Dusk")],
	['clay', localize('bimStudies.preset.clay', "Clay model")],
];

/**
 * The studies of the BIM view: render presets, walk mode, a high-quality still, the 4D playback
 * of the construction programme, the terrain under the building, the sun of the study day and
 * the phase filter. Their actions go into the building editor's "..." menu; the 4D playback
 * puts a bar over the view.
 */
export class BimStudies extends Disposable {

	private preset: RenderPreset = 'standard';
	private walking = false;
	private terrainShown = false;
	private phase: string | undefined;
	/** The project's phases, read when the building loads. */
	private knownPhases: readonly { readonly id: string; readonly name: string }[] = parsePhasing(undefined).phases;
	private dates: ElementDates | undefined;
	private day: string | undefined;
	private readonly barStore = this._register(new DisposableStore());
	private bar: HTMLElement | undefined;
	private timer: number | undefined;

	constructor(
		private readonly viewer: () => Promise<object | undefined>,
		private readonly overlayParent: HTMLElement,
		private readonly bimText: () => string | undefined,
		private readonly elementIds: () => Iterable<string>,
		@ICommandService private readonly commands: ICommandService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IFileService private readonly fileService: IFileService,
		@IFileDialogService private readonly fileDialogs: IFileDialogService,
		@INotificationService private readonly notifications: INotificationService,
	) {
		super();
		this._register(toDisposable(() => {
			this.stop();
			this.phaseItems.forEach(a => a.dispose());
		}));
	}

	private async study(): Promise<IBuildingStudyViewer | undefined> {
		return (await this.viewer()) as IBuildingStudyViewer | undefined;
	}

	private async read(rel: string): Promise<string | undefined> {
		const root = this.projectService.project?.root;
		if (!root) {
			return undefined;
		}
		try {
			return (await this.fileService.readFile(joinPath(root, ...rel.split('/')))).value.toString();
		} catch {
			return undefined;
		}
	}

	// The actions keep their objects (the frame updates checks in place and sets a new list only
	// when the ids change: the phase submenu's id names its phases).
	private readonly presetActions = PRESETS.map(([preset, label]) => this._register(new Action(`saengine.bim.render.${preset}`, label, undefined, true, async () => {
		this.preset = preset;
		this.presetActions.forEach(a => a.checked = a.id === `saengine.bim.render.${preset}`);
		await (await this.study())?.setRenderPreset?.(preset);
	})));
	private readonly walkAction = this._register(new Action('saengine.bim.walk', localize('bimStudies.walk', "Walk Mode (W A S D, Q E, arrows)"), undefined, true, async () => {
		this.walking = !this.walking;
		this.walkAction.checked = this.walking;
		await (await this.study())?.setWalkMode?.(this.walking);
	}));
	private readonly stillAction = this._register(new Action('saengine.bim.still', localize('bimStudies.still', "Export Still Image..."), undefined, true, () => this.exportStill()));
	private readonly sunAction = this._register(new Action('saengine.bim.sun', localize('bimStudies.sun', "Sun at Noon on the Study Day"), undefined, true, () => this.sunAtNoon()));
	private readonly fourDAction = this._register(new Action('saengine.bim.4d', localize('bimStudies.4d', "4D Playback of the Programme"), undefined, true, () => this.toggle4d()));
	private readonly terrainAction = this._register(new Action('saengine.bim.terrain', localize('bimStudies.terrain', "Show Terrain"), undefined, true, () => this.toggleTerrain()));
	private phaseMenu: SubmenuAction | undefined;
	private phaseItems: Action[] = [];

	/** The actions of the "..." menu (states shown as checks). */
	actions(): IAction[] {
		this.presetActions.forEach(a => a.checked = a.id === `saengine.bim.render.${this.preset}`);
		const key = this.knownPhases.map(p => p.id).join(',');
		if (!this.phaseMenu || this.phaseMenu.id !== `saengine.bim.phase:${key}`) {
			this.phaseItems.forEach(a => a.dispose());
			const all = new Action('saengine.bim.phase.all', localize('bimStudies.phase.all', "All Phases"), undefined, true, () => this.showPhase(undefined));
			this.phaseItems = [all, ...this.knownPhases.map(({ id, name }) => new Action(`saengine.bim.phase.${id}`, name, undefined, true, () => this.showPhase(id)))];
			this.phaseMenu = new SubmenuAction(`saengine.bim.phase:${key}`, localize('bimStudies.phase', "Phase"), this.phaseItems);
		}
		this.phaseItems.forEach(a => a.checked = a.id === `saengine.bim.phase.${this.phase ?? 'all'}`);
		return [
			new SubmenuAction('saengine.bim.render', localize('bimStudies.render', "Render"), this.presetActions),
			this.walkAction,
			this.stillAction,
			this.sunAction,
			new Separator(),
			this.fourDAction,
			this.terrainAction,
			this.phaseMenu,
		];
	}

	/** After the building was (re)loaded in the viewer: the frame, terrain, 4D day and phase again. */
	async afterLoad(): Promise<void> {
		const viewer = await this.study();
		if (!viewer) {
			return;
		}
		this.knownPhases = parsePhasing(await this.read(PHASING_FILE)).phases;
		const extents = bimExtents(this.bimText());
		if (extents) {
			viewer.setProjectFrame?.(extents.min, extents.max);
		}
		if (this.preset !== 'standard') {
			await viewer.setRenderPreset?.(this.preset);
		}
		if (this.terrainShown) {
			await this.loadTerrain(viewer);
		}
		if (this.dates) {
			await viewer.setConstruction?.(this.dates, this.day);
		}
		if (this.phase) {
			await this.showPhase(this.phase);
		}
	}

	private async exportStill(): Promise<void> {
		const viewer = await this.study();
		if (!viewer?.exportStill) {
			this.notifications.info(localize('bimStudies.noStill', "This 3D view cannot export stills yet (update SAEngine)."));
			return;
		}
		const root = this.projectService.project?.root;
		const target = await this.fileDialogs.showSaveDialog({ defaultUri: root ? joinPath(root, '11 Exports', 'render.png') : undefined, filters: [{ name: 'PNG', extensions: ['png'] }] });
		if (!target) {
			return;
		}
		const blob = await viewer.exportStill({ scale: 2, supersample: 2 });
		await this.fileService.writeFile(target, VSBuffer.wrap(new Uint8Array(await blob.arrayBuffer())));
		this.notifications.info(localize('bimStudies.stillWritten', "Still written: {0}", target.fsPath));
	}

	private async sunAtNoon(): Promise<void> {
		const root = this.projectService.project?.root;
		if (!root) {
			return;
		}
		const answer = await this.commands.executeCommand<{ problems?: string[]; path?: { hour: number; direction: number[] }[] }>(OFFICE_REQUEST_COMMAND, 'office/sun', { projectRoot: root.fsPath });
		if (answer?.problems?.length) {
			this.notifications.warn(answer.problems.join(' '));
			return;
		}
		const path = answer?.path ?? [];
		const noon = path.reduce<{ hour: number; direction: number[] } | undefined>((best, s) => !best || Math.abs(s.hour - 12) < Math.abs(best.hour - 12) ? s : best, undefined);
		const viewer = await this.study();
		if (this.preset === 'standard') {
			this.preset = 'daylight';
			await viewer?.setRenderPreset?.('daylight');
		}
		viewer?.setSun?.(noon?.direction);
	}

	private async toggleTerrain(): Promise<void> {
		this.terrainShown = !this.terrainShown;
		this.terrainAction.checked = this.terrainShown;
		const viewer = await this.study();
		if (!viewer) {
			return;
		}
		if (this.terrainShown) {
			await this.loadTerrain(viewer);
		} else {
			viewer.setTerrain?.(undefined);
		}
	}

	private async loadTerrain(viewer: IBuildingStudyViewer): Promise<void> {
		const root = this.projectService.project?.root;
		if (!root) {
			return;
		}
		const mesh = await this.commands.executeCommand<{ points?: number[]; triangles?: number[] }>(OFFICE_REQUEST_COMMAND, 'office/terrainMesh', { projectRoot: root.fsPath });
		if (!mesh?.points?.length) {
			this.notifications.info(localize('bimStudies.noTerrain', "The project has no terrain: import a survey in Office Tools > Site and Environment."));
			this.terrainShown = false;
			this.terrainAction.checked = false;
			return;
		}
		viewer.setTerrain?.(mesh.points, mesh.triangles);
	}

	private async showPhase(phase: string | undefined): Promise<void> {
		this.phase = phase;
		this.phaseItems.forEach(a => a.checked = a.id === `saengine.bim.phase.${phase ?? 'all'}`);
		const viewer = await this.study();
		if (!phase) {
			await viewer?.setPhaseStates?.(undefined);
			return;
		}
		const phasing = parsePhasing(await this.read(PHASING_FILE));
		if (!phasing.phases.some(p => p.id === phase)) {
			this.notifications.info(localize('bimStudies.noPhase', "06 BIM/phasing.json has no phase '{0}'.", phase));
			return;
		}
		await viewer?.setPhaseStates?.(phaseStates(phasing, this.elementIds(), phase));
	}

	// ─────────────────────────────── 4D playback ───────────────────────────────

	/**
	 * W4C-13 (walk 4): opens the 4D bar (the programme's dates, a slider and Play) when it is not
	 * open, for "Play in the BIM View" of Office Tools > 4D Programme; with `autoplay` it starts.
	 */
	async play4d(autoplay = false): Promise<void> {
		if (!this.bar) {
			await this.toggle4d();
		}
		if (autoplay && this.bar && !this.timer) {
			this.bar.querySelector<HTMLButtonElement>('button.office-button')?.click();
		}
	}

	private async toggle4d(): Promise<void> {
		if (this.bar) {
			this.stop();
			this.bar.remove();
			this.bar = undefined;
			this.barStore.clear();
			this.dates = undefined;
			this.day = undefined;
			this.fourDAction.checked = false;
			await (await this.study())?.setConstruction?.(undefined, undefined);
			return;
		}
		const text = await this.read(SCHEDULE_FILE);
		let schedule: ISchedule | undefined;
		try {
			schedule = text ? JSON.parse(text) as ISchedule : undefined;
		} catch {
			schedule = undefined;
		}
		if (!schedule?.activities?.length) {
			this.notifications.info(localize('bimStudies.noSchedule', "The project has no programme: generate it in Office Tools > 4D Programme."));
			return;
		}
		this.dates = elementDates(schedule);
		this.fourDAction.checked = true;
		const start = schedule.start;
		const finish = schedule.finish ?? addDays(start, 30);
		const total = Math.max(daysBetween(start, finish) + 1, 1);
		this.day = start;
		const bar = this.bar = append(this.overlayParent, $('.office-4d-bar'));
		const play = append(bar, $<HTMLButtonElement>('button.office-button', { type: 'button' }, localize('bimStudies.play', "Play")));
		const slider = append(bar, $<HTMLInputElement>('input', { type: 'range', min: '0', max: String(total), value: '0' }));
		const label = append(bar, $('span.office-4d-day'));
		const show = async (offset: number) => {
			this.day = addDays(start, offset);
			slider.value = String(offset);
			clearNode(label);
			const building = schedule!.activities.filter(a => a.earlyStart && a.earlyFinish && a.earlyStart <= this.day! && this.day! <= a.earlyFinish).map(a => a.name);
			label.textContent = localize('bimStudies.day', "{0}: {1}", this.day, building.slice(0, 2).join(', ') || localize('bimStudies.nothing', "no work"));
			await (await this.study())?.setConstruction?.(this.dates, this.day);
		};
		this.barStore.add(addDisposableListener(slider, EventType.INPUT, () => void show(Number(slider.value))));
		this.barStore.add(addDisposableListener(play, EventType.CLICK, () => {
			if (this.timer) {
				this.stop();
				play.textContent = localize('bimStudies.play', "Play");
				return;
			}
			play.textContent = localize('bimStudies.pause', "Pause");
			const step = Math.max(1, Math.round(total / 120));
			this.timer = getWindow(this.overlayParent).setInterval(() => {
				const next = Number(slider.value) + step;
				if (next > total) {
					this.stop();
					play.textContent = localize('bimStudies.play', "Play");
					return;
				}
				void show(next);
			}, 250);
		}));
		await show(0);
	}

	private stop(): void {
		if (this.timer) {
			getWindow(this.overlayParent).clearInterval(this.timer);
			this.timer = undefined;
		}
	}
}
