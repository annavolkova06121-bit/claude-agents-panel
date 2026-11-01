// Рендер прозрачных кадров оверлея 1080x1920 из overlay_source.html (Playwright + Chromium).
// Запуск: node render_overlay.js <overlay_source.html> <папка_кадров> <fps> <t_от> <t_до> [bright=0]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [file, outdir, fpsS, t0S, t1S, opt] = process.argv.slice(2);
  const fps = parseFloat(fpsS), t0 = parseFloat(t0S), t1 = parseFloat(t1S);
  fs.rmSync(outdir, { recursive: true, force: true }); fs.mkdirSync(outdir, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 3 });
  await p.goto('file://' + file + '#overlay' + (opt ? '&' + opt : ''));
  await p.waitForTimeout(800);
  const n = Math.round((t1 - t0) * fps) + 1;
  for (let k = 0; k < n; k++) {
    const t = t0 + k / fps;
    await p.evaluate(t => { window.__capture = true; window.__f(t); }, t);
    await p.screenshot({ path: `${outdir}/f_${String(k).padStart(4, '0')}.png`, omitBackground: true });
  }
  await b.close();
  console.log('кадров:', n);
})();
