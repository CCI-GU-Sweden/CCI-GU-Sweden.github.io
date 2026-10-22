// Optional browser integration checks. Fixtures are synthetic and route-local.
import assert from "node:assert/strict";
import {readFile, mkdir} from "node:fs/promises";
import {chromium} from "../.local/portal-testing/node_modules/playwright/index.mjs";

const base = process.env.PUBLICATIONS_TEST_URL || "http://127.0.0.1:4001";
const catalogue = JSON.parse(await readFile(new URL("../assets/data/publications.json", import.meta.url)));
const browser = await chromium.launch({headless: true});
const context = await browser.newContext({viewport: {width: 1280, height: 900}});
// Keep browser tests local; the existing layout's external analytics is blocked.
await context.route("**/*", route => {
  const url = new URL(route.request().url());
  if (url.origin === new URL(base).origin) return route.continue();
  // Jekyll's preview config uses port 4000 for absolute logo URLs. Keep
  // those requests on this isolated test server when it uses another port.
  if (["127.0.0.1", "localhost"].includes(url.hostname)) {
    return route.continue({url: new URL(url.pathname + url.search, base).href});
  }
  return route.abort();
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await mkdir(".local/portal-testing/screenshots", {recursive: true});

async function ready(page) {
  await page.locator("[name=q]").waitFor();
  await page.waitForFunction(() => !document.querySelector(".publications-controls > fieldset").disabled);
}

async function count(page, expected) {
  await page.waitForFunction(expected => document.querySelectorAll(".publication-card").length === expected, expected);
}

try {
  await page.goto(`${base}/publications/`);
  await ready(page);
  await count(page, 20);
  assert.equal(await page.locator("[name=year]").inputValue(), "");
  assert.equal(await page.locator("[name=sort]").inputValue(), "newest");
  assert.match(await page.locator("[data-status]").textContent(), /20 of 138/);
  assert.equal(await page.locator(".publication-year").first().textContent(), "2026");
  assert.equal(await page.locator("[data-technology-controls]").isVisible(), false);
  assert.equal(await page.locator('nav a[href="/publications/"]').getAttribute("class"), "active");
  assert.equal(await page.locator(".project-logo").evaluate(img => img.complete && img.naturalWidth > 0), true);
  await page.screenshot({path: ".local/portal-testing/screenshots/desktop.png", fullPage: false});
  console.log("PASS: all years/newest default, initial results, navigation, and untagged catalogue");

  await page.locator("[data-more]").click();
  await count(page, 40);
  assert.match(await page.locator("[data-status]").textContent(), /40 of 138/);
  assert.equal(await page.evaluate(() => document.activeElement === document.querySelectorAll(".publication-card h2 a")[20]), true);
  await page.locator("[name=year]").selectOption("2025");
  await count(page, 20);
  assert.match(await page.locator("[data-status]").textContent(), /of 36/);
  await page.locator("[name=q]").fill("10.1093/jxb/erae387");
  await count(page, 1);
  assert.equal(await page.locator(".publication-year").textContent(), "2025");
  assert.equal(await page.locator(".publication-doi a").getAttribute("href"), "https://doi.org/10.1093/jxb/erae387");
  await page.reload();
  await ready(page);
  await count(page, 1);
  assert.equal(await page.locator("[name=year]").inputValue(), "2025");
  console.log("PASS: pagination, corrected year, DOI search, and shared URL restoration");

  await page.locator("[data-clear]").click();
  await count(page, 20);
  assert.equal(await page.locator("[name=year]").inputValue(), "");
  assert.equal(await page.locator("[name=sort]").inputValue(), "newest");
  assert.equal(new URL(page.url()).search, "");
  await page.locator("[name=sort]").selectOption("oldest");
  assert.equal(await page.locator(".publication-year").first().textContent(), "2022");
  await page.locator("[name=q]").fill("zzzz-no-synthetic-match-zzzz");
  await count(page, 0);
  assert.equal(await page.locator("[data-empty]").isVisible(), true);
  await page.locator("[data-clear]").click();
  await page.locator("[name=q]").fill("10.1038/s41592-023-01987-9");
  await count(page, 1);
  assert.equal(await page.locator(".publication-year").textContent(), "2024");
  await page.locator('[data-disclosure="authors"]').click();
  assert.equal(await page.locator('[data-disclosure="authors"]').getAttribute("aria-expanded"), "true");
  await page.locator("[name=q]").focus();
  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement.id), "publication-year");
  console.log("PASS: sorting, empty state, reset, full author disclosure, and keyboard navigation");

  await page.locator("[data-clear]").click();
  for (const width of [375, 768, 1024]) {
    await page.setViewportSize({width, height: 900});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Overflow at ${width}px`);
  }
  await page.setViewportSize({width: 375, height: 812});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path: ".local/portal-testing/screenshots/mobile.png", fullPage: false});
  console.log("PASS: responsive layout at 375, 768, and 1024 pixels");

  const fixture = structuredClone(catalogue);
  fixture.publications = fixture.publications.slice(0, 2);
  fixture.publications[0].title = "Synthetic fixture <img src=x onerror=window.__injected=1>";
  fixture.publications[0].technologies = ["confocal", "light_sheet"];
  fixture.publications[0].authors = ["Synthetic A", "Synthetic B", "Synthetic C", "Synthetic D", "Synthetic E", "Synthetic F"];
  fixture.publications[0].abstract = {text: "Synthetic abstract first paragraph.\n\nSecond paragraph <script>window.__injected=1</script>.",
    source_url: "https://doi.org/10.1234/synthetic", license_url: "https://creativecommons.org/licenses/by/4.0/"};
  fixture.publications[1].title = "Synthetic second fixture";
  fixture.publications[1].technologies = ["electron"];
  delete fixture.publications[1].abstract;
  fixture.vocabulary = {technologies: [
    {id: "confocal", label: "Confocal microscopy"},
    {id: "light_sheet", label: "Light-sheet microscopy"},
    {id: "electron", label: "Electron microscopy"},
  ]};
  await page.route("**/assets/data/publications.json", route => route.fulfill({json: fixture}));
  await page.goto(`${base}/publications/`);
  await ready(page);
  await count(page, 2);
  assert.equal(await page.locator(".publication-card img").count(), 0);
  assert.equal(await page.evaluate(() => window.__injected), undefined);
  const abstractButton = page.locator('[data-disclosure="abstract"]');
  assert.equal(await abstractButton.count(), 1);
  const abstractPanel = page.locator(".publication-abstract-text");
  assert.equal(await abstractPanel.isVisible(), false);
  const authorButton = page.locator('[data-disclosure="authors"]').first();
  const authorBox = await authorButton.boundingBox();
  const abstractBox = await abstractButton.boundingBox();
  assert.ok(Math.abs(authorBox.y - abstractBox.y) < 2, "Abstract control should sit beside the authors control");
  assert.ok(abstractBox.x > authorBox.x, "Abstract should be on the right");
  await abstractButton.focus();
  await page.keyboard.press("Enter");
  assert.equal(await abstractPanel.isVisible(), true);
  assert.equal(await abstractPanel.locator("script").count(), 0);
  assert.equal(await abstractPanel.locator("p").count(), 3);
  await authorButton.click();
  assert.equal(await abstractButton.getAttribute("aria-expanded"), "true");
  assert.equal(await authorButton.getAttribute("aria-expanded"), "true");
  await abstractButton.click();
  assert.equal(await abstractPanel.isVisible(), false);
  console.log("PASS: adjacent author/abstract controls, independent panels, keyboard access, and safe abstract text");
  await page.getByLabel("Confocal microscopy", {exact: true}).check();
  await count(page, 1);
  await page.getByLabel("Electron microscopy", {exact: true}).check();
  await count(page, 2);
  assert.equal(await page.locator(".publication-tag").count(), 3);
  console.log("PASS: future multi-technology filtering and safe external text rendering");

  let failed = true;
  await page.unroute("**/assets/data/publications.json");
  await page.route("**/assets/data/publications.json", route => failed ? route.fulfill({status: 503, body: "Unavailable"}) : route.fulfill({json: catalogue}));
  await page.goto(`${base}/publications/`);
  await page.locator("[data-retry]").waitFor({state: "visible"});
  assert.match(await page.locator("[data-status]").textContent(), /couldn’t load/);
  failed = false;
  await page.locator("[data-retry]").click();
  await ready(page);
  await count(page, 20);
  assert.deepEqual(errors, []);
  console.log("PASS: failed request, retry recovery, and no browser exceptions");
} catch (error) {
  await page.screenshot({path: ".local/portal-testing/screenshots/failure.png", fullPage: false});
  throw error;
} finally {
  await browser.close();
}
