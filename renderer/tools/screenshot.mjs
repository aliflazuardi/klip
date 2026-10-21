// Capture a web page for a stage `screenshot` element.
// Usage: node screenshot.mjs '<json>'  with {url, out, chrome, width, height, scale, selector, wait_ms, timeout_ms}
// Uses puppeteer-core (installed with HyperFrames) and the headless Chrome HyperFrames downloads.
import puppeteer from "puppeteer-core";

const o = JSON.parse(process.argv[2]);
const browser = await puppeteer.launch({ executablePath: o.chrome, headless: true,
  args: ["--no-sandbox", "--hide-scrollbars", "--disable-notifications"] });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: o.width, height: o.height, deviceScaleFactor: o.scale });
  await page.setUserAgent("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36");
  try {
    await page.goto(o.url, { waitUntil: "networkidle2", timeout: o.timeout_ms });
  } catch (e) {
    if (!String(e).includes("Timeout")) throw e;   // slow trackers: keep what has loaded
  }
  await new Promise((r) => setTimeout(r, o.wait_ms));
  if (o.selector) {
    const el = await page.$(o.selector);
    if (!el) throw new Error(`selector not found: ${o.selector}`);
    await el.screenshot({ path: o.out });
  } else {
    await page.screenshot({ path: o.out, clip: { x: 0, y: 0, width: o.width, height: o.height } });
  }
} finally {
  await browser.close();
}
