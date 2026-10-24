// Records a silent backup video of the demo (replay provider, no LLM quota): scenario 1 -> report -> audit -> scenario 5 -> overview.
// Usage: node scripts/record-backup.mjs   -> ../docs/demo_backup.webm
import { chromium } from "playwright";
import { mkdirSync, renameSync, readdirSync } from "node:fs";
const dir = "../docs/video-tmp";
mkdirSync(dir, { recursive: true });
const api = (p) => fetch(`http://127.0.0.1:8000${p}`, { method: "POST" }).then((r) => r.json());
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir, size: { width: 1920, height: 1080 } } });
const page = await ctx.newPage();
await api("/api/demo/reset");
await page.goto("http://localhost:5173");
await page.waitForSelector('[data-testid="conn"]:has-text("Connected")');
await page.keyboard.press("p");
await wait(8000);
const approve = async (reason) => {
  await page.waitForSelector('[data-testid="approval"]', { timeout: 180000 });
  await wait(5000);
  await page.fill('[data-testid="approval"] textarea', reason);
  await wait(1200);
  await page.click('[data-testid="approve"]');
};
await api("/api/demo/fault/1?provider=replay");
await approve("Diff matches the error logs; revert is low risk");
await page.waitForSelector('[data-testid="sla-final"]', { timeout: 180000 });
await wait(6000);
await page.click('[data-testid="tab-report"]');
await wait(5000);
await page.mouse.move(900, 700);
for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, 350); await wait(1200); }
await page.click('[data-testid="tab-audit"]');
await wait(5000);
await page.keyboard.press("Escape");
await api("/api/demo/reset");
await wait(5000);
await api("/api/demo/fault/5?provider=replay");
await page.waitForSelector(".step-warning", { timeout: 180000 });
await approve("Rolling back to deploy-5; the deploy-1 instruction came from a log line");
await page.waitForSelector('[data-testid="sla-final"]', { timeout: 180000 });
await wait(5000);
await page.click('[data-testid="tab-overview"]');
await wait(7000);
await ctx.close();
await browser.close();
const f = readdirSync(dir).find((x) => x.endsWith(".webm"));
renameSync(`${dir}/${f}`, "../docs/demo_backup.webm");
console.log("saved docs/demo_backup.webm");
