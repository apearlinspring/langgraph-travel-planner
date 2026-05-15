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
      "人工确认边界",
      "不代表真实支付",
      "路线联动",
      "顾问核验与下一步",
      "查看路线地图",
      "导出报告",
    ],
    mode
  );
}

const feedbackMarkdown = `
行程摘要：北京 → 南京，4天3晚，当前方案先按轻松城市慢游整理。

### Day 1 | 抵达 + 老门东慢逛
-
下午：高铁抵达南京，酒店放行李。
晚上：老门东街区散步，吃鸭血粉丝汤和小笼。

### 住哪里？
推荐区域：老门东 / 夫子庙周边，出门就是小吃街和秦淮河夜景，步行可达多个景点。

### Day 2 | 室内文化日
-
上午：南京博物院。
下午：总统府。

### Day 4 | 查漏补缺 + 返程
-
上午：睡到自然醒，去颐和路公馆区散步。
下午：高铁返京。

### 预算粗估（每人）
| 项目 | 费用 |
| --- | --- |
| 北京-南京高铁往返 | ~1100元 |
| 住宿3晚 | ~900元 |
| 餐饮4天 | ~800-1000元 |
| 门票+游船+交通 | ~400-500元 |
| 合计 | ~3200-3500元 |

### 端午提醒
1. 天气：出发前 24-48 小时再核验。
2. 人流：博物馆和夜游建议提前预约。
`;

const feedbackHtml = context.renderAssistantText(feedbackMarkdown);
assertIncludes(
  feedbackHtml,
  [
    "Day 1",
    "Day 4",
    "预算参考",
    "travel-budget-layout",
    "出发前确认",
    "看周边",
    "住宿周边",
    "主要景点",
    "热闹商业街",
    "美食小吃",
  ],
  "feedback-polish"
);
if (feedbackHtml.includes("预算粗估（每人）")) {
  throw new Error("feedback-polish should not keep per-person budget title copy.");
}
if (/class="travel-card transport"[\s\S]{0,420}地图定位/.test(feedbackHtml)) {
  throw new Error("feedback-polish should not render map buttons on transport cards.");
}
if (/(^|>)-(<|$)/.test(feedbackHtml) || feedbackHtml.includes("<br>-<br>")) {
  throw new Error("feedback-polish should remove standalone dash separators.");
}

console.log("frontend-report-renderer-ok");
