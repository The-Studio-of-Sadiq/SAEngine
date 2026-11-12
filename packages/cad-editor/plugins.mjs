// esbuild plugins shared by the bundle build and the tests.
import * as acorn from 'acorn';
import * as walk from 'acorn-walk';
import MagicString from 'magic-string';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { applyPatches } from './patches/mlightcad.mjs';

const HELPER = path.resolve(import.meta.dirname, 'src/trustedTypes.ts').replace(/\\/g, '/');
export const rewritten = new Map();
export const patched = [];

export const trustedTypes = {
	name: 'trusted-types',
	setup(build) {
		build.onLoad({ filter: /[\\/]@mlightcad[\\/].*\.js$/ }, async args => {
			const original = await readFile(args.path, 'utf8');
			const source = applyPatches(args.path, original, patched);
			if (!source.includes('innerHTML') && !source.includes('new Worker')) {
				return source === original ? undefined : { contents: source, loader: 'js' };
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
				return source === original ? undefined : { contents: source, loader: 'js' };
			}
			rewritten.set(path.relative(process.cwd(), args.path), count);
			out.prepend(`import { trustedHtml as __saengineTrustedHtml, trustedScriptUrl as __saengineTrustedScriptUrl } from '${HELPER}';\n`);
			return { contents: out.toString(), loader: 'js' };
		});
	},
};

// mlightcad imports three.js example modules without their extension (Vite tolerates that).
export const threeExamples = {
	name: 'three-examples',
	setup(build) {
		build.onResolve({ filter: /^three\/examples\/jsm\// }, args => args.path.endsWith('.js')
			? undefined
			: build.resolve(`${args.path}.js`, { kind: args.kind, resolveDir: args.resolveDir }));
	},
};
