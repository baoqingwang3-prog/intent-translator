"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

function check(condition, message) {
  if (!condition) throw new Error(message);
}

async function waitForResult(page) {
  await page.locator("#result-content").waitFor({ state: "visible" });
  await page.locator("#compile-button:not([disabled])").waitFor({ state: "visible" });
}

async function runScenario(page, scenario) {
  await page.locator("#reset-session").click();
  await page.locator(`[data-example="${scenario.id}"]`).click();
  await waitForResult(page);
  check(!(await page.locator("#empty-result").isVisible()), `${scenario.id}: empty state still occupies the result pane`);

  const understanding = (await page.locator("#understanding-text").innerText()).trim();
  const selectedSkill = (await page.locator("#selected-skill").innerText()).trim();
  const permission = (await page.locator("#permission-state").innerText()).trim();
  const sourceMap = (await page.locator("#source-map").innerText()).trim();
  const comparisonVisible = await page.locator("#comparison-text").isVisible();
  const comparison = comparisonVisible
    ? (await page.locator("#comparison-text").innerText()).trim()
    : "";

  for (const expected of scenario.understanding_includes || []) {
    check(understanding.includes(expected), `${scenario.id}: understanding lost '${expected}'`);
  }
  if (scenario.selected_skill) {
    check(selectedSkill === scenario.selected_skill, `${scenario.id}: routed to '${selectedSkill}'`);
  }
  for (const expected of scenario.source_map_includes || []) {
    check(sourceMap.includes(expected), `${scenario.id}: source map lost '${expected}'`);
  }
  if (!scenario.may_execute) {
    check(!permission.includes("可执行"), `${scenario.id}: unsafe executable state '${permission}'`);
    check(!permission.includes("can run"), `${scenario.id}: unsafe executable state '${permission}'`);
  }
  if (scenario.requires_comparison) {
    check(comparisonVisible && comparison.length > 0, `${scenario.id}: correction comparison missing`);
  }

  return {
    id: scenario.id,
    passed: true,
    understanding,
    selected_skill: selectedSkill,
    permission,
    source_map: sourceMap,
    correction_comparison_visible: comparisonVisible,
  };
}

async function main() {
  const contract = JSON.parse(process.env.STUDIO_SMOKE_CONTRACT || "{}");
  const studioUrl = process.env.STUDIO_URL;
  const screenshotDir = process.env.STUDIO_SCREENSHOT_DIR || "";
  const browserExecutable = process.env.STUDIO_BROWSER_EXECUTABLE || "";
  check(studioUrl, "STUDIO_URL is required");

  const launchOptions = { headless: true };
  if (browserExecutable) launchOptions.executablePath = browserExecutable;
  const browser = await chromium.launch(launchOptions);
  const viewportReports = [];

  try {
    for (const viewport of contract.viewports || []) {
      const page = await browser.newPage({
        viewport: { width: viewport.width, height: viewport.height },
        locale: "zh-CN",
      });
      const pageErrors = [];
      page.on("pageerror", (error) => pageErrors.push(String(error)));
      page.on("console", (message) => {
        if (message.type() === "error") pageErrors.push(message.text());
      });

      await page.goto(studioUrl, { waitUntil: "networkidle" });
      await page.locator("#runtime-state").waitFor({ state: "visible" });
      await page.waitForFunction(() => !document.querySelector("#runtime-state").textContent.includes("正在连接"));

      const firstViewText = await page.locator("body").innerText();
      const localMode = (await page.locator("#local-mode-label").innerText()).trim();
      check(
        localMode.includes(contract.generic_first_run_label),
        `${viewport.name}: generic first-run memory status is missing`,
      );
      for (const term of contract.forbidden_first_view_terms || []) {
        check(!firstViewText.includes(term), `${viewport.name}: first view exposes '${term}'`);
      }

      const layout = await page.evaluate(() => ({
        document_width: document.documentElement.scrollWidth,
        viewport_width: window.innerWidth,
        body_width: document.body.scrollWidth,
      }));
      check(layout.document_width <= layout.viewport_width, `${viewport.name}: horizontal document overflow`);
      check(layout.body_width <= layout.viewport_width, `${viewport.name}: horizontal body overflow`);
      check(await page.locator("#intent-input").isVisible(), `${viewport.name}: natural-language input hidden`);
      check(await page.locator("#compile-button").isVisible(), `${viewport.name}: compile button hidden`);

      const scenarios = [];
      for (const scenario of contract.scenarios || []) {
        scenarios.push(await runScenario(page, scenario));
      }

      if (screenshotDir) {
        fs.mkdirSync(screenshotDir, { recursive: true });
        await page.screenshot({
          path: path.join(screenshotDir, `${viewport.name}.png`),
          fullPage: true,
        });
      }
      check(pageErrors.length === 0, `${viewport.name}: browser errors: ${pageErrors.join(" | ")}`);
      viewportReports.push({
        name: viewport.name,
        width: viewport.width,
        height: viewport.height,
        passed: true,
        horizontal_overflow: false,
        first_view_internal_terms: 0,
        scenarios,
      });
      await page.close();
    }
  } finally {
    await browser.close();
  }

  process.stdout.write(JSON.stringify({
    schema_version: 1,
    passed: true,
    browser: "chromium",
    viewports: viewportReports,
    metrics: {
      viewport_failures: 0,
      scenario_failures: 0,
      horizontal_overflow_count: 0,
      first_view_internal_term_count: 0,
      unsafe_execution_count: 0,
    },
  }));
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 2;
});
