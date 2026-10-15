// Bundles the viewers and their dependencies (three, That Open, camera-controls) into one ESM file.
// The workbench renderer cannot resolve bare module specifiers, so it loads this single file by URL.
import * as esbuild from 'esbuild';
import { copyFile, mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const TRUSTED_TYPES_MODULE = fileURLToPath(new URL('./src/trustedTypes.ts', import.meta.url));

// The workbench enforces Trusted Types, so any `innerHTML` assignment throws, and workers may only be
// started from a TrustedScriptURL. Each patch must match exactly, so an upgrade that changes the
// patched code fails the build instead of shipping a viewer that breaks at runtime.
const PATCHES = [
	{
		// That Open's renderer builds its (hidden by us) branding logo with `innerHTML`; skip the
		// markup so the element stays empty. Attribution remains in the bundled license notices.
		file: /@thatopen[\\/]components[\\/]dist[\\/]index\.mjs$/,
		find: 'el.innerHTML = THAT_OPEN_LOGO_SVG;',
		replace: '',
	},
	{
		// Fragments start their worker from a URL string: route it through the host's policy.
		file: /@thatopen[\\/]fragments[\\/]dist[\\/]FragmentsModels[\\/]src[\\/]multithreading[\\/]multithreading-helper\.mjs$/,
		find: 'return classic ? new Worker(url) : new Worker(url, { type: "module" });',
		replace: 'return classic ? new Worker(__saengineTrustedScriptUrl(url)) : new Worker(__saengineTrustedScriptUrl(url), { type: "module" });',
		prepend: `import { trustedScriptUrl as __saengineTrustedScriptUrl } from ${JSON.stringify(TRUSTED_TYPES_MODULE)};\n`,
	},
];

const applied = new Set();
const trustedTypesPatches = {
	name: 'trusted-types-patches',
	setup(build) {
		for (const patch of PATCHES) {
			build.onLoad({ filter: patch.file }, async args => {
				const source = await readFile(args.path, 'utf8');
				if (!source.includes(patch.find)) {
					throw new Error(`trusted-types-patches: "${patch.find}" not found in ${args.path}; re-check the patch after upgrading That Open.`);
				}
				applied.add(patch);
				return { contents: (patch.prepend ?? '') + source.replace(patch.find, patch.replace), loader: 'js' };
			});
		}
	},
};

const options = {
	entryPoints: ['src/index.ts'],
	outfile: 'dist/fem-viewer.js',
	bundle: true,
	format: 'esm',
	platform: 'browser',
	target: 'es2022',
	sourcemap: true,
	minify: !process.argv.includes('--watch'),
	legalComments: 'linked',
	logLevel: 'info',
	plugins: [trustedTypesPatches],
};

// Loaded at runtime by URL: the fragments worker and the IFC importer's web-ifc wasm.
async function copyAssets() {
	await mkdir('dist/web-ifc', { recursive: true });
	await copyFile('node_modules/@thatopen/fragments/dist/Worker/worker.mjs', 'dist/fragments-worker.mjs');
	await copyFile('node_modules/web-ifc/web-ifc.wasm', 'dist/web-ifc/web-ifc.wasm');
}

if (process.argv.includes('--watch')) {
	await copyAssets();
	await (await esbuild.context(options)).watch();
} else {
	await esbuild.build(options);
	if (applied.size !== PATCHES.length) {
		throw new Error(`Only ${applied.size} of ${PATCHES.length} That Open patches were applied.`);
	}
	await copyAssets();
}
