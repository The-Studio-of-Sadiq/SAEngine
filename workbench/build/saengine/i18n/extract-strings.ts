/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

// Extracts every SAEngine UI string (localize()/localize2() calls) into the translation
// table that translators edit, and regenerates the built-in language pack from it.
//
//   node build/saengine/i18n/extract-strings.ts            update the table + the pack
//   node build/saengine/i18n/extract-strings.ts --check    fail if the table or pack is out of date
//   node build/saengine/i18n/extract-strings.ts --stats    print counts only
//
// The table keeps translations across runs. A string whose English source changed keeps its
// old Bangla text but drops back to status "review", so a translator looks at it again.
// See README.md next to this file.

import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
// The same analyser the build uses for nls.keys.json, so module ids and keys match exactly.
import { analyzeLocalizeCalls, parseLocalizeKeyOrValue } from '../../lib/nls-analysis.ts';

const here = dirname(fileURLToPath(import.meta.url));
const workbenchRoot = join(here, '..', '..', '..');
const srcRoot = join(workbenchRoot, 'src');
const language = 'bn';
const tablePath = join(here, language, `strings.${language}.json`);
const packRoot = join(workbenchRoot, 'extensions', `saengine-language-pack-${language}`);
const packMainPath = join(packRoot, 'translations', 'main.i18n.json');

// The commit that imported upstream Code-OSS. Strings in non-SAEngine files that are new or
// changed since then are SAEngine's own (rebranded Explorer, title bar, ...).
const upstreamImportCommit = '36180362';

// Built-in extensions owned by SAEngine whose package.nls.json is translated too.
const saengineExtensions = ['theme-saengine'];

const statuses = new Set(['translated', 'review', 'untranslated']);

interface ISourceString {
	readonly key: string;
	readonly en: string;
	readonly comment?: string;
}

interface ISourceModule {
	readonly file: string;
	readonly strings: Map<string, ISourceString>;
}

interface IEntry {
	en: string;
	comment?: string;
	bn: string;
	status: string;
	note?: string;
}

interface ITable {
	$comment?: string;
	language?: string;
	modules: Record<string, { file: string; strings: Record<string, IEntry> }>;
}

function walk(dir: string, out: string[] = []): string[] {
	for (const name of readdirSync(dir)) {
		const full = join(dir, name);
		if (statSync(full).isDirectory()) {
			if (name !== 'test') {
				walk(full, out);
			}
		} else if (name.endsWith('.ts') && !name.endsWith('.d.ts') && !name.endsWith('.test.ts')) {
			out.push(full);
		}
	}
	return out;
}

function saengineSourceFiles(): string[] {
	const files: string[] = [];
	const roots: string[] = [];
	for (const layer of ['platform', 'workbench/contrib', 'workbench/services']) {
		const layerDir = join(srcRoot, 'vs', ...layer.split('/'));
		for (const name of readdirSync(layerDir)) {
			if (/^saengine/i.test(name)) {
				roots.push(join(layerDir, name));
			}
		}
	}
	for (const root of roots) {
		walk(root, files);
	}
	return files;
}

function toPosix(p: string): string {
	return p.split(sep).join('/');
}

function moduleIdOf(file: string): string {
	return toPosix(relative(srcRoot, file)).replace(/\.ts$/, '');
}

/** Returns [{ key, en, comment }] in source order, like the build. */
function analyze(contents: string): ISourceString[] {
	const result: ISourceString[] = [];
	for (const fn of ['localize', 'localize2'] as const) {
		for (const call of analyzeLocalizeCalls(contents, fn)) {
			const key = parseLocalizeKeyOrValue(call.key);
			const en = parseLocalizeKeyOrValue(call.value) as string;
			result.push({
				key: typeof key === 'string' ? key : key.key,
				en,
				comment: typeof key === 'string' ? undefined : key.comment?.join(' ')
			});
		}
	}
	return result;
}

function git(args: string[]): string {
	return execFileSync('git', args, { cwd: workbenchRoot, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

function changedUpstreamFiles(): string[] {
	try {
		const names = git(['diff', '--name-only', upstreamImportCommit, 'HEAD', '--', 'src/vs']).split('\n');
		const prefix = toPosix(relative(git(['rev-parse', '--show-toplevel']).trim(), workbenchRoot));
		return names
			.filter(n => n.endsWith('.ts') && !n.includes('/test/') && !/\/saengine/i.test(n))
			.map(n => join(workbenchRoot, prefix ? n.slice(prefix.length + 1) : n))
			.filter(f => existsSync(f));
	} catch (e) {
		console.warn(`warning: cannot diff against the upstream import ${upstreamImportCommit}; non-SAEngine files skipped (${e.message.split('\n')[0]})`);
		return [];
	}
}

function upstreamVersion(file: string): string {
	const rel = toPosix(relative(git(['rev-parse', '--show-toplevel']).trim(), file));
	try {
		return git(['show', `${upstreamImportCommit}:${rel}`]);
	} catch {
		return '';
	}
}

/** module id -> { file, strings: key -> { en, comment } } */
function collectSource(): Map<string, ISourceModule> {
	const modules = new Map<string, ISourceModule>();
	const add = (file: string, entries: ISourceString[]) => {
		if (!entries.length) {
			return;
		}
		const strings = new Map<string, ISourceString>();
		for (const e of entries) {
			strings.set(e.key, e);
		}
		modules.set(moduleIdOf(file), { file: toPosix(relative(workbenchRoot, file)), strings });
	};
	for (const file of saengineSourceFiles()) {
		add(file, analyze(readFileSync(file, 'utf8')));
	}
	for (const file of changedUpstreamFiles()) {
		const before = new Map(analyze(upstreamVersion(file)).map(e => [e.key, e.en]));
		add(file, analyze(readFileSync(file, 'utf8')).filter(e => before.get(e.key) !== e.en));
	}
	for (const ext of saengineExtensions) {
		const nlsPath = join(workbenchRoot, 'extensions', ext, 'package.nls.json');
		if (existsSync(nlsPath)) {
			const nls = JSON.parse(readFileSync(nlsPath, 'utf8'));
			const strings = new Map<string, ISourceString>();
			for (const [key, value] of Object.entries<string | { message: string; comment?: string[] }>(nls)) {
				strings.set(key, typeof value === 'string' ? { key, en: value } : { key, en: value.message, comment: value.comment?.join(' ') });
			}
			modules.set(`extension:vscode.${ext}`, { file: toPosix(relative(workbenchRoot, nlsPath)), strings });
		}
	}
	return new Map([...modules.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0));
}

export function placeholders(text: string): string {
	return (text.match(/\{\d+\}/g) ?? []).sort().join(' ');
}

function readTable(): ITable {
	if (!existsSync(tablePath)) {
		return { modules: {} };
	}
	return JSON.parse(readFileSync(tablePath, 'utf8'));
}

function mergeTable(source: Map<string, ISourceModule>, old: ITable): { table: ITable; counts: Record<string, number> } {
	const modules: ITable['modules'] = {};
	const counts: Record<string, number> = { translated: 0, review: 0, untranslated: 0, changedSource: 0, removed: 0 };
	for (const [moduleId, { file, strings }] of source) {
		const oldModule = old.modules?.[moduleId]?.strings ?? {};
		const out: Record<string, IEntry> = {};
		for (const [key, { en, comment }] of strings) {
			const prev: IEntry | undefined = oldModule[key];
			const entry: IEntry = { en, ...(comment ? { comment } : {}), bn: prev?.bn ?? '', status: prev?.status ?? 'untranslated' };
			if (prev?.note) {
				entry.note = prev.note;
			}
			if (prev && prev.en !== en && entry.bn) {
				entry.status = 'review';
				entry.note = `English source changed (was: ${JSON.stringify(prev.en)})`;
				counts.changedSource++;
			}
			if (!entry.bn) {
				entry.status = 'untranslated';
			}
			counts[entry.status]++;
			out[key] = entry;
		}
		modules[moduleId] = { file, strings: out };
	}
	for (const [moduleId, m] of Object.entries(old.modules ?? {})) {
		for (const key of Object.keys(m.strings ?? {})) {
			if (!modules[moduleId]?.strings[key]) {
				counts.removed++;
			}
		}
	}
	return {
		table: {
			$comment: 'SAEngine UI strings in Bangla. Edit "bn" and "status" (translated | review | untranslated) only; run build/saengine/i18n/extract-strings.ts to refresh "en" and regenerate the language pack. Keep {0} placeholders, units and shortcuts as they are. Glossary: glossary.bn.md.',
			language,
			modules
		},
		counts
	};
}

/** Problems a translator must fix: wrong status values and placeholder mismatches. */
export function validate(table: ITable): string[] {
	const problems: string[] = [];
	for (const [moduleId, m] of Object.entries(table.modules)) {
		for (const [key, e] of Object.entries(m.strings)) {
			const id = `${moduleId}#${key}`;
			if (!statuses.has(e.status)) {
				problems.push(`${id}: unknown status ${JSON.stringify(e.status)}`);
			}
			if (e.status !== 'untranslated' && !e.bn) {
				problems.push(`${id}: status ${e.status} but no Bangla text`);
			}
			if (e.bn && placeholders(e.bn) !== placeholders(e.en)) {
				problems.push(`${id}: placeholders differ (en: ${placeholders(e.en) || '-'}, bn: ${placeholders(e.bn) || '-'})`);
			}
		}
	}
	return problems;
}

/** Language pack files from the table: path -> JSON text. Untranslated strings stay English (omitted). */
export function packFiles(table: ITable): Map<string, string> {
	const main: Record<string, Record<string, string>> = {};
	const extensions: Record<string, { package: Record<string, string> }> = {};
	for (const [moduleId, m] of Object.entries(table.modules)) {
		const contents: Record<string, string> = {};
		for (const [key, e] of Object.entries(m.strings)) {
			if (e.bn && e.status !== 'untranslated') {
				contents[key] = e.bn;
			}
		}
		if (!Object.keys(contents).length) {
			continue;
		}
		if (moduleId.startsWith('extension:')) {
			extensions[moduleId.slice('extension:'.length)] = { package: contents };
		} else {
			main[moduleId] = contents;
		}
	}
	const header = { '': ['Generated by build/saengine/i18n/extract-strings.ts from build/saengine/i18n/bn/strings.bn.json. Do not edit.'], version: '1.0.0' };
	const files = new Map<string, string>();
	files.set(packMainPath, JSON.stringify({ ...header, contents: main }, null, '\t') + '\n');
	for (const [id, contents] of Object.entries(extensions)) {
		files.set(join(packRoot, 'translations', 'extensions', `${id}.i18n.json`), JSON.stringify({ ...header, contents }, null, '\t') + '\n');
	}
	return files;
}

function main(): void {
	const args = new Set(process.argv.slice(2));
	const old = readTable();
	const { table, counts } = mergeTable(collectSource(), old);
	const tableText = JSON.stringify(table, null, '\t') + '\n';
	const files = new Map<string, string>([[tablePath, tableText], ...packFiles(table)]);
	const total = counts.translated + counts.review + counts.untranslated;
	console.log(`${total} SAEngine strings in ${Object.keys(table.modules).length} modules: ${counts.translated} translated, ${counts.review} for review, ${counts.untranslated} untranslated` +
		(counts.changedSource ? `, ${counts.changedSource} with changed English source` : '') +
		(counts.removed ? `, ${counts.removed} removed from source` : ''));

	const problems = validate(table);
	for (const p of problems) {
		console.error(`error: ${p}`);
	}

	if (args.has('--stats')) {
		return;
	}
	if (args.has('--check')) {
		const stale = [...files].filter(([path, text]) => !existsSync(path) || readFileSync(path, 'utf8').replace(/\r\n/g, '\n') !== text).map(([path]) => toPosix(relative(workbenchRoot, path)));
		for (const path of stale) {
			console.error(`error: ${path} is out of date; run node build/saengine/i18n/extract-strings.ts`);
		}
		if (stale.length || problems.length) {
			process.exitCode = 1;
		}
		return;
	}
	for (const [path, text] of files) {
		mkdirSync(dirname(path), { recursive: true });
		writeFileSync(path, text);
	}
	if (problems.length) {
		process.exitCode = 1;
	}
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
	main();
}
