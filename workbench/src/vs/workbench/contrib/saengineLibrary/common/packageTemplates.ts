/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

/*
 * The templates of the installed packages as the app applies them (docs/marketplace-plan.md,
 * round M4), read from the backend's `codes/templates` (saengine.codes.catalogue):
 *  - structure presets fill the modeller's Generate panel (grouped by package);
 *  - building specifications prefill the New Building wizard;
 *  - full building templates (an inputs-only `.civil`) open through New Project from Template...
 * Installing and removing them stays on the Packages page.
 */

/** `{ kind: 'structureTemplate' | 'buildingTemplate', root? }` -> the templates (backend). */
export const CODES_TEMPLATES_COMMAND = 'saengine.codes.templates';
/** `{ path, author? }` -> `{ ok, problems }`: may the archive be opened as a full template (backend). */
export const CODES_CHECK_TEMPLATE_COMMAND = 'saengine.codes.checkTemplate';
/** `{ path? }`: New Project from Template... (picks an installed full template when no path). */
export const NEW_FROM_TEMPLATE_COMMAND = 'saengine.project.newFromTemplate';
/** The building template the New Building wizard starts from. */
export const DEFAULT_BUILDING_TEMPLATE = 'saengine-default-building';

type Raw = { readonly [key: string]: unknown };

function isRaw(value: unknown): value is Raw {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

interface ITemplateOrigin {
	readonly package: string;
	readonly packageName: string;
	readonly version: string;
	readonly scope: string;
	readonly file: string;
}

/** A preset of a parametric shape: the Generate form's `shape`. */
export interface IStructurePreset extends ITemplateOrigin {
	readonly name: string;
	readonly description: string;
	readonly shape: Raw;
}

/** A building template: a specification (`spec`) or an inputs-only archive (`path`). */
export interface IBuildingTemplate extends ITemplateOrigin {
	readonly name: string;
	readonly description: string;
	readonly author: string;
	readonly type: 'spec' | 'archive';
	readonly spec?: Raw;
	readonly path?: string;
}

function origin(raw: Raw): ITemplateOrigin {
	return { package: str(raw.package), packageName: str(raw.packageName) || str(raw.package), version: str(raw.version), scope: str(raw.scope), file: str(raw.file) };
}

export function readStructurePresets(value: unknown): IStructurePreset[] {
	const list = isRaw(value) && Array.isArray(value.presets) ? value.presets : [];
	return list.filter(isRaw).filter(p => isRaw(p.shape) && str(p.name)).map(p => ({
		...origin(p),
		name: str(p.name),
		description: str(p.description),
		shape: p.shape as Raw,
	}));
}

export function readBuildingTemplates(value: unknown): IBuildingTemplate[] {
	const list = isRaw(value) && Array.isArray(value.templates) ? value.templates : [];
	const templates: IBuildingTemplate[] = [];
	for (const t of list.filter(isRaw)) {
		if (t.type === 'spec' && isRaw(t.spec)) {
			templates.push({ ...origin(t), name: str(t.name), description: str(t.description), author: str(t.author), type: 'spec', spec: t.spec });
		} else if (t.type === 'archive' && str(t.path)) {
			templates.push({ ...origin(t), name: str(t.name), description: str(t.description), author: str(t.author), type: 'archive', path: str(t.path) });
		}
	}
	return templates;
}

/** Presets grouped by package, in the backend's order (the built-in shapes first). */
export function groupPresets(presets: readonly IStructurePreset[]): { readonly package: string; readonly name: string; readonly presets: readonly IStructurePreset[] }[] {
	const groups = new Map<string, { package: string; name: string; presets: IStructurePreset[] }>();
	for (const preset of presets) {
		let group = groups.get(preset.package);
		if (!group) {
			group = { package: preset.package, name: preset.packageName, presets: [] };
			groups.set(preset.package, group);
		}
		group.presets.push(preset);
	}
	return [...groups.values()];
}
