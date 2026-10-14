// Bundles mlightcad and the wrapper into one ESM file plus its worker script.
// The workbench enforces Trusted Types, so mlightcad's `x.innerHTML = value` and `new Worker(url)`
// are rewritten (on the syntax tree, not by text search) to go through src/trustedTypes.ts.
import * as esbuild from 'esbuild';
import { PATCHES } from './patches/mlightcad.mjs';
import { patched, rewritten, threeExamples, trustedTypes } from './plugins.mjs';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';

await esbuild.build({
	entryPoints: ['src/index.ts'],
	outfile: 'dist/cad-editor.js',
	bundle: true,
	format: 'esm',
	platform: 'browser',
	target: 'es2022',
	sourcemap: true,
	minify: true,
	legalComments: 'linked',
	logLevel: 'info',
	// The workbench defines a global AMD `define`; bundled UMD modules (loglevel, ...) would
	// register through it instead of exporting, so hide it from the bundle.
	define: { define: 'undefined' },
	plugins: [trustedTypes, threeExamples],
});

if (patched.length !== PATCHES.length) {
	throw new Error(`Only ${patched.length} of ${PATCHES.length} mlightcad patches were applied: ${patched.join('; ')}`);
}
console.log(`mlightcad patches: ${patched.length} applied`);
const total = [...rewritten.values()].reduce((a, b) => a + b, 0);
console.log(`trusted-types: rewrote ${total} innerHTML/Worker site(s) in ${rewritten.size} file(s)`);
const bundle = await readFile('dist/cad-editor.js', 'utf8');
if (/\.innerHTML\s*=(?!=)/.test(bundle.replace(/innerHTML=__saengineTrustedHtml|innerHTML=\w+\(/g, ''))) {
	console.warn('trusted-types: an innerHTML assignment may have escaped the rewrite; check the bundle.');
}

// The MTEXT layout worker is loaded by URL at runtime.
await mkdir('dist', { recursive: true });
await copyFile('node_modules/@mlightcad/mtext-renderer/dist/mtext-renderer-worker.js', 'dist/mtext-renderer-worker.js');

// Offline assets. mlightcad's defaults come from an unlicensed CDN repository, so SAEngine ships
// its own: an ezdxf-generated template (scripts/make-template.py) and openly licensed fonts,
// registered under the names drawings reference. mlightcad matches a style's font by its file
// name, lower-cased and without extension ("LiberationSans-Bold.ttf" -> "liberationsans-bold").
// Bold/italic variants map to the regular face.
const VARIANTS = ['', '-regular', '-bold', '-italic', '-bolditalic', '-light', '-lightitalic', '-semibold', '-semibolditalic', '-extrabold', '-extrabolditalic'];
const variants = (...families) => families.flatMap(f => VARIANTS.map(v => f + v));
const FONTS = [
	{
		// DejaVu (Bitstream Vera license): AutoCAD's default SHX names fall back to it.
		source: 'node_modules/dejavu-fonts-ttf/ttf/DejaVuSans.ttf', file: 'DejaVuSans.ttf',
		license: ['node_modules/dejavu-fonts-ttf/LICENSE', 'DejaVu-LICENSE.txt'],
		names: ['dejavu sans', ...variants('dejavusans'), 'standard', 'txt', 'simplex', 'romans', 'romand', 'isocp', 'iso', 'monotxt'],
	},
	{
		source: 'node_modules/dejavu-fonts-ttf/ttf/DejaVuSansMono.ttf', file: 'DejaVuSansMono.ttf',
		names: ['dejavu sans mono', ...variants('dejavusansmono', 'liberationmono', 'couriernew', 'cour', 'consolas')],
	},
	{
		source: 'node_modules/dejavu-fonts-ttf/ttf/DejaVuSerif.ttf', file: 'DejaVuSerif.ttf',
		names: ['dejavu serif', ...variants('dejavuserif', 'liberationserif', 'times', 'timesnewroman', 'romant')],
	},
	{
		// Arimo (OFL): the Liberation Sans design, metric-compatible with Arial.
		source: 'node_modules/@expo-google-fonts/arimo/400Regular/Arimo_400Regular.ttf', file: 'Arimo.ttf',
		license: ['node_modules/@expo-google-fonts/arimo/LICENSE_FONT', 'Arimo-LICENSE.txt'],
		names: ['arimo', ...variants('arimo', 'arial', 'liberationsans', 'opensans', 'opensanscondensed', 'helvetica', 'calibri', 'segoeui', 'tahoma', 'verdana')],
	},
	{
		// Noto Sans Bengali (OFL), for Bengali notes and titles in drawings.
		source: 'node_modules/@expo-google-fonts/noto-sans-bengali/400Regular/NotoSansBengali_400Regular.ttf', file: 'NotoSansBengali.ttf',
		license: ['node_modules/@expo-google-fonts/noto-sans-bengali/LICENSE_FONT', 'NotoSansBengali-LICENSE.txt'],
		names: ['noto sans bengali', ...variants('notosansbengali', 'vrinda', 'nirmalaui', 'solaimanlipi', 'kalpurush', 'siyamrupali', 'shonarbangla')],
	},
];

await mkdir('dist/assets/templates', { recursive: true });
await mkdir('dist/assets/fonts', { recursive: true });
await copyFile('assets/templates/acadiso.dxf', 'dist/assets/templates/acadiso.dxf');
for (const font of FONTS) {
	await copyFile(font.source, `dist/assets/fonts/${font.file}`);
	if (font.license) {
		await copyFile(font.license[0], `dist/assets/fonts/${font.license[1]}`);
	}
}
await writeFile('dist/assets/fonts/fonts.json', JSON.stringify(
	FONTS.map(f => ({ file: f.file, type: 'mesh', name: [...new Set(f.names)] })), undefined, '\t'));
console.log(`fonts: ${FONTS.map(f => f.file).join(', ')}`);
