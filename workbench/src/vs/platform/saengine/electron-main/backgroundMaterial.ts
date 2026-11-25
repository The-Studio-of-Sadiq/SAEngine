/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import type { BrowserWindow } from 'electron';

/**
 * SAEngine: the windows that currently show the Windows 11 acrylic backdrop (set through the native
 * host's setWindowBackgroundMaterial). Their background colour must stay transparent: the theme
 * service leaves them alone until the material is switched off again.
 */
export const acrylicWindows = new WeakSet<BrowserWindow>();
