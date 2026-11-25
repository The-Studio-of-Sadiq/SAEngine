/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import './media/startBackdrop.css';
import { addDisposableListener } from '../../../../base/browser/dom.js';
import { mainWindow } from '../../../../base/browser/window.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { INativeHostService } from '../../../../platform/native/common/native.js';
import { isHighContrast } from '../../../../platform/theme/common/theme.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { ISaengineProjectService } from '../../../services/saengineProject/common/saengineProject.js';
import { wantsAcrylic } from '../common/startBackdrop.js';

/** Body class while the window shows the acrylic backdrop (see media/startBackdrop.css). */
const ACRYLIC_CLASS = 'saengine-acrylic';

/**
 * The Start page on the Windows 11 acrylic (frosted) backdrop, a calm first screen: while no
 * project is open the window's background turns translucent and the workbench layers over the
 * Start page let it through (the main process keeps the window buttons unfilled meanwhile).
 * Opening a project brings back the theme's solid background. On Windows before 11 22H2 the
 * native host declines and the page stays solid.
 */
class StartBackdropContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.startBackdrop';

	private readonly reducedTransparency = mainWindow.matchMedia('(prefers-reduced-transparency: reduce)');
	private requested: boolean | undefined;

	constructor(
		@INativeHostService private readonly nativeHostService: INativeHostService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@IThemeService private readonly themeService: IThemeService,
	) {
		super();
		this._register(this.projectService.onDidChangeProject(() => this.update()));
		this._register(this.themeService.onDidColorThemeChange(() => this.update()));
		this._register(addDisposableListener(this.reducedTransparency, 'change', () => this.update()));
		this.update();
	}

	private update(): void {
		const wanted = wantsAcrylic(!!this.projectService.project, isHighContrast(this.themeService.getColorTheme().type), this.reducedTransparency.matches);
		if (wanted === this.requested) {
			return;
		}
		this.requested = wanted;
		if (!wanted) {
			// Solid at once: the page must not go transparent over a solid window.
			mainWindow.document.body.classList.remove(ACRYLIC_CLASS);
		}
		this.nativeHostService.setWindowBackgroundMaterial(wanted ? 'acrylic' : 'none').then(shown => {
			if (this.requested === wanted) {
				mainWindow.document.body.classList.toggle(ACRYLIC_CLASS, shown);
			}
		}, () => { /* unsupported: keep the solid look */ });
	}
}

registerWorkbenchContribution2(StartBackdropContribution.ID, StartBackdropContribution, WorkbenchPhase.BlockRestore);
