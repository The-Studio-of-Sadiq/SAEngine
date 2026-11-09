/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/femResultsView.css';
import './media/femCfdWind.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Action } from '../../../../base/common/actions.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { IntervalTimer } from '../../../../base/common/async.js';
import { DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IDialogService } from '../../../../platform/dialogs/common/dialogs.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { EditorInputCapabilities, IEditorOpenContext, IEditorSerializer, IUntypedEditorInput } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow, EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { renderSheet } from './femChart.js';

/*
 * Alpha 9 L3: the CFD wind tunnel, an optional link to the user's own OpenFOAM (never bundled or
 * downloaded by SAEngine). The page finds OpenFOAM (WSL on Windows) or shows how to install it,
 * writes one OpenFOAM case per wind direction from the building's envelope, runs them in the
 * background when the user presses Run (progress, Cancel), and shows the pressure coefficients
 * per facade zone and storey, the storey forces and their comparison with the code's static wind.
 * The settings live in Project Settings > Wind > CFD wind tunnel (one home); the backend is
 * `saengine.fem.cfd_wind` over the `cfd/*` methods (electron-browser/saengineFem.contribution.ts).
 * The results are engineer-supplied loads that need validation: the page says so first.
 */

/** Opens the CFD Wind Tunnel page of the project. */
export const CFD_WIND_COMMAND = 'saengine.fem.cfdWind';
/** `{}` -> the installation found (`cfd/detect`) with `install` steps. Internal. */
export const CFD_DETECT_COMMAND = 'saengine.fem.cfd.detect';
/** `{projectRoot, installation?}` -> the cases written (`cfd/write`). Internal. */
export const CFD_WRITE_COMMAND = 'saengine.fem.cfd.write';
/** `{projectRoot}` -> the run started (`cfd/start`). Internal. */
export const CFD_START_COMMAND = 'saengine.fem.cfd.start';
/** `{projectRoot}` -> the run's status (`cfd/status`). Internal. */
export const CFD_STATUS_COMMAND = 'saengine.fem.cfd.status';
/** `{projectRoot}` -> asks the run to stop (`cfd/cancel`). Internal. */
export const CFD_CANCEL_COMMAND = 'saengine.fem.cfd.cancel';
/** `{projectRoot}` -> the coefficients and storey forces (`cfd/results`). Internal. */
export const CFD_RESULTS_COMMAND = 'saengine.fem.cfd.results';
/** The OpenFOAM installation to use: its `etc/bashrc` (inside WSL on Windows) or install folder. */
export const CFD_OPENFOAM_SETTING = 'saengine.cfdWind.openfoam';
/** The WSL distribution OpenFOAM is installed in (Windows); empty: the default one. */
export const CFD_WSL_SETTING = 'saengine.cfdWind.wslDistribution';

const PROJECT_SETTINGS_COMMAND = 'saengine.project.openSettings';
const STATUS_POLL_MS = 3000;
const INSTALLATION_KEY = 'saengine.cfdWind.installation';

export interface ICfdInstallation {
	readonly found: boolean;
	readonly mode?: string;
	readonly distribution?: string | null;
	readonly distributions?: readonly string[];
	readonly bashrc?: string | null;
	readonly version?: string | null;
	readonly flavour?: string | null;
	readonly solver?: string | null;
	readonly parallel?: boolean;
	readonly cores?: number | null;
	readonly problems?: readonly string[];
	readonly install?: readonly string[];
}

export interface ICfdDirectionStatus {
	readonly angle: number;
	readonly case?: string;
	readonly state: string;
	readonly step?: string;
	readonly iteration?: number | null;
	readonly iterations?: number | null;
	readonly message?: string | null;
}

export interface ICfdStatus {
	readonly state: string;
	readonly progress?: number;
	readonly message?: string | null;
	readonly directions?: readonly ICfdDirectionStatus[];
}

interface ICfdDirectionRow {
	readonly angle: number;
	readonly case: string;
	readonly converged?: boolean | null;
	readonly iterations?: number | null;
	readonly Vx_kN?: number;
	readonly Vy_kN?: number;
	readonly T_kNm?: number;
	readonly shareX?: number | null;
	readonly shareY?: number | null;
	readonly CFx_m2: number;
	readonly CFy_m2: number;
}

interface ICfdStoreyRow {
	readonly z_m: number;
	readonly CFx_m2: number;
	readonly CFy_m2: number;
	readonly CMz_m3: number;
	readonly cfAlong?: number | null;
	readonly Fx_kN?: number;
	readonly Fy_kN?: number;
	readonly Mz_kNm?: number;
}

interface ICfdZoneRow {
	readonly z_m: number;
	readonly zone: string;
	readonly role: string;
	readonly area_m2: number;
	readonly cpMean: number;
	readonly cpMin: number;
	readonly cpMax: number;
}

export interface ICfdResults {
	readonly available: boolean;
	readonly reason?: string;
	readonly complete?: boolean;
	readonly stale?: boolean;
	readonly q_kPa?: number | null;
	readonly height_m?: number;
	readonly code?: { readonly X: { readonly V_kN: number }; readonly Y: { readonly V_kN: number } } | null;
	readonly pack?: { readonly name?: string; readonly covers?: boolean; readonly validation?: string; readonly procedure?: string; readonly lowerLimit?: number | null };
	readonly directions?: readonly ICfdDirectionRow[];
	readonly storeys?: readonly { readonly angle: number; readonly rows: readonly ICfdStoreyRow[] }[];
	readonly zones?: readonly { readonly angle: number; readonly rows: readonly ICfdZoneRow[] }[];
	readonly useInAnalysis?: boolean;
	readonly notes?: readonly string[];
}

const cfdIcon = registerIcon('saengine-fem-cfd-wind-label-icon', Codicon.symbolEvent, localize('femCfdLabelIcon', "Icon of the CFD Wind Tunnel page label."));

/** The CFD Wind Tunnel page of a project (its root folder). */
export class FemCfdWindInput extends EditorInput {

	static readonly ID = 'workbench.input.saengine.femCfdWind';
	static readonly EDITOR_ID = 'workbench.editor.saengine.femCfdWind';

	constructor(readonly root: URI) {
		super();
	}

	override get resource(): URI | undefined {
		return undefined;
	}

	override get typeId(): string {
		return FemCfdWindInput.ID;
	}

	override get editorId(): string {
		return FemCfdWindInput.EDITOR_ID;
	}

	override get capabilities(): EditorInputCapabilities {
		return EditorInputCapabilities.Singleton;
	}

	override getName(): string {
		return localize('femCfd.tabTitle', "CFD Wind Tunnel");
	}

	override getIcon(): ThemeIcon {
		return cfdIcon;
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		if (super.matches(other)) {
			return true;
		}
		return other instanceof FemCfdWindInput && other.root.toString() === this.root.toString();
	}
}

export class FemCfdWindInputSerializer implements IEditorSerializer {

	canSerialize(): boolean {
		return true;
	}

	serialize(editor: FemCfdWindInput): string {
		return JSON.stringify({ root: editor.root.toJSON() });
	}

	deserialize(_instantiationService: IInstantiationService, serialized: string): FemCfdWindInput {
		const { root } = JSON.parse(serialized);
		return new FemCfdWindInput(URI.revive(root));
	}
}

function fixed(value: number | null | undefined, digits = 1): string {
	return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '-';
}

/** A run's state in words. */
export function cfdStateLabel(state: string | undefined): string {
	switch (state) {
		case 'starting': return localize('femCfd.state.starting', "Starting");
		case 'running': return localize('femCfd.state.running', "Running");
		case 'done': return localize('femCfd.state.done', "Done");
		case 'failed': return localize('femCfd.state.failed', "Failed");
		case 'cancelled': return localize('femCfd.state.cancelled', "Cancelled");
		case 'stopped': return localize('femCfd.state.stopped', "Stopped");
		case 'waiting': return localize('femCfd.state.waiting', "Waiting");
		default: return localize('femCfd.state.none', "Not run");
	}
}

/** Whether a status is of a run still going. */
export function cfdRunning(status: ICfdStatus | undefined): boolean {
	return status?.state === 'starting' || status?.state === 'running';
}

/**
 * CFD Wind Tunnel: find OpenFOAM, write the cases, run them in the background, and read the
 * pressure coefficients and storey forces (see the comment at the top of this file).
 */
export class FemCfdWindEditor extends EditorPane {

	static readonly ID = FemCfdWindInput.EDITOR_ID;

	private frame!: EditorFrame;
	private body!: HTMLElement;
	private installation: ICfdInstallation | undefined;
	private status: ICfdStatus | undefined;
	private results: ICfdResults | undefined;
	private settings: Record<string, unknown> | undefined;
	private shownAngle: number | undefined;
	private busy = false;
	private request = 0;

	private readonly renderStore = this._register(new DisposableStore());
	private readonly poll = this._register(new MutableDisposable());

	private readonly findAction = this._register(new Action('saengine.fem.cfd.find', localize('femCfd.find', "Find OpenFOAM"), ThemeIcon.asClassName(Codicon.search), true, () => this.detect()));
	private readonly writeAction = this._register(new Action('saengine.fem.cfd.writeCases', localize('femCfd.write', "Write Cases"), ThemeIcon.asClassName(Codicon.fileCode), true, () => this.writeCases()));
	private readonly runAction = this._register(new Action('saengine.fem.cfd.run', localize('femCfd.run', "Run CFD..."), ThemeIcon.asClassName(Codicon.play), true, () => this.run()));
	private readonly cancelAction = this._register(new Action('saengine.fem.cfd.cancelRun', localize('femCfd.cancel', "Cancel Run"), ThemeIcon.asClassName(Codicon.debugStop), false, () => this.cancel()));
	private readonly refreshAction = this._register(new Action('saengine.fem.cfd.refresh', localize('femCfd.refresh', "Refresh"), ThemeIcon.asClassName(Codicon.refresh), true, () => this.load()));
	private readonly folderAction = this._register(new Action('saengine.fem.cfd.folder', localize('femCfd.folder', "Reveal Cases in File Explorer"), undefined, true, async () => {
		const root = this.root;
		if (root) {
			await this.commandService.executeCommand('revealFileInOS', joinPath(root, '08 FEM', 'cfd-wind'));
		}
	}));
	private readonly openfoamSettingAction = this._register(new Action('saengine.fem.cfd.setting', localize('femCfd.setting', "Set the OpenFOAM Location..."), undefined, true, async () => {
		await this.commandService.executeCommand('workbench.action.openSettings', 'saengine.cfdWind');
	}));
	private readonly projectSettingsAction = this._register(new Action('saengine.fem.cfd.projectSettings', localize('femCfd.projectSettings', "Edit in Project Settings"), undefined, true, async () => {
		await this.commandService.executeCommand(PROJECT_SETTINGS_COMMAND);
	}));

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService private readonly storage: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService,
		@IFileService private readonly fileService: IFileService,
		@IDialogService private readonly dialogService: IDialogService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(FemCfdWindEditor.ID, group, telemetryService, themeService, storage);
		try {
			const kept = this.storage.get(INSTALLATION_KEY, StorageScope.APPLICATION);
			this.installation = kept ? JSON.parse(kept) as ICfdInstallation : undefined;
		} catch {
			this.installation = undefined;
		}
	}

	protected createEditor(parent: HTMLElement): void {
		this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
			id: FemCfdWindEditor.ID,
			ariaLabel: localize('femCfd.toolbar', "CFD Wind Tunnel"),
			properties: { title: localize('femCfd.properties', "CFD Settings"), defaultWidth: 320 },
		}));
		this.frame.element.classList.add('saengine-fem-cfd-editor');
		this.frame.setTitle(localize('femCfd.title', "CFD Wind Tunnel"));
		this.frame.setHelp(localize('femCfd.help', "A steady CFD simulation (OpenFOAM) of the building in an atmospheric boundary layer, one case per wind direction: surface pressure coefficients per facade zone and storey, storey force coefficients, and the storey forces with the code's design velocity pressure, compared with the code's static wind. OpenFOAM is not part of SAEngine: install it yourself (WSL on Windows). Nothing runs until you press Run. The results are engineer-supplied loads: validate them (a wind tunnel test) before you use them for design. Project Settings > Wind > CFD wind tunnel holds the settings, and Use in the analysis turns the CFD storey forces into the wind cases."));
		this.frame.setActions(
			[this.findAction, this.writeAction, this.runAction, this.cancelAction, this.refreshAction, this.frame.togglePropertiesAction],
			[this.folderAction, this.openfoamSettingAction, this.projectSettingsAction],
		);
		this.body = append(this.frame.main, $('.fem-cfd-body'));
		this.body.tabIndex = 0;
	}

	override async setInput(input: FemCfdWindInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		await this.load();
	}

	override clearInput(): void {
		this.request++;
		this.poll.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.frame.layout(dimension.width, dimension.height);
	}

	override focus(): void {
		super.focus();
		this.body?.focus();
	}

	private get root(): URI | undefined {
		return (this.input as FemCfdWindInput | undefined)?.root;
	}

	private async engine<T>(command: string, args: object = {}): Promise<T | undefined> {
		const root = this.root;
		try {
			return await this.commandService.executeCommand<T>(command, { projectRoot: root?.fsPath, ...args });
		} catch (error) {
			this.notificationService.notify({ severity: Severity.Error, message: localize('femCfd.engineError', "CFD wind tunnel: {0}", error instanceof Error ? error.message : String(error)) });
			return undefined;
		}
	}

	private async readSettings(): Promise<void> {
		const root = this.root;
		this.settings = undefined;
		if (!root) {
			return;
		}
		try {
			const text = (await this.fileService.readFile(joinPath(root, '02 Project Settings', 'project-settings.json'))).value.toString();
			const wind = (JSON.parse(text) as { wind?: { cfd?: Record<string, unknown> | null } }).wind;
			this.settings = wind?.cfd ?? undefined;
		} catch {
			this.settings = undefined;
		}
	}

	private async load(): Promise<void> {
		const request = ++this.request;
		this.frame.setStatus({ text: localize('femCfd.loading', "Reading the CFD run..."), busy: true });
		await this.readSettings();
		const [status, results] = await Promise.all([
			this.engine<ICfdStatus>(CFD_STATUS_COMMAND),
			this.engine<ICfdResults>(CFD_RESULTS_COMMAND),
		]);
		if (request !== this.request) {
			return;
		}
		this.status = status;
		this.results = results;
		this.render();
		this.watch();
	}

	/** Polls the status while a run is going; the results once it ends. */
	private watch(): void {
		if (!cfdRunning(this.status)) {
			this.poll.clear();
			return;
		}
		if (this.poll.value) {
			return;
		}
		const timer = new IntervalTimer();
		timer.cancelAndSet(async () => {
			const request = this.request;
			const status = await this.engine<ICfdStatus>(CFD_STATUS_COMMAND);
			if (request !== this.request) {
				return;
			}
			const was = this.status;
			this.status = status;
			const finishedOne = (status?.directions ?? []).filter(d => d.state === 'done').length !== (was?.directions ?? []).filter(d => d.state === 'done').length;
			if (finishedOne || !cfdRunning(status)) {
				this.results = await this.engine<ICfdResults>(CFD_RESULTS_COMMAND);
			}
			this.render();
			if (!cfdRunning(status)) {
				this.poll.clear();
			}
		}, STATUS_POLL_MS);
		this.poll.value = timer;
	}

	private async detect(): Promise<void> {
		if (this.busy) {
			return;
		}
		this.busy = true;
		this.frame.setStatus({ text: localize('femCfd.finding', "Looking for OpenFOAM (WSL may take a moment to start)..."), busy: true });
		this.frame.showProgress();
		try {
			const found = await this.engine<ICfdInstallation>(CFD_DETECT_COMMAND);
			if (found) {
				this.installation = found;
				this.storage.store(INSTALLATION_KEY, JSON.stringify(found), StorageScope.APPLICATION, StorageTarget.MACHINE);
			}
		} finally {
			this.busy = false;
			this.frame.hideProgress();
			this.render();
		}
	}

	private async writeCases(): Promise<void> {
		if (this.busy) {
			return;
		}
		this.busy = true;
		this.frame.setStatus({ text: localize('femCfd.writing', "Writing the OpenFOAM cases..."), busy: true });
		try {
			const written = await this.engine<{ ok: boolean; message?: string; folder?: string; directions?: number[]; estimatedCells?: number; z0?: number; notes?: string[] }>(CFD_WRITE_COMMAND, { installation: this.installation });
			if (written && !written.ok) {
				this.notificationService.notify({ severity: Severity.Warning, message: written.message ?? localize('femCfd.writeFailed', "The cases could not be written.") });
			} else if (written) {
				this.notificationService.notify({
					severity: Severity.Info,
					message: localize('femCfd.written', "{0} OpenFOAM cases written to {1} (about {2} cells each, z0 = {3} m). Nothing was run.", written.directions?.length ?? 0, written.folder ?? '', (written.estimatedCells ?? 0).toLocaleString(), written.z0 ?? '-'),
				});
			}
		} finally {
			this.busy = false;
			this.render();
		}
	}

	private async run(): Promise<void> {
		if (this.busy || cfdRunning(this.status)) {
			return;
		}
		const { confirmed } = await this.dialogService.confirm({
			type: 'question',
			message: localize('femCfd.runConfirm', "Run the CFD wind tunnel?"),
			detail: [
				localize('femCfd.runWhat', "SAEngine writes one OpenFOAM case per wind direction and runs them one after the other with your OpenFOAM installation, in the background (it goes on when this page is closed). Each direction can take from minutes to hours, depending on the mesh and the computer."),
				localize('femCfd.runReplace', "The previous CFD results of this project are replaced. You can cancel the run at any time."),
				localize('femCfd.runValidate', "The results are engineer-supplied loads: validate them before using them for design."),
			].join('\n\n'),
			primaryButton: localize('femCfd.runButton', "&&Run"),
		});
		if (!confirmed) {
			return;
		}
		this.busy = true;
		this.frame.setStatus({ text: localize('femCfd.starting', "Finding OpenFOAM, writing the cases and starting the run..."), busy: true });
		this.frame.showProgress();
		try {
			const started = await this.engine<{ ok: boolean; message?: string; installation?: ICfdInstallation; install?: string[] }>(CFD_START_COMMAND);
			if (started?.installation) {
				this.installation = { ...started.installation, install: started.install ?? this.installation?.install };
				this.storage.store(INSTALLATION_KEY, JSON.stringify(this.installation), StorageScope.APPLICATION, StorageTarget.MACHINE);
			}
			if (started && !started.ok) {
				this.notificationService.notify({ severity: Severity.Warning, message: started.message ?? localize('femCfd.startFailed', "The CFD run could not start.") });
			}
		} finally {
			this.busy = false;
			this.frame.hideProgress();
		}
		await this.load();
	}

	private async cancel(): Promise<void> {
		const { confirmed } = await this.dialogService.confirm({
			type: 'warning',
			message: localize('femCfd.cancelConfirm', "Cancel the CFD run?"),
			detail: localize('femCfd.cancelDetail', "The OpenFOAM program running is stopped; the directions already finished keep their results."),
			primaryButton: localize('femCfd.cancelButton', "&&Cancel Run"),
		});
		if (confirmed) {
			await this.engine(CFD_CANCEL_COMMAND);
			await this.load();
		}
	}

	// ── rendering ──

	private render(): void {
		this.renderStore.clear();
		clearNode(this.body);
		const running = cfdRunning(this.status);
		this.runAction.enabled = !running && !this.busy;
		this.writeAction.enabled = !running && !this.busy;
		this.findAction.enabled = !this.busy;
		this.cancelAction.enabled = running;
		this.renderWarning();
		this.renderInstallation();
		this.renderRun();
		this.renderResults();
		this.renderProperties();
		this.renderStatusLine();
	}

	private section(title: string): HTMLElement {
		const section = append(this.body, $('section.fem-cfd-section'));
		append(section, $('h3', undefined, title));
		return section;
	}

	private renderWarning(): void {
		const box = append(this.body, $('.fem-cfd-warning', { role: 'note' }));
		append(box, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
		const text = append(box, $('div'));
		append(text, $('strong', undefined, localize('femCfd.warningTitle', "Engineer-supplied loads, not validated.")));
		append(text, $('div', undefined, localize('femCfd.warningText', "A steady RANS simulation of the building alone gives mean pressures; it is not a code wind tunnel test (no peaks, no dynamic response, no neighbours), and it depends on the mesh and the turbulence model. Most codes ask for a boundary-layer wind tunnel test before such loads are used.")));
		const pack = this.results?.pack;
		if (pack?.validation) {
			append(text, $('div.fem-cfd-code', undefined, localize('femCfd.codeRule', "{0}: {1}", pack.name ?? '', pack.validation)));
		}
	}

	private renderInstallation(): void {
		const section = this.section(localize('femCfd.openfoam', "OpenFOAM"));
		const inst = this.installation;
		if (!inst) {
			append(section, $('p', undefined, localize('femCfd.notChecked', "Not looked for yet. Find OpenFOAM looks in WSL (Windows) or on this computer; nothing is installed or downloaded.")));
			return;
		}
		if (inst.found) {
			const where = inst.mode === 'wsl' ? localize('femCfd.inWsl', "in WSL ({0})", inst.distribution || localize('femCfd.defaultDistro', "default distribution")) : localize('femCfd.onHost', "on this computer");
			append(section, $('p', undefined, localize('femCfd.found', "Found OpenFOAM {0} ({1}) {2}: {3}{4}.",
				inst.version || '?',
				inst.flavour === 'com' ? 'OpenFOAM.com' : inst.flavour === 'org' ? 'OpenFOAM.org' : localize('femCfd.unknownFlavour', "unknown flavour"),
				where,
				inst.solver === 'foamRun' ? 'foamRun -solver incompressibleFluid' : 'simpleFoam',
				inst.parallel ? localize('femCfd.parallel', ", MPI with {0} processors", inst.cores ?? '?') : '')));
		} else {
			append(section, $('p.fem-cfd-problem', undefined, localize('femCfd.notFound', "OpenFOAM was not found: {0}", (inst.problems ?? []).join('; ') || localize('femCfd.noReason', "no reason given"))));
		}
		if (!inst.found && inst.install?.length) {
			append(section, $('p', undefined, localize('femCfd.howTo', "To install it (SAEngine does not install or download OpenFOAM):")));
			const list = append(section, $('ol.fem-cfd-steps'));
			for (const step of inst.install) {
				append(list, $('li', undefined, step));
			}
		}
	}

	private renderRun(): void {
		const section = this.section(localize('femCfd.runHeading', "Run"));
		const status = this.status;
		if (!status || status.state === 'none') {
			append(section, $('p', undefined, localize('femCfd.noRun', "No run yet. Run CFD finds OpenFOAM, writes a case per direction (08 FEM/cfd-wind/cases) and runs them in the background; Write Cases only writes them.")));
			return;
		}
		append(section, $('p', undefined, localize('femCfd.runState', "{0}: {1} % {2}", cfdStateLabel(status.state), Math.round((status.progress ?? 0) * 100), status.message ?? '')));
		renderSheet(section, {
			name: 'directions',
			columns: [localize('femCfd.col.runDirection', "Direction [°]"), localize('femCfd.col.state', "State"), localize('femCfd.col.step', "Step"), localize('femCfd.col.iteration', "Iteration"), localize('femCfd.col.note', "Note")],
			rows: (status.directions ?? []).map(d => [d.angle, cfdStateLabel(d.state), d.step ?? '', d.iteration ? `${d.iteration} / ${d.iterations ?? '?'}` : '', d.message ?? '']),
		});
	}

	private renderResults(): void {
		const section = this.section(localize('femCfd.results', "Results"));
		const results = this.results;
		if (!results?.available) {
			append(section, $('p', undefined, results?.reason ?? localize('femCfd.noResults', "No direction has finished yet.")));
			return;
		}
		const code = results.code;
		append(section, $('p', undefined, results.q_kPa
			? localize('femCfd.scaling', "Storey forces F = q·CF with q = {0} kN/m² (the code's design velocity pressure at H = {1} m times its gust factor). Code static wind on the envelope: Vx = {2} kN, Vy = {3} kN.", fixed(results.q_kPa, 3), fixed(results.height_m, 2), fixed(code?.X.V_kN), fixed(code?.Y.V_kN))
			: localize('femCfd.noScaling', "The site has no basic wind speed: coefficients only.")));
		append(section, $('p', undefined, results.useInAnalysis
			? localize('femCfd.used', "Used in the analysis: the wind cases WX, WY and their variants take these storey forces (derive the model again after a new run).")
			: localize('femCfd.notUsed', "Not used in the analysis: turn on Use in the analysis in Project Settings > Wind > CFD wind tunnel to make them the wind cases.")));
		renderSheet(section, {
			name: 'cfd',
			columns: [
				localize('femCfd.col.direction', "Direction [°]"), localize('femCfd.col.case', "Case"),
				'Vx [kN]', 'Vy [kN]', 'T [kN·m]',
				localize('femCfd.col.shareX', "Vx / code X"), localize('femCfd.col.shareY', "Vy / code Y"),
				localize('femCfd.col.converged', "Converged"),
			],
			rows: (results.directions ?? []).map(r => [
				r.angle, r.case, r.Vx_kN ?? '-', r.Vy_kN ?? '-', r.T_kNm ?? '-',
				r.shareX ?? '-', r.shareY ?? '-',
				r.converged ? localize('femCfd.convergedYes', "yes") : localize('femCfd.convergedNo', "no"),
			]),
			notes: results.notes,
		});
		const angles = (results.storeys ?? []).map(s => s.angle);
		if (!angles.length) {
			return;
		}
		if (this.shownAngle === undefined || !angles.includes(this.shownAngle)) {
			this.shownAngle = angles[0];
		}
		const pick = append(section, $('label.fem-cfd-pick', undefined, localize('femCfd.direction', "Direction ")));
		const select = append(pick, $<HTMLSelectElement>('select', { 'aria-label': localize('femCfd.directionAria', "Wind direction shown") }));
		for (const angle of angles) {
			const option = append(select, $<HTMLOptionElement>('option', { value: String(angle) }, `${angle}°`));
			option.selected = angle === this.shownAngle;
		}
		this.renderStore.add(addDisposableListener(select, EventType.CHANGE, () => {
			this.shownAngle = Number(select.value);
			this.render();
		}));
		const storey = results.storeys?.find(s => s.angle === this.shownAngle);
		if (storey) {
			append(section, $('h4', undefined, localize('femCfd.storeys', "Storey force coefficients and forces")));
			renderSheet(section, {
				name: 'storeys',
				columns: ['z [m]', 'CFx [m²]', 'CFy [m²]', 'CMz [m³]', localize('femCfd.col.cfAlong', "Cf along"), 'Fx [kN]', 'Fy [kN]', 'Mz [kN·m]'],
				rows: storey.rows.map(r => [r.z_m, r.CFx_m2, r.CFy_m2, r.CMz_m3, r.cfAlong ?? '-', r.Fx_kN ?? '-', r.Fy_kN ?? '-', r.Mz_kNm ?? '-']),
			});
		}
		const zones = results.zones?.find(z => z.angle === this.shownAngle);
		if (zones) {
			append(section, $('h4', undefined, localize('femCfd.zones', "Facade pressure coefficients per storey")));
			renderSheet(section, {
				name: 'zones',
				columns: ['z [m]', localize('femCfd.col.zone', "Zone"), localize('femCfd.col.role', "Role"), localize('femCfd.col.area', "Area [m²]"), localize('femCfd.col.cpMean', "Cp mean"), localize('femCfd.col.cpMin', "Cp min"), localize('femCfd.col.cpMax', "Cp max")],
				rows: zones.rows.map(r => [r.z_m, r.zone, r.role, r.area_m2, r.cpMean, r.cpMin, r.cpMax]),
			});
		}
	}

	private renderProperties(): void {
		const panel = this.frame.properties;
		if (!panel) {
			return;
		}
		clearNode(panel);
		appendPropertyHeading(panel, localize('femCfd.settingsHeading', "Project Settings > Wind > CFD wind tunnel"));
		const s = this.settings;
		if (!s) {
			appendPropertyNote(panel, localize('femCfd.settingsDefault', "Not set: the defaults are used (the code pack's directions and z0, k-ε, 8 cells per building height, 3 refinement levels, 1500 iterations, not used in the analysis)."));
		} else {
			const text = (value: unknown) => value === undefined || value === null || (Array.isArray(value) && !value.length) ? localize('femCfd.byPack', "by the code pack / default") : Array.isArray(value) ? value.join(', ') : String(value);
			appendPropertyRow(panel, localize('femCfd.p.directions', "Directions [°]"), text(s.directions));
			appendPropertyRow(panel, localize('femCfd.p.step', "Direction step [°]"), text(s.directionStep));
			appendPropertyRow(panel, localize('femCfd.p.z0', "Roughness z0 [m]"), text(s.roughness));
			appendPropertyRow(panel, localize('femCfd.p.turbulence', "Turbulence model"), text(s.turbulence));
			appendPropertyRow(panel, localize('femCfd.p.cells', "Cells per height"), text(s.cellsPerHeight));
			appendPropertyRow(panel, localize('femCfd.p.surface', "Refinement at the building"), text(s.surfaceLevel));
			appendPropertyRow(panel, localize('femCfd.p.iterations', "Iterations"), text(s.iterations));
			appendPropertyRow(panel, localize('femCfd.p.processors', "Processors"), text(s.processors));
			appendPropertyRow(panel, localize('femCfd.p.use', "Use in the analysis"), s.useInAnalysis ? localize('femCfd.yes', "yes") : localize('femCfd.no', "no"));
		}
		const link = append(panel, $<HTMLAnchorElement>('a.fem-cfd-link', { role: 'button', tabindex: '0' }, localize('femCfd.projectSettingsLink', "Edit in Project Settings")));
		const open = () => void this.commandService.executeCommand(PROJECT_SETTINGS_COMMAND);
		this.renderStore.add(addDisposableListener(link, EventType.CLICK, open));
		this.renderStore.add(addDisposableListener(link, EventType.KEY_DOWN, (e: KeyboardEvent) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				open();
			}
		}));
		appendPropertyHeading(panel, localize('femCfd.machineHeading', "This computer"));
		appendPropertyNote(panel, localize('femCfd.machineNote', "The OpenFOAM location and the WSL distribution are settings of this computer (Settings > SAEngine > CFD Wind), not of the project."));
	}

	private renderStatusLine(): void {
		const status = this.status;
		if (cfdRunning(status)) {
			const progress = status?.progress ?? 0;
			this.frame.showProgress(progress);
			this.frame.setStatus({ text: localize('femCfd.statusRunning', "CFD run: {0} % ({1})", Math.round(progress * 100), status?.message ?? cfdStateLabel(status?.state)), busy: true });
			return;
		}
		this.frame.hideProgress();
		const results = this.results;
		if (results?.available) {
			this.frame.setStatus({
				text: results.stale
					? localize('femCfd.statusStale', "{0} directions; the building changed since the run: run it again", results.directions?.length ?? 0)
					: localize('femCfd.statusResults', "{0} directions{1}", results.directions?.length ?? 0, results.complete ? '' : localize('femCfd.incomplete', " (not every direction finished)")),
				severity: results.stale ? 'warning' : 'info',
			});
		} else {
			this.frame.setStatus({ text: cfdStateLabel(status?.state) });
		}
	}
}
