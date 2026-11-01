/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { SETUP_COMPONENTS, SetupComponent } from '../../../../platform/saengine/common/femSolver.js';

/**
 * The optional components of the SAEngine setup (docs/marketplace-plan.md §6, round M6): the
 * separate programs EnergyPlus, LibreCAD and LibreDWG, and the built-in extensions of the AI
 * assistant (Copilot), Git and collaboration, ticked in the setup's Full type and left out of
 * Compact. A missing component is a state, not an error: the part that uses it says so and
 * offers *Add Component...*, which re-runs the setup the user chose (checked against the release's
 * SHA-256) with `/COMPONENTS=`. SAEngine downloads no program by itself (D7).
 *
 * The workbench side (../electron-browser/saengineComponents.ts) finds each state where the
 * program is found for use (the backend's `find_energyplus` and `find_converter`, the shared
 * process's `findCadProgram`) and runs the setup.
 */

/** `(component?: SetupComponent)`: adds a component by re-running the setup (desktop only). */
export const COMPONENTS_ADD_COMMAND = 'saengine.components.add';
/** `()` -> `IComponentStates`: the state of every optional component (desktop only). */
export const COMPONENTS_STATES_COMMAND = 'saengine.components.states';
/** `()`: Help > Installer Components..., the list with each state (desktop only). */
export const COMPONENTS_SHOW_COMMAND = 'saengine.components.show';

/**
 * The components that are built-in extensions (`code.iss` installs their folders under
 * `resources\app\extensions`), each with the extension whose presence tells its state.
 */
export const EXTENSION_COMPONENTS = {
	ai: 'GitHub.copilot-chat',
	git: 'vscode.git',
	collaboration: 'vscode.tunnel-forwarding',
} as const satisfies { readonly [K in SetupComponent]?: string };

export type ExtensionComponent = keyof typeof EXTENSION_COMPONENTS;

/**
 * The context key that holds an extension component's state (`installed`, `elsewhere`,
 * `missing`), so menus and view welcomes can offer *Add Component...* where the component is
 * used, e.g. `saengine.component.git == missing` in Source Control.
 */
export function componentContextKey(component: ExtensionComponent): string {
	return `saengine.component.${component}`;
}

/** Whether the part that uses the component can use it (the setup's copy or one found elsewhere). */
export function isUsable(status: IComponentStatus): boolean {
	return status.state === 'installed' || status.state === 'elsewhere';
}

/**
 * The command link of *Add Component...* for a view welcome or a Markdown message
 * (`command:saengine.components.add?["git"]`).
 */
export function addComponentLink(component: SetupComponent): string {
	return `command:${COMPONENTS_ADD_COMMAND}?${encodeURIComponent(JSON.stringify([component]))}`;
}

/**
 * `installed`: the setup's copy in the app folder; `elsewhere`: found another way (an environment
 * variable, a setting, a program installed separately), which works too; `missing`: none, the
 * part works without it in a reduced way; `unknown`: the backend could not be asked.
 */
export type ComponentState = 'installed' | 'elsewhere' | 'missing' | 'unknown';

export interface IComponentStatus {
	readonly state: ComponentState;
	/** The program found, for `installed` and `elsewhere`. */
	readonly path?: string;
}

export type IComponentStates = { readonly [K in SetupComponent]: IComponentStatus };

/** The component's name as the setup's Select Components page shows it. */
export function componentLabel(component: SetupComponent): string {
	switch (component) {
		case 'energyplus': return localize('component.energyplus', "Energy simulation (EnergyPlus)");
		case 'librecad': return localize('component.librecad', "CAD editor (LibreCAD)");
		case 'libredwg': return localize('component.libredwg', "DWG import and export (LibreDWG)");
		case 'ai': return localize('component.ai', "AI assistant");
		case 'git': return localize('component.git', "Git");
		case 'collaboration': return localize('component.collaboration', "Collaboration (remote access)");
	}
}

/** What the component is for, and what SAEngine does without it. */
export function componentPurpose(component: SetupComponent): string {
	switch (component) {
		case 'energyplus': return localize('component.energyplusPurpose', "The design-day cooling loads of 7 MEP › HVAC. Without it the loads are SAEngine's estimate.");
		case 'librecad': return localize('component.librecadPurpose', "Edits the DXF drawings SAEngine exports (Open in LibreCAD). Without it they open in the program Windows uses for DXF files.");
		case 'libredwg': return localize('component.libredwgPurpose', "Reads the architects' DWG drawings (underlays, imports) and writes the drawing sheets as DWG. Without it a DWG must be saved as DXF first, and the sheets are DXF only.");
		case 'ai': return localize('component.aiPurpose', "The AI Assistant view (BNBC 2020 questions answered from the code pack with clause citations, explanations of results, changes you preview and accept; your own Anthropic or OpenAI-compatible key) and the GitHub Copilot chat. Without it there is no assistant in SAEngine; assistants outside SAEngine can still connect (Allow AI Assistants to Control This Window).");
		case 'git': return localize('component.gitPurpose', "Project history with Git and GitHub, in Developer Mode. Without it SAEngine keeps its own versions of the project.");
		case 'collaboration': return localize('component.collaborationPurpose', "Port forwarding and Microsoft sign-in for remote access, and live co-editing of a shared project once its engine is added. Shared projects (office copy, sync, part locks, presence) work without it.");
	}
}

/** One short line for a state, e.g. in a list. */
export function componentStateText(status: IComponentStatus): string {
	switch (status.state) {
		case 'installed': return localize('component.installed', "installed");
		case 'elsewhere': return localize('component.elsewhere', "not installed by the setup; using {0}", status.path ?? '');
		case 'missing': return localize('component.missing', "not installed");
		case 'unknown': return localize('component.unknown', "state unknown (the SAEngine backend is not running)");
	}
}

/**
 * The `/COMPONENTS=` list for re-running the setup to add `add`: the components the setup
 * installed and `add`, in the setup's order. Inno Setup takes the list as the whole selection
 * (it has no merge switch for components), so a component left out would be removed.
 */
export function setupComponents(states: IComponentStates, add: SetupComponent): SetupComponent[] {
	return SETUP_COMPONENTS.filter(component => component === add || states[component].state === 'installed');
}

/**
 * The releases page on GitHub for the releases API URL of product.json's
 * `saengineUpdate.releasesUrl` (`https://api.github.com/repos/<owner>/<repo>/releases...`).
 */
export function releasesPage(releasesUrl: string | undefined): string | undefined {
	const match = /^https:\/\/api\.github\.com\/repos\/([^/?#]+)\/([^/?#]+)\/releases\b/.exec(releasesUrl ?? '');
	return match ? `https://github.com/${match[1]}/${match[2]}/releases` : undefined;
}

/** A component state from the backend's `components/list` answer (`{state, path?}`). */
export function readComponentStatus(value: unknown): IComponentStatus {
	const bag = (typeof value === 'object' && value !== null ? value : {}) as { readonly state?: unknown; readonly path?: unknown };
	const state = bag.state === 'installed' || bag.state === 'elsewhere' || bag.state === 'missing' ? bag.state : 'unknown';
	return typeof bag.path === 'string' && state !== 'missing' ? { state, path: bag.path } : { state };
}
