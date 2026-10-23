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
  const moduleURL = await page.locator('script[type="module"]').getAttribute('src');
  assert.ok(new URL(moduleURL, base).searchParams.get('v'), 'Module URL must change when a new build is served');
  assert.equal(await page.locator("[name=year]").inputValue(), "");
  assert.equal(await page.locator("[name=sort]").inputValue(), "newest");
  assert.match(await page.locator("[data-status]").textContent(), new RegExp(`20 of ${catalogue.publications.length}\\b`));
  assert.equal(await page.locator(".publication-year").first().textContent(), String(Math.max(...catalogue.publications.map(record => record.year))));
  const assignedTags = [...new Set(catalogue.publications.flatMap(record => record.technologies || []))].sort();
  assert.equal(await page.locator('[name=technology]').count(), assignedTags.length);
  assert.equal(await page.locator('[data-technology-value]').textContent(), 'All technologies');
  assert.equal(await page.locator('nav a[href="/publications/"]').getAttribute("class"), "active");
  assert.equal(await page.locator(".project-logo").evaluate(img => img.complete && img.naturalWidth > 0), true);
  await page.screenshot({path: ".local/portal-testing/screenshots/desktop.png", fullPage: false});
  console.log("PASS: all years/newest default, initial results, navigation, and technology dropdown");

  if (assignedTags.length) {
    const firstTag = assignedTags[0];
    await page.locator('[data-technology-picker] summary').click();
    await page.locator(`[name=technology][value="${firstTag}"]`).check();
    const firstMatches = catalogue.publications.filter(record => record.technologies?.includes(firstTag));
    await count(page, Math.min(20, firstMatches.length));
    assert.ok(new URL(page.url()).searchParams.getAll('technology').includes(firstTag));
    await page.reload();
    await ready(page);
    assert.equal(await page.locator(`[name=technology][value="${firstTag}"]`).isChecked(), true);
    if (assignedTags.length > 1) {
      const secondTag = assignedTags[1];
      await page.locator('[data-technology-picker] summary').focus();
      await page.keyboard.press('Enter');
      await page.locator(`[name=technology][value="${secondTag}"]`).check();
      const matches = catalogue.publications.filter(record => record.technologies?.some(tag => [firstTag, secondTag].includes(tag)));
      await count(page, Math.min(20, matches.length));
      assert.equal(await page.locator('[data-technology-value]').textContent(), '2 technologies selected');
      await page.locator(`[name=technology][value="${secondTag}"]`).press('Escape');
      assert.equal(await page.locator('[data-technology-picker]').getAttribute('open'), null);
      assert.equal(await page.locator('[data-technology-picker] summary').evaluate(node => node === document.activeElement), true);
      await page.locator('[name=year]').selectOption('2026');
      await page.locator('[name=cci_involvement]').selectOption('service-provision');
      await count(page, Math.min(20, matches.filter(record => record.year === 2026 && record.cci_involvement === 'service-provision').length));
    }
    await page.locator('[data-clear]').click();
    assert.equal(await page.locator('[name=technology]:checked').count(), 0);
    assert.equal(await page.locator('[data-technology-value]').textContent(), 'All technologies');
    assert.equal(new URL(page.url()).search, '');
    console.log('PASS: real technology tags, multi-choice dropdown, URL restoration, combined filters, keyboard and reset');
  }

  const collaborationCount = catalogue.publications.filter(record => record.cci_involvement === "scientific-collaboration").length;
  const serviceCount = catalogue.publications.filter(record => record.cci_involvement === "service-provision").length;
  assert.equal(await page.locator('[name=cci_involvement]').inputValue(), "");
  assert.equal(await page.locator('.publication-involvement').count(), 20);
  await page.locator('[name=cci_involvement]').selectOption('scientific-collaboration');
  await count(page, Math.min(20, collaborationCount));
  assert.equal(await page.locator('[data-involvement="scientific-collaboration"]').count(), Math.min(20, collaborationCount));
  assert.equal(new URL(page.url()).searchParams.get('involvement'), 'scientific-collaboration');
  assert.equal(await page.locator('[data-clear]').isEnabled(), true);
  await page.reload();
  await ready(page);
  assert.equal(await page.locator('[name=cci_involvement]').inputValue(), 'scientific-collaboration');
  await count(page, Math.min(20, collaborationCount));
  await page.locator('[name=cci_involvement]').selectOption('service-provision');
  await count(page, Math.min(20, serviceCount));
  assert.equal(await page.locator('[data-involvement="service-provision"]').count(), Math.min(20, serviceCount));
  assert.match(await page.locator('[data-status]').textContent(), new RegExp(`of ${serviceCount}`));
  await page.locator('[data-more]').click();
  await count(page, Math.min(40, serviceCount));
  const combinedYear = catalogue.publications.find(record => record.cci_involvement === 'scientific-collaboration').year;
  await page.locator('[name=cci_involvement]').selectOption('scientific-collaboration');
  await page.locator('[name=year]').selectOption(String(combinedYear));
  const combinedCount = catalogue.publications.filter(record => record.cci_involvement === 'scientific-collaboration' && record.year === combinedYear).length;
  await count(page, Math.min(20, combinedCount));
  await page.locator('[name=q]').fill('zzzz-no-synthetic-match-zzzz');
  await count(page, 0);
  assert.equal(await page.locator('[data-empty]').isVisible(), true);
  await page.locator('[data-clear]').click();
  assert.equal(await page.locator('[name=cci_involvement]').inputValue(), '');
  assert.equal(new URL(page.url()).search, '');
  await page.goto(`${base}/publications/?involvement=unknown`);
  await ready(page);
  await count(page, 20);
  assert.equal(await page.locator('[name=cci_involvement]').inputValue(), '');
  await page.goto(`${base}/publications/`);
  await ready(page);
  console.log('PASS: involvement badges, both filters, combined search/year, pagination, URL restoration and reset');

  await page.locator("[data-more]").click();
  await count(page, 40);
  assert.match(await page.locator("[data-status]").textContent(), new RegExp(`40 of ${catalogue.publications.length}\\b`));
  assert.equal(await page.evaluate(() => document.activeElement === document.querySelectorAll(".publication-card h2 a")[20]), true);
  await page.locator("[name=year]").selectOption("2025");
  await count(page, 20);
  assert.match(await page.locator("[data-status]").textContent(), new RegExp(`of ${catalogue.publications.filter(record => record.year === 2025).length}\\b`));
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
  assert.equal(await page.locator(".publication-year").first().textContent(), String(Math.min(...catalogue.publications.map(record => record.year))));
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
  const pmidOnly = catalogue.publications.find(record => record.pmid && !record.doi);
  if (pmidOnly) {
    await page.locator('[name=q]').fill(`PMID:${pmidOnly.pmid}`);
    await count(page, 1);
    assert.equal(await page.getByRole('link', {name: `PubMed: ${pmidOnly.pmid}`, exact: true}).getAttribute('href'),
      `https://pubmed.ncbi.nlm.nih.gov/${pmidOnly.pmid}/`);
    assert.equal(await page.locator('.publication-card h2').textContent(), pmidOnly.title);
    await page.locator('[data-clear]').click();
    console.log('PASS: imported PMID-only publication search and PubMed reference');
  }
  for (const width of [375, 561, 640, 768, 1024]) {
    await page.setViewportSize({width, height: 900});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Overflow at ${width}px`);
    await page.locator('[data-technology-picker] summary').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, `Open technology menu overflow at ${width}px`);
    await page.locator('[data-technology-picker] summary').press('Escape');
  }
  await page.setViewportSize({width: 375, height: 812});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path: ".local/portal-testing/screenshots/mobile.png", fullPage: false});
  await page.locator('.publications-controls').screenshot({path: '.local/portal-testing/screenshots/mobile-controls.png'});
  await page.locator('.publication-card').first().screenshot({path: '.local/portal-testing/screenshots/mobile-card.png'});
  await page.locator('[data-technology-picker] summary').click();
  await page.locator('[data-technology-picker]').scrollIntoViewIfNeeded();
  await page.screenshot({path: '.local/portal-testing/screenshots/mobile-technologies.png'});
  await page.locator('[data-technology-picker] summary').press('Escape');
  console.log("PASS: responsive layout at 375, 768, and 1024 pixels");

  const fixture = structuredClone(catalogue);
  fixture.publications = fixture.publications.slice(0, 2);
  fixture.publications[0].title = "Synthetic fixture <img src=x onerror=window.__injected=1>";
  fixture.publications[0].technologies = ["confocal", "light_sheet"];
  fixture.publications[0].authors = ["Synthetic A", "Synthetic B", "Synthetic C", "Synthetic D", "Synthetic E", "Synthetic F"];
  fixture.publications[0].abstract = {text: "Synthetic abstract first paragraph.\n\nSecond paragraph <script>window.__injected=1</script>.",
    source_url: "https://doi.org/10.1234/synthetic", license_url: "https://creativecommons.org/licenses/by/4.0/"};
  fixture.publications[1].title = "Synthetic second fixture";
  fixture.publications[1].doi = null;
  fixture.publications[1].pmid = "12345678";
  fixture.publications[1].publication_url = "https://pubmed.ncbi.nlm.nih.gov/12345678/";
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
  assert.equal(await page.getByRole('link', {name: 'PubMed: 12345678', exact: true}).getAttribute('href'),
    'https://pubmed.ncbi.nlm.nih.gov/12345678/');
  await page.locator('[name=q]').fill('PMID:12345678');
  await count(page, 1);
  assert.equal(await page.locator('.publication-card h2').textContent(), 'Synthetic second fixture');
  await page.locator('[data-clear]').click();
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
  await page.locator('[data-technology-picker] summary').click();
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
