/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/saengineTokens.css';
import './media/projectNavigator.css';
import './media/startEditor.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { NEW_PROJECT_COMMAND } from './newBuildingModel.js';
import { ProjectOpener } from './projectOpener.js';
import { appendProjectPath } from './projectParts.js';
import { StartEditorInput } from './startEditorInput.js';
import { IMPORT_STRUCTURAL_UI_COMMAND } from './structuralImportModel.js';
import { formatDate } from '../../../services/saengineProject/common/formatting.js';
import { renderBrandMark, renderBrandWordmark } from './saengineBrand.js';

/** The public source repository of SAEngine. */
const SOURCE_URL = 'https://github.com/The-Studio-of-Sadiq/SAEngine';

function formatOpened(time: number): string {
	const date = new Date(time);
	const today = new Date();
	if (date.toDateString() === today.toDateString()) {
		return localize('start.openedToday', "Today");
	}
	return formatDate(date, { day: 'numeric', month: 'short', year: date.getFullYear() === today.getFullYear() ? undefined : 'numeric' });
}

/**
 * The start page, filling the window while no project is open: the actions (new project, open
 * project, open the sample project, import) beside the recent projects. New Project opens the
 * New Project wizard.
 */
export class StartEditor extends EditorPane {

	private container!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private main!: HTMLElement;
	private focusTarget: { focus(): void } | undefined;
	private readonly opener: ProjectOpener;
	private readonly pageDisposables = this._register(new DisposableStore());
	private readonly sideDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@IInstantiationService instantiationService: IInstantiationService,
		@INotificationService private readonly notificationService: INotificationService,
		@IPathService private readonly pathService: IPathService,
		@ICommandService private readonly commandService: ICommandService,
		@IOpenerService private readonly openerService: IOpenerService,
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
		renderBrandMark(brand);
		append(brand, $('span.divider'));
		const title = append(brand, $('.brand-text'));
		renderBrandWordmark(append(title, $('h1')), localize('start.title', "SAEngine"));
		append(title, $('p.subtitle', undefined, localize('start.subtitle', "Structural analysis and design")));

		const actions = append(side, $('nav.actions', { 'aria-label': localize('start.actions', "Start") }));
		const action = (icon: ThemeIcon, label: string, run: () => void) => {
			const button = append(actions, $('button.action', { type: 'button' }));
			append(button, $(`span${ThemeIcon.asCSSSelector(icon)}`));
			append(button, $('span.label', undefined, label));
			this.sideDisposables.add(addDisposableListener(button, EventType.CLICK, run));
			return button;
		};
		// The one way to start a project: the New Project wizard (the grid, a template or an empty project).
		action(Codicon.newFolder, localize('start.new', "New Project..."), () => this.run(async () => { await this.commandService.executeCommand(NEW_PROJECT_COMMAND); }));
		action(Codicon.folderOpened, localize('start.open', "Open Project..."), () => this.run(() => this.opener.pickAndOpen()));
		action(Codicon.library, localize('start.sample', "Open Sample Project..."), () => this.run(() => this.opener.openSample()));
		// Another program's model (ETABS, STAAD.Pro, SAP2000) as a new project: the command asks the rest.
		action(Codicon.cloudDownload, localize('start.import', "Import from ETABS, STAAD or SAP2000..."), () => this.run(async () => { await this.commandService.executeCommand(IMPORT_STRUCTURAL_UI_COMMAND); }));

		this.main = append(shell, $('main.main'));

		// Who makes SAEngine and under which licence, at the foot of the page.
		const credits = append(this.container, $('footer.credits'));
		append(credits, $('p', undefined, localize('start.developer', "Developed by The Studio of Sadiq")));
		const source = append(credits, $('p'));
		append(source, document.createTextNode(localize('start.openSource', "This is an open source project.") + ' '));
		const more = append(source, $('a.see-more', { href: SOURCE_URL, role: 'link' }, localize('start.seeMore', "See More")));
		this.sideDisposables.add(addDisposableListener(more, EventType.CLICK, e => {
			e.preventDefault();
			this.openerService.open(SOURCE_URL, { openExternal: true });
		}));
		append(credits, $('p', undefined, localize('start.copyright', "Copyright © 2026 The Studio of Sadiq. Free software under the GNU Affero General Public License v3.0 (AGPL-3.0-only), with no warranty.")));
	}

	private resetMain(): HTMLElement {
		this.pageDisposables.clear();
		clearNode(this.main);
		this.scrollable.setScrollPosition({ scrollTop: 0 });
		return this.main;
	}

	/** Shows the recent projects. */
	private async renderRecent(): Promise<void> {
		const page = this.resetMain();
		this.focusTarget = undefined;
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

	private run(action: () => Promise<void>): void {
		action().catch(error => this.notificationService.error(error));
	}
}
