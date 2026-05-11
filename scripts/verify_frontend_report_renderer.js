const fs = require("fs");
const path = require("path");
const vm = require("vm");

const repoRoot = path.resolve(__dirname, "..");
const appScript = fs.readFileSync(path.join(repoRoot, "frontend", "app.js"), "utf8");

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

function sampleReportData(mode) {
  const isAgency = mode === "agency_plan";
  return {
    version: "travel_report.v1",
    overview: {
      route_label: isAgency ? "北京到成都 4 日顾问方案" : "北京到成都 4 日自由规划",
      duration: "4 天",
      people: "2 人",
      travel_styles: ["美食慢游", isAgency ? "省心方案" : "自由行"],
    },
    transport: { summary: "高铁优先，正式购票前复核余票和票价。" },
    accommodation: { summary: "春熙路附近舒适型酒店，入住政策待核验。" },
    food_preferences: { summary: "川菜、小吃，保留低辣备选。" },
    itinerary: [
      {
        day_number: 1,
        title: "抵达成都",
        time_blocks: ["上午抵达成都东站", "下午宽窄巷子慢逛"],
        route: { summary: "成都东站 → 宽窄巷子" },
        meals: ["宽窄巷子小吃"],
        plan_b: "雨天改室内茶馆和博物馆。",
        risk_notes: ["节假日排队较久"],
      },
    ],
    map_routes: [
      {
        day_number: 1,
        summary: "成都东站 → 宽窄巷子",
        route_points: ["成都东站", "宽窄巷子"],
      },
    ],
    agency_context: {
      mode,
      summary: isAgency
        ? "按旅行社顾问方案交付，重点保留服务节点和预订前核验。"
        : "按自由规划交付，重点保留自订弹性和风险提醒。",
      highlights: ["交通酒店出发前复核", "预算按可追溯、估算、待核验拆分"],
      mode_reason: isAgency ? "用户希望省心方案" : "用户说明自己预订",
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

function assertIncludes(html, fragments, label) {
  const missing = fragments.filter((fragment) => !html.includes(fragment));
  if (missing.length) {
    throw new Error(`${label} missing fragments: ${missing.join(", ")}`);
  }
}

const context = createRenderContext();

for (const mode of ["agency_plan", "free_planning"]) {
  const html = context.renderAssistantText("自然语言正文不应驱动核心报告结构", {
    reportData: sampleReportData(mode),
  });
  assertIncludes(
    html,
    [
      'data-report-source="structured"',
      mode === "agency_plan" ? "旅行社顾问方案" : "自由规划",
      "预算置信度",
      "正式购票前复核余票和票价",
      "不承诺真实库存",
      "审批治理边界",
      "不代表真实支付",
      "路线联动",
      "顾问核验与下一步",
    ],
    mode
  );
}

console.log("frontend-report-renderer-ok");
