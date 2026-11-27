// Waits until the Run All status/toast says done or failed; prints the step timeline.
const { chromium } = require(require('path').join(__dirname, '..', '..', 'workbench', 'node_modules', 'playwright-core'));
(async () => {
	const browser = await chromium.connectOverCDP('http://127.0.0.1:' + (process.env.SAENGINE_GATE_PORT || 9347));
	const page = browser.contexts().flatMap(c => c.pages()).find(p => p.url().includes('workbench'));
	const t0 = Date.now();
	let last = '';
	for (;;) {
		const s = await page.evaluate(() => {
			const sb = document.querySelector('.part.statusbar')?.innerText || '';
			const toasts = [...document.querySelectorAll('.notifications-toasts .notification-list-item-message, .notification-list-item-message')].map(e => e.innerText).join(' || ');
			return (sb.match(/Run All[^\n]*/)?.[0] || '') + ' ## ' + toasts;
		}).catch(e => 'ERR ' + e.message);
		if (s !== last) { console.log(((Date.now() - t0) / 1000).toFixed(0) + 's', s); last = s; }
		if (/Run All done in|Run All: step \d+ of \d+ .*failed|Run All (stopped|failed)/.test(s)) { break; }
		if (Date.now() - t0 > 3 * 3600e3) { console.log('TIMEOUT'); break; }
		await new Promise(r => setTimeout(r, 5000));
	}
	process.exit(0);
})();
