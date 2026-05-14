const fs = require("fs");
const path = require("path");
const vm = require("vm");

const repoRoot = path.resolve(__dirname, "..");
const appScript = fs.readFileSync(path.join(repoRoot, "frontend", "app.js"), "utf8");
const fixtureDir = path.join(repoRoot, "tests", "fixtures", "report_data");

function loadReportFixture(fileName) {
  return JSON.parse(fs.readFileSync(path.join(fixtureDir, fileName), "utf8"));
}

function escapeHtmlText(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function createRenderContext() {
  const context = {
    console,
    window: {
      location: { protocol: "file:", hostname: "localhost", port: "" },
      addEventListener() {},
    },
    localStorage: {
      getItem() {
        return null;
      },
      setItem() {},
      removeItem() {},
    },
    document: {
      addEventListener() {},
      createElement() {
        return {
          _text: "",
          set textContent(value) {
            this._text = escapeHtmlText(value);
          },
          get innerHTML() {
            return this._text;
          },
        };
      },
    },
    setTimeout,
    clearTimeout,
    URL,
    Blob,
  };
  vm.createContext(context);
  vm.runInContext(appScript, context);
  return context;
}

function assertIncludes(html, fragments, label) {
  const missing = fragments.filter((fragment) => !html.includes(fragment));
  if (missing.length) {
    throw new Error(`${label} missing fragments: ${missing.join(", ")}`);
  }
}

const context = createRenderContext();

const fixtures = [
  ["agency_plan", loadReportFixture("agency_plan_desensitized.json")],
  ["free_planning", loadReportFixture("free_planning_desensitized.json")],
];

for (const [mode, reportData] of fixtures) {
  const html = context.renderAssistantText("自然语言正文不应驱动核心报告结构", {
    reportData,
  });
  assertIncludes(
    html,
    [
      'data-report-source="structured"',
      mode === "agency_plan" ? "旅行社顾问方案" : "自由规划",
      "脱敏演示",
      "预算置信度",
      "待核验清单",
      "风险提醒",
      "不承诺真实库存",
      "审批治理边界",
      "不代表真实支付",
      "路线联动",
      "顾问核验与下一步",
      "查看路线地图",
      "导出报告",
    ],
    mode
  );
}

console.log("frontend-report-renderer-ok");
