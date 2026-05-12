const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const repoRoot = path.resolve(__dirname, "..");
const frontendHtmlPath = path.join(repoRoot, "frontend", "zhixing.html");
const runtimeDir = path.join(repoRoot, ".runtime");
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
  return {
    version: "travel_report.v1",
    overview: {
      route_label: "北京到成都 4 日顾问方案",
      duration: "4 天",
      people: "2 人",
      travel_styles: ["美食慢游", "省心方案"],
    },
    transport: { summary: "高铁优先，正式购票前复核余票和票价。" },
    accommodation: { summary: "春熙路附近舒适型酒店，入住政策待核验。" },
    food_preferences: { summary: "川菜、小吃，保留低辣备选。" },
    itinerary: [
      {
        day_number: 1,
        title: "抵达成都",
        time_blocks: ["上午抵达成都东站", "下午宽窄巷子慢逛"],
        route: { summary: "成都东站 -> 宽窄巷子 -> 春熙路" },
        meals: ["宽窄巷子小吃"],
        plan_b: "雨天改室内茶馆和博物馆。",
        risk_notes: ["节假日排队较久"],
      },
      {
        day_number: 2,
        title: "市区慢游",
        time_blocks: ["上午人民公园", "下午太古里和锦里"],
        route: { summary: "人民公园 -> 太古里 -> 锦里" },
        meals: ["川菜正餐", "夜市小吃"],
        plan_b: "高温时减少户外停留。",
        risk_notes: ["热门餐厅需排队"],
      },
    ],
    map_routes: [
      {
        day_number: 1,
        summary: "成都东站 -> 宽窄巷子 -> 春熙路",
        route_points: ["成都东站", "宽窄巷子", "春熙路"],
      },
      {
        day_number: 2,
        summary: "人民公园 -> 太古里 -> 锦里",
        route_points: ["人民公园", "太古里", "锦里"],
      },
    ],
    agency_context: {
      mode: "agency_plan",
      summary: "按旅行社顾问方案交付，重点保留服务节点和预订前核验。",
      highlights: ["交通酒店出发前复核", "预算按可追溯、估算、待核验拆分"],
      mode_reason: "用户希望省心方案",
    },
    budget: {
      total: 5000,
      items: [
        {
          label: "交通",
          amount: 1800,
          basis: "按高铁往返规则估算",
          confidence: "待核验",
        },
        {
          label: "住宿",
          amount: 1600,
          basis: "按舒适型酒店两晚估算",
          confidence: "规则估算",
        },
      ],
    },
    budget_confidence: {
      level: "中",
      confirmed_items: ["人数 2 人，天数 4 天已确认。"],
      estimated_items: ["交通按高铁往返规则估算。"],
      verification_items: ["正式购票前复核余票和票价。"],
    },
    risks: ["出发前 24-48 小时复核天气和景区预约。"],
    tool_audit_summary: {
      readiness: "可交付，预订前需核验",
      used_sources: ["预算：已拆分为已确认、估算和待核验项目"],
      pending_checks: ["酒店入住政策和取消规则"],
      unsupported_actions: ["不承诺真实库存、真实锁价或真实预订成功。"],
      approval: {
        approval_id: "approval-demo",
        action: "generate_order_id",
        status: "none",
        pending: false,
        requires_approval: false,
        is_blocking: false,
        record_only: true,
        boundary:
          "当前订单号仅用于项目内报告串联，不代表真实支付、真实预订、真实锁价或履约成功。",
        unsupported_without_integration: ["不生成支付链接"],
      },
      events: [
        {
          name: "generate_order_tool",
          status: "success",
          elapsed_seconds: 0.3,
          evidence_type: "state_transition",
        },
      ],
    },
    evidence_bundle: {
      approval_governance: {
        approval_id: "approval-demo",
        action: "generate_order_id",
        status: "none",
        pending: false,
        requires_approval: false,
        is_blocking: false,
        record_only: true,
        boundary:
          "当前订单号仅用于项目内报告串联，不代表真实支付、真实预订、真实锁价或履约成功。",
        unsupported_without_integration: ["不生成支付链接"],
      },
    },
  };
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
              detail: "用于前端浏览器回归的记录型审批事件。",
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
              reason: "验证治理台审批记录渲染。",
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
    () => document.getElementById("readinessStatusPill")?.textContent?.trim() === "ready",
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
}

async function checkReportSurface(page) {
  await expectVisible(page, '[data-report-source="structured"]', "structured report");
  await expectVisible(page, ".travel-report-card", "report card");
  await expectVisible(page, '[data-report-action="export"]', "export report button");
  await expectVisible(page, '[data-report-action="map"]', "map preview entry");
  await expectVisible(page, ".travel-report-route-digest", "route digest");
  const cardCount = await page.locator(".travel-report-card").count();
  if (cardCount < 5) {
    throw new Error(`Expected at least 5 report cards, found ${cardCount}.`);
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
    await checkLayoutHealth(main.page, viewport);
    const screenshotPath = path.join(
      runtimeDir,
      `frontend-browser-regression-${viewport.name}.png`
    );
    await main.page.screenshot({ path: screenshotPath, fullPage: true });
    const viewportScreenshots = [screenshotPath];
    const reportScreenshotPath = path.join(
      runtimeDir,
      `frontend-browser-regression-${viewport.name}-report.png`
    );
    await main.page
      .locator('[data-report-source="structured"]')
      .screenshot({ path: reportScreenshotPath });
    viewportScreenshots.push(reportScreenshotPath);
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
