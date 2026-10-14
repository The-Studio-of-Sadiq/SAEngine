/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/startEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { InputBox, MessageType } from '../../../../base/browser/ui/inputbox/inputBox.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IContextViewService } from '../../../../platform/contextview/browser/contextView.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles, defaultInputBoxStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { ProjectOpener } from './projectOpener.js';
import { StartEditorInput } from './startEditorInput.js';

/**
 * The start window. Its home page offers New Project, Open Project and the recent projects;
 * New Project switches to a short form (name and location).
 */
export class StartEditor extends EditorPane {

	private container!: HTMLElement;
	private focusTarget: { focus(): void } | undefined;
	private readonly opener: ProjectOpener;
	private readonly pageDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IContextViewService private readonly contextViewService: IContextViewService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super(StartEditorInput.EDITOR_ID, group, telemetryService, themeService, storageService);
		this.opener = instantiationService.createInstance(ProjectOpener);
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = append(parent, $('.saengine-start'));
	}

	override async setInput(input: StartEditorInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		await this.renderHome();
	}

	override clearInput(): void {
		this.pageDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
	}

	override focus(): void {
		super.focus();
		this.focusTarget?.focus();
	}

	private resetPage(): HTMLElement {
		this.pageDisposables.clear();
		clearNode(this.container);
		const header = append(this.container, $('.header'));
		append(header, $('h1', undefined, localize('start.title', "SAEngine")));
		append(header, $('p.subtitle', undefined, localize('start.subtitle', "Structural analysis and design workbench")));
		return append(this.container, $('.page'));
	}

	private async renderHome(): Promise<void> {
		const page = this.resetPage();

		const actions = append(page, $('.actions'));
		const newButton = this.pageDisposables.add(new Button(actions, { ...defaultButtonStyles, supportIcons: true }));
		newButton.label = `$(${Codicon.newFolder.id}) ${localize('start.new', "New Project")}`;
		this.pageDisposables.add(newButton.onDidClick(() => this.renderNewProject()));
		this.focusTarget = newButton;

		const openButton = this.pageDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
		openButton.label = `$(${Codicon.folderOpened.id}) ${localize('start.open', "Open Project...")}`;
		this.pageDisposables.add(openButton.onDidClick(() => this.run(() => this.opener.pickAndOpen())));

		append(page, $('h2', undefined, localize('start.recent', "Recent Projects")));
		const list = append(page, $('ul.recent'));
		const loading = append(list, $('li.empty', undefined, localize('start.loading', "Loading...")));

		const recent = await this.opener.recentProjects();
		if (!list.isConnected) {
			return; // navigated away meanwhile
		}
		loading.remove();
		if (!recent.length) {
			append(list, $('li.empty', undefined, localize('start.noRecent', "No recent projects.")));
			return;
		}
		for (const { project, label } of recent) {
			const item = append(list, $('li'));
			const link = append(item, $('a.recent-project', { href: '#', title: project.root.fsPath }));
			append(link, $(`span${ThemeIcon.asCSSSelector(Codicon.project)}`));
			append(link, $('span.name', undefined, label));
			append(link, $('span.path', undefined, project.root.fsPath));
			this.pageDisposables.add(addDisposableListener(link, EventType.CLICK, e => {
				e.preventDefault();
				this.run(() => this.opener.open(project.root));
			}));
		}
	}

	private async renderNewProject(): Promise<void> {
		const page = this.resetPage();
		append(page, $('h2', undefined, localize('start.newTitle', "New Project")));

		const form = append(page, $('.form'));
		append(form, $('label', undefined, localize('start.name', "Project name")));
		const name = this.pageDisposables.add(new InputBox(form, this.contextViewService, {
			inputBoxStyles: defaultInputBoxStyles,
			placeholder: localize('start.namePlaceholder', "e.g. Office Building"),
			validationOptions: {
				validation: value => {
					const error = this.opener.validateName(value);
					return error ? { content: error, type: MessageType.ERROR } : null;
				},
			},
		}));

		append(form, $('label', undefined, localize('start.location', "Location")));
		const locationRow = append(form, $('.location'));
		const location = this.pageDisposables.add(new InputBox(locationRow, this.contextViewService, { inputBoxStyles: defaultInputBoxStyles }));
		location.value = (await this.opener.defaultLocation()).fsPath;
		const browse = this.pageDisposables.add(new Button(locationRow, { ...defaultButtonStyles, secondary: true }));
		browse.label = localize('start.browse', "Browse...");
		this.pageDisposables.add(browse.onDidClick(async () => {
			const picked = await this.opener.browseForLocation(URI.file(location.value));
			if (picked) {
				location.value = picked.fsPath;
			}
		}));

		const target = append(form, $('p.target'));
		const updateTarget = () => {
			target.textContent = name.value.trim() && !this.opener.validateName(name.value)
				? localize('start.target', "The project will be created in {0}", joinPath(URI.file(location.value), name.value.trim()).fsPath)
				: '';
		};
		this.pageDisposables.add(name.onDidChange(updateTarget));
		this.pageDisposables.add(location.onDidChange(updateTarget));

		const buttons = append(page, $('.actions.form-actions'));
		const back = this.pageDisposables.add(new Button(buttons, { ...defaultButtonStyles, secondary: true }));
		back.label = localize('start.back', "Back");
		this.pageDisposables.add(back.onDidClick(() => this.renderHome()));
		const create = this.pageDisposables.add(new Button(buttons, defaultButtonStyles));
		create.label = localize('start.create', "Create Project");

		const submit = () => {
			name.validate(); // shows the message, if any
			if (this.opener.validateName(name.value) || !location.value.trim()) {
				name.focus();
				return;
			}
			this.run(() => this.opener.createAndOpen(URI.file(location.value.trim()), name.value));
		};
		this.pageDisposables.add(create.onDidClick(submit));
		this.pageDisposables.add(addDisposableListener(form, EventType.KEY_DOWN, e => {
			if (e.key === 'Enter') {
				submit();
			}
		}));
		this.focusTarget = name;
		name.focus();
	}

	private run(action: () => Promise<void>): void {
		action().catch(error => this.notificationService.error(error));
	}
}
