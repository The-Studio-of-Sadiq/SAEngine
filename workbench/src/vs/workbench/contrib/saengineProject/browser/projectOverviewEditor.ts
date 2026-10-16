/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/projectNavigator.css';
import './media/projectOverview.css';
import { $, addDisposableListener, append, clearNode, Dimension, EventType } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorOptions } from '../../../../platform/editor/common/editor.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorOpenContext } from '../../../common/editor.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { ISaenginePartStatusService, nextStep } from '../../../services/saengineProject/common/partStatus.js';
import { IProjectPart, ISaengineProjectService, PROJECT_TYPES } from '../../../services/saengineProject/common/saengineProject.js';
import { appendProjectPath, openPart, partGroups, partName, stateClass, stateLabel, stateText } from './projectParts.js';
import { ProjectOverviewInput } from './projectOverviewInput.js';

/**
 * The overview of the open project: the parts in the sidebar's grouped, numbered layout with
 * their status, the next thing to do, and a way into each part.
 */
export class ProjectOverviewEditor extends EditorPane {

	private container!: HTMLElement;
	private scrollable!: DomScrollableElement;
	private readonly renderDisposables = this._register(new DisposableStore());

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService themeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@IOpenerService private readonly openerService: IOpenerService,
		@ICommandService private readonly commandService: ICommandService,
		@INotificationService private readonly notificationService: INotificationService,
		@IPathService private readonly pathService: IPathService,
	) {
		super(ProjectOverviewInput.EDITOR_ID, group, telemetryService, themeService, storageService);
		this._register(this.statusService.onDidChange(() => this.render()));
		this._register(this.projectService.onDidChangeProject(() => this.render()));
	}

	protected createEditor(parent: HTMLElement): void {
		this.container = $('.saengine-overview', { tabIndex: -1 });
		// The workbench's own scrollbar, as in the side bar and the other editors.
		this.scrollable = this._register(new DomScrollableElement(this.container, { horizontal: ScrollbarVisibility.Hidden, vertical: ScrollbarVisibility.Auto }));
		append(parent, this.scrollable.getDomNode());
	}

	override async setInput(input: ProjectOverviewInput, options: IEditorOptions | undefined, context: IEditorOpenContext, token: CancellationToken): Promise<void> {
		await super.setInput(input, options, context, token);
		this.render();
	}

	override clearInput(): void {
		this.renderDisposables.clear();
		super.clearInput();
	}

	override layout(dimension: Dimension): void {
		this.container.style.width = `${dimension.width}px`;
		this.container.style.height = `${dimension.height}px`;
		this.scrollable.scanDomNode();
	}

	override focus(): void {
		super.focus();
		this.container.focus();
	}

	private render(): void {
		if (!this.input) {
			return;
		}
		this.renderDisposables.clear();
		// A status change re-renders the page where it was scrolled to.
		const { scrollTop } = this.scrollable.getScrollPosition();
		clearNode(this.container);
		const page = append(this.container, $('.page'));
		const project = this.projectService.project;
		if (!project) {
			append(page, $('p.muted', undefined, localize('overview.noProject', "No SAEngine project is open.")));
			return;
		}

		const header = append(page, $('.header'));
		append(header, $('h1', undefined, project.name));
		const type = PROJECT_TYPES.find(t => t.type === project.type)?.label ?? '';
		const path = append(header, $('p.path', { title: project.root.fsPath }));
		if (type) {
			append(path, $('span.type', undefined, localize('overview.type', "{0} ·", type)));
		}
		appendProjectPath(path, project.root, this.pathService.resolvedUserHome);

		const parts = this.projectService.parts;
		const statuses = this.statusService.statuses;
		const next = nextStep(statuses);
		const nextPart = next && parts[next.index];
		const nextBox = append(page, $('.next'));
		if (next && nextPart) {
			append(nextBox, $(`span.next-icon${ThemeIcon.asCSSSelector(Codicon.arrowRight)}`));
			append(nextBox, $('span.next-text', undefined, localize('overview.next', "Next: {0} {1} — {2}", next.index + 1, partName(nextPart), next.status.hint ?? '')));
			const button = this.renderDisposables.add(new Button(nextBox, defaultButtonStyles));
			button.label = localize('overview.openNext', "Open {0}", partName(nextPart));
			this.renderDisposables.add(button.onDidClick(() => this.open(nextPart)));
		} else if (statuses.length) {
			append(nextBox, $(`span.next-icon${ThemeIcon.asCSSSelector(Codicon.check)}`));
			append(nextBox, $('span.next-text', undefined, localize('overview.allDone', "Every part is up to date.")));
		}

		for (const group of partGroups(parts)) {
			const section = append(page, $('section.group'));
			append(section, $('h2', undefined, group.label));
			const list = append(section, $('ul'));
			for (const entry of group.parts) {
				const status = this.statusService.statusOf(entry.part.id);
				const item = append(list, $('li'));
				const row = append(item, $('button.part', { type: 'button', title: localize('overview.openPart', "Open {0}", entry.name) }));
				row.classList.toggle('is-next', entry.part === nextPart);
				append(row, $('span.number', undefined, String(entry.number)));
				append(row, $('span.name', undefined, entry.name));
				append(row, $(`span.sa-state-dot.${stateClass(status?.state)}`, { title: stateLabel(status) }));
				append(row, $('span.state', undefined, stateText(status)));
				append(row, $(`span.chevron${ThemeIcon.asCSSSelector(Codicon.chevronRight)}`));
				row.setAttribute('aria-label', [`${entry.number} ${entry.name}`, stateLabel(status), status?.text].filter(Boolean).join(', '));
				this.renderDisposables.add(addDisposableListener(row, EventType.CLICK, () => this.open(entry.part)));
			}
		}
		this.container.scrollTop = scrollTop;
		this.scrollable.scanDomNode();
	}

	private open(part: IProjectPart): void {
		const project = this.projectService.project;
		if (project) {
			openPart(project, part, { editorService: this.editorService, fileService: this.fileService, openerService: this.openerService, commandService: this.commandService })
				.catch(error => this.notificationService.error(error));
		}
	}
}
