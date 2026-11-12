/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import assert from 'assert';
import { promises as fs } from 'fs';
import { tmpdir } from 'os';
import { FileAccess } from '../../../../../base/common/network.js';
import { join } from '../../../../../base/common/path.js';
import { generateUuid } from '../../../../../base/common/uuid.js';
import { resolveNLSConfiguration } from '../../../../../base/node/nls.js';
import { ensureNoDisposablesAreLeakedInTestSuite } from '../../../../../base/test/common/utils.js';

interface ITableEntry {
	readonly en: string;
	readonly bn: string;
	readonly status: string;
	readonly note?: string;
}

interface ITable {
	readonly modules: Record<string, { readonly file: string; readonly strings: Record<string, ITableEntry> }>;
}

interface ILocalization {
	readonly languageId: string;
	readonly localizedLanguageName?: string;
	readonly translations: readonly { readonly id: string; readonly path: string }[];
}

const workbenchRoot = join(FileAccess.asFileUri('').fsPath, '..');
const packRoot = join(workbenchRoot, 'extensions', 'saengine-language-pack-bn');
const tablePath = join(workbenchRoot, 'build', 'saengine', 'i18n', 'bn', 'strings.bn.json');

function placeholders(text: string): string {
	return (text.match(/\{\d+\}/g) ?? []).sort().join(' ');
}

async function readJson<T>(path: string): Promise<T> {
	return JSON.parse(await fs.readFile(path, 'utf8'));
}

/** The translations the pack must carry: every entry not marked untranslated. */
function expectedContents(table: ITable, moduleFilter: (moduleId: string) => boolean): Record<string, Record<string, string>> {
	const result: Record<string, Record<string, string>> = {};
	for (const [moduleId, m] of Object.entries(table.modules)) {
		if (!moduleFilter(moduleId)) {
			continue;
		}
		for (const [key, e] of Object.entries(m.strings)) {
			if (e.bn && e.status !== 'untranslated') {
				(result[moduleId] ??= {})[key] = e.bn;
			}
		}
	}
	return result;
}

suite('SAEngine Bangla language pack', () => {
	ensureNoDisposablesAreLeakedInTestSuite();

	test('contributes the bn localization with existing translation files', async () => {
		const manifest = await readJson<{ contributes: { localizations: ILocalization[] } }>(join(packRoot, 'package.json'));
		const [localization] = manifest.contributes.localizations;
		assert.strictEqual(localization.languageId, 'bn');
		assert.strictEqual(localization.localizedLanguageName, 'বাংলা');
		assert.deepStrictEqual(localization.translations.map(t => t.id), ['vscode', 'vscode.theme-saengine']);
		for (const translation of localization.translations) {
			await fs.access(join(packRoot, translation.path));
		}
	});

	test('every string has Bangla text or is listed as untranslated, with the same placeholders', async () => {
		const table = await readJson<ITable>(tablePath);
		const problems: string[] = [];
		let strings = 0;
		for (const [moduleId, m] of Object.entries(table.modules)) {
			for (const [key, e] of Object.entries(m.strings)) {
				strings++;
				const id = `${moduleId}#${key}`;
				if (!['translated', 'review', 'untranslated'].includes(e.status)) {
					problems.push(`${id}: status ${e.status}`);
				} else if (e.status !== 'untranslated' && !e.bn) {
					problems.push(`${id}: no Bangla text`);
				}
				if (e.bn && placeholders(e.bn) !== placeholders(e.en)) {
					problems.push(`${id}: placeholders ${placeholders(e.en)} vs ${placeholders(e.bn)}`);
				}
			}
		}
		assert.ok(strings > 1000, `only ${strings} strings in the table`);
		assert.deepStrictEqual(problems, []);
	});

	test('the generated pack matches the translation table', async () => {
		const table = await readJson<ITable>(tablePath);
		const main = await readJson<{ contents: Record<string, Record<string, string>> }>(join(packRoot, 'translations', 'main.i18n.json'));
		assert.deepStrictEqual(main.contents, expectedContents(table, id => !id.startsWith('extension:')), 'run node build/saengine/i18n/extract-strings.ts');
		const theme = await readJson<{ contents: Record<string, Record<string, string>> }>(join(packRoot, 'translations', 'extensions', 'vscode.theme-saengine.i18n.json'));
		assert.deepStrictEqual(theme.contents, { package: expectedContents(table, id => id === 'extension:vscode.theme-saengine')['extension:vscode.theme-saengine'] });
	});

	test('loads through the NLS resolver of a built product', async () => {
		const table = await readJson<ITable>(tablePath);
		const root = join(tmpdir(), `saengine-bn-pack-${generateUuid()}`);
		const nlsMetadataPath = join(root, 'out');
		const userDataPath = join(root, 'user-data');
		await fs.mkdir(nlsMetadataPath, { recursive: true });
		await fs.mkdir(userDataPath, { recursive: true });

		// nls.keys.json / nls.messages.json as the build writes them for these modules.
		const keys: [string, string[]][] = [];
		const messages: string[] = [];
		const expected: string[] = [];
		for (const [moduleId, m] of Object.entries(table.modules)) {
			if (moduleId.startsWith('extension:')) {
				continue;
			}
			keys.push([moduleId, Object.keys(m.strings)]);
			for (const e of Object.values(m.strings)) {
				messages.push(e.en);
				expected.push(e.bn && e.status !== 'untranslated' ? e.bn : e.en);
			}
		}
		await fs.writeFile(join(nlsMetadataPath, 'nls.keys.json'), JSON.stringify(keys));
		await fs.writeFile(join(nlsMetadataPath, 'nls.messages.json'), JSON.stringify(messages));

		// languagepacks.json as LanguagePacksCache writes it for a built-in extension.
		const manifest = await readJson<{ version: string; contributes: { localizations: ILocalization[] } }>(join(packRoot, 'package.json'));
		const [localization] = manifest.contributes.localizations;
		const translations: Record<string, string> = {};
		for (const t of localization.translations) {
			translations[t.id] = join(packRoot, t.path);
		}
		await fs.writeFile(join(userDataPath, 'languagepacks.json'), JSON.stringify({
			bn: { hash: 'test', label: localization.localizedLanguageName, extensions: [{ extensionIdentifier: { id: 'vscode.saengine-language-pack-bn' }, version: manifest.version }], translations }
		}));

		const dev = process.env['VSCODE_DEV'];
		delete process.env['VSCODE_DEV']; // the resolver ignores language packs in dev builds
		try {
			const config = await resolveNLSConfiguration({ userLocale: 'bn', osLocale: 'en', userDataPath, commit: 'test-commit', nlsMetadataPath });
			assert.strictEqual(config.resolvedLanguage, 'bn');
			assert.ok(config.languagePack);
			const resolved: string[] = await readJson(config.languagePack.messagesFile);
			assert.deepStrictEqual(resolved, expected);
			assert.ok(resolved.some((message, i) => message !== messages[i]), 'no message was translated');
		} finally {
			if (dev !== undefined) {
				process.env['VSCODE_DEV'] = dev;
			}
			await fs.rm(root, { recursive: true, force: true });
		}
	});
});
