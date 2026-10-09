/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/structuralEngineering.css';
import { append, $ } from '../../../../base/browser/dom.js';
import { Button } from '../../../../base/browser/ui/button/button.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { localize } from '../../../../nls.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { defaultButtonStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewletViewOptions } from '../../../browser/parts/views/viewsViewlet.js';

export const STRUCTURAL_ENGINEERING_VIEW_ID = 'workbench.view.structuralEngineering';

const engineeringActions = [
	{
		id: 'structuralEngineering.createProject',
		label: localize('structuralEngineering.createProject', "Create Engineering Project"),
		icon: Codicon.newFolder,
	},
	{
		id: 'structuralEngineering.openProject',
		label: localize('structuralEngineering.openProject', "Open Engineering Project"),
		icon: Codicon.folderOpened,
	},
	{
		id: 'structuralEngineering.configurePython',
		label: localize('structuralEngineering.configurePython', "Configure Python Runtime"),
		icon: Codicon.settingsGear,
	},
	{
		id: 'structuralEngineering.runAnalysis',
		label: localize('structuralEngineering.runAnalysis', "Run Analysis"),
		icon: Codicon.run,
	},
];

export class StructuralEngineeringView extends ViewPane {

	constructor(
		options: IViewletViewOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);

		const content = append(container, $('.structural-engineering-view'));
		const heading = append(content, $('h2'));
		heading.textContent = localize('structuralEngineering.heading', "Structural Engineering");

		const description = append(content, $('.structural-engineering-description'));
		description.textContent = localize(
			'structuralEngineering.description',
			"Create and analyze structural models in your engineering workspace.",
		);

		const actions = append(content, $('.structural-engineering-actions'));
		for (const [index, action] of engineeringActions.entries()) {
			const button = this._register(new Button(actions, {
				...defaultButtonStyles,
				secondary: index > 0,
				supportIcons: true,
			}));
			button.label = action.label;
			button.icon = action.icon;
			button.element.classList.add('structural-engineering-action');
			this._register(button.onDidClick(() => {
				void this.commandService.executeCommand(action.id);
			}));
		}

		const status = append(content, $('.structural-engineering-status'));
		status.textContent = localize(
			'structuralEngineering.initialStatus',
			"Project management, Python runtime configuration, and solver integration are not implemented yet.",
		);
	}
}
