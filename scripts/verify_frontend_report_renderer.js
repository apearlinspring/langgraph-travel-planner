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

function assertExcludes(html, fragments, label) {
  const leaked = fragments.filter((fragment) => html.includes(fragment));
  if (leaked.length) {
    throw new Error(`${label} leaked fragments: ${leaked.join(", ")}`);
  }
}

function countOccurrences(text, fragment) {
  return String(text || "").split(fragment).length - 1;
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
      mode === "agency_plan" ? "省心方案" : "个性化旅游规划",
      "脱敏演示",
      "风险提醒",
      "路线预览",
      "轻量地图预览",
      "分日路线",
      "路线参考",
      "全屏",
      "商业街区",
      "服务/预留",
      "travel-report-budget-table",
      "查看路线地图",
      "导出报告",
    ],
    mode
  );
  assertExcludes(
    html,
    ["travel-report-day-map", "放大查看地图", ">放大<", "分日状态", "待继续比较交通方式", "待继续补住宿区域"],
    `${mode}-day-map-suppressed`
  );
  assertExcludes(
    html,
    ["预算置信度", "交付清单", "顾问核验与下一步", "治理边界", "人工确认边界", "不承诺真实库存"],
    `${mode}-customer-view`
  );
  if (html.includes("人均参考") || html.includes("预算粗估（每人）")) {
    throw new Error(`${mode} should not default to per-person budget copy.`);
  }
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
    "路线说明",
    "展开分日路线",
    'data-map-action="toggle-tools"',
    'data-map-action="toggle-sidebar"',
    "journey-map-tools-collapsed",
    "journey-map-sidebar-collapsed",
  ],
  "feedback-polish"
);
if (feedbackHtml.includes("预算粗估（每人）")) {
  throw new Error("feedback-polish should not keep per-person budget title copy.");
}
if (/class="travel-card transport"[\s\S]{0,420}地图定位/.test(feedbackHtml)) {
  throw new Error("feedback-polish should not render map buttons on transport cards.");
}
if (/住宿周边|热闹商业街|美食小吃/.test(feedbackHtml)) {
  throw new Error("feedback-polish should keep route preview sidebar focused on day routes only.");
}
if (/(^|>)-(<|$)/.test(feedbackHtml) || feedbackHtml.includes("<br>-<br>")) {
  throw new Error("feedback-polish should remove standalone dash separators.");
}

const mixedBudgetHtml = context.renderAssistantText(`
### 行程概览
西藏 7 天路线先按拉萨适应 + 林芝舒缓方向整理。

### 预算边界
下面先按当前信息做估算，正式出发前再核验。
| 项目 | 预算区间 | 说明 |
| --- | --- | --- |
| 当地交通 | 1500-2000元 | 包车和市内接送 |
| 住宿 | 2500-3000元 | 6晚舒适酒店 |
| 合计 | 5800-7600元 | 不含大交通 |
`);
assertIncludes(
  mixedBudgetHtml,
  ["travel-budget-layout", "当前估算", "当地交通", "5800-7600元"],
  "mixed-budget-table"
);
if (mixedBudgetHtml.includes("| 项目 |") || mixedBudgetHtml.includes("| --- |")) {
  throw new Error("mixed-budget-table should render Markdown tables visually.");
}

const duplicatedBudgetHtml = context.renderAssistantText(`
# 杭州 5 天省心方案

### 预算拆分与依据
| 项目 | 参考 |
| --- | --- |
| 门票 | 45元 |
| 门票 | 80元 |

### 预算拆分与依据
| 项目 | 参考 |
| --- | --- |
| 门票 | 45元 |
| 门票 | 80元 |

### 预算拆分与依据
| 项目 | 参考 |
| --- | --- |
| 门票 | 45元 |
| 门票 | 80元 |
`);
const duplicatedBudgetCardCount =
  countOccurrences(duplicatedBudgetHtml, "travel-budget-layout") +
  countOccurrences(duplicatedBudgetHtml, "message-table-wrap");
if (duplicatedBudgetCardCount !== 1) {
  throw new Error("duplicated-budget-card should keep a single budget card.");
}

const prematureBudgetHtml = context.renderAssistantText(`
### 出发地
西安 → 杭州，4天3晚，2位成人。

### 预算参考
| 项目 | 费用 |
| --- | --- |
| 美食 | 600-700元 |

### 住宿商圈
与星级档次参考，核心景点门票和动线安排后续补齐。
`);
assertExcludes(
  prematureBudgetHtml,
  ["travel-budget-layout", "当前估算", "600-700元"],
  "premature-budget-card"
);

const decisionHtml = context.renderAssistantText(`
### 想跟你确认一下
这条“拉萨适应 + 林芝舒缓”的路线方向你觉得合适吗？还是你想看看其他备选？

### 预算参考
| 项目 | 费用 |
| --- | --- |
| 住宿 | 2500元 |
| 合计 | 4500元 |
`);
assertIncludes(decisionHtml, ['class="travel-card next', "想跟你确认一下"], "decision-card");

const reportNextActionHtml = context.renderAssistantText(`
# 杭州 4 天旅游规划报告

### 行程概览
杭州 4 天省心方案草案已整理，路线先按西湖、灵隐和老城慢逛展开。

### 交通口径
西安到杭州优先高铁或航班，正式出发前二次核验。

### 费用说明
总预算约 5000 元/人，正式票价、酒店和门票出发前再核验。

### 下一步
* 请评价本方案草案：
* 满意：确认可行后，我将生成详细版旅游规划报告。
* 想改哪里：例如想换酒店商圈、增加亲子点或压缩预算。
`);
assertIncludes(
  reportNextActionHtml,
  ["travel-report-next-action", "需要你确认", "满意：确认可行后"],
  "report-next-action-bottom"
);
if (
  reportNextActionHtml.indexOf("travel-report-next-action") <
  reportNextActionHtml.indexOf("travel-report-grid")
) {
  throw new Error("report-next-action-bottom should render after the main report grid.");
}
assertExcludes(
  reportNextActionHtml,
  ['travel-report-card next', "<br>* 请评价"],
  "report-next-action-not-grid-card"
);

const embeddedNextActionHtml = context.renderAssistantText(`
# 杭州 5 天旅游规划报告

### 行程概览
下一步
请您评价这版方案：
- 如果满意，我将按此结构生成最终可导出的旅行规划报告。
- 如果想调整，请告诉我具体想改哪里。

### 天气与风险提醒
出发前 24-48 小时重新核验天气和预约状态。
`);
assertIncludes(
  embeddedNextActionHtml,
  ["travel-report-next-action", "请您评价这版方案"],
  "embedded-next-action-bottom"
);
assertExcludes(
  embeddedNextActionHtml,
  ['travel-report-card next', "行程概览</h4>"],
  "embedded-next-action-not-grid"
);

const sparseRouteReportData = JSON.parse(JSON.stringify(fixtures[0][1]));
sparseRouteReportData.overview.duration = "5 天 4 晚";
sparseRouteReportData.overview.route_label = "西安 → 杭州 5 天";
sparseRouteReportData.itinerary = [
  {
    day_number: 1,
    title: "抵达杭州与西湖初见",
    time_blocks: ["下午抵达杭州东站", "傍晚西湖湖滨散步"],
    route: { summary: "杭州东站 -> 湖滨银泰 -> 西湖" },
  },
  {
    day_number: 2,
    title: "灵隐与西湖经典",
    time_blocks: ["上午灵隐寺", "下午曲院风荷", "傍晚北山街"],
    route: { summary: "灵隐寺 -> 曲院风荷 -> 北山街" },
  },
  {
    day_number: 3,
    title: "西溪湿地慢游",
    time_blocks: ["上午西溪湿地", "下午河坊街", "晚上南宋御街"],
    route: { summary: "西溪湿地 -> 河坊街 -> 南宋御街" },
  },
  {
    day_number: 4,
    title: "龙井与九溪",
    time_blocks: ["上午龙井村", "下午九溪烟树"],
    route: { summary: "龙井村 -> 九溪烟树" },
  },
  {
    day_number: 5,
    title: "返程前补漏",
    time_blocks: ["上午武林广场", "下午杭州东站返程"],
    route: { summary: "武林广场 -> 杭州东站" },
  },
];
sparseRouteReportData.map_routes = sparseRouteReportData.map_routes.filter((route) =>
  [1, 4, 5].includes(Number(route.day_number))
);
sparseRouteReportData.route_map.days = sparseRouteReportData.route_map.days.filter((day) =>
  [1, 4, 5].includes(Number(day.day_number))
);
const sparseRouteHtml = context.renderAssistantText("", {
  reportData: sparseRouteReportData,
});
assertIncludes(
  sparseRouteHtml,
  [
    "report-day-1",
    "report-day-2",
    "report-day-3",
    "report-day-4",
    "report-day-5",
    "灵隐寺",
    "西溪湿地",
  ],
  "sparse-route-days"
);
assertExcludes(
  sparseRouteHtml,
  ["journey-map-bottom-drawer"],
  "sparse-route-no-bottom-drawer"
);

const bareDailyMarkerHtml = context.renderAssistantText(`
# 杭州 5 天旅游规划报告

行程概览：西安 → 杭州，5天4晚。

【每日安排】

### Day 1 | 抵达杭州
下午：杭州东站 → 湖滨银泰 → 西湖。

### Day 2 | 灵隐慢游
上午：灵隐寺。下午：曲院风荷。
`);
assertExcludes(
  bareDailyMarkerHtml,
  ["【每日安排】"],
  "bare-daily-marker-hidden"
);

const visualJourneyData = {
  version: "journey_plan.v1",
  overview: {
    title: "西藏7天经典之旅",
    destination: "西藏",
    date_range: "2026-05-27至2026-06-02",
    duration_days: 7,
    route_label: "林芝进拉萨出",
    summary: "林芝进拉萨出，低海拔渐进适应高反。",
  },
  days: [
    {
      day_number: 1,
      date: "2026-05-27",
      weekday: "周三",
      title: "林芝初抵·巴松措",
      summary: "林芝 · 巴松措",
      pois: [
        {
          id: "d1-p1",
          name: "林芝",
          city: "林芝",
          type_label: "城市节点",
          suggested_time: "抵达后",
          duration_minutes: 60,
          description: "低海拔适应点。",
          estimated_cost: "待核验",
          map_verified: true,
          address: "林芝市巴宜区",
          amap_type: "城市节点",
        },
        {
          id: "d1-p2",
          name: "巴松措",
          city: "林芝",
          type_label: "景点",
          suggested_time: "下午",
          duration_minutes: 180,
          description: "湖泊、雪山和寺庙组合。",
          estimated_cost: "待核验",
          coordinate_estimated: true,
          verification_note: "暂按同日已核验地点附近落点展示。",
        },
      ],
    },
  ],
  pois: [
    {
      id: "d1-p1",
      name: "林芝",
      city: "林芝",
      type_label: "城市节点",
      suggested_time: "抵达后",
      duration_minutes: 60,
      description: "低海拔适应点。",
      estimated_cost: "待核验",
      map_verified: true,
      address: "林芝市巴宜区",
      amap_type: "城市节点",
    },
    {
      id: "d1-p2",
      name: "巴松措",
      city: "林芝",
      type_label: "景点",
      suggested_time: "下午",
      duration_minutes: 180,
      description: "湖泊、雪山和寺庙组合。",
      estimated_cost: "待核验",
      coordinate_estimated: true,
      verification_note: "暂按同日已核验地点附近落点展示。",
    },
  ],
  pending_checks: ["地图路段距离和时长以高德实时路线为准。"],
};
const visualJourneyHtml = context.renderAssistantText("可视化旅程草案已整理完成。", {
  journeyData: visualJourneyData,
  planningTrace: [
    {
      phase: "search",
      status: "completed",
      title: "公开攻略检索任务完成",
      detail: "正在搜索小红书和全网公开信息：西藏7天经典旅游路线推荐拉萨林芝羊湖。",
      count: 1,
    },
  ],
});
assertIncludes(
  visualJourneyHtml,
  [
    "visual-journey-workbench",
    "data-journey-data",
    "西藏7天经典之旅",
    "visual-journey-stats",
    "路线预览",
    "巴松措",
    "visual-poi-card",
    "visual-poi-media",
    "visual-poi-evidence",
    "高德核验",
    "估算落点",
    "visual-day-focus-btn",
    "visual-poi-focus-btn",
    "journey-status-chip",
    "journey-map-title-pill",
    "journey-map-sidebar-routes",
    "路线参考",
    "journey-poi-bottom-sheet",
    "journey-poi-bottom-media",
    "data-poi-sheet-proof",
    "data-poi-sheet-action",
    "替换这个点",
    "核验门票交通",
    "保留继续规划",
    "沉浸地图",
    "推荐点",
    "路程时间行前确认",
    "地图路段距离和时长以高德实时路线为准",
  ],
  "visual-journey-workbench"
);
assertExcludes(
  visualJourneyHtml,
  ["规划过程", "journey-map-bottom-drawer"],
  "visual-journey-customer-view"
);
assertIncludes(appScript, ["/api/v1/chat/journey/"], "journey-draft-save-api");
assertIncludes(
  appScript,
  [
    "amap-journey-day-badge",
    "leaflet-journey-day-badge",
    "leaflet-journey-day-marker",
    "getJourneyDayBadgeLabel",
    "getJourneyShortDayLabel",
    "getJourneySegmentLabelParts",
    "activateJourneyBottomStop",
    "isJourneyRecommendationPoint",
    "replaceJourneyPoiFromSheet",
    "getJourneyReplacementCandidates",
  ],
  "journey-map-day-badges"
);

const placeholderReportData = JSON.parse(JSON.stringify(fixtures[0][1]));
placeholderReportData.itinerary = [
  {
    day_number: 1,
    title: "待补齐当天安排",
    time_blocks: ["这一天还没有出现在当前报告数据里，需要继续补齐玩法、餐饮和动线。"],
    missing: true,
  },
];
const placeholderHtml = context.renderAssistantText("", {
  reportData: placeholderReportData,
});
assertIncludes(placeholderHtml, ["正式每日行程尚未生成"], "placeholder-report-days");
if (
  placeholderHtml.includes("待补齐当天安排") ||
  placeholderHtml.includes("这一天还没有出现在当前报告")
) {
  throw new Error("placeholder-report-days should not expose incomplete day placeholders.");
}

const thinkingHtml = context.renderAssistantText(
  "公开建议。<think>内部推理 query_transport_options</think>继续说明。"
);
assertIncludes(thinkingHtml, ["公开建议", "继续说明"], "thinking-filter");
if (
  thinkingHtml.includes("<think") ||
  thinkingHtml.includes("内部推理") ||
  thinkingHtml.includes("query_transport_options")
) {
  throw new Error("thinking-filter should hide model-only reasoning content.");
}

const thinkingFilter = context.createAssistantThinkingFilter();
const streamVisible =
  thinkingFilter.feed("公开<thi") +
  thinkingFilter.feed("nk>隐藏工具计划") +
  thinkingFilter.feed("</thi") +
  thinkingFilter.feed("nk>继续") +
  thinkingFilter.finish();
if (streamVisible !== "公开继续") {
  throw new Error(`thinking stream filter output mismatch: ${streamVisible}`);
}

console.log("frontend-report-renderer-ok");
