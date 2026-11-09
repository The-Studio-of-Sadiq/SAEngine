// Bundles the web viewer and three.js into one classic script (IIFE): the exported index.html is
// opened from disk (file://), where browsers refuse ES modules, so it loads `viewer.js` with a plain
// <script> tag. The release build copies dist/web-viewer.js to
// workbench/resources/saengine/web-viewer/viewer.js, where the backend's web viewer export finds it
// (saengine.exporters.web_viewer.viewer_bundle); without it the export uses its built-in view.
import * as esbuild from 'esbuild';

await esbuild.build({
	entryPoints: ['src/index.ts'],
	outfile: 'dist/web-viewer.js',
	bundle: true,
	format: 'iife',
	platform: 'browser',
	target: 'es2020',
	minify: true,
	legalComments: 'linked',
	logLevel: 'info',
});
