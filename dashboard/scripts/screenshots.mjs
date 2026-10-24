// Section 11.6 UI check: 5 states x 2 resolutions -> docs/screenshots/. Requires `demo.py up`.
// Usage: node scripts/screenshots.mjs [scenario=1] [outdir=../docs/screenshots]
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
const scenario = process.argv[2] ?? "1";
const out = process.argv[3] ?? "../docs/screenshots";
mkdirSync(out, { recursive: true });
const api = (p, m = "POST") => fetch(`http://127.0.0.1:8000${p}`, { method: m }).then((r) => r.json());
const sizes = [[1920, 1080], [1366, 768]];
const browser = await chromium.launch();
const pages = [];
for (const [w, h] of sizes) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  pages.push({ page, tag: `${w}x${h}` });
}
const all = (fn) => Promise.all(pages.map(fn));
const shot = (name) => all(({ page, tag }) => page.screenshot({ path: `${out}/${name}-${tag}.png` }));
const problems = [];
const audit = async (state) => all(async ({ page, tag }) => {
  const r = await page.evaluate(() => {
    const doc = document.documentElement;
    const issues = [];
    if (doc.scrollWidth > doc.clientWidth + 1) issues.push(`horizontal scroll ${doc.scrollWidth}>${doc.clientWidth}`);
    if (doc.scrollHeight > doc.clientHeight + 1) issues.push(`page scroll ${doc.scrollHeight}>${doc.clientHeight}`);
    for (const el of document.querySelectorAll(".card, .tile, .chart")) {
      if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX === "visible") issues.push(`overflow-x in ${el.className.slice(0, 40)}`);
    }
    const small = [...document.querySelectorAll("body *")].filter((e) => e.childElementCount === 0 && e.textContent.trim() && e.offsetParent && parseFloat(getComputedStyle(e).fontSize) < 11);
    if (small.length) issues.push(`${small.length} text nodes < 11px`);
    return issues;
  });
  if (r.length) problems.push(`${state} @${tag}: ${r.join("; ")}`);
});

await api("/api/demo/reset");
await all(({ page }) => page.goto("http://localhost:5173"));
await all(({ page }) => page.waitForSelector('[data-testid="conn"]:has-text("Connected")'));
await new Promise((r) => setTimeout(r, 6000));
await shot("1-idle"); await audit("idle");
await api(`/api/demo/fault/${scenario}`);
await all(({ page }) => page.waitForSelector('[data-testid="ticket"]', { timeout: 60000 }));
await new Promise((r) => setTimeout(r, 1500));
await shot("2-alert"); await audit("alert");
await all(({ page }) => page.waitForFunction(() => document.querySelectorAll(".step").length >= 6, null, { timeout: 120000 }));
await shot("3-investigating"); await audit("investigating");
await all(({ page }) => page.waitForSelector('[data-testid="approval"]', { timeout: 180000 }));
await new Promise((r) => setTimeout(r, 2500));
await shot("4-approval"); await audit("approval");
const p0 = pages[0].page;
await p0.fill('[data-testid="approval"] textarea', "Diff matches the error logs; low-risk revert");
await p0.click('[data-testid="approve"]');
await all(({ page }) => page.waitForSelector('[data-testid="sla-final"]', { timeout: 180000 }));
await new Promise((r) => setTimeout(r, 4000));
await shot("5-resolved"); await audit("resolved");
await all(({ page }) => page.click('[data-testid="tab-report"]'));
await all(({ page }) => page.waitForSelector(".markdown", { timeout: 30000 }));
await new Promise((r) => setTimeout(r, 800));
await shot("6-report"); await audit("report");
await all(({ page }) => page.click('[data-testid="tab-overview"]'));
await new Promise((r) => setTimeout(r, 1000));
await shot("7-overview");
console.log(problems.length ? "ISSUES:\n" + problems.join("\n") : "layout audit: no overflow / scroll / tiny-text issues");
await browser.close();
