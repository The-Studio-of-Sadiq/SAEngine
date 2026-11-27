// Waits until the status bar no longer shows a running job (· m:ss timer or "Engine working"); prints changes.
const { chromium } = require(require('path').join(__dirname, '..', '..', 'workbench', 'node_modules', 'playwright-core'));
(async () => {
	const browser = await chromium.connectOverCDP('http://127.0.0.1:' + (process.env.SAENGINE_GATE_PORT || 9347));
	const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes('workbench'));
	const t0 = Date.now();
	let last = '', idle = 0;
	for (;;) {
		const s = await page.evaluate(() => {
			const sb = (document.querySelector('.part.statusbar')?.innerText || '').replace(/\d+:\d\d|\d+ s\b/g, '#');
			const toasts = [...document.querySelectorAll('.notification-list-item-message')].map(e => e.innerText).join(' || ');
			return sb.replace(/\n/g, ' | ') + ' ## ' + toasts;
		}).catch(e => 'ERR ' + e.message);
		if (s !== last) { console.log(((Date.now() - t0) / 1000).toFixed(0) + 's', s); last = s; }
		const busy = /·\s*#|Engine working|Run All \d+\/\d+/.test(s);
		idle = busy ? 0 : idle + 1;
		if (idle >= 3) { break; }
		if (Date.now() - t0 > 3 * 3600e3) { console.log('TIMEOUT'); break; }
		await new Promise(r => setTimeout(r, 5000));
	}
	console.log('end', ((Date.now() - t0) / 1000).toFixed(0) + 's');
	process.exit(0);
})();
