/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/modelViews.css';
import { $, append, clearNode } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService, ModelSelection } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { PropertyAction, propertySheet } from './modelData.js';
import { OPEN_OWNER_LABELS, openOwner, ProjectDocuments } from './projectDocuments.js';

const ACTION_ICONS: { readonly [action in PropertyAction]: ThemeIcon } = {
	showInFloorPlan: Codicon.symbolArray,
	editGrids: Codicon.table,
	editObjectType: Codicon.symbolClass,
};

/**
 * The properties of the selected item, read-only. Each sheet links to the editor that owns
 * what it shows, where it is changed.
 */
export class PropertiesView extends ViewPane {

	static readonly ID = 'saengine.properties';

	private sheetContainer: HTMLElement | undefined;
	private readonly documents: ProjectDocuments;
	private readonly sheetDisposables = this._register(new DisposableStore());

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
		this.sheetContainer = append(container, $('.saengine-properties'));
		this._register(this.selectionService.onDidChangeSelection(() => this.renderSheet()));
		this._register(this.documents.onDidChange(() => this.renderSheet()));
		this.renderSheet();
	}

	private renderSheet(): void {
		const body = this.sheetContainer;
		if (!body) {
			return;
		}
		this.sheetDisposables.clear();
		clearNode(body);
		const selection = this.selectionService.selection;
		const sheet = selection && propertySheet(selection, this.documents.documents);
		if (!selection || !sheet) {
			append(body, $('p.properties-empty', undefined, localize('properties.empty', "Select a member, story, grid line or object type in the Floor Plan or the Model Explorer to see its properties.")));
			return;
		}
		const header = append(body, $('.properties-header'));
		append(header, $('span.properties-title', undefined, sheet.title));
		append(header, $('span.properties-subtitle', undefined, sheet.subtitle));

		for (const section of sheet.sections) {
			append(body, $('h4.properties-section', undefined, section.title));
			const table = append(body, $('.properties-table', { role: 'table', 'aria-label': section.title }));
			for (const row of section.rows) {
				const line = append(table, $('.properties-row', { role: 'row' }));
				append(line, $('span.properties-label', { role: 'rowheader' }, row.label));
				const value = append(line, $('span.properties-value', { role: 'cell' }));
				if (row.problem) {
					value.classList.add('problem');
					append(value, $(`span${ThemeIcon.asCSSSelector(Codicon.warning)}`)).setAttribute('aria-hidden', 'true');
				}
				append(value, $('span', undefined, row.value));
			}
		}

		append(body, $('p.properties-note', undefined, localize('properties.readOnly', "Properties are read-only here; change them in the editor that owns them.")));
		const actions = append(body, $('.properties-actions'));
		for (const action of sheet.actions) {
			const button = this.sheetDisposables.add(new Button(actions, { ...defaultButtonStyles, secondary: true, supportIcons: true }));
			button.label = `$(${ACTION_ICONS[action].id}) ${OPEN_OWNER_LABELS[action]}`;
			this.sheetDisposables.add(button.onDidClick(() => this.run(action, selection, sheet.objectType)));
		}
	}

	private run(action: PropertyAction, selection: ModelSelection, objectType: string | undefined): void {
		const root = this.projectService.project?.root;
		switch (action) {
			case 'showInFloorPlan':
				void openOwner(selection, 'floorPlan', root, this.editorService);
				break;
			case 'editGrids':
				void openOwner(undefined, 'grids', root, this.editorService);
				break;
			case 'editObjectType':
				void openOwner(objectType ? { kind: 'objectType', id: objectType } : undefined, 'objects', root, this.editorService);
				break;
		}
	}
}
