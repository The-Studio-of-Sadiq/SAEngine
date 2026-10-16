/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/projectNavigator.css';
import { $, append, isHTMLElement } from '../../../../base/browser/dom.js';
import { IListVirtualDelegate } from '../../../../base/browser/ui/list/list.js';
import { IObjectTreeElement, ITreeNode, ITreeRenderer, ObjectTreeElementCollapseState } from '../../../../base/browser/ui/tree/tree.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { isEqual, isEqualOrParent, joinPath } from '../../../../base/common/resources.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService, IFileStat } from '../../../../platform/files/common/files.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { WorkbenchObjectTree } from '../../../../platform/list/browser/listService.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { EditorResourceAccessor } from '../../../common/editor.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IPartStatus, ISaenginePartStatusService } from '../../../services/saengineProject/common/partStatus.js';
import { IProjectPart, ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IPartEntry, openPart, partGroups, partResource, stateClass, stateLabel, stateText } from './projectParts.js';

/** Setting (registered with the developer mode) that shows the raw files under each part. */
export const DEVELOPER_MODE_SETTING = 'saengine.developerMode';

/** How deep the raw files of a part are listed in developer mode. */
const FILE_DEPTH = 4;

interface IGroupNode {
	readonly kind: 'group';
	readonly id: string;
	readonly label: string;
}

interface IPartNode {
	readonly kind: 'part';
	readonly id: string;
	readonly entry: IPartEntry;
	readonly status: IPartStatus | undefined;
}

interface IFileNode {
	readonly kind: 'file';
	readonly id: string;
	readonly resource: URI;
	readonly name: string;
	readonly isDirectory: boolean;
}

type NavigatorNode = IGroupNode | IPartNode | IFileNode;

class Delegate implements IListVirtualDelegate<NavigatorNode> {
	getHeight(node: NavigatorNode): number {
		switch (node.kind) {
			case 'group': return 30;
			case 'part': return 28;
			default: return 22;
		}
	}
	getTemplateId(node: NavigatorNode): string {
		return node.kind;
	}
}

class GroupRenderer implements ITreeRenderer<NavigatorNode, void, HTMLElement> {
	readonly templateId = 'group';
	renderTemplate(container: HTMLElement): HTMLElement {
		return append(container, $('.sa-nav-group'));
	}
	renderElement(node: ITreeNode<NavigatorNode, void>, _index: number, label: HTMLElement): void {
		label.textContent = node.element.kind === 'group' ? node.element.label : '';
	}
	disposeTemplate(): void { }
}

interface IPartTemplate {
	readonly row: HTMLElement;
	readonly number: HTMLElement;
	readonly name: HTMLElement;
	readonly dot: HTMLElement;
	readonly text: HTMLElement;
}

class PartRenderer implements ITreeRenderer<NavigatorNode, void, IPartTemplate> {
	readonly templateId = 'part';
	constructor(private readonly isActive: (part: IProjectPart) => boolean) { }
	renderTemplate(container: HTMLElement): IPartTemplate {
		const row = append(container, $('.sa-nav-part'));
		return {
			row,
			number: append(row, $('span.sa-nav-number')),
			name: append(row, $('span.sa-nav-name')),
			dot: append(row, $('span.sa-state-dot')),
			text: append(row, $('span.sa-nav-state')),
		};
	}
	renderElement(node: ITreeNode<NavigatorNode, void>, _index: number, template: IPartTemplate): void {
		if (node.element.kind !== 'part') {
			return;
		}
		const { entry, status } = node.element;
		template.number.textContent = String(entry.number);
		template.name.textContent = entry.name;
		template.dot.className = `sa-state-dot ${stateClass(status?.state)}`;
		template.dot.title = stateLabel(status);
		template.text.textContent = stateText(status);
		template.row.classList.toggle('active', this.isActive(entry.part));
	}
	disposeTemplate(): void { }
}

interface IFileTemplate {
	readonly icon: HTMLElement;
	readonly name: HTMLElement;
}

class FileRenderer implements ITreeRenderer<NavigatorNode, void, IFileTemplate> {
	readonly templateId = 'file';
	renderTemplate(container: HTMLElement): IFileTemplate {
		const row = append(container, $('.sa-nav-file'));
		return { icon: append(row, $('span.sa-nav-file-icon')), name: append(row, $('span.sa-nav-file-name')) };
	}
	renderElement(node: ITreeNode<NavigatorNode, void>, _index: number, template: IFileTemplate): void {
		if (node.element.kind !== 'file') {
			return;
		}
		template.icon.className = `sa-nav-file-icon ${ThemeIcon.asClassName(node.element.isDirectory ? Codicon.folder : Codicon.file)}`;
		template.name.textContent = node.element.name;
	}
	disposeTemplate(): void { }
}

/**
 * The project in the sidebar: its parts, numbered in workflow order under small group headings,
 * each with its status. Selecting a part opens its editor. In developer mode the files of each
 * part are listed under it.
 */
export class ProjectNavigatorView extends ViewPane {

	static readonly ID = 'saengine.projectNavigator';

	private tree: WorkbenchObjectTree<NavigatorNode, void> | undefined;
	private activeResource: URI | undefined;
	private partNodes: IPartNode[] = [];
	private readonly refreshScheduler = this._register(new RunOnceScheduler(() => void this.refresh(), 200));

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
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this._register(this.projectService.onDidChangeProject(() => {
			this._onDidChangeTitleArea.fire();
			this.refreshScheduler.schedule();
		}));
	}

	/** The sidebar's title is the project's name. */
	override get singleViewPaneContainerTitle(): string | undefined {
		return this.projectService.project?.name ?? super.singleViewPaneContainerTitle;
	}

	private get developerMode(): boolean {
		return this.configurationService.getValue<boolean>(DEVELOPER_MODE_SETTING) === true;
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		container.classList.add('saengine-project-navigator');
		this.tree = this._register(this.instantiationService.createInstance(WorkbenchObjectTree<NavigatorNode, void>, 'SaengineProjectNavigator', container, new Delegate(), [
			new GroupRenderer(),
			new PartRenderer(part => this.isActive(part)),
			new FileRenderer(),
		], {
			identityProvider: { getId: node => node.id },
			accessibilityProvider: {
				getAriaLabel: node => {
					switch (node.kind) {
						case 'group': return node.label;
						case 'part': return [`${node.entry.number} ${node.entry.name}`, stateLabel(node.status), node.status?.text].filter(Boolean).join(', ');
						default: return node.name;
					}
				},
				getWidgetAriaLabel: () => localize('projectNavigator.aria', "Project Parts"),
			},
			keyboardNavigationLabelProvider: { getKeyboardNavigationLabel: node => node.kind === 'part' ? node.entry.name : node.kind === 'file' ? node.name : node.label },
			multipleSelectionSupport: false,
			expandOnlyOnTwistieClick: true,
			indent: 12,
		}));
		this._register(this.tree.onDidOpen(e => void this.open(e.element, !!e.editorOptions.preserveFocus)));
		// Only opening a part moves the selection: a heading, or a twistie (which expands a part
		// without opening it), leaves it on the part whose editor is active.
		this._register(this.tree.onDidChangeSelection(e => {
			const selected = e.elements[0];
			const twistie = isHTMLElement(e.browserEvent?.target) && !!e.browserEvent.target.closest('.monaco-tl-twistie');
			if (selected?.kind === 'group' || (selected?.kind === 'part' && twistie && !this.isActive(selected.entry.part))) {
				this.selectActive();
			}
		}));
		this._register(this.statusService.onDidChange(() => this.refreshScheduler.schedule()));
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(DEVELOPER_MODE_SETTING)) {
				this.refreshScheduler.schedule();
			}
		}));
		// The raw files change without the parts' statuses changing.
		this._register(this.fileService.onDidFilesChange(e => {
			const root = this.projectService.project?.root;
			if (root && this.developerMode && e.affects(root)) {
				this.refreshScheduler.schedule();
			}
		}));
		this._register(this.editorService.onDidActiveEditorChange(() => this.updateActive()));
		this.updateActive();
		void this.refresh();
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		this.tree?.layout(height, width);
	}

	override focus(): void {
		super.focus();
		this.tree?.domFocus();
	}

	private isActive(part: IProjectPart): boolean {
		const project = this.projectService.project;
		const active = this.activeResource;
		if (!project || !active) {
			return false;
		}
		const resource = partResource(project, part);
		return resource ? isEqual(resource, active) : isEqualOrParent(active, joinPath(project.root, part.folder));
	}

	/** The part whose editor is active is the selected row. */
	private updateActive(): void {
		this.activeResource = EditorResourceAccessor.getOriginalUri(this.editorService.activeEditor);
		if (!this.tree) {
			return;
		}
		this.selectActive();
		// The list rerenders all rows only with dynamic heights: the parts are rerendered one by one.
		for (const node of this.partNodes) {
			this.tree.rerender(node);
		}
	}

	/** Selects (and focuses) the part whose editor is active; nothing when no part's is. */
	private selectActive(): void {
		if (!this.tree) {
			return;
		}
		const active = this.partNodes.find(node => this.isActive(node.entry.part));
		const selected = this.tree.getSelection()[0];
		if (active) {
			if (selected !== active) {
				this.tree.setSelection([active]);
				this.tree.setFocus([active]);
			}
		} else if (selected && selected.kind !== 'file') {
			this.tree.setSelection([]);
		}
	}

	private async refresh(): Promise<void> {
		const project = this.projectService.project;
		if (!this.tree) {
			return;
		}
		this.element.classList.toggle('developer-mode', this.developerMode);
		if (!project) {
			this.tree.setChildren(null, []);
			return;
		}
		const developerMode = this.developerMode;
		const elements: IObjectTreeElement<NavigatorNode>[] = [];
		const partNodes: IPartNode[] = [];
		for (const group of partGroups(this.projectService.parts)) {
			elements.push({ element: { kind: 'group', id: `group:${group.id}`, label: group.label }, collapsible: false });
			for (const entry of group.parts) {
				const children = developerMode ? await this.files(joinPath(project.root, entry.part.folder), FILE_DEPTH) : [];
				const node: IPartNode = { kind: 'part', id: `part:${entry.part.id}`, entry, status: this.statusService.statusOf(entry.part.id) };
				partNodes.push(node);
				elements.push({
					element: node,
					children,
					collapsible: children.length > 0,
					collapsed: ObjectTreeElementCollapseState.PreserveOrCollapsed,
				});
			}
		}
		if (project !== this.projectService.project) {
			return; // changed meanwhile
		}
		this.tree.setChildren(null, elements);
		this.partNodes = partNodes;
		this.updateActive();
	}

	private async files(folder: URI, depth: number): Promise<IObjectTreeElement<NavigatorNode>[]> {
		let stat: IFileStat;
		try {
			stat = await this.fileService.resolve(folder);
		} catch {
			return [];
		}
		const children = [...stat.children ?? []].sort((a, b) => Number(b.isDirectory) - Number(a.isDirectory) || a.name.localeCompare(b.name));
		return Promise.all(children.map(async child => {
			const grandChildren = child.isDirectory && depth > 1 ? await this.files(child.resource, depth - 1) : [];
			return {
				element: { kind: 'file' as const, id: `file:${child.resource.toString()}`, resource: child.resource, name: child.name, isDirectory: child.isDirectory },
				children: grandChildren,
				collapsible: child.isDirectory,
				collapsed: ObjectTreeElementCollapseState.PreserveOrCollapsed,
			};
		}));
	}

	private async open(node: NavigatorNode | undefined, preserveFocus: boolean): Promise<void> {
		const project = this.projectService.project;
		if (!node || !project) {
			return;
		}
		if (node.kind === 'part') {
			await openPart(project, node.entry.part, { editorService: this.editorService, fileService: this.fileService, openerService: this.openerService, commandService: this.commandService }, { preserveFocus });
		} else if (node.kind === 'file' && !node.isDirectory) {
			await this.editorService.openEditor({ resource: node.resource, options: { preserveFocus } });
		}
	}
}
