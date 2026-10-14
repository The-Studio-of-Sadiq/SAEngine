// Bundles the viewer and its dependencies (three, That Open, camera-controls) into one ESM file.
// The workbench renderer cannot resolve bare module specifiers, so it loads this single file by URL.
import * as esbuild from 'esbuild';
import { readFile } from 'node:fs/promises';

// The workbench enforces Trusted Types, so any `innerHTML` assignment throws. That Open's renderer
// builds its (hidden by us) branding logo with `innerHTML`; skip the markup so the element stays empty.
// Attribution for That Open remains in the bundled license notices.
const trustedTypesPatches = {
	name: 'trusted-types-patches',
	setup(build) {
		build.onLoad({ filter: /@thatopen[\\/]components[\\/]dist[\\/]index\.mjs$/ }, async args => {
			const source = await readFile(args.path, 'utf8');
			const patched = source.replace('el.innerHTML = THAT_OPEN_LOGO_SVG;', '');
			if (patched === source) {
				throw new Error('trusted-types-patches: That Open logo assignment not found; re-check the patch after upgrading @thatopen/components.');
			}
			return { contents: patched, loader: 'js' };
		});
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

if (process.argv.includes('--watch')) {
	await (await esbuild.context(options)).watch();
} else {
	await esbuild.build(options);
}
