// Bundles mlightcad and the wrapper into one ESM file plus its worker script.
// The workbench enforces Trusted Types, so mlightcad's `x.innerHTML = value` and `new Worker(url)`
// are rewritten (on the syntax tree, not by text search) to go through src/trustedTypes.ts.
import * as esbuild from 'esbuild';
import * as acorn from 'acorn';
import * as walk from 'acorn-walk';
import MagicString from 'magic-string';
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const HELPER = path.resolve('src/trustedTypes.ts').replace(/\\/g, '/');
const rewritten = new Map();

const trustedTypes = {
	name: 'trusted-types',
	setup(build) {
		build.onLoad({ filter: /[\\/]@mlightcad[\\/].*\.js$/ }, async args => {
			const source = await readFile(args.path, 'utf8');
			if (!source.includes('innerHTML') && !source.includes('new Worker')) {
				return undefined;
			}
			const ast = acorn.parse(source, { ecmaVersion: 'latest', sourceType: 'module' });
			const out = new MagicString(source);
			let count = 0;
			walk.simple(ast, {
				AssignmentExpression(node) {
					const target = node.left;
					if (target.type === 'MemberExpression' && !target.computed && target.property.name === 'innerHTML') {
						out.appendLeft(node.right.start, '__saengineTrustedHtml(');
						out.appendRight(node.right.end, ')');
						count++;
					}
				},
				NewExpression(node) {
					if (node.callee.type === 'Identifier' && node.callee.name === 'Worker' && node.arguments.length) {
						out.appendLeft(node.arguments[0].start, '__saengineTrustedScriptUrl(');
						out.appendRight(node.arguments[0].end, ')');
						count++;
					}
				},
			});
			if (!count) {
				return undefined;
			}
			rewritten.set(path.relative(process.cwd(), args.path), count);
			out.prepend(`import { trustedHtml as __saengineTrustedHtml, trustedScriptUrl as __saengineTrustedScriptUrl } from '${HELPER}';\n`);
			return { contents: out.toString(), loader: 'js' };
		});
	},
};

// mlightcad imports three.js example modules without their extension (Vite tolerates that).
const threeExamples = {
	name: 'three-examples',
	setup(build) {
		build.onResolve({ filter: /^three\/examples\/jsm\// }, args => args.path.endsWith('.js')
			? undefined
			: build.resolve(`${args.path}.js`, { kind: args.kind, resolveDir: args.resolveDir }));
	},
};

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
// its own: an ezdxf-generated template (scripts/make-template.py) and DejaVu Sans (Bitstream Vera
// license) registered under the font names drawings and mlightcad fall back to.
await mkdir('dist/assets/templates', { recursive: true });
await mkdir('dist/assets/fonts', { recursive: true });
await copyFile('assets/templates/acadiso.dxf', 'dist/assets/templates/acadiso.dxf');
await copyFile('node_modules/dejavu-fonts-ttf/ttf/DejaVuSans.ttf', 'dist/assets/fonts/DejaVuSans.ttf');
await copyFile('node_modules/dejavu-fonts-ttf/LICENSE', 'dist/assets/fonts/DejaVuSans-LICENSE.txt');
const fonts = [{
	file: 'DejaVuSans.ttf',
	type: 'mesh',
	name: ['DejaVu Sans', 'standard', 'txt', 'simplex', 'romans', 'isocp', 'arial', 'simsun'],
}];
await writeFile('dist/assets/fonts/fonts.json', JSON.stringify(fonts, undefined, '\t'));
