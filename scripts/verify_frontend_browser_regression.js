const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const repoRoot = path.resolve(__dirname, "..");
const frontendHtmlPath = path.join(repoRoot, "frontend", "zhixing.html");
const frontendStylesText = fs.readFileSync(path.join(repoRoot, "frontend", "styles.css"), "utf8");
const runtimeDir = path.join(repoRoot, ".runtime");
const reportFixturePath = path.join(
  repoRoot,
  "tests",
  "fixtures",
  "report_data",
  "agency_plan_desensitized.json"
);
const reportFixture = JSON.parse(fs.readFileSync(reportFixturePath, "utf8"));
const runningInCi = ["1", "true"].includes(String(process.env.CI || "").toLowerCase());
const strictMissingBrowser =
  process.env.ZHIXING_FRONTEND_BROWSER_STRICT === "1" || runningInCi;

function finishMissingDependency(message, details = []) {
  const header = strictMissingBrowser
    ? "frontend-browser-regression-dependency-missing"
    : "frontend-browser-regression-skip";
  const lines = [header, message, ...details];
  const text = lines.filter(Boolean).join("\n");
  if (strictMissingBrowser) {
    console.error(text);
    process.exit(1);
  }
  console.warn(text);
  process.exit(0);
}

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (error) {
    finishMissingDependency("Playwright is not installed in this checkout.", [
      "Install local browser test dependencies with: npm install",
      "Then install Chromium if needed with: npx playwright install chromium",
      "CI and ZHIXING_FRONTEND_BROWSER_STRICT=1 treat this as a failed gate.",
    ]);
  }
}

const playwright = loadPlaywright();

const viewports = [
  { name: "desktop", width: 1440, height: 1000, isMobile: false },
  { name: "mobile", width: 390, height: 900, isMobile: true },
];

const readinessPayload = {
  status: "ready",
  environment: "browser-regression",
  startup_complete: true,
  missing_required: [],
  degraded_optional: [],
  services: {
    checkpointer: { status: "ready", ready: true },
    store: { status: "ready", ready: true },
    mcp: { status: "ready", ready: true },
    session_lock: { status: "ready", ready: true },
    approval_governance: {
      status: "ready",
      ready: true,
      persistent: true,
      hitl_closed_loop: true,
    },
  },
};

const tinyPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
  "base64"
);

function sampleReportData() {
  return JSON.parse(JSON.stringify(reportFixture));
}

function responseJson(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

async function installNetworkStubs(context) {
  await context.route("https://cdn.bootcdn.net/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/css; charset=utf-8",
      body: ".fa,.fa-solid,.fa-regular{display:inline-block}.fa::before{content:''}",
    });
  });
  await context.route("https://images.unsplash.com/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: tinyPng,
    });
  });
  await context.addInitScript((payload) => {
    const originalFetch = window.fetch.bind(window);
    const json = (body, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json; charset=utf-8" },
      });

    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string" ? input : input?.url || "";
      const url = String(rawUrl);
      if (url.includes("/health/ready")) return json(payload.readiness);
      if (url.includes("/api/v1/conversations")) {
        return json({
          conversations: [
            {
              id: "browser-regression-trip",
              title: "浏览器回归行程",
              created_at: "2026-05-11T14:00:00Z",
              updated_at: "2026-05-11T14:30:00Z",
            },
          ],
        });
      }
      if (url.includes("/api/v1/approvals/browser-regression-approval/events")) {
        return json({
          events: [
            {
              event_type: "created",
              actor: "browser-regression",
              created_at: 1778508000,
              detail: "用于前端浏览器回归的记录型人工确认事件。",
            },
          ],
        });
      }
      if (url.includes("/api/v1/approvals?")) {
        return json({
          approvals: [
            {
              approval_id: "browser-regression-approval",
              action: "generate_order_id",
              label: "生成报告订单号",
              reason: "验证治理台人工确认记录渲染。",
              status: "none",
              requires_approval: false,
              created_at: 1778508000,
              expires_at: null,
            },
          ],
        });
      }
      if (url.endsWith("/api/v1/approvals")) {
        return json({
          approval_id: "browser-regression-approval",
          status: "none",
        });
      }
      if (url.includes("/api/v1/maps/preview")) {
        return json({
          points: [
            { name: "成都东站", lat: 30.629, lng: 104.141, kind: "route" },
            { name: "宽窄巷子", lat: 30.669, lng: 104.052, kind: "route" },
            { name: "春熙路", lat: 30.657, lng: 104.08, kind: "route" },
          ],
        });
      }
      return originalFetch(input, init);
    };
  }, { readiness: readinessPayload });
}

async function createPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.isMobile ? 2 : 1,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    acceptDownloads: true,
    reducedMotion: "reduce",
    locale: "zh-CN",
  });
  await installNetworkStubs(context);
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      consoleErrors.push(message.text());
    }
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  return { context, page, consoleErrors, pageErrors };
}

async function gotoFrontend(page) {
  await page.goto(pathToFileURL(frontendHtmlPath).href, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector("#readinessStatusPill", { state: "attached" });
  await page.waitForFunction(
    () =>
      ["ready", "就绪"].includes(
        document.getElementById("readinessStatusPill")?.textContent?.trim()
      ),
    null,
    { timeout: 5000 }
  );
}

async function expectVisible(page, selector, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 5000 });
  const box = await locator.boundingBox();
  if (!box || box.width < 4 || box.height < 4) {
    throw new Error(`${label} is visible but has an empty box.`);
  }
  return box;
}

async function expectText(page, selector, label, minLength = 2) {
  const text = (await page.locator(selector).first().textContent()) || "";
  if (text.trim().length < minLength) {
    throw new Error(`${label} has too little rendered text.`);
  }
}

async function expectContainsText(page, selector, fragments, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 5000 });
  const text = (await locator.textContent()) || "";
  const missing = fragments.filter((fragment) => !text.includes(fragment));
  if (missing.length) {
    throw new Error(`${label} missing text: ${missing.join(", ")}`);
  }
}

async function checkAuthSurface(page) {
  await expectVisible(page, "#introOverlay", "intro overlay");
  await page.locator("#introOverlay").click();
  await expectVisible(page, "#authOverlay", "auth overlay");
  await expectVisible(page, "#username", "username input");
  await expectVisible(page, "#password", "password input");
  await expectVisible(page, "#authBtn", "login button");
  await expectText(page, "#authServiceHint", "auth ready-check hint", 8);
}

async function seedLoggedInState(page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("token", "browser-regression-token");
    window.localStorage.setItem(
      "user",
      JSON.stringify({
        id: "browser-regression-user",
        username: "browser-regression",
        role: "admin",
      })
    );
  });
}

async function injectReport(page) {
  await page.evaluate((reportData) => {
    const container = document.getElementById("chatMessages");
    container.innerHTML = "";
    window.addMessage("assistant", "结构化报告浏览器回归", { reportData });
  }, sampleReportData());
  await page.waitForSelector('[data-report-source="structured"]', {
    state: "visible",
    timeout: 5000,
  });
}

async function checkMainSurface(page, viewport) {
  await expectVisible(page, ".sidebar", `${viewport.name} sidebar`);
  await expectVisible(page, ".chat-main", `${viewport.name} chat main`);
  await expectVisible(page, "#chatMessages", `${viewport.name} chat messages`);
  await expectVisible(page, ".chat-input-area", `${viewport.name} chat input area`);
  await expectVisible(page, "#governanceConsole", `${viewport.name} governance console`);
  await expectVisible(page, ".governance-section.readiness", `${viewport.name} ready check area`);
  await expectText(page, "#readinessSummary", "ready check summary", 20);
  await expectContainsText(
    page,
    "#readinessSummary",
    ["可用能力", "外部服务", "人工确认边界"],
    `${viewport.name} readiness human copy`
  );
  await page.locator("#governanceDetails").evaluate((node) => {
    node.open = true;
  });
  await page.evaluate(() => {
    window.rememberToolAuditEvent?.({
      tool: "query_transport_options",
      status: "degraded",
      semantic_status: "not_found",
      status_label: "未查到合适结果",
      status_explanation: "工具调用成功，但这次没有查到合适交通结果；不是系统崩溃。",
      elapsed_seconds: 0.24,
      retry_count: 0,
      evidence_type: "live_transport_query",
      error_type: "empty_transport_result",
      degraded: true,
    });
    window.rememberToolAuditEvent?.({
      tool: "query_hotel_options",
      status: "skipped",
      elapsed_seconds: 0.01,
      retry_count: 0,
      evidence_type: "live_hotel_search",
      error_type: "invalid_hotel_query_args",
      degraded: true,
    });
    window.rememberTurnObservability?.({
      observability: {
        turn_id: "turn_browser_regression_123456",
        status: "completed",
        step: "transport_planning",
        planning_mode: "agency_plan",
        degradation_status: "degraded",
        first_token_seconds: 0.42,
        total_elapsed_seconds: 2.4,
        tool_call_count: 2,
        tool_failure_count: 1,
        fallback_count: 1,
        estimated_total_tokens: 180,
      },
    });
  });
  await expectContainsText(
    page,
    "#governanceConsole",
    ["不会真实下单", "未来接入真实支付、短信通知或客户资料导出", "查询结果"],
    `${viewport.name} governance explanation copy`
  );
  await expectContainsText(
    page,
    "#toolAuditList",
    ["交通查询", "未查到合适结果", "不是系统崩溃", "住宿查询", "参数不足"],
    `${viewport.name} tool audit semantic copy`
  );
  await expectContainsText(
    page,
    "#turnObservabilityGrid",
    ["交通规划", "旅行社顾问方案", "追踪码"],
    `${viewport.name} turn observability labels`
  );
  const observabilityText = (await page.locator("#turnObservabilityGrid").textContent()) || "";
  if (observabilityText.includes("unknown")) {
    throw new Error(`${viewport.name} turn observability should not render unknown.`);
  }
}

async function checkReportSurface(page) {
  await expectVisible(page, '[data-report-source="structured"]', "structured report");
  await expectVisible(page, ".travel-report-card", "report card");
  await expectVisible(page, '[data-report-action="export"]', "export report button");
  await expectVisible(page, '[data-report-action="map"]', "map preview entry");
  await expectVisible(page, ".travel-report-route-digest", "route digest");
  await expectVisible(page, ".travel-report-card.budget", "budget card");
  await expectVisible(page, ".travel-report-card.warning", "risk card");
  await expectVisible(page, ".travel-report-card.confidence", "budget confidence card");
  await expectVisible(page, ".travel-report-card.handoff", "handoff verification card");
  await expectVisible(page, ".travel-report-card.governance", "governance card");
  await expectContainsText(
    page,
    '[data-report-source="structured"]',
    ["脱敏演示", "旅行社顾问方案", "导出报告", "查看路线地图"],
    "structured report shell"
  );
  await expectContainsText(
    page,
    ".travel-report-card.budget",
    ["交通", "住宿", "规则估算", "待核验"],
    "budget card"
  );
  await expectContainsText(
    page,
    ".travel-report-card.warning",
    ["风险提醒", "顾问待核验", "出发前 24-48 小时"],
    "risk card"
  );
  await expectContainsText(
    page,
    ".travel-report-card.confidence",
    ["预算置信度", "已确认 / 可追溯", "规则估算", "待核验"],
    "budget confidence card"
  );
  await expectContainsText(
    page,
    ".travel-report-card.handoff",
    ["待核验清单", "不支持承诺", "酒店入住政策"],
    "handoff verification card"
  );
  await expectContainsText(
    page,
    ".travel-report-card.governance",
    ["人工确认边界", "不代表真实支付", "不生成支付链接"],
    "governance card"
  );
  await expectContainsText(
    page,
    ".travel-report-route-digest",
    ["景点地图", "成都东站", "都江堰景区"],
    "route digest"
  );
  const cardCount = await page.locator(".travel-report-card").count();
  if (cardCount < 5) {
    throw new Error(`Expected at least 5 report cards, found ${cardCount}.`);
  }
}

async function checkMapPreviewEntry(page) {
  await page.locator('[data-report-action="map"]').click();
  await page
    .locator("#toast.show", { hasText: "已定位到路线地图" })
    .waitFor({ state: "visible", timeout: 5000 });
  await expectVisible(page, ".travel-report-route-digest", "map digest after map action");
}

async function checkReportExport(page, viewport) {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator('[data-report-action="export"]').click(),
  ]);
  const suggestedFilename = download.suggestedFilename();
  if (!suggestedFilename.endsWith(".html") || !suggestedFilename.includes("知行")) {
    throw new Error(`${viewport.name} export filename looks wrong: ${suggestedFilename}`);
  }
  const downloadedPath = await download.path();
  if (!downloadedPath) {
    throw new Error(`${viewport.name} export did not produce a readable download.`);
  }
  const html = fs.readFileSync(downloadedPath, "utf8");
  const requiredFragments = [
    "知行 ZhiXing 旅游报告",
    'data-report-source="structured"',
    "北京到成都 4 日顾问方案（脱敏演示）",
    "预算置信度",
    "待核验清单",
    "人工确认边界",
    "不代表真实支付",
    "景点地图",
  ];
  const missing = requiredFragments.filter((fragment) => !html.includes(fragment));
  if (missing.length) {
    throw new Error(`${viewport.name} export missing fragments: ${missing.join(", ")}`);
  }
  if (/<button[\s>]/i.test(html)) {
    throw new Error(`${viewport.name} export should not keep interactive buttons.`);
  }
  if (
    !html.includes(".message.assistant .message-text .travel-report") &&
    !html.includes("styles.css")
  ) {
    throw new Error(`${viewport.name} export did not include inline styles or stylesheet fallback.`);
  }
  await download.delete();
}

async function buildReportEvidenceHtml(page) {
  const reportHtml = await page.evaluate(() => {
    const report = document.querySelector('[data-report-source="structured"]');
    if (!report) throw new Error("structured report missing for screenshot");
    return report.outerHTML;
  });
  return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
      ${frontendStylesText}
      body {
        margin: 0;
        min-height: 100vh;
        padding: 24px;
        overflow: visible;
        background: #f5f2eb;
      }
      .report-evidence-shell {
        max-width: 1120px;
        margin: 0 auto;
      }
      .message.assistant .message-text {
        max-width: none;
      }
    </style>
  </head>
  <body>
    <main class="report-evidence-shell">
      <section class="message assistant">
        <div class="message-text">${reportHtml}</div>
      </section>
    </main>
  </body>
</html>`;
}

async function captureReportScreenshot(browser, page, viewport, screenshotPath) {
  const html = await buildReportEvidenceHtml(page);
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.isMobile ? 2 : 1,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    reducedMotion: "reduce",
    locale: "zh-CN",
  });
  await context.route("https://cdn.bootcdn.net/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/css; charset=utf-8",
      body: ".fa,.fa-solid,.fa-regular{display:inline-block}.fa::before{content:''}",
    });
  });
  const evidencePage = await context.newPage();
  try {
    await evidencePage.setContent(html, { waitUntil: "domcontentloaded" });
    await expectVisible(evidencePage, '[data-report-source="structured"]', "report screenshot");
    await evidencePage.screenshot({ path: screenshotPath, fullPage: true });
  } finally {
    await context.close();
  }
}

function intersectionArea(a, b) {
  const left = Math.max(a.left, b.left);
  const right = Math.min(a.right, b.right);
  const top = Math.max(a.top, b.top);
  const bottom = Math.min(a.bottom, b.bottom);
  return Math.max(0, right - left) * Math.max(0, bottom - top);
}

async function checkLayoutHealth(page, viewport) {
  const layout = await page.evaluate(() => {
    const selectors = [
      ".sidebar",
      ".chat-main",
      "#governanceConsole",
      ".service-banner",
      "#chatMessages",
      '[data-report-source="structured"]',
      ".travel-report-grid",
      ".travel-report-card.budget",
      ".travel-report-card.warning",
      ".travel-report-card.confidence",
      ".travel-report-card.handoff",
      ".travel-report-card.governance",
      ".travel-report-actions",
      ".travel-report-route-digest",
    ];
    return selectors.map((selector) => {
      const element = document.querySelector(selector);
      if (!element) return { selector, missing: true };
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return {
        selector,
        textLength: (element.textContent || "").trim().length,
        display: style.display,
        visibility: style.visibility,
        width: rect.width,
        height: rect.height,
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
      };
    });
  });

  const bySelector = new Map(layout.map((item) => [item.selector, item]));
  for (const selector of [
    ".sidebar",
    ".chat-main",
    "#governanceConsole",
    "#chatMessages",
    '[data-report-source="structured"]',
    ".travel-report-grid",
  ]) {
    const item = bySelector.get(selector);
    if (!item || item.missing) throw new Error(`${selector} was not rendered.`);
    if (item.display === "none" || item.visibility === "hidden") {
      throw new Error(`${selector} is hidden.`);
    }
    if (item.width < 120 || item.height < 80) {
      throw new Error(
        `${selector} appears blank or collapsed: ${Math.round(item.width)}x${Math.round(item.height)}.`
      );
    }
    if (item.textLength < 20) {
      throw new Error(`${selector} appears empty.`);
    }
  }

  const topLevelSelectors = [".sidebar", ".chat-main", "#governanceConsole"];
  const topLevelBoxes = topLevelSelectors.map((selector) => bySelector.get(selector));
  for (let index = 0; index < topLevelBoxes.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < topLevelBoxes.length; otherIndex += 1) {
      const first = topLevelBoxes[index];
      const second = topLevelBoxes[otherIndex];
      const area = intersectionArea(first, second);
      const limit = Math.min(first.width * first.height, second.width * second.height) * 0.02;
      if (area > Math.max(limit, 64)) {
        throw new Error(
          `${viewport.name} layout overlap detected between ${first.selector} and ${second.selector}.`
        );
      }
    }
  }
}

function assertNoConsoleErrors(viewport, consoleErrors, pageErrors) {
  if (consoleErrors.length || pageErrors.length) {
    const details = [...consoleErrors, ...pageErrors].join("\n");
    throw new Error(`${viewport.name} console/page errors:\n${details}`);
  }
}

async function runViewport(browser, viewport) {
  const auth = await createPage(browser, viewport);
  try {
    await gotoFrontend(auth.page);
    await checkAuthSurface(auth.page);
    assertNoConsoleErrors(viewport, auth.consoleErrors, auth.pageErrors);
  } finally {
    await auth.context.close();
  }

  const main = await createPage(browser, viewport);
  try {
    await seedLoggedInState(main.page);
    await gotoFrontend(main.page);
    await checkMainSurface(main.page, viewport);
    await injectReport(main.page);
    await checkReportSurface(main.page);
    const viewportScreenshots = [];
    const reportScreenshotPath = path.join(
      runtimeDir,
      `frontend-browser-regression-${viewport.name}-report.png`
    );
    await captureReportScreenshot(browser, main.page, viewport, reportScreenshotPath);
    viewportScreenshots.push(reportScreenshotPath);
    await checkMapPreviewEntry(main.page);
    await checkReportExport(main.page, viewport);
    await checkLayoutHealth(main.page, viewport);
    const screenshotPath = path.join(
      runtimeDir,
      `frontend-browser-regression-${viewport.name}.png`
    );
    await main.page.screenshot({ path: screenshotPath, fullPage: true });
    viewportScreenshots.unshift(screenshotPath);
    if (viewport.isMobile) {
      await main.page.locator("#governanceConsole").scrollIntoViewIfNeeded();
      const governanceScreenshotPath = path.join(
        runtimeDir,
        "frontend-browser-regression-mobile-governance.png"
      );
      await main.page.screenshot({ path: governanceScreenshotPath, fullPage: false });
      viewportScreenshots.push(governanceScreenshotPath);
    }
    assertNoConsoleErrors(viewport, main.consoleErrors, main.pageErrors);
    return viewportScreenshots;
  } finally {
    await main.context.close();
  }
}

async function main() {
  fs.mkdirSync(runtimeDir, { recursive: true });
  let browser;
  try {
    browser = await playwright.chromium.launch({ headless: true });
  } catch (error) {
    const message = String(error?.message || error);
    if (
      message.includes("Executable doesn't exist") ||
      message.includes("Please run the following command")
    ) {
      finishMissingDependency("Chromium for Playwright is not installed.", [
        "Install it with: npx playwright install chromium",
        "CI and ZHIXING_FRONTEND_BROWSER_STRICT=1 treat this as a failed gate.",
      ]);
    }
    throw error;
  }

  const screenshots = [];
  try {
    for (const viewport of viewports) {
      screenshots.push(...(await runViewport(browser, viewport)));
    }
  } finally {
    await browser.close();
  }

  console.log("frontend-browser-regression-ok");
  console.log(`viewports=${viewports.map((item) => `${item.width}x${item.height}`).join(",")}`);
  console.log(`screenshots=${screenshots.join(",")}`);
}

main().catch((error) => {
  console.error("frontend-browser-regression-failed");
  console.error(error);
  process.exit(1);
});
