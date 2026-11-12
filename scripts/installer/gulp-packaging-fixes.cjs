/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/
// @ts-check

/**
 * Preloaded (NODE_OPTIONS=--require) into the Code - OSS gulp packaging run by
 * scripts/build-installer.ps1. It fixes three problems of a local (non-CI) Windows packaging run
 * of this checkout without changing the shared build scripts. The fixes only rewrite data the
 * build reads (command output, a rules file, an environment variable); nothing else is patched.
 *
 * 1. The SAEngine viewer bundles. The workbench depends on the local packages
 *    `@saengine/fem-viewer` and `@saengine/cad-editor` (`file:../packages/...`, installed as
 *    symlinks). Their dist/ folders are self-contained ESM bundles loaded by URL from
 *    node_modules.asar. `build/lib/dependencies.ts` collects production dependencies with
 *    `npm ls --all --omit=dev --parseable`, which also lists every package inside
 *    packages/<name>/node_modules (dev dependencies included) as paths outside the workbench
 *    folder; the asar step cannot place those (`../packages/...`) and the build fails with
 *    "Cannot read properties of undefined (reading 'files')". The `npm ls` output is rewritten:
 *    - paths outside the folder npm ran in are dropped (the bundles already contain that code);
 *    - `node_modules/@saengine/<name>` becomes `node_modules/@saengine/<name>/dist`, so only the
 *      built bundle, its workers and assets are packaged, not the package's own node_modules.
 *
 * 2. The built-in Copilot extension. `build/.moduleignore` strips `@github/copilot/**` from every
 *    node_modules folder, which also empties `extensions/copilot/node_modules/@github/copilot`
 *    of a locally compiled Copilot extension (CI downloads it as a VSIX instead). The later
 *    packaging step `prepareBuiltInCopilotRipgrepShim` requires its `sdk` folder and fails with
 *    "Copilot SDK directory not found". The rule is replaced, in what the build reads, by rules
 *    for the other-platform natives the shim does not prune itself (see `copilotRules`). The
 *    nested `@github/copilot-sdk/node_modules/@github/copilot/**` rule stays.
 */

const childProcess = require('child_process');
const fs = require('fs');
const path = require('path');
const { syncBuiltinESMExports } = require('module');

// --- 1. npm ls ---------------------------------------------------------------------------------

const originalExecSync = childProcess.execSync;

/**
 * @param {string} output
 * @param {string} cwd
 */
function filterNpmLs(output, cwd) {
	const root = path.resolve(cwd);
	return output.split(/\r?\n/).flatMap(line => {
		if (!line.trim()) {
			return [line];
		}
		const relative = path.relative(root, line);
		if (relative.startsWith('..') || path.isAbsolute(relative)) {
			return [];
		}
		if (/^node_modules[\\/]@saengine[\\/][^\\/]+$/.test(relative)) {
			return [path.join(line, 'dist')];
		}
		return [line];
	}).join('\n');
}

/**
 * @param {string} command
 * @param {import('child_process').ExecSyncOptions} [options]
 */
function execSync(command, options) {
	const isNpmLs = typeof command === 'string' && /^npm ls .*--parseable/.test(command);
	if (!isNpmLs) {
		return originalExecSync.apply(childProcess, /** @type {any} */ (arguments));
	}
	const cwd = options?.cwd ? String(options.cwd) : process.cwd();
	try {
		const output = originalExecSync(command, options);
		return typeof output === 'string' ? filterNpmLs(output, cwd) : Buffer.from(filterNpmLs(output.toString('utf8'), cwd));
	} catch (err) {
		if (err && typeof err.stdout === 'string') {
			err.stdout = filterNpmLs(err.stdout, cwd);
		}
		throw err;
	}
}

childProcess.execSync = /** @type {typeof childProcess.execSync} */ (execSync);

// --- 2. .moduleignore --------------------------------------------------------------------------

const originalReadFileSync = fs.readFileSync;
const moduleIgnore = path.join('build', '.moduleignore');
/**
 * What replaces `@github/copilot/**`: the other-platform builds of its clipboard addon, the only
 * other-platform natives the shim does not prune. They must go, because the win32 packaging step
 * stamps version resources into every `*.node` with rcedit, which cannot load ELF or Mach-O
 * files ("Unable to load file ... clipboard.linux-x64-gnu.node"). Only win32-x64 is built here.
 */
const copilotRules = [
	'@teddyzhu/clipboard/clipboard.{darwin,linux,freebsd,android}*.node',
	'@teddyzhu/clipboard/clipboard.win32-{arm64,ia32}*.node',
];

/**
 * @param {fs.PathOrFileDescriptor} file
 */
function readFileSync(file) {
	const result = originalReadFileSync.apply(fs, /** @type {any} */ (arguments));
	if (typeof file === 'string' && path.normalize(file).endsWith(moduleIgnore) && typeof result === 'string') {
		return result.split(/\r?\n/).flatMap(line => line.trim() === '@github/copilot/**' ? copilotRules : [line]).join('\n');
	}
	return result;
}

fs.readFileSync = /** @type {typeof fs.readFileSync} */ (readFileSync);

// `import * as fs from 'fs'` in the ESM build scripts sees the patched functions only after this.
syncBuiltinESMExports();

// --- 3. The commit --------------------------------------------------------------------------
// The build reads the commit from workbench/.git, which does not exist (the repository is the
// parent folder), so product.json would get none and the packaged app would behave as if run
// from sources. CI passes it in BUILD_SOURCEVERSION; build-installer.ps1 passes it in
// SAENGINE_BUILD_COMMIT and it becomes BUILD_SOURCEVERSION in the gulp process only. Child
// processes must not see it: the Copilot extension's own build (extensions/copilot/.esbuild.mts)
// takes it as "running in CI" and then rewrites extensions/copilot/package.json in the source tree.
const buildCommit = process.env['SAENGINE_BUILD_COMMIT'];
if (buildCommit && /^[0-9a-f]{40}$/i.test(buildCommit)) {
	const isGulp = process.argv.some(arg => /[\\/]gulp[\\/]bin[\\/]gulp\.js$/.test(arg));
	if (isGulp) {
		process.env['BUILD_SOURCEVERSION'] = buildCommit;
	} else if (process.env['BUILD_SOURCEVERSION'] === buildCommit) {
		delete process.env['BUILD_SOURCEVERSION'];
	}
}
