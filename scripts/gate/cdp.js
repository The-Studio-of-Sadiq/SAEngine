// CDP helper for the gate walk. Usage:
//   node cdp.js shot <name> [w h]        screenshot (optionally emulate w x h first)
//   node cdp.js eval <file.js|code>      evaluate in the workbench page, print JSON
//   node cdp.js size <w> <h>             1366: resizeTo; 1920: device-metrics emulation; 0 0 clears
//   node cdp.js click <css|text=...>     click an element (CDP-dispatched, not the real mouse)
//   node cdp.js type <text>              type into the focused element
//   node cdp.js key <Key>                press a key (e.g. Enter, Escape)
//   node cdp.js text [css]               innerText of the page/element (first 6000 chars)
const path = require('path');
const fs = require('fs');
const { chromium } = require(require('path').join(__dirname, '..', '..', 'workbench', 'node_modules', 'playwright-core'));
const OUT = path.join(process.env.SAENGINE_GATE_DIR || path.join(require('os').homedir(), 'Documents', 'saengine-walk-gate'), 'shots');

(async () => {
	const [cmd, ...rest] = process.argv.slice(2);
	const browser = await chromium.connectOverCDP('http://127.0.0.1:' + (process.env.SAENGINE_GATE_PORT || 9347));
	const pages = browser.contexts().flatMap(c => c.pages());
	const page = pages.find(p => p.url().includes('workbench')) || pages[0];
	const metricsFile = path.join(OUT, '.metrics.json');
	async function applyMetrics() {
		if (!fs.existsSync(metricsFile)) { return; }
		const m = JSON.parse(fs.readFileSync(metricsFile, 'utf8'));
		if (m.w) {
			const s = await page.context().newCDPSession(page);
			await s.send('Emulation.setDeviceMetricsOverride', { width: m.w, height: m.h, deviceScaleFactor: 1, mobile: false });
		}
	}
	let out;
	switch (cmd) {
		case 'size': {
			const w = +rest[0], h = +rest[1];
			fs.mkdirSync(OUT, { recursive: true });
			const s = await page.context().newCDPSession(page);
			if (w > 1366) {
				fs.writeFileSync(metricsFile, JSON.stringify({ w, h }));
				await s.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
			} else {
				if (fs.existsSync(metricsFile)) { fs.unlinkSync(metricsFile); }
				await s.send('Emulation.clearDeviceMetricsOverride');
				if (w) { await page.evaluate(([w, h]) => { moveTo(0, 0); resizeTo(w, h); }, [w, h]); }
			}
			out = await page.evaluate(() => [innerWidth, innerHeight, outerWidth, outerHeight, screenX, screenY]);
			break;
		}
		case 'shot': {
			await applyMetrics();
			fs.mkdirSync(OUT, { recursive: true });
			const f = path.join(OUT, rest[0] + '.png');
			await page.screenshot({ path: f, timeout: 30000 });
			out = f;
			break;
		}
		case 'eval': {
			let code = rest.join(' ');
			if (fs.existsSync(code)) { code = fs.readFileSync(code, 'utf8'); }
			out = await page.evaluate(`(async () => { ${code} })()`);
			break;
		}
		case 'click': {
			const sel = rest.join(' ');
			await page.locator(sel).first().click({ timeout: 10000 });
			out = 'clicked ' + sel;
			break;
		}
		case 'dblclick': {
			const sel = rest.join(' ');
			await page.locator(sel).first().dblclick({ timeout: 10000 });
			out = 'dblclicked ' + sel;
			break;
		}
		case 'fill': {
			const [sel, ...v] = rest;
			await page.locator(sel).first().fill(v.join(' '), { timeout: 10000 });
			out = 'filled';
			break;
		}
		case 'mclick': {
			// coordinates in screenshot pixels of a 2000-wide downscale of a DPR-2 shot -> CSS px
			const f = rest[2] ? +rest[2] : 0.68;
			await page.mouse.click(+rest[0] * f, +rest[1] * f);
			out = 'mclicked';
			break;
		}
		case 'type': await page.keyboard.type(rest.join(' ')); out = 'typed'; break;
		case 'key': await page.keyboard.press(rest[0]); out = 'pressed ' + rest[0]; break;
		case 'text': {
			out = await page.evaluate(sel => (sel ? document.querySelector(sel) : document.body)?.innerText?.slice(0, 6000), rest.join(' ') || null);
			break;
		}
		default: out = pages.map(p => p.url());
	}
	console.log(typeof out === 'string' ? out : JSON.stringify(out, null, 1));
	process.exit(0);
})().catch(e => { console.error('ERR', e.message.split('\n')[0]); process.exit(1); });
