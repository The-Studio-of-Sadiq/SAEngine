/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/projectNavigator.css';
import './media/startEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType, isHTMLButtonElement } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { InputBox } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { SelectBox } from '../../../../base/browser/ui/selectBox/selectBox.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles, defaultSelectBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { PROJECT_TYPES, ProjectType } from '../../../services/saengineProject/common/saengineProject.js';
import { NEW_BUILDING_COMMAND } from './newBuildingModel.js';
import { BNBC, SETTINGS_SCHEMA } from '../../../services/saengineProject/common/projectLibraries.generated.js';
import { DESIGN_CODES, DesignCode, ProjectOpener, projectFolderName } from './projectOpener.js';
import { appendProjectPath } from './projectParts.js';
import { StartEditorInput } from './startEditorInput.js';
import { IMPORT_STRUCTURAL_UI_COMMAND } from './structuralImportModel.js';

const SVG = 'http://www.w3.org/2000/svg';

/** The SAEngine mark (resources/saengine-mark.svg): a two-bay frame with its nodes. */
function renderMark(parent: HTMLElement): void {
	const document = parent.ownerDocument;
	const svg = parent.appendChild(document.createElementNS(SVG, 'svg'));
	svg.setAttribute('viewBox', '0 0 512 512');
	svg.setAttribute('class', 'mark');
	svg.setAttribute('aria-hidden', 'true');
	const add = (name: string, attributes: { [name: string]: string }, into: Element = svg) => {
		const element = into.appendChild(document.createElementNS(SVG, name));
		for (const [key, value] of Object.entries(attributes)) {
			element.setAttribute(key, value);
		}
		return element;
	};
	add('rect', { x: '12', y: '12', width: '488', height: '488', rx: '112', fill: '#111d2a' });
	const lines = add('g', { fill: 'none', stroke: '#54d7c6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'stroke-width': '25' });
	for (const d of ['M132 379V145h248v234', 'M132 258h248', 'M256 145v234', 'M104 379h304']) {
		add('path', { d }, lines);
	}
	const nodes = add('g', { fill: '#ffbf73', stroke: '#111d2a', 'stroke-width': '10' });
	for (const cx of [132, 256, 380]) {
		for (const cy of [145, 258, 379]) {
			add('circle', { cx: String(cx), cy: String(cy), r: '18' }, nodes);
		}
	}
}

/** The building uses Project Settings offers (`occupancy.use`), from the settings schema. */
function occupancyUses(): { readonly value: string; readonly label: string }[] {
	const use = SETTINGS_SCHEMA.$defs?.['Occupancy']?.properties?.['use'];
	const values = (use?.enum ?? []) as string[];
	return values.map((value, i) => ({ value, label: use?.enumDescriptions?.[i] ?? value }));
}

function formatOpened(time: number): string {
	const date = new Date(time);
	const today = new Date();
	if (date.toDateString() === today.toDateString()) {
		return localize('start.openedToday', "Today");
	}
	return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: date.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}

/**
 * The start page, filling the window while no project is open: the actions (new project, open
 * project, open the sample project) beside the recent projects; New Project switches the right
 * side to a short form.
 */
export class StartEditor extends EditorPane {

	private container!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private main!: HTMLElement;
	private focusTarget: { focus(): void } | undefined;
	private newProjectAction: HTMLElement | undefined;
	private readonly opener: ProjectOpener;
	private readonly pageDisposables = this._register(new DisposableStore());
	private readonly sideDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@INotificationService private readonly notificationService: INotificationService,
		@IPathService private readonly pathService: IPathService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super(StartEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
		this.opener = instantiationService.createInstance(ProjectOpener);
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = $('.saengine-start');
		// The workbench's own scrollbar, as in the side bar and the other editors.
		this.scrollable = this._register(new DomScrollableElement(this.container, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(parent, this.scrollable.getDomNode());
	}

	override async setInput(input: StartEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.renderShell();
		await this.renderRecent();
	}

	override clearInput(): void {
		this.pageDisposables.clear();
		this.sideDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
		this.scrollable.scanDomNode();
	}

	override focus(): void {
		super.focus();
		this.focusTarget?.focus();
	}

	private renderShell(): void {
		this.sideDisposables.clear();
		clearNode(this.container);
		const shell = append(this.container, $('.shell'));
		const side = append(shell, $('aside.side'));

		const brand = append(side, $('.brand'));
		renderMark(brand);
		const title = append(brand, $('.brand-text'));
		append(title, $('h1', undefined, localize('start.title', "SAEngine")));
		append(title, $('p.subtitle', undefined, localize('start.subtitle', "Structural analysis and design")));

		const actions = append(side, $('nav.actions', { 'aria-label': localize('start.actions', "Start") }));
		const action = (icon: ThemeIcon, label: string, run: () => void) => {
			const button = append(actions, $('button.action', { type: 'button' }));
			append(button, $(`span${ThemeIcon.asCSSSelector(icon)}`));
			append(button, $('span.label', undefined, label));
			this.sideDisposables.add(addDisposableListener(button, EventType.CLICK, run));
			return button;
		};
		this.newProjectAction = action(Codicon.newFolder, localize('start.new', "New Project..."), () => void this.renderNewProject());
		// A whole building from its grids and storeys, in the New Building wizard.
		action(Codicon.symbolStructure, localize('start.newBuilding', "New Building from Grid..."), () => this.run(async () => { await this.commandService.executeCommand(NEW_BUILDING_COMMAND); }));
		action(Codicon.folderOpened, localize('start.open', "Open Project..."), () => this.run(() => this.opener.pickAndOpen()));
		action(Codicon.library, localize('start.sample', "Open Sample Project..."), () => this.run(() => this.opener.openSample()));
		// Another program's model (ETABS, STAAD.Pro, SAP2000) as a new project: the command asks the rest.
		action(Codicon.cloudDownload, localize('start.import', "Import from ETABS, STAAD or SAP2000..."), () => this.run(async () => { await this.commandService.executeCommand(IMPORT_STRUCTURAL_UI_COMMAND); }));

		this.main = append(shell, $('main.main'));
	}

	private resetMain(): HTMLElement {
		this.pageDisposables.clear();
		clearNode(this.main);
		this.scrollable.setScrollPosition({ scrollTop: 0 });
		return this.main;
	}

	/** Shows the recent projects; back from the form, the focus returns to New Project. */
	private async renderRecent(fromForm = false): Promise<void> {
		const page = this.resetMain();
		this.focusTarget = fromForm ? this.newProjectAction : undefined;
		this.focusTarget?.focus();
		append(page, $('h2', undefined, localize('start.recent', "Recent Projects")));
		const list = append(page, $('ul.recent'));
		const loading = append(list, $('li.empty', undefined, localize('start.loading', "Loading...")));

		const recent = await this.opener.recentProjects();
		if (!list.isConnected) {
			return; // navigated away meanwhile
		}
		loading.remove();
		if (!recent.length) {
			append(list, $('li.empty', undefined, localize('start.noRecent', "No recent projects. Create one, or open the sample project to look around.")));
			this.scrollable.scanDomNode();
			return;
		}
		const userHome = this.pathService.resolvedUserHome;
		for (const { project, label, parent, opened } of recent) {
			const item = append(list, $('li'));
			const link = append(item, $('button.recent-project', { type: 'button', title: project.root.fsPath }));
			const top = append(link, $('span.top'));
			append(top, $('span.name', undefined, label));
			// Projects of the same name are told apart by their folder.
			if (parent) {
				append(top, $('span.parent', undefined, localize('start.inFolder', "in {0}", parent)));
			}
			const date = formatOpened(opened);
			append(top, $('span.date', { 'aria-label': localize('start.lastOpened', "Last opened {0}", date) }, date));
			appendProjectPath(link, project.root, userHome).classList.add('path');
			this.pageDisposables.add(addDisposableListener(link, EventType.CLICK, () => this.run(() => this.opener.open(project.root))));
		}
		this.scrollable.scanDomNode();
	}

	/** A row of mutually exclusive choices, as radio buttons. */
	private choices<T extends string>(parent: HTMLElement, label: string, options: readonly { readonly value: T; readonly label: string; readonly description?: string }[], initial: T, onChange: (value: T) => void): void {
		const group = append(parent, $('.choices', { role: 'radiogroup', 'aria-label': label }));
		const buttons = options.map(option => {
			const button = append(group, $('button.choice', { type: 'button', role: 'radio' }));
			append(button, $('span.choice-label', undefined, option.label));
			if (option.description) {
				append(button, $('span.choice-description', undefined, option.description));
			}
			this.pageDisposables.add(addDisposableListener(button, EventType.CLICK, () => select(option.value)));
			return { button, value: option.value };
		});
		const select = (value: T) => {
			for (const option of buttons) {
				option.button.classList.toggle('selected', option.value === value);
				option.button.setAttribute('aria-checked', String(option.value === value));
			}
			onChange(value);
		};
		select(initial);
	}

	private async renderNewProject(): Promise<void> {
		const page = this.resetMain();
		append(page, $('h2', undefined, localize('start.newTitle', "New Project")));

		const form = append(page, $('.form'));
		append(form, $('label', undefined, localize('start.name', "Name")));
		const name = this.pageDisposables.add(new InputBox(form, this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder: localize('start.namePlaceholder', "e.g. Mirpur Residence (Plot 12/A)"),
			ariaLabel: localize('start.name', "Name"),
		}));
		// The message sits in the form's flow, under the field, not in a popup over the next label.
		const nameError = append(form, $('p.error', { role: 'alert' }));
		const validateName = () => {
			const error = name.value ? this.opener.validateDisplayName(name.value) : undefined;
			nameError.textContent = error ?? '';
			name.inputElement.setAttribute('aria-invalid', String(!!error));
			return error;
		};
		this.pageDisposables.add(name.onDidChange(validateName));

		// Where the building stands: its seismic zone and wind speed (BNBC 2020 Part 6 Chapter 2).
		append(form, $('label', undefined, localize('start.site', "Site")));
		const sites = Object.entries(BNBC.locations).sort((a, b) => a[1].name.localeCompare(b[1].name));
		const siteIndex = Math.max(0, sites.findIndex(([id]) => id === 'dhaka'));
		const site = this.pageDisposables.add(new SelectBox(sites.map(([, l]) => ({ text: localize('start.siteOption', "{0} (zone {1}, wind {2} m/s)", l.name, l.zone, l.windSpeed) })), siteIndex, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('start.site', "Site") }));
		site.render(append(form, $('.select')));
		let siteId = sites[siteIndex]?.[0];
		this.pageDisposables.add(site.onDidSelect(e => siteId = sites[e.index]?.[0]));

		// What the building is used for: the live loads and the occupancy category follow it in Project Settings.
		append(form, $('label', undefined, localize('start.use', "Building use")));
		const uses = occupancyUses();
		const useIndex = Math.max(0, uses.findIndex(u => u.value === 'residential'));
		const use = this.pageDisposables.add(new SelectBox(uses.map(u => ({ text: u.label })), useIndex, this.contextViewService, defaultSelectBoxStyles, { ariaLabel: localize('start.use', "Building use") }));
		use.render(append(form, $('.select')));
		let useValue = uses[useIndex]?.value;
		this.pageDisposables.add(use.onDidSelect(e => useValue = uses[e.index]?.value));

		append(form, $('label', undefined, localize('start.folder', "Folder")));
		const locationRow = append(form, $('.location'));
		const location = this.pageDisposables.add(new InputBox(locationRow, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles, ariaLabel: localize('start.folder', "Folder") }));
		location.value = (await this.opener.defaultLocation()).fsPath;
		const browse = this.pageDisposables.add(new Button(locationRow, { ...defaultButtonStyles, secondary: true }));
		browse.label = localize('start.browse', "Browse...");
		this.pageDisposables.add(browse.onDidClick(async () => {
			const picked = await this.opener.browseForLocation(URI.file(location.value));
			if (picked) {
				location.value = picked.fsPath;
			}
		}));

		// What the project designs decides how Part 5 models it.
		let type: ProjectType = 'building';
		append(form, $('label', undefined, localize('start.type', "Type")));
		const typeHint = $('p.hint');
		this.choices(form, localize('start.type', "Type"), PROJECT_TYPES.map(t => ({ value: t.type, label: t.label })), type, value => {
			type = value;
			typeHint.textContent = PROJECT_TYPES.find(t => t.type === value)?.description ?? '';
		});
		append(form, typeHint);

		let code: DesignCode = 'bnbc';
		append(form, $('label', undefined, localize('start.code', "Design code")));
		this.choices(form, localize('start.code', "Design code"), DESIGN_CODES.map(c => ({ value: c.code, label: c.label })), code, value => code = value);

		const target = append(form, $('p.target'));
		const updateTarget = () => {
			target.textContent = name.value.trim() && !this.opener.validateDisplayName(name.value)
				? localize('start.target', "Created in {0}", joinPath(URI.file(location.value), projectFolderName(name.value)).fsPath)
				: '';
		};
		this.pageDisposables.add(name.onDidChange(updateTarget));
		this.pageDisposables.add(location.onDidChange(updateTarget));
		updateTarget();

		const buttons = append(page, $('.form-actions'));
		const create = this.pageDisposables.add(new Button(buttons, defaultButtonStyles));
		create.label = localize('start.create', "Create Project");
		const back = this.pageDisposables.add(new Button(buttons, { ...defaultButtonStyles, secondary: true }));
		back.label = localize('start.cancel', "Cancel");
		this.pageDisposables.add(back.onDidClick(() => this.renderRecent(true)));

		const submit = () => {
			nameError.textContent = this.opener.validateDisplayName(name.value) ?? '';
			if (nameError.textContent || !location.value.trim()) {
				name.focus();
				return;
			}
			this.run(() => this.opener.createAndOpen(URI.file(location.value.trim()), name.value, type, { code, location: siteId, use: useValue }));
		};
		this.pageDisposables.add(create.onDidClick(submit));
		this.pageDisposables.add(addDisposableListener(form, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter' && !isHTMLButtonElement(e.target)) {
				submit();
			} else if (e.key === 'Escape') {
				void this.renderRecent(true);
			}
		}));
		this.focusTarget = name;
		name.focus();
		this.scrollable.scanDomNode();
	}

	private run(action: () => Promise<void>): void {
		action().catch(error => this.notificationService.error(error));
	}
}
