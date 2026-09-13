// Capture one page of the dev environment.
//
// Usage: node screenshot.js <url> <output.png>
//
// Kept deliberately small: it renders a page and writes a PNG. Anything that
// needs a login is out of scope — the session container holds no user
// credentials, and giving it some to make screenshots prettier would defeat
// the isolation the whole runner is built around.

const { chromium } = require('playwright');

const [, , url, output] = process.argv;

if (!url || !output) {
  console.error('usage: screenshot.js <url> <output.png>');
  process.exit(2);
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      // No sandbox: the container is already the sandbox, and Chromium's own
      // needs user namespaces that the runner's seccomp profile denies.
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    const page = await context.newPage();

    const response = await page.goto(url, {
      waitUntil: 'networkidle',
      timeout: 45_000,
    });
    if (response && response.status() >= 400) {
      console.error(`page returned HTTP ${response.status()}`);
    }

    // Angular renders after hydration; a short settle beats a fixed long wait.
    await page.waitForTimeout(1_500);
    await page.screenshot({ path: output, fullPage: true });
    console.log(`wrote ${output}`);
  } catch (error) {
    console.error(`screenshot failed: ${error.message}`);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
  }
})();
