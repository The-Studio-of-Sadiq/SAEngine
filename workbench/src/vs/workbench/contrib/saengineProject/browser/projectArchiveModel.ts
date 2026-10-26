/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { basename, dirname, extUriBiasedIgnorePathCase } from '../../../../base/common/resources.js';
import { URI } from '../../../../base/common/uri.js';
import { language } from '../../../../base/common/platform.js';
import { localize } from '../../../../nls.js';
import { readPart, partLabel } from './versionsModel.js';

/*
 * The project archive (`.civil`): one file holding a whole project, to send or keep. The backend
 * writes and reads it; this file holds the command ids, their arguments and what the UI makes of
 * the answers (free of DOM and services, so that it can be tested on its own).
 */

/** The archive's file extension, without the dot. */
export const ARCHIVE_EXTENSION = 'civil';

/** `{projectRoot, outPath, includeResults, includeVersions}` -> `{path, size, problems}`. */
export const ARCHIVE_EXPORT_COMMAND = 'saengine.project.export';
/** `{path}` -> the archive's manifest and `problems` (read with {@link readArchiveManifest}). */
export const ARCHIVE_INSPECT_COMMAND = 'saengine.project.inspectArchive';
/** `{path, destParent, name}` -> `{root, problems}`: the project unpacked into `<destParent>/<name>`. */
export const ARCHIVE_IMPORT_COMMAND = 'saengine.project.import';
/** `{path}` -> `{program, ok}`: opens a DXF in the bundled LibreCAD, else the system's DXF program. */
export const CAD_OPEN_COMMAND = 'saengine.cad.open';
/**
 * `{path}` -> `{ok, dxf, warnings}` or `{ok: false, code, message}`: a DWG drawing converted to
 * DXF (cached in a `.dwg-cache` folder beside it) by the bundled GNU LibreDWG.
 */
export const DWG_TO_DXF_COMMAND = 'saengine.cad.dwgToDxf';

/** The UI commands (≡ File menu, the Exports page). Each takes its paths as arguments, for tests. */
export const EXPORT_ARCHIVE_UI_COMMAND = 'saengine.project.exportArchive';
export const OPEN_ARCHIVE_UI_COMMAND = 'saengine.project.openArchive';
export const OPEN_DXF_IN_CAD_UI_COMMAND = 'saengine.cad.openDxf';

export interface IArchiveExportOptions {
	/** The computed results (FEM, MEP, substructure): larger, but opens without running again. */
	readonly includeResults: boolean;
	/** The version history: the receiver can see and restore earlier versions. */
	readonly includeVersions: boolean;
}

export interface IArchiveExportArgs extends IArchiveExportOptions {
	readonly projectRoot: string;
	readonly outPath: string;
}

export interface IArchiveImportArgs {
	readonly path: string;
	readonly destParent: string;
	readonly name: string;
}

/** The arguments of {@link EXPORT_ARCHIVE_UI_COMMAND}: any left out is asked. */
export interface IExportArchiveCommandArgs {
	readonly outPath?: string;
	readonly includeResults?: boolean;
	readonly includeVersions?: boolean;
}

/** The arguments of {@link OPEN_ARCHIVE_UI_COMMAND}: any left out is asked; `open: false` imports without opening. */
export interface IOpenArchiveCommandArgs {
	readonly path?: string;
	readonly destParent?: string;
	readonly name?: string;
	readonly open?: boolean;
}

export const DEFAULT_EXPORT_OPTIONS: IArchiveExportOptions = { includeResults: false, includeVersions: true };

export function exportArgs(projectRoot: string, outPath: string, options: Partial<IArchiveExportOptions> = {}): IArchiveExportArgs {
	return {
		projectRoot,
		outPath: withArchiveExtension(outPath),
		includeResults: options.includeResults ?? DEFAULT_EXPORT_OPTIONS.includeResults,
		includeVersions: options.includeVersions ?? DEFAULT_EXPORT_OPTIONS.includeVersions,
	};
}

export function importArgs(path: string, destParent: string, name: string): IArchiveImportArgs {
	return { path, destParent, name: name.trim() };
}

/** `path` ending in `.civil` (added when the save dialog left it out). */
/** The DXF a command was given: a file URI, a path, or `{path}` / `{resource}`; undefined asks. */
export function dxfCommandTarget(target: unknown): URI | undefined {
	if (URI.isUri(target)) {
		return target;
	}
	if (typeof target === 'string' && target.trim()) {
		return /^[a-z][a-z0-9+.-]+:\/\//i.test(target) ? URI.parse(target) : URI.file(target);
	}
	if (isBag(target)) {
		if (URI.isUri(target.resource)) {
			return target.resource;
		}
		return dxfCommandTarget(target.path ?? target.resource);
	}
	return undefined;
}

export function withArchiveExtension(path: string): string {
	return path.toLowerCase().endsWith(`.${ARCHIVE_EXTENSION}`) ? path : `${path}.${ARCHIVE_EXTENSION}`;
}

function pad(value: number): string {
	return String(value).padStart(2, '0');
}

/** "Sample Frame 2026-10-19.civil": the project's name and the day, for the save dialog. */
export function defaultArchiveName(projectName: string, date: Date): string {
	const day = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
	return `${projectName.trim() || 'Project'} ${day}.${ARCHIVE_EXTENSION}`;
}

/** The project name to unpack an archive as: its manifest's name, else the file name without the extension and date. */
export function projectNameForArchive(fileName: string, manifestName?: string): string {
	if (manifestName?.trim()) {
		return manifestName.trim();
	}
	const stem = fileName.replace(new RegExp(`\\.${ARCHIVE_EXTENSION}$`, 'i'), '');
	return stem.replace(/\s+\d{4}-\d{2}-\d{2}$/, '').trim() || stem;
}

const FORBIDDEN_IN_FOLDER_NAMES = /[<>:"|?*\\\x00-\x1f]/g;
const RESERVED_FOLDER_NAMES = /^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³])(\..*)?$/i;

/**
 * `name` as a Windows folder name, cleaned exactly as the backend's `archive.safe_name()` does
 * (forbidden characters to "-", no trailing dots or spaces, reserved device names avoided), so
 * the UI's "(2)" check sees the folder an earlier import made.
 */
export function safeFolderName(name: string): string {
	let cleaned = name.replace(/\//g, '-').replace(FORBIDDEN_IN_FOLDER_NAMES, '-').trim().replace(/[. ]+$/, '');
	if (RESERVED_FOLDER_NAMES.test(cleaned)) {
		cleaned += '_';
	}
	return cleaned || 'Project';
}

/** "Sample Frame", "Sample Frame (2)", ... : the first name not in `taken` (`name` cleaned with {@link safeFolderName}). */
export function uniqueFolderName(wanted: string, taken: (candidate: string) => boolean): string {
	const name = safeFolderName(wanted);
	if (!taken(name)) {
		return name;
	}
	for (let i = 2; i < 1000; i++) {
		const candidate = `${name} (${i})`;
		if (!taken(candidate)) {
			return candidate;
		}
	}
	return `${name} (${Date.now()})`;
}

/** "740 KB", "12.4 MB". */
export function formatSize(bytes: number | undefined): string {
	if (bytes === undefined || !Number.isFinite(bytes)) {
		return '';
	}
	if (bytes < 1024) {
		return localize('archive.bytes', "{0} B", bytes);
	}
	if (bytes < 1024 * 1024) {
		return localize('archive.kilobytes', "{0} KB", Math.round(bytes / 1024));
	}
	const mb = bytes / (1024 * 1024);
	return localize('archive.megabytes', "{0} MB", mb < 100 ? mb.toFixed(1) : Math.round(mb));
}

export interface IArchiveManifest {
	readonly name?: string;
	readonly type?: string;
	/** The SAEngine version that wrote it. */
	readonly appVersion?: string;
	/** When it was written [ms since the epoch]. */
	readonly created?: number;
	/** The parts in it (part ids). */
	readonly parts: readonly string[];
	readonly size?: number;
	readonly files?: number;
	readonly includesResults?: boolean;
	readonly includesVersions?: boolean;
	/** The number of versions in it. */
	readonly versions?: number;
	/** False when the backend refuses the archive (an error among the problems). */
	readonly ok?: boolean;
	/** The errors (problems without a severity count as errors). */
	readonly problems: readonly string[];
	/** The backend's warnings and notes: the archive still opens. */
	readonly notes: readonly string[];
}

type Bag = { readonly [key: string]: unknown };

function isBag(value: unknown): value is Bag {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(...values: unknown[]): string | undefined {
	for (const value of values) {
		if (typeof value === 'string' && value.trim()) {
			return value.trim();
		}
		if (typeof value === 'number' && Number.isFinite(value)) {
			return String(value);
		}
	}
	return undefined;
}

function num(...values: unknown[]): number | undefined {
	return values.find((v): v is number => typeof v === 'number' && Number.isFinite(v));
}

function bool(...values: unknown[]): boolean | undefined {
	return values.find((v): v is boolean => typeof v === 'boolean');
}

/** The messages of an answer's `problems` (strings or `{message, severity}`), all severities. */
export function readProblems(value: unknown): string[] {
	const { errors, notes } = readProblemsBySeverity(value);
	return [...errors, ...notes];
}

/** An answer's `problems` split into errors and the rest (`severity` 'warning' / 'info'); a plain string is an error. */
export function readProblemsBySeverity(value: unknown): { readonly errors: string[]; readonly notes: string[] } {
	const problems = isBag(value) ? value.problems : undefined;
	const errors: string[] = [];
	const notes: string[] = [];
	for (const p of Array.isArray(problems) ? problems : []) {
		const message = isBag(p) ? text(p.message, p.text) ?? JSON.stringify(p) : String(p);
		const severity = isBag(p) ? text(p.severity, p.level)?.toLowerCase() : undefined;
		(severity === 'warning' || severity === 'warn' || severity === 'info' || severity === 'note' ? notes : errors).push(message);
	}
	return { errors, notes };
}

/** The manifest in an answer of `saengine.project.inspectArchive` (flat, or under `manifest`). */
export function readArchiveManifest(value: unknown): IArchiveManifest {
	const outer = isBag(value) ? value : {};
	const m = isBag(outer.manifest) ? outer.manifest : outer;
	const project = isBag(m.project) ? m.project : {};
	const rawParts = Array.isArray(m.parts) ? m.parts : isBag(m.parts) ? Object.keys(m.parts) : [];
	const parts: string[] = [];
	for (const item of rawParts) {
		if (isBag(item) && item.missing === true) {
			continue; // listed by the backend, but not in the archive
		}
		const part = readPart(isBag(item) ? item.id ?? item.part ?? item.folder : item);
		if (part && !parts.includes(part)) {
			parts.push(part);
		}
	}
	const created = m.created ?? m.createdAt ?? m.created_at ?? m.exported ?? m.exportedAt ?? m.exported_at;
	const createdTime = typeof created === 'number' ? (created < 1e11 ? created * 1000 : created) : typeof created === 'string' ? Date.parse(created) : NaN;
	const versions = m.versions;
	const includes = isBag(m.includes) ? m.includes : {};
	const outerProblems = readProblemsBySeverity(outer);
	const innerProblems = m !== outer ? readProblemsBySeverity(m) : { errors: [], notes: [] };
	return {
		name: text(m.name, project.name, m.projectName, m.project_name),
		type: text(m.type, project.type),
		appVersion: text(m.appVersion, m.app_version, m.saengineVersion, m.saengine_version, m.version),
		created: Number.isNaN(createdTime) ? undefined : createdTime,
		parts,
		size: num(outer.size, m.size, m.bytes),
		files: num(outer.files, m.fileCount, m.file_count, m.files),
		includesResults: bool(includes.results, m.includesResults, m.includes_results, m.includeResults, m.include_results),
		includesVersions: bool(includes.versions, m.includesVersions, m.includes_versions, m.includeVersions, m.include_versions) ?? (typeof versions === 'number' ? versions > 0 : undefined),
		versions: typeof versions === 'number' ? versions : Array.isArray(versions) ? versions.length : undefined,
		ok: bool(outer.ok),
		problems: [...outerProblems.errors, ...innerProblems.errors],
		notes: [...outerProblems.notes, ...innerProblems.notes],
	};
}

/** "includes a version history" -> "Includes a version history." */
function sentence(message: string): string {
	const trimmed = message.trim();
	return trimmed.charAt(0).toUpperCase() + trimmed.slice(1) + (/[.!?]$/.test(trimmed) ? '' : '.');
}

/** The lines of the "open archive" dialog: what the archive holds. */
export function archiveSummaryLines(manifest: IArchiveManifest, fileName: string): string[] {
	const lines: string[] = [];
	lines.push(localize('archive.summaryProject', "Project: {0}", manifest.name ?? fileName));
	if (manifest.appVersion) {
		lines.push(localize('archive.summaryVersion', "Written by SAEngine {0}", manifest.appVersion));
	}
	if (manifest.created !== undefined) {
		lines.push(localize('archive.summaryCreated', "Exported: {0}", new Date(manifest.created).toLocaleString(language, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })));
	}
	if (manifest.parts.length) {
		lines.push(localize('archive.summaryParts', "Parts ({0}): {1}", manifest.parts.length, manifest.parts.map(p => partLabel(p)).join(', ')));
	}
	const size = formatSize(manifest.size);
	const contents = [
		size,
		manifest.includesResults === true ? localize('archive.withResults', "with results") : manifest.includesResults === false ? localize('archive.withoutResults', "without results") : undefined,
		manifest.versions ? localize('archive.withVersions', "{0} versions", manifest.versions) : manifest.includesVersions === true ? localize('archive.withHistory', "with versions") : undefined,
	].filter(Boolean);
	if (contents.length) {
		lines.push(contents.join(' · '));
	}
	if (manifest.problems.length) {
		lines.push(localize('archive.summaryProblems', "Problems: {0}", manifest.problems.join(' ')));
	}
	if (manifest.notes.length) {
		lines.push(localize('archive.summaryNotes', "Note: {0}", manifest.notes.map(sentence).join(' ')));
	}
	return lines;
}

/**
 * The Exports page's line for the last archive written: "<file> (<size>), next to the project
 * folder" when it is there (the save dialog's default), else "<file> (<size>) in <folder>".
 */
export function lastArchiveDescription(archive: URI, size: number | undefined, projectRoot: URI): string {
	const folder = dirname(archive);
	return extUriBiasedIgnorePathCase.isEqual(folder, dirname(projectRoot))
		? localize('archive.lastBeside', "{0} ({1}), next to the project folder", basename(archive), formatSize(size))
		: localize('archive.lastIn', "{0} ({1}) in {2}", basename(archive), formatSize(size), folder.fsPath);
}
