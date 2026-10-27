/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/editorFrame.css';
import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { ActionsOrientation } from '../../../../base/browser/ui/actionbar/actionbar.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { getDefaultHoverDelegate } from '../../../../base/browser/ui/hover/hoverDelegateFactory.js';
import { ProgressBar } from '../../../../base/browser/ui/progressbar/progressbar.js';
import { Orientation, Sash, SashState } from '../../../../base/browser/ui/sash/sash.js';
import { ToolBar } from '../../../../base/browser/ui/toolbar/toolbar.js';
import { Action, IAction } from '../../../../base/common/actions.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { Disposable, DisposableStore, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IStorageService, StorageScope, StorageTarget } from '../../../../platform/storage/common/storage.js';
import { defaultButtonStyles, defaultProgressBarStyles } from '../../../../platform/theme/browser/defaultStyles.js';

/*
 * The shared frame of the SAEngine editors: one slim toolbar, the editor's own canvas or table,
 * an optional properties panel on the right and a one-line status line at the bottom.
 *
 *   ┌ title/selectors │ inline controls ············ end slot │ icon buttons │ … ┐
 *   │                                                         ┊                  │
 *   │  main (canvas, table)                                   ┊  properties      │
 *   │                                                         ┊                  │
 *   └ status line (muted text, optional link) ─────────────────────────────────────┘
 *
 * Usage (in an EditorPane):
 *
 *   this.frame = this._register(this.instantiationService.createInstance(EditorFrame, parent, {
 *   	id: MyEditorInput.EDITOR_ID, ariaLabel: localize(...),
 *   	properties: { title: localize('props', "Properties") },
 *   }));
 *   append(this.frame.titleSlot, ...);              // a selector or a title
 *   this.frame.setActions([runAction, this.frame.togglePropertiesAction], [exportAction]);
 *   this.frame.setStatus({ text: localize(...), link: { label: localize(...), run: () => ... } });
 *   this.frame.setHelp(localize(...));              // optional: "?" after the title, explains the editor
 *   this.frame.setEmpty({ title, text, actions });   // optional: calm centred message, undefined hides it
 *   this.frame.layout(dimension.width, dimension.height); // from EditorPane.layout
 *   this._register(this.frame.onDidLayoutMain(() => this.canvas.layout()));
 *
 * Primary actions are icon buttons (an `Action` whose `class` is a codicon class name, and whose
 * label is the tooltip; `checked` shows a toggle as pressed); secondary actions go to the "..."
 * overflow menu. The properties panel's width and visibility are remembered per `id`; fill it
 * with `appendPropertyHeading` / `appendPropertyRow` / `appendPropertyNote`. Append to `main`
 * rather than clearing it: the empty state lives there too.
 */

/** Options of the properties panel on the right of the frame. */
export interface IEditorFramePropertiesOptions {
	/** Heading of the panel, e.g. "Properties". */
	readonly title: string;
	/** Whether the panel shows the first time this editor type opens (default: true). */
	readonly defaultVisible?: boolean;
	/** Width the first time this editor type opens [px] (default: 280). */
	readonly defaultWidth?: number;
	readonly minWidth?: number;
	readonly maxWidth?: number;
}

export interface IEditorFrameOptions {
	/** Editor type id: the properties panel's width and visibility are remembered per id. */
	readonly id: string;
	/** Accessible name of the toolbar. */
	readonly ariaLabel: string;
	/** Omit for an editor without a properties panel. */
	readonly properties?: IEditorFramePropertiesOptions;
}

/** What the status line says: muted text, with an icon and an inline link when given. */
export interface IEditorFrameStatus {
	/** The text, or text and elements (a small chart, a swatch) in a row. */
	readonly text: string | readonly (string | HTMLElement)[];
	readonly severity?: 'info' | 'warning' | 'error';
	/** A codicon before the text; `busy` shows a spinner instead. */
	readonly icon?: ThemeIcon;
	readonly busy?: boolean;
	readonly link?: { readonly label: string; readonly run: () => void };
}

/** A button of the empty state (see {@link EditorFrame.setEmpty}). */
export interface IEditorFrameEmptyAction {
	readonly label: string;
	readonly icon?: ThemeIcon;
	/** The empty state's main action (button colours); the others are secondary. */
	readonly primary?: boolean;
	readonly enabled?: boolean;
	readonly run: () => void;
}

/**
 * What the main area shows while the editor has nothing to show yet: a calm, centred message
 * over the main area, with at most a few buttons and a link.
 */
export interface IEditorFrameEmptyState {
	readonly icon?: ThemeIcon;
	readonly title: string;
	readonly text?: string;
	readonly actions?: readonly IEditorFrameEmptyAction[];
	readonly link?: { readonly label: string; readonly run: () => void };
}

/** An icon button of an inline toolbar control (see {@link EditorFrame.createIconButton}). */
export interface IEditorFrameIconButton extends IDisposable {
	readonly element: HTMLButtonElement;
	setIcon(icon: ThemeIcon): void;
	setTitle(title: string): void;
}

/** The remembered layout of a frame's properties panel. */
export interface IEditorFrameState {
	readonly visible: boolean;
	readonly width: number;
}

const DEFAULT_PANEL_WIDTH = 280;
const MIN_PANEL_WIDTH = 200;
const MAX_PANEL_WIDTH = 640;
/** The main area keeps at least this width when the panel is dragged wider [px]. */
const MIN_MAIN_WIDTH = 240;

/**
 * The properties panel's width within `min`..`max`, leaving the main area at least
 * {@link MIN_MAIN_WIDTH} of `available` (never below `min`).
 */
/** Opens the user manual, at a chapter (`docs/manual/<chapter>.md`) when one is given (saengineShell.contribution.ts). */
export const OPEN_MANUAL_COMMAND = 'saengine.openManual';

/** The manual chapter of each part's editors, by a word of their frame id (editor ids differ in prefix only). */
const MANUAL_CHAPTERS: readonly (readonly [RegExp, string])[] = [
	[/soil/i, '01-soil-report'],
	[/settings/i, '02-project-settings'],
	[/floorPlan|membersTable/i, '05-floor-plan'],
	// Before "structure", which it contains.
	[/substructure/i, '09-substructure'],
	[/structure/i, '05-floor-plan'],
	[/building|bim/i, '06-bim'],
	[/mep/i, '07-mep'],
	[/fem/i, '08-fem'],
	[/boq/i, '10-boq'],
	[/exports|drawing|versions/i, '11-exports'],
	[/library/i, '03-materials'],
];

/** The user manual chapter for an editor frame with `id`, if it belongs to a part. */
export function manualChapterOf(id: string): string | undefined {
	return MANUAL_CHAPTERS.find(([pattern]) => pattern.test(id))?.[1];
}

export function clampPanelWidth(width: number, available: number, min = MIN_PANEL_WIDTH, max = MAX_PANEL_WIDTH): number {
	const upper = Math.max(min, Math.min(max, available - MIN_MAIN_WIDTH));
	return Math.round(Math.max(min, Math.min(upper, Number.isFinite(width) ? width : min)));
}

/** The remembered panel state in `raw` (stored JSON), falling back to `defaults` field by field. */
export function readFrameState(raw: string | undefined, defaults: IEditorFrameState): IEditorFrameState {
	try {
		const value = raw ? JSON.parse(raw) : undefined;
		return {
			visible: typeof value?.visible === 'boolean' ? value.visible : defaults.visible,
			width: typeof value?.width === 'number' && Number.isFinite(value.width) ? value.width : defaults.width,
		};
	} catch {
		return defaults;
	}
}

/**
 * Appends a heading of the property sheet (`.sa-props-heading`) to a properties panel, with a
 * muted `detail` after the text (a member's type).
 */
export function appendPropertyHeading(container: HTMLElement, text: string, detail?: string): HTMLElement {
	if (!detail) {
		return append(container, $('.sa-props-heading', undefined, text));
	}
	const heading = append(container, $('.sa-props-heading'));
	append(heading, $('span', undefined, text));
	append(heading, $('span.sa-props-detail', undefined, detail));
	return heading;
}

/**
 * Appends a name/value row of the property sheet (`.sa-props-row`); the value may be an element.
 * `problem` marks the value with a warning.
 */
export function appendPropertyRow(container: HTMLElement, name: string, value: string | HTMLElement, problem?: boolean): HTMLElement {
	const row = append(container, $('.sa-props-row'));
	append(row, $('span.name', undefined, name));
	const cell = append(row, $('span.value'));
	if (problem) {
		cell.classList.add('problem');
		append(cell, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
	}
	if (typeof value !== 'string') {
		append(cell, value);
	} else if (problem) {
		append(cell, $('span', undefined, value));
	} else {
		cell.textContent = value;
	}
	return row;
}

/** Appends a muted note of the property sheet (`.sa-props-note`). */
export function appendPropertyNote(container: HTMLElement, text: string): HTMLElement {
	return append(container, $('.sa-props-note', undefined, text));
}

/**
 * The layout SAEngine editor panes compose: a slim toolbar (selectors on the left, icon buttons
 * and an overflow menu on the right, a progress bar along its bottom edge), the main area, an
 * optional resizable properties panel and a status line. See the comment at the top of this file.
 */
export class EditorFrame extends Disposable {

	readonly element: HTMLElement;
	/** Left of the toolbar: a title, or the editor's main selector(s). */
	readonly titleSlot: HTMLElement;
	/** After the title: small inline controls shown only when relevant (a slider, a picker). */
	readonly controlsSlot: HTMLElement;
	/** Right of the toolbar, before the icon buttons: status pills ("Out of date"). */
	readonly endSlot: HTMLElement;
	/** The editor's canvas or table (a flex column filling the space left). */
	readonly main: HTMLElement;
	/** Content of the properties panel (scrolls); undefined without one. */
	readonly properties: HTMLElement | undefined;
	/** Shows or hides the properties panel: put it among the primary actions. */
	readonly togglePropertiesAction: Action;

	private readonly toolbar: ToolBar;
	private readonly progress: ProgressBar;
	private readonly body: HTMLElement;
	private readonly panel: HTMLElement | undefined;
	private readonly sash: Sash | undefined;
	private readonly status: HTMLElement;
	private readonly statusStore = this._register(new DisposableStore());
	private readonly helpSlot: HTMLElement;
	private readonly helpStore = this._register(new DisposableStore());
	private readonly emptyElement: HTMLElement;
	private readonly emptyStore = this._register(new DisposableStore());
	private readonly storageKey: string;
	private state: IEditorFrameState;
	private width = 0;
	private height = 0;

	private readonly _onDidLayoutMain = this._register(new Emitter<void>());
	/** The main area changed size (the frame was laid out, the panel shown, hidden or resized). */
	readonly onDidLayoutMain: Event<void> = this._onDidLayoutMain.event;

	constructor(
		container: HTMLElement,
		private readonly options: IEditorFrameOptions,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IStorageService private readonly storageService: IStorageService,
		@IHoverService private readonly hoverService: IHoverService,
	) {
		super();
		this.storageKey = `saengine.editorFrame.${options.id}`;
		const panelOptions = options.properties;
		this.state = readFrameState(this.storageService.get(this.storageKey, StorageScope.PROFILE), {
			visible: panelOptions?.defaultVisible ?? true,
			width: panelOptions?.defaultWidth ?? DEFAULT_PANEL_WIDTH,
		});

		this.element = append(container, $('.saengine-editor-frame'));

		const bar = append(this.element, $('.sa-frame-toolbar', { role: 'toolbar', 'aria-label': options.ariaLabel }));
		this.titleSlot = append(bar, $('.sa-frame-title'));
		this.helpSlot = append(bar, $('.sa-frame-help'));
		this.controlsSlot = append(bar, $('.sa-frame-controls'));
		append(bar, $('.sa-frame-spacer'));
		this.endSlot = append(bar, $('.sa-frame-end'));
		this.toolbar = this._register(new ToolBar(append(bar, $('.sa-frame-actions')), contextMenuService, {
			orientation: ActionsOrientation.HORIZONTAL,
			ariaLabel: options.ariaLabel,
			toggleMenuTitle: localize('editorFrame.more', "More Actions..."),
			highlightToggledItems: true,
		}));
		this.progress = this._register(new ProgressBar(bar, defaultProgressBarStyles));
		this.progress.getContainer().classList.add('sa-frame-progress');

		this.body = append(this.element, $('.sa-frame-body'));
		this.main = append(this.body, $('.sa-frame-main'));
		this.emptyElement = append(this.main, $('.sa-frame-empty'));

		this.togglePropertiesAction = this._register(new Action('saengine.editorFrame.toggleProperties',
			panelOptions ? localize('editorFrame.toggleProperties', "Toggle {0}", panelOptions.title) : '',
			ThemeIcon.asClassName(Codicon.layoutSidebarRightOff), !!panelOptions, async () => this.setPropertiesVisible(!this.state.visible)));

		if (panelOptions) {
			this.panel = append(this.body, $('.sa-frame-panel'));
			const header = append(this.panel, $('.sa-frame-panel-header'));
			append(header, $('span.sa-frame-panel-title', undefined, panelOptions.title));
			const hideLabel = localize('editorFrame.hideProperties', "Hide {0}", panelOptions.title);
			const close = append(header, $<HTMLButtonElement>('button.sa-frame-panel-close', { type: 'button', 'aria-label': hideLabel }));
			this._register(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), close, hideLabel));
			append(close, $(ThemeIcon.asCSSSelector(Codicon.close)));
			this._register(addDisposableListener(close, EventType.CLICK, () => this.setPropertiesVisible(false)));
			this.properties = append(this.panel, $('.sa-frame-panel-content'));

			const sash = this.sash = this._register(new Sash(this.body, { getVerticalSashLeft: () => this.mainWidth() }, { orientation: Orientation.VERTICAL }));
			let start = 0;
			this._register(sash.onDidStart(() => start = this.state.width));
			this._register(sash.onDidChange(e => this.resizePanel(start + e.startX - e.currentX, false)));
			this._register(sash.onDidEnd(() => this.save()));
			this._register(sash.onDidReset(() => this.resizePanel(panelOptions.defaultWidth ?? DEFAULT_PANEL_WIDTH, true)));
		}

		this.status = append(this.element, $('.sa-frame-status', { role: 'status', 'aria-live': 'polite' }));
		this.applyPanel();
		this.setHelp(undefined);
	}

	/**
	 * A small icon button for an inline control in the toolbar (e.g. the − and + of a scale),
	 * with a hover. Dispose it with the control.
	 */
	createIconButton(container: HTMLElement, icon: ThemeIcon, title: string, run: () => void): IEditorFrameIconButton {
		const store = new DisposableStore();
		const element = append(container, $<HTMLButtonElement>('button.sa-frame-icon-button', { type: 'button', 'aria-label': title }));
		const glyph = append(element, $(ThemeIcon.asCSSSelector(icon)));
		const hover = store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), element, title));
		store.add(addDisposableListener(element, EventType.CLICK, () => run()));
		return {
			element,
			setIcon: next => glyph.className = ThemeIcon.asClassName(next),
			setTitle: next => {
				element.setAttribute('aria-label', next);
				hover.update(next);
			},
			dispose: () => store.dispose(),
		};
	}

	/**
	 * A pill in the toolbar's end slot ("Out of date"): `run` makes it a button. Dispose it to
	 * remove it.
	 */
	createPill(text: string, options: { readonly severity?: 'warn' | 'fail'; readonly icon?: ThemeIcon; readonly title?: string; readonly run?: () => void }): IDisposable {
		const store = new DisposableStore();
		const pill = append(this.endSlot, $<HTMLElement>(options.run ? 'button.sa-frame-pill' : 'span.sa-frame-pill'));
		if (options.severity) {
			pill.classList.add(options.severity);
		}
		if (options.icon) {
			append(pill, $(ThemeIcon.asCSSSelector(options.icon)));
		}
		append(pill, $('span', undefined, text));
		if (options.title) {
			store.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), pill, options.title));
		}
		const run = options.run;
		if (run) {
			store.add(addDisposableListener(pill, EventType.CLICK, () => run()));
		}
		store.add(toDisposable(() => pill.remove()));
		return store;
	}

	/** The icon buttons (primary) and the overflow menu (secondary; `Separator`s group it). */
	setActions(primary: readonly IAction[], secondary: readonly IAction[] = []): void {
		this.toolbar.setActions(primary, secondary);
	}

	/** Replaces the title slot's content with a plain title. */
	setTitle(title: string): void {
		clearNode(this.titleSlot);
		append(this.titleSlot, $('span.sa-frame-title-text', undefined, title));
	}

	/** What the status line says; undefined empties it. */
	setStatus(status: IEditorFrameStatus | undefined): void {
		this.statusStore.clear();
		clearNode(this.status);
		this.status.className = `sa-frame-status${status?.severity ? ` ${status.severity}` : ''}`;
		if (!status) {
			return;
		}
		const icon = status.busy ? ThemeIcon.modify(Codicon.loading, 'spin') : status.icon
			?? (status.severity === 'error' ? Codicon.error : status.severity === 'warning' ? Codicon.warning : undefined);
		if (icon) {
			append(this.status, $(`span.sa-frame-status-icon${ThemeIcon.asCSSSelector(icon)}`));
		}
		const text = append(this.status, $('span.sa-frame-status-text'));
		for (const part of typeof status.text === 'string' ? [status.text] : status.text) {
			if (typeof part === 'string') {
				append(text, $('span', undefined, part));
			} else {
				append(text, part);
			}
		}
		const link = status.link;
		if (link) {
			const anchor = append(this.status, $<HTMLAnchorElement>('a.sa-frame-status-link', { role: 'button', tabIndex: 0 }, link.label));
			this.statusStore.add(addDisposableListener(anchor, EventType.CLICK, () => link.run()));
			this.statusStore.add(addDisposableListener(anchor, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					link.run();
				}
			}));
		}
	}

	/**
	 * A "?" button after the title whose hover explains the editor (what used to be a paragraph
	 * at the top); undefined removes it. Clicking it, or Enter on it, shows the hover too.
	 */
	setHelp(text: string | undefined): void {
		this.helpStore.clear();
		clearNode(this.helpSlot);
		// Every part's editor has the "?", with a link to its chapter of the user manual (G13).
		const chapter = manualChapterOf(this.options.id);
		if (!text && !chapter) {
			return;
		}
		const label = localize('editorFrame.help', "About This Editor");
		const button = append(this.helpSlot, $<HTMLButtonElement>('button.sa-frame-icon-button.sa-frame-help-button', { type: 'button', 'aria-label': label }));
		append(button, $(ThemeIcon.asCSSSelector(Codicon.question)));
		const content = new MarkdownString(undefined, { isTrusted: { enabledCommands: [OPEN_MANUAL_COMMAND] } });
		content.appendText(text ?? localize('editorFrame.helpDefault', "How this part works, step by step, is in the user manual."));
		if (chapter) {
			content.appendMarkdown(`\n\n[${localize('editorFrame.learnMore', "Learn more in the user manual")}](command:${OPEN_MANUAL_COMMAND}?${encodeURIComponent(JSON.stringify([chapter]))})`);
		}
		const hover = this.helpStore.add(this.hoverService.setupManagedHover(getDefaultHoverDelegate('element'), button, { markdown: content, markdownNotSupportedFallback: text }));
		this.helpStore.add(addDisposableListener(button, EventType.CLICK, () => hover.show(true)));
	}

	/**
	 * A calm message centred over the main area while the editor has nothing to show (not made
	 * yet, no file); undefined hides it. The main area's own content stays underneath.
	 */
	setEmpty(state: IEditorFrameEmptyState | undefined): void {
		this.emptyStore.clear();
		clearNode(this.emptyElement);
		// Last in the main area, so it covers the editor's own content.
		this.main.appendChild(this.emptyElement);
		this.emptyElement.classList.toggle('visible', !!state);
		if (!state) {
			return;
		}
		const content = append(this.emptyElement, $('.sa-frame-empty-content'));
		if (state.icon) {
			append(content, $(`span.sa-frame-empty-icon${ThemeIcon.asCSSSelector(state.icon)}`));
		}
		append(content, $('.sa-frame-empty-title', undefined, state.title));
		if (state.text) {
			append(content, $('.sa-frame-empty-text', undefined, state.text));
		}
		if (state.actions?.length) {
			const actions = append(content, $('.sa-frame-empty-actions'));
			for (const action of state.actions) {
				const button = this.emptyStore.add(new Button(actions, { ...defaultButtonStyles, secondary: !action.primary, supportIcons: true }));
				button.label = action.icon ? `$(${action.icon.id}) ${action.label}` : action.label;
				button.enabled = action.enabled ?? true;
				this.emptyStore.add(button.onDidClick(() => action.run()));
			}
		}
		const link = state.link;
		if (link) {
			const anchor = append(content, $<HTMLAnchorElement>('a.sa-frame-empty-link', { role: 'button', tabIndex: 0 }, link.label));
			this.emptyStore.add(addDisposableListener(anchor, EventType.CLICK, () => link.run()));
			this.emptyStore.add(addDisposableListener(anchor, EventType.KEY_DOWN, e => {
				if (e.key === 'Enter' || e.key === ' ') {
					e.preventDefault();
					link.run();
				}
			}));
		}
	}

	/** Shows the toolbar's progress bar: `fraction` 0..1, or undefined for an indefinite one. */
	showProgress(fraction?: number): void {
		if (fraction === undefined) {
			this.progress.infinite().show();
		} else {
			this.progress.total(1000).setWorked(Math.round(Math.max(0, Math.min(1, fraction)) * 1000)).show();
		}
	}

	hideProgress(): void {
		this.progress.stop().hide();
	}

	get isPropertiesVisible(): boolean {
		return !!this.panel && this.state.visible;
	}

	setPropertiesVisible(visible: boolean): void {
		if (!this.panel || visible === this.state.visible) {
			return;
		}
		this.state = { ...this.state, visible };
		this.applyPanel();
		this.save();
	}

	/** Lays the frame out in `width` x `height` (from `EditorPane.layout`). */
	layout(width: number, height: number): void {
		this.width = width;
		this.height = height;
		this.element.style.width = `${width}px`;
		this.element.style.height = `${height}px`;
		this.applyPanel();
	}

	private mainWidth(): number {
		return this.isPropertiesVisible ? Math.max(0, this.width - this.panelWidth()) : this.width;
	}

	private panelWidth(): number {
		const options = this.options.properties;
		return this.width ? clampPanelWidth(this.state.width, this.width, options?.minWidth, options?.maxWidth) : this.state.width;
	}

	private resizePanel(width: number, save: boolean): void {
		const options = this.options.properties;
		this.state = { ...this.state, width: clampPanelWidth(width, this.width, options?.minWidth, options?.maxWidth) };
		this.applyPanel();
		if (save) {
			this.save();
		}
	}

	private applyPanel(): void {
		const visible = this.isPropertiesVisible;
		this.togglePropertiesAction.checked = visible;
		if (this.panel) {
			this.panel.classList.toggle('hidden', !visible);
			this.panel.style.width = `${this.panelWidth()}px`;
		}
		if (this.sash) {
			this.sash.state = visible ? SashState.Enabled : SashState.Disabled;
			this.sash.layout();
		}
		if (this.width && this.height) {
			this._onDidLayoutMain.fire();
		}
	}

	private save(): void {
		this.storageService.store(this.storageKey, JSON.stringify(this.state), StorageScope.PROFILE, StorageTarget.MACHINE);
	}
}
