/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelViews.css';
import { $, append, isKeyboardEvent } from '../../../../base/browser/dom.js';
import { IListVirtualDelegate } from '../../../../base/browser/ui/list/list.js';
import { IObjectTreeElement, ITreeNode, ITreeRenderer, ObjectTreeElementCollapseState } from '../../../../base/browser/ui/tree/tree.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { FuzzyScore } from '../../../../base/common/filters.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { WorkbenchObjectTree } from '../../../../platform/list/browser/listService.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService, sameSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { IModelNode, modelTree } from './modelData.js';
import { openOwner, ProjectDocuments } from './projectDocuments.js';

const SOURCE = 'explorer';

interface ITemplate {
	readonly icon: HTMLElement;
	readonly label: HTMLElement;
	readonly description: HTMLElement;
	readonly problem: HTMLElement;
}

class Delegate implements IListVirtualDelegate<IModelNode> {
	getHeight(): number {
		return 22;
	}
	getTemplateId(): string {
		return 'node';
	}
}

class Renderer implements ITreeRenderer<IModelNode, FuzzyScore, ITemplate> {
	readonly templateId = 'node';

	renderTemplate(container: HTMLElement): ITemplate {
		const row = append(container, $('.model-node'));
		return {
			icon: append(row, $('span.model-node-icon')),
			label: append(row, $('span.model-node-label')),
			description: append(row, $('span.model-node-description')),
			problem: append(row, $(`span.model-node-problem${ThemeIcon.asCSSSelector(Codicon.warning)}`)),
		};
	}

	renderElement(node: ITreeNode<IModelNode, FuzzyScore>, _index: number, template: ITemplate): void {
		const element = node.element;
		template.icon.className = `model-node-icon ${ThemeIcon.asClassName(element.icon)}`;
		template.label.textContent = element.label;
		template.description.textContent = element.description ?? '';
		template.problem.style.display = element.problem ? '' : 'none';
		template.problem.title = element.problem ?? '';
	}

	disposeTemplate(): void { }
}

/**
 * The project's model as a tree: the floor plan's grid lines and stories with the members on
 * each, the object types, and the state of the building model. Read-only: selecting shows the
 * item in the Floor Plan and the Properties view; opening it goes to the editor that owns it.
 */
export class ModelExplorerView extends ViewPane {

	static readonly ID = 'saengine.modelExplorer';

	private tree: WorkbenchObjectTree<IModelNode, FuzzyScore> | undefined;
	private readonly documents: ProjectDocuments;
	private nodes: IModelNode[] = [];
	private applyingSelection = false;

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
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this.documents = this._register(instantiationService.createInstance(ProjectDocuments));
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		container.classList.add('saengine-model-explorer');
		this.tree = this._register(this.instantiationService.createInstance(WorkbenchObjectTree<IModelNode, FuzzyScore>, 'SaengineModelExplorer', container, new Delegate(), [new Renderer()], {
			identityProvider: { getId: node => node.id },
			accessibilityProvider: {
				getAriaLabel: node => [node.label, node.description, node.problem].filter(Boolean).join(', '),
				getWidgetAriaLabel: () => localize('modelExplorer.aria', "Model Explorer"),
			},
			keyboardNavigationLabelProvider: { getKeyboardNavigationLabel: node => node.label },
			multipleSelectionSupport: false,
		}));
		this._register(this.tree.onDidChangeSelection(e => {
			const node = e.elements[0];
			if (!this.applyingSelection && node?.selection) {
				this.selectionService.setSelection(node.selection, SOURCE);
			}
		}));
		this._register(this.tree.onDidOpen(e => {
			const node = e.element;
			if (node && (e.browserEvent?.detail === 2 || (e.browserEvent && isKeyboardEvent(e.browserEvent)))) {
				void openOwner(node.selection, node.part, this.projectService.project?.root, this.editorService);
			}
		}));
		this._register(this.documents.onDidChange(() => this.refresh()));
		this._register(this.selectionService.onDidChangeSelection(({ source }) => {
			if (source !== SOURCE) {
				this.revealSelection();
			}
		}));
		this.refresh();
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		this.tree?.layout(height, width);
	}

	private refresh(): void {
		if (!this.tree) {
			return;
		}
		this.nodes = this.projectService.project ? modelTree(this.documents.documents) : [];
		const toElements = (nodes: readonly IModelNode[], depth: number): IObjectTreeElement<IModelNode>[] => nodes.map(node => ({
			element: node,
			children: node.children ? toElements(node.children, depth + 1) : undefined,
			collapsible: !!node.children?.length,
			// The floor plan, its stories and the type lists start open; member groups closed.
			collapsed: depth < 2 ? ObjectTreeElementCollapseState.PreserveOrExpanded : ObjectTreeElementCollapseState.PreserveOrCollapsed,
		}));
		this.tree.setChildren(null, toElements(this.nodes, 0));
		this.revealSelection();
	}

	/** Selects the node of the shared selection (e.g. a member picked in the Floor Plan). */
	private revealSelection(): void {
		const tree = this.tree;
		const selection = this.selectionService.selection;
		if (!tree) {
			return;
		}
		const find = (nodes: readonly IModelNode[]): IModelNode | undefined => {
			for (const node of nodes) {
				if (node.selection && sameSelection(node.selection, selection)) {
					return node;
				}
				const child = node.children && find(node.children);
				if (child) {
					return child;
				}
			}
			return undefined;
		};
		const node = selection ? find(this.nodes) : undefined;
		this.applyingSelection = true;
		try {
			if (node) {
				tree.expandTo(node);
				tree.setSelection([node]);
				tree.setFocus([node]);
				tree.reveal(node);
			} else {
				tree.setSelection([]);
			}
		} finally {
			this.applyingSelection = false;
		}
	}
}
