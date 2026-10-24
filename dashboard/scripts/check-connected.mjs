import { chromium } from "playwright";
const url = process.argv[2] ?? "http://localhost:5173";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
await page.goto(url);
await page.waitForSelector('[data-testid="conn"]:has-text("Connected")', { timeout: 15000 });
console.log("dashboard:", (await page.textContent('[data-testid="conn"]')).trim());
if (process.argv[3]) await page.screenshot({ path: process.argv[3] });
await browser.close();
