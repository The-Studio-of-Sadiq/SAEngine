/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelViews.css';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore, toDisposable } from '../../../../base/common/lifecycle.js';
import { localize, localize2 } from '../../../../nls.js';
import { Action2, registerAction2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { registerIcon } from '../../../../platform/theme/common/iconRegistry.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { Extensions as ViewExtensions, IViewContainersRegistry, IViewDescriptorService, IViewsRegistry, ViewContainerLocation } from '../../../common/views.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaenginePartStatusService, nextStep } from '../../../services/saengineProject/common/partStatus.js';
import { projectStages, stageStateLabel } from '../../../services/saengineProject/common/projectStages.js';
import { ISaengineProject, ISaengineProjectService, PROJECT_TYPES } from '../../../services/saengineProject/common/saengineProject.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { appendPropertyHeading, appendPropertyNote, appendPropertyRow } from '../../saengineProject/browser/editorFrame.js';
import { openPart, partName, stateText } from '../../saengineProject/browser/projectParts.js';
import { frameOfContainer } from '../../saengineProject/browser/modelLayoutModel.js';
import { dockStyleClasses, IPropertiesDockFrame, ISaenginePropertiesDockService, PROPERTIES_VIEW_CONTAINER_ID, PROPERTIES_VIEW_ID } from '../../saengineProject/browser/propertiesDock.js';
import { propertySheet } from './modelData.js';
import { openOwner, ProjectDocuments } from './projectDocuments.js';
import { propertyLink, renderPropertySheet } from './propertySheetView.js';

/*
 * The Properties panel on the right of the window (propertiesDock.ts): the properties of the
 * active SAEngine editor (its own panel's content, edited there as before), else the selection
 * made in the Tables or the Model Explorer (read-only, with where to change it), else the
 * project: its stages and the next step.
 */

/** The selection the Properties panel shows without an editor, as the Model Explorer selects it. */
export class PropertiesView extends ViewPane {

	static readonly ID = PROPERTIES_VIEW_ID;

	private dockElement: HTMLElement | undefined;
	private fallback: HTMLElement | undefined;
	private docked: IPropertiesDockFrame | undefined;
	private readonly documents: ProjectDocuments;
	private readonly fallbackStore = this._register(new DisposableStore());
	private readonly fallbackScheduler = this._register(new RunOnceScheduler(() => this.renderFallback(), 50));

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
		@ISaenginePropertiesDockService private readonly dockService: ISaenginePropertiesDockService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaenginePartStatusService private readonly statusService: ISaenginePartStatusService,
		@IEditorService private readonly editorService: IEditorService,
		@IFileService private readonly fileService: IFileService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this.documents = this._register(instantiationService.createInstance(ProjectDocuments));
		this._register(toDisposable(() => this.dock(undefined)));
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		container.classList.add('saengine-properties-view');
		this.dockElement = append(container, $('.sa-properties-dock'));
		this.fallback = append(container, $('.sa-properties-fallback.saengine-editor-frame'));

		const update = () => this.update();
		this._register(this.editorService.onDidActiveEditorChange(update));
		this._register(this.dockService.onDidChangeFrames(update));
		this._register(this.dockService.onDidChangeEnabled(update));
		this._register(this.onDidChangeBodyVisibility(update));
		const schedule = () => {
			if (!this.docked) {
				this.fallbackScheduler.schedule();
			}
		};
		this._register(this.selectionService.onDidChangeSelection(schedule));
		this._register(this.documents.onDidChange(schedule));
		this._register(this.statusService.onDidChange(schedule));
		this._register(this.projectService.onDidChangeProject(schedule));
		this.update();
	}

	/** Shows the properties of the active editor, or the selection and the project without one. */
	private update(): void {
		const visible = this.isBodyVisible() && this.dockService.enabled;
		const pane = this.editorService.activeEditorPane;
		const frame = visible && pane instanceof EditorPane ? frameOfContainer(this.dockService.frames, pane.getContainer()) : undefined;
		this.dock(frame);
		if (!frame) {
			this.renderFallback();
		}
	}

	private dock(frame: IPropertiesDockFrame | undefined): void {
		const host = this.dockElement;
		if (frame !== this.docked) {
			this.docked?.dock(undefined);
			this.docked = frame;
			if (host) {
				clearNode(host);
				if (frame) {
					// The editor's own classes, so its styles for the properties apply here too.
					const wrapper = append(host, $('.sa-docked-frame'));
					wrapper.classList.add(...dockStyleClasses(frame.element));
					frame.dock(wrapper);
				}
			}
		}
		host?.classList.toggle('hidden', !frame);
		this.fallback?.classList.toggle('hidden', !!frame);
	}

	private renderFallback(): void {
		const panel = this.fallback;
		if (!panel || this.docked) {
			return;
		}
		this.fallbackStore.clear();
		clearNode(panel);
		const content = append(panel, $('.sa-frame-panel-content'));
		const project = this.projectService.project;
		if (!project) {
			appendPropertyNote(content, localize('properties.noProject', "Open or create a project (File > New Project...) to see its model and the properties of what you select."));
			return;
		}
		const selection = this.selectionService.selection;
		const sheet = selection && propertySheet(selection, this.documents.documents);
		if (sheet) {
			renderPropertySheet(content, sheet, this.fallbackStore, action => {
				const part = action === 'editGrids' ? 'grids' : action === 'editObjectType' ? 'objects' : undefined;
				void openOwner(action === 'editObjectType' && sheet.objectType ? { kind: 'objectType', id: sheet.objectType } : selection, part, project.root, this.editorService);
			});
			appendPropertyNote(content, localize('properties.openToEdit', "Open the model view to change it: its properties then show here, ready to edit."));
			return;
		}
		this.renderProject(content, project);
	}

	/** The project summary: its stages, and the next step with a link to the part. */
	private renderProject(content: HTMLElement, project: ISaengineProject): void {
		const type = PROJECT_TYPES.find(t => t.type === project.type)?.label ?? project.type;
		appendPropertyHeading(content, project.name, type);
		const statuses = this.statusService.statuses;
		const next = nextStep(statuses);
		const part = next && this.projectService.parts.find(p => p.id === next.status.part);
		if (next && part) {
			append(content, $('.sa-props-section', undefined, localize('properties.next', "Next step")));
			appendPropertyRow(content, partName(part), stateText(next.status), next.status.state === 'failed' || next.status.state === 'error');
			if (next.status.hint) {
				appendPropertyNote(content, next.status.hint);
			}
			propertyLink(append(content, $('.sa-props-links')), localize('properties.openPart', "Open {0}", partName(part)), () => void openPart(project, part, {
				editorService: this.editorService, fileService: this.fileService, openerService: this.openerService, commandService: this.commandService,
			}), this.fallbackStore);
		}
		const stages = projectStages(statuses);
		if (stages.length) {
			append(content, $('.sa-props-section', undefined, localize('properties.stages', "Stages")));
			for (const stage of stages) {
				appendPropertyRow(content, stage.label, stageStateLabel(stage.state), stage.state === 'failed');
			}
		}
		appendPropertyNote(content, localize('properties.selectHint', "Select a member, a storey or a grid line in the model view, the Tables or the Model Explorer to see its properties here."));
	}
}

const propertiesViewIcon = registerIcon('saengine-properties-view-icon', Codicon.symbolProperty, localize('propertiesViewIcon', "View icon of the SAEngine Properties panel."));

const propertiesContainer = Registry.as<IViewContainersRegistry>(ViewExtensions.ViewContainersRegistry).registerViewContainer({
	id: PROPERTIES_VIEW_CONTAINER_ID,
	title: localize2('properties', "Properties"),
	icon: propertiesViewIcon,
	order: -1,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [PROPERTIES_VIEW_CONTAINER_ID, { mergeViewWithContainerWhenSingleView: true }]),
	storageId: PROPERTIES_VIEW_CONTAINER_ID,
}, ViewContainerLocation.AuxiliaryBar, { doNotRegisterOpenCommand: true });

Registry.as<IViewsRegistry>(ViewExtensions.ViewsRegistry).registerViews([{
	id: PROPERTIES_VIEW_ID,
	name: localize2('properties', "Properties"),
	containerIcon: propertiesViewIcon,
	ctorDescriptor: new SyncDescriptor(PropertiesView),
	canToggleVisibility: false,
	canMoveView: true,
	order: 0,
}], propertiesContainer);

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'saengine.showProperties',
			title: localize2('saengine.showProperties', "Show Properties"),
			category: localize2('saengine.category', "SAEngine"),
			f1: true,
		});
	}

	override async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IViewsService).openView(PROPERTIES_VIEW_ID, true);
	}
});
