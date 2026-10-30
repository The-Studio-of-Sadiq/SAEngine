/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { BNBC } from '../../../services/saengineProject/common/projectLibraries.generated.js';

/*
 * Code packs: a design code (BNBC 2020, or a region's own) as a folder of data tables with a
 * manifest (`pack.json`), which may extend another pack. The backend (`saengine.codes`) finds,
 * resolves and validates them; this module turns what its commands answer into what the project
 * settings' "Design code" selector and the Code Packs page show. It reads the answers tolerantly:
 * a field missing or of another shape falls back to a quiet default rather than failing.
 */

/** `{ root? }` → the packs found: built-in, the user's and the project's (with their problems). */
export const CODES_LIST_COMMAND = 'saengine.codes.list';
/** `{ id, root? }` → one pack resolved: its manifest, tables, sources, problems and trust state. */
export const CODES_SHOW_COMMAND = 'saengine.codes.show';
/** `{ id, name, extends, dest?, scope, root? }` → `{ path }`: makes a new pack's skeleton. */
export const CODES_NEW_COMMAND = 'saengine.codes.new';
/** `{ path, scope: 'user' | 'project', root? }` → `{ id, path }`: copies a pack folder or zip in. */
export const CODES_INSTALL_COMMAND = 'saengine.codes.install';
/** `{ path }` → the problems of the pack folder at `path` (empty when it is valid). */
export const CODES_VALIDATE_COMMAND = 'saengine.codes.validate';
/** `{ id, trusted, root? }`: allows (or no longer allows) a pack's hooks to run. */
export const CODES_TRUST_COMMAND = 'saengine.codes.trust';

/** The pack a project uses when its settings name none (and every project before code packs). */
export const DEFAULT_CODE_PACK = 'bnbc2020';

/** The folder of a project's own packs, which travel with the project and its archive. */
export const PROJECT_PACKS_FOLDER = '02 Project Settings/code-packs';

/** Where a pack is installed. */
export type CodePackScope = 'builtin' | 'user' | 'project';

const SCOPES: readonly CodePackScope[] = ['builtin', 'user', 'project'];

/** Whether a pack's hooks (Python that replaces design functions) may run. */
export type CodePackTrust = 'none' | 'trusted' | 'untrusted';

/** One clause or document a table comes from ("BNBC 2020 Part 6 Table 6.2.14, p. 3160"). */
export interface ICodePackSource {
	/** The table (or "pack") the reference is for. */
	readonly table: string;
	readonly text: string;
}

/** A pack as the list shows it. */
export interface ICodePackInfo {
	readonly id: string;
	readonly name: string;
	readonly edition: string;
	readonly region: string;
	readonly version: string;
	readonly extends: string | undefined;
	/** The areas the pack provides itself (`locations`, `combinations`, ...), the rest inherited. */
	readonly covers: readonly string[];
	readonly scope: CodePackScope;
	/** The pack's folder on disk, when the backend tells it. */
	readonly path: string | undefined;
	readonly problems: readonly string[];
	/**
	 * Whether the pack can be loaded and chosen: false when it or a pack it extends has an error
	 * (the backend's `usable`, else no problem of severity `error`).
	 */
	readonly usable: boolean;
	/** False when a pack of the same id in a higher scope is used instead (the project's over the user's over a built-in one). */
	readonly effective: boolean;
	/** The scope whose pack of the same id is used instead of this one, when shadowed. */
	readonly shadowedBy: CodePackScope | undefined;
	readonly trust: CodePackTrust;
	/** The packs of the chain whose hooks run with this pack (its own and its parents'). */
	readonly hooksFrom: readonly string[];
	readonly author: string;
	readonly licence: string;
	readonly description: string;
	readonly sources: readonly ICodePackSource[];
	/** The resolved tables (own and inherited) with where each comes from, when shown in detail. */
	readonly tables: readonly { readonly name: string; readonly from: string }[];
}

/** A group of the Code Packs page: Built-in, Your packs, This project. */
export interface ICodePackGroup {
	readonly scope: CodePackScope;
	readonly title: string;
	readonly packs: readonly ICodePackInfo[];
	/** What the group says when it has no packs. */
	readonly empty: string;
}

type Raw = { readonly [key: string]: unknown };

function isRaw(value: unknown): value is Raw {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown, fallback = ''): string {
	return typeof value === 'string' ? value : typeof value === 'number' ? String(value) : fallback;
}

/** A list of strings from `value`: strings, `{ message }` objects, or the keys of an object. */
function texts(value: unknown, key = 'message'): string[] {
	if (Array.isArray(value)) {
		return value.map(v => isRaw(v) ? text(v[key] ?? v.text ?? v.id ?? v.name) : text(v)).filter(v => v.length > 0);
	}
	if (isRaw(value)) {
		return Object.keys(value).filter(k => value[k] !== false);
	}
	return [];
}

function scopeOf(raw: Raw): CodePackScope {
	const value = text(raw.scope ?? raw.origin ?? raw.kind ?? raw.location).toLowerCase().replace(/[-_ ]/g, '');
	if (value === 'builtin' || value === 'bundled' || value === 'system') {
		return 'builtin';
	}
	if (value === 'project' || value === 'local') {
		return 'project';
	}
	return value === 'user' ? 'user' : (raw.builtin === true || raw.builtIn === true ? 'builtin' : 'user');
}

function scopeValue(value: unknown): CodePackScope | undefined {
	const scope = text(value).toLowerCase().replace(/[-_ ]/g, '');
	return scope === 'builtin' || scope === 'user' || scope === 'project' ? scope : undefined;
}

/**
 * Whether the pack runs hooks and may: the backend's PackInfo says `hooks: true` (its own or its
 * parents'), with `trusted` and `untrustedHooks`; a manifest names the module (a string or an object).
 */
function trustOf(raw: Raw, manifest: Raw): CodePackTrust {
	const hooks = raw.hooks ?? manifest.hooks;
	const untrusted = texts(raw.untrustedHooks);
	const has = hooks === true || raw.hasHooks === true || (typeof hooks === 'string' && hooks.length > 0) || (isRaw(hooks) && Object.keys(hooks).length > 0)
		|| texts(raw.hooksFrom).length > 0 || untrusted.length > 0;
	if (!has) {
		return 'none';
	}
	return (raw.trusted === true || raw.trust === 'trusted') && untrusted.length === 0 ? 'trusted' : 'untrusted';
}

/** The problems that stop a pack from loading: those of severity `error` (the backend's default). */
function errorCount(value: unknown): number {
	return Array.isArray(value) ? value.filter(p => isRaw(p) && text(p.severity, 'error').toLowerCase() === 'error').length : 0;
}

function sourcesOf(value: unknown): ICodePackSource[] {
	const result: ICodePackSource[] = [];
	if (Array.isArray(value)) {
		for (const item of value) {
			if (isRaw(item)) {
				const clause = text(item.text ?? item.clause ?? item.ref ?? item.title);
				const page = text(item.page);
				if (clause) {
					result.push({ table: text(item.table, 'pack'), text: page ? localize('codePacks.sourcePage', "{0}, p. {1}", clause, page) : clause });
				}
			} else if (text(item)) {
				result.push({ table: 'pack', text: text(item) });
			}
		}
	} else if (isRaw(value)) {
		for (const [table, refs] of Object.entries(value)) {
			for (const ref of sourcesOf(Array.isArray(refs) ? refs : [refs])) {
				result.push({ table, text: ref.text });
			}
		}
	}
	return result;
}

function tablesOf(value: unknown): { name: string; from: string }[] {
	if (Array.isArray(value)) {
		return value.map(v => isRaw(v) ? { name: text(v.name ?? v.id), from: text(v.from ?? v.pack ?? v.source) } : { name: text(v), from: '' }).filter(t => t.name);
	}
	if (isRaw(value)) {
		return Object.entries(value).map(([name, from]) => ({ name, from: isRaw(from) ? text(from.from ?? from.pack) : text(from) }));
	}
	return [];
}

/**
 * A pack from the backend's answer (`PackInfo`, or `saengine.codes.show`'s pack), read
 * tolerantly: the manifest's fields at the top or under `info`/`manifest`. Undefined without an id.
 */
export function readCodePack(value: unknown): ICodePackInfo | undefined {
	if (!isRaw(value)) {
		return undefined;
	}
	const manifest = isRaw(value.info) ? value.info : isRaw(value.manifest) ? value.manifest : {};
	const field = (key: string) => value[key] ?? manifest[key];
	const id = text(field('id'));
	if (!id) {
		return undefined;
	}
	const name = text(field('name'), id);
	const problems = value.problems ?? value.errors;
	const usable = typeof value.usable === 'boolean' ? value.usable : errorCount(problems) === 0;
	return {
		id,
		name,
		edition: text(field('edition')),
		region: text(field('region') ?? field('country')),
		version: text(field('version')),
		extends: text(field('extends')) || undefined,
		covers: texts(field('covers')),
		scope: scopeOf(value),
		path: text(value.path ?? value.folder ?? value.dir) || undefined,
		problems: texts(problems),
		usable,
		effective: value.effective !== false,
		shadowedBy: value.effective === false ? scopeValue(value.shadowedBy) : undefined,
		trust: trustOf(value, manifest),
		hooksFrom: texts(value.hooksFrom),
		author: text(field('author')),
		licence: text(field('licence') ?? field('license')),
		description: text(field('description')),
		sources: sourcesOf(field('sources') ?? field('clauses')),
		tables: tablesOf(value.tables),
	};
}

/** The packs in the backend's list answer (an array, or `{ packs }`), duplicates dropped. */
export function readCodePacks(value: unknown): ICodePackInfo[] {
	const list = Array.isArray(value) ? value : isRaw(value) && Array.isArray(value.packs) ? value.packs : [];
	const seen = new Set<string>();
	const packs: ICodePackInfo[] = [];
	for (const item of list) {
		const pack = readCodePack(item);
		if (pack && !seen.has(`${pack.scope}/${pack.id}`)) {
			seen.add(`${pack.scope}/${pack.id}`);
			packs.push(pack);
		}
	}
	return packs;
}

/** The problems in `saengine.codes.validate`'s answer (a list, or `{ problems }`). */
export function readProblems(value: unknown): string[] {
	return texts(isRaw(value) && !Array.isArray(value) ? (value.problems ?? value.errors ?? []) : value);
}

/**
 * The built-in BNBC 2020 pack as the app knows it without the backend: what the selector shows
 * until `saengine.codes.list` answers.
 */
export function builtinDefaultPack(): ICodePackInfo {
	return {
		id: DEFAULT_CODE_PACK, name: BNBC.edition, edition: BNBC.edition, region: localize('codePacks.bangladesh', "Bangladesh"), version: '',
		extends: undefined, covers: [], scope: 'builtin', path: undefined, problems: [], usable: true, effective: true, shadowedBy: undefined, trust: 'none', hooksFrom: [],
		author: '', licence: '', description: '', sources: [], tables: [],
	};
}

/** The pack the settings choose (their `codePack`, else the default). */
export function chosenPackId(settings: { readonly [key: string]: unknown } | undefined): string {
	const id = settings?.codePack;
	return typeof id === 'string' && id.trim() ? id.trim() : DEFAULT_CODE_PACK;
}

export function scopeLabel(scope: CodePackScope): string {
	switch (scope) {
		case 'builtin': return localize('codePacks.scopeBuiltin', "built-in");
		case 'user': return localize('codePacks.scopeUser', "your pack");
		case 'project': return localize('codePacks.scopeProject', "this project");
	}
}

/** "BNBC 2020 (built-in)": the pack's name and where it is installed. */
export function packLabel(pack: ICodePackInfo): string {
	return localize('codePacks.label', "{0} ({1})", pack.name, scopeLabel(pack.scope));
}

/** The human name of a coverage area (`windSeismic` → "Wind and seismic"). */
export function coverageLabel(area: string): string {
	switch (area) {
		case 'locations': return localize('codePacks.coverLocations', "Locations");
		case 'loads': case 'areaLoads': return localize('codePacks.coverLoads', "Area loads");
		case 'windSeismic': return localize('codePacks.coverWindSeismic', "Wind and seismic");
		case 'wind': return localize('codePacks.coverWind', "Wind");
		case 'windSpeeds': return localize('codePacks.coverWindSpeeds', "Wind speeds");
		case 'seismic': return localize('codePacks.coverSeismic', "Seismic");
		case 'zoneCoefficients': return localize('codePacks.coverZones', "Zone coefficients");
		case 'combinations': return localize('codePacks.coverCombinations', "Combinations");
		case 'materials': return localize('codePacks.coverMaterials', "Materials");
		case 'factors': return localize('codePacks.coverFactors', "Resistance factors");
		case 'concrete': return localize('codePacks.coverConcrete', "Concrete");
		case 'steel': return localize('codePacks.coverSteel', "Steel");
		case 'detailing': return localize('codePacks.coverDetailing', "Detailing");
		case 'plumbing': return localize('codePacks.coverPlumbing', "Plumbing");
		case 'hvac': return localize('codePacks.coverHvac', "HVAC");
		case 'electrical': return localize('codePacks.coverElectrical', "Electrical");
		case 'fire': return localize('codePacks.coverFire', "Fire protection");
		case 'steelSections': return localize('codePacks.coverSteelSections', "Steel sections");
		case 'hooks': return localize('codePacks.coverHooks', "Design hooks");
		default: return area.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, c => c.toUpperCase());
	}
}

/** "Extends BNBC 2020" for a pack that extends another (named when known), else undefined. */
export function extendsLabel(pack: ICodePackInfo, packs: readonly ICodePackInfo[]): string | undefined {
	if (!pack.extends) {
		return undefined;
	}
	const base = packs.find(p => p.id === pack.extends);
	return localize('codePacks.extends', "Extends {0}", base ? base.name : pack.extends);
}

/** The packs grouped Built-in, Your packs and This project (the last only for a project). */
export function groupPacks(packs: readonly ICodePackInfo[], hasProject: boolean): ICodePackGroup[] {
	const byName = (a: ICodePackInfo, b: ICodePackInfo) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
	const groups: ICodePackGroup[] = [];
	for (const scope of SCOPES) {
		if (scope === 'project' && !hasProject) {
			continue;
		}
		groups.push({
			scope,
			title: scope === 'builtin' ? localize('codePacks.groupBuiltin', "Built-in") : scope === 'user' ? localize('codePacks.groupUser', "Your Packs") : localize('codePacks.groupProject', "This Project"),
			packs: packs.filter(p => p.scope === scope).sort(byName),
			empty: scope === 'builtin'
				? localize('codePacks.emptyBuiltin', "No built-in packs found.")
				: scope === 'user'
					? localize('codePacks.emptyUser', "None yet. New Code Pack makes one that extends a built-in pack; Install Code Pack adds one you were given.")
					: localize('codePacks.emptyProject', "None. A pack kept here travels with the project and its .civil archive."),
		});
	}
	return groups;
}

/** One entry of the "Design code" selector. */
export interface ICodePackOption {
	readonly id: string;
	readonly label: string;
	readonly description: string;
	/** The pack is not installed here (the settings name one this computer does not have). */
	readonly missing: boolean;
	/**
	 * The pack (or one it extends) has errors, so the backend cannot load it: the selector shows
	 * it disabled and the project cannot switch to it (a project already on it keeps showing it).
	 */
	readonly unusable: boolean;
	/** Its problems, for the message that says why it cannot be chosen. */
	readonly problems: readonly string[];
}

/**
 * The selector's entries: every pack in force (a project's own pack overrides a user pack of the
 * same id, which overrides a built-in one; the backend marks the others `effective: false`), and
 * the chosen pack even when it is not installed here.
 */
export function packOptions(packs: readonly ICodePackInfo[], chosen: string): ICodePackOption[] {
	const effective = new Map<string, ICodePackInfo>();
	for (const scope of SCOPES) {
		for (const pack of packs.filter(p => p.scope === scope && p.effective)) {
			effective.set(pack.id, pack);
		}
	}
	if (!effective.has(DEFAULT_CODE_PACK) && !packs.length) {
		effective.set(DEFAULT_CODE_PACK, builtinDefaultPack());
	}
	const options: ICodePackOption[] = [...effective.values()]
		.sort((a, b) => SCOPES.indexOf(a.scope) - SCOPES.indexOf(b.scope) || a.name.localeCompare(b.name))
		.map(pack => ({
			id: pack.id,
			label: pack.usable ? packLabel(pack) : localize('codePacks.unusableLabel', "{0} (has errors)", packLabel(pack)),
			description: pack.usable ? packDescription(pack, packs) : localize('codePacks.unusableDescription', "This pack, or a pack it extends, has errors and cannot be used until they are fixed: {0}", pack.problems.join('; ') || localize('codePacks.unusableSeeDetails', "see Code Packs")),
			missing: false,
			unusable: !pack.usable,
			problems: pack.problems,
		}));
	if (!effective.has(chosen)) {
		options.push({
			id: chosen,
			label: localize('codePacks.missingLabel', "{0} (not installed)", chosen),
			description: localize('codePacks.missingDescription', "The settings choose the code pack {0}, which is not installed on this computer. Install it from Code Packs, or choose another.", chosen),
			missing: true,
			unusable: true,
			problems: [],
		});
	}
	return options;
}

/** Why the project cannot switch to `option`, or undefined when it can. */
export function packOptionBlock(option: ICodePackOption): { readonly message: string; readonly detail: string } | undefined {
	if (option.missing) {
		return {
			message: localize('codePacks.blockMissingMessage', "{0} is not installed on this computer.", option.id),
			detail: localize('codePacks.blockMissingDetail', "Install it from Code Packs (≡ > Code Packs...) first."),
		};
	}
	if (!option.unusable) {
		return undefined;
	}
	return {
		message: localize('codePacks.blockMessage', "{0} cannot be used as the design code yet.", option.label),
		detail: localize('codePacks.blockDetail', "The pack, or a pack it extends, has errors, so analysis, design and reports could not load it. Fix them (Code Packs > Validate lists them) and choose it again. The project keeps its current design code.\n\n{0}", option.problems.join('\n') || localize('codePacks.blockNoList', "Its problems are listed in Code Packs.")),
	};
}

/** A pack in one line: its edition, what it extends and what it provides. */
export function packDescription(pack: ICodePackInfo, packs: readonly ICodePackInfo[]): string {
	const parts: string[] = [];
	if (pack.edition && pack.edition !== pack.name) {
		parts.push(pack.edition);
	}
	if (pack.region) {
		parts.push(pack.region);
	}
	const base = extendsLabel(pack, packs);
	if (base) {
		parts.push(base);
	}
	if (pack.covers.length) {
		parts.push(localize('codePacks.provides', "provides {0}", pack.covers.map(coverageLabel).join(', ')));
	}
	return parts.join(' · ');
}

/** What the confirmation says before the project switches from one pack to another. */
export function changePackWarning(from: string, to: ICodePackOption): { readonly message: string; readonly detail: string } {
	return {
		message: localize('codePacks.changeMessage', "Use {0} as the design code of this project?", to.label),
		detail: localize('codePacks.changeDetail', "The site and hazard values, importance factors, structural system factors, live load minimums and the seismic and wind coefficients come from the chosen pack, so loads and design results will change (the project keeps its own load combinations; resistance factors and detailing limits are still BNBC 2020's in this version). Run the analysis and design again (Run All) before using any result. The project currently uses {0}; Edit > Undo switches back.", from),
	};
}

/** A pack id the backend accepts: lowercase letters, digits, dots, hyphens and underscores. */
export function packIdProblem(id: string, taken: readonly string[]): string | undefined {
	if (!id) {
		return localize('codePacks.idEmpty', "Give the pack an id, such as nbc-nepal-2020.");
	}
	if (!/^[a-z0-9][a-z0-9._-]{1,63}$/.test(id)) {
		return localize('codePacks.idInvalid', "Use 2 to 64 lowercase letters, digits, dots, hyphens or underscores, starting with a letter or digit.");
	}
	if (taken.includes(id)) {
		return localize('codePacks.idTaken', "A pack with the id {0} is already installed.", id);
	}
	return undefined;
}

/** "Not in force: this project's pack of the same id is used instead", for a shadowed pack. */
export function shadowedLabel(pack: ICodePackInfo): string | undefined {
	if (pack.effective) {
		return undefined;
	}
	return pack.shadowedBy
		? localize('codePacks.shadowedBy', "Not in force: the pack with the same id in {0} is used instead", scopeLabel(pack.shadowedBy))
		: localize('codePacks.shadowed', "Not in force: another pack with the same id is used instead");
}

/** What the trust state means, for the details pane. */
export function trustLabel(trust: CodePackTrust): string {
	switch (trust) {
		case 'none': return localize('codePacks.trustNone', "Data only (no hooks)");
		case 'trusted': return localize('codePacks.trustTrusted', "Hooks trusted: they run during design");
		case 'untrusted': return localize('codePacks.trustUntrusted', "Hooks not trusted: the pack's data is used, its hooks do not run");
	}
}
