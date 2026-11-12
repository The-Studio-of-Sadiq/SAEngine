/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { createTrustedTypesPolicy } from '../../../../base/browser/trustedTypes.js';
import { resolveAmdNodeModulePath } from '../../../../amdX.js';

export type ViewerModule = typeof import('@saengine/fem-viewer');

const PACKAGE = '@saengine/fem-viewer';

let viewerModule: Promise<ViewerModule> | undefined;

/** Folder URL (with trailing slash) of the viewer's runtime assets (fragments worker, web-ifc wasm). */
export function viewerAssetBaseUrl(): string {
	return resolveAmdNodeModulePath(PACKAGE, 'dist/');
}

/**
 * The 3D viewers (FEM model, building model) bundle three.js and That Open Engine as a single
 * ESM file, loaded by URL on first use so the workbench startup bundle does not pay for it. Its
 * workers may only be started from the bundle's own folder (Trusted Types).
 */
export function loadViewerModule(): Promise<ViewerModule> {
	if (!viewerModule) {
		viewerModule = (async () => {
			const module = await import(/* webpackIgnore: true */ /* @vite-ignore */ `${resolveAmdNodeModulePath(PACKAGE, 'dist/fem-viewer.js')}`) as ViewerModule;
			const base = viewerAssetBaseUrl();
			const policy = createTrustedTypesPolicy('saengineIfcWorker', {
				createScriptURL(value: string) {
					if (!value.startsWith(base)) {
						throw new Error(`Refusing to start a viewer worker from ${value}`);
					}
					return value;
				},
			});
			module.setTrustedTypesHost({ scriptUrl: value => policy?.createScriptURL(value) ?? value });
			return module;
		})();
		viewerModule.catch(() => viewerModule = undefined);
	}
	return viewerModule;
}
