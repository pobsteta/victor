// enregistrer_visuel.js — filme une scène de visuels-animes.html (Playwright headless).
// Lancé par VICTOR (production vidéo), avec NODE_PATH pointant sur le node_modules du kit.
// Usage : node enregistrer_visuel.js <url> <sortie.webm> <secondes>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const [url, sortie, secondes] = process.argv.slice(2);
  if (!url || !sortie || !(Number(secondes) > 0)) {
    throw new Error('usage : node enregistrer_visuel.js <url> <sortie.webm> <secondes>');
  }
  fs.mkdirSync(path.dirname(sortie), { recursive: true });
  const dir = fs.mkdtempSync(path.join(path.dirname(sortie), '.visuel-'));
  let browser;
  try {
    browser = await chromium.launch();
    const size = { width: 1920, height: 1080 };
    const ctx = await browser.newContext({ viewport: size, recordVideo: { dir, size } });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
    await page.waitForTimeout(Number(secondes) * 1000);
    const video = page.video();
    await ctx.close();                    // finalise la vidéo
    await video.saveAs(sortie);
    console.log('✓ Visuel', sortie);
  } finally {
    if (browser) await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
})().catch((e) => { console.error(e.message); process.exit(1); });
