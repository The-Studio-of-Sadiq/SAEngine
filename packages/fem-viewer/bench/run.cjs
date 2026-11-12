/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

// Runs the viewer benchmark (bench.html) in an Electron window placed off-screen and prints its
// result as JSON. Build the viewer first (npm run build), then, with the workbench's Electron:
//
//   "<workbench>/.build/electron/Code - OSS.exe" packages/fem-viewer/bench [--model=<file.osmodel>]
//       [--storeys=30] [--theme=dark|light] [--shots=<folder>] [--out=<file.json>]
//
// --shots saves screenshots of the model and of a few results instead of timing.

const { app, BrowserWindow } = require('electron');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const args = Object.fromEntries(process.argv.slice(1).filter(a => a.startsWith('--')).map(a => {
	const [key, ...value] = a.slice(2).split('=');
	return [key, value.join('=') || 'true'];
}));
const root = path.resolve(__dirname, '..');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.json': 'application/json', '.wasm': 'application/wasm', '.map': 'application/json' };

app.commandLine.appendSwitch('js-flags', '--expose-gc');
app.commandLine.appendSwitch('enable-precise-memory-info');
app.setPath('userData', path.join(os.tmpdir(), 'viewerperf-bench-ud'));

function serve() {
	const server = http.createServer((request, response) => {
		const url = new URL(request.url, 'http://localhost');
		const file = url.pathname === '/model' ? path.resolve(args.model) : path.join(root, decodeURIComponent(url.pathname));
		if (url.pathname !== '/model' && !file.startsWith(root)) {
			response.writeHead(403).end();
			return;
		}
		fs.readFile(file, (error, data) => {
			if (error) {
				response.writeHead(404).end();
				return;
			}
			response.writeHead(200, { 'Content-Type': types[path.extname(file)] ?? 'application/octet-stream' }).end(data);
		});
	});
	return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}

app.whenReady().then(async () => {
	const server = await serve();
	const window = new BrowserWindow({
		x: -4000, y: 0, width: 1600, height: 1000, show: true, title: 'viewerperf-bench',
		webPreferences: { backgroundThrottling: false },
	});
	const query = new URLSearchParams();
	if (args.model) {
		query.set('model', '/model');
	}
	for (const key of ['storeys', 'theme', 'shots']) {
		if (args[key]) {
			query.set(key, args[key]);
		}
	}
	const finish = code => {
		server.close();
		app.exit(code);
	};
	window.webContents.on('console-message', async event => {
		const message = event.message;
		if (message.startsWith('BENCH_RESULT ')) {
			const text = JSON.stringify(JSON.parse(message.slice(13)), undefined, '\t');
			if (args.out) {
				fs.writeFileSync(args.out, text);
			}
			process.stdout.write(text + '\n');
			finish(0);
		} else if (message.startsWith('BENCH_SHOT ')) {
			const image = await window.webContents.capturePage();
			fs.mkdirSync(args.shots, { recursive: true });
			fs.writeFileSync(path.join(args.shots, message.slice(11) + '.png'), image.toPNG());
			await window.webContents.executeJavaScript('window.benchShotTaken()');
		} else if (event.level === 'error' || message.startsWith('Uncaught')) {
			process.stderr.write(`page: ${message}\n`);
		}
	});
	window.webContents.on('render-process-gone', () => finish(1));
	setTimeout(() => {
		process.stderr.write('benchmark timed out\n');
		finish(2);
	}, 10 * 60 * 1000);
	await window.loadURL(`http://127.0.0.1:${server.address().port}/bench/bench.html?${query}`);
});
