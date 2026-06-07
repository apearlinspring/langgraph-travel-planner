(function (global) {
  function createReportDataViewModel({ parseJourneyChineseDayNumber } = {}) {
    function isStructuredTravelReportData(reportData) {
      return (
        reportData &&
        typeof reportData === "object" &&
        reportData.version === "travel_report.v1" &&
        reportData.overview
      );
    }

    function formatReportDataMoney(value) {
      if (typeof value !== "number" || Number.isNaN(value)) return "";
      return `${Math.round(value).toLocaleString("zh-CN")} 元`;
    }

    function normalizeReportDataList(items = []) {
      return (Array.isArray(items) ? items : [])
        .map((item) => String(item || "").trim())
        .filter(Boolean);
    }

    const reportBudgetGroups = [
      { key: "transport", label: "交通", icon: "fa-train-subway" },
      { key: "accommodation", label: "住宿", icon: "fa-bed" },
      { key: "food", label: "餐饮", icon: "fa-utensils" },
      { key: "attractions", label: "景点/体验", icon: "fa-ticket" },
      { key: "service_reserve", label: "服务/预留", icon: "fa-shield-heart" },
      { key: "other", label: "其他", icon: "fa-wallet" },
    ];

    function reportBudgetGroupKey(item = {}) {
      const source = `${item.key || item.category || ""} ${item.label || ""}`.toLowerCase();
      if (/transport|traffic|交通|高铁|航班|机票|火车/.test(source)) return "transport";
      if (/accommodation|hotel|lodging|住宿|酒店|民宿|房/.test(source)) return "accommodation";
      if (/food|dining|meal|餐|美食|小吃/.test(source)) return "food";
      if (/attraction|scenic|sight|experience|景点|门票|体验|游船/.test(source)) return "attractions";
      if (/service|reserve|contingency|buffer|misc|服务|预留|机动/.test(source)) return "service_reserve";
      return "other";
    }

    function normalizeReportBudgetItems(budget = {}) {
      const grouped = new Map(
        reportBudgetGroups.map((group) => [
          group.key,
          {
            ...group,
            amount: 0,
            basis: "",
            confidence: "",
          },
        ])
      );
      (Array.isArray(budget.items) ? budget.items : []).forEach((item) => {
        if (!item || typeof item !== "object") return;
        const group = grouped.get(reportBudgetGroupKey(item)) || grouped.get("other");
        if (typeof item.amount === "number" && !Number.isNaN(item.amount)) {
          group.amount += item.amount;
        }
        if (item.basis && !group.basis) group.basis = String(item.basis);
        if (item.confidence && !group.confidence) group.confidence = String(item.confidence);
      });

      const fieldFallbacks = {
        transport: "transport",
        accommodation: "accommodation",
        food: "food",
        attractions: "attractions",
        service_reserve: budget.service_reserve !== undefined ? "service_reserve" : "misc",
        other: "other",
      };
      Object.entries(fieldFallbacks).forEach(([groupKey, budgetKey]) => {
        const group = grouped.get(groupKey);
        const value = budget[budgetKey];
        if (group && !group.amount && typeof value === "number" && !Number.isNaN(value)) {
          group.amount = value;
        }
      });

      const defaults = {
        transport: "交通票价、余票和退改签规则需在正式预订前复核。",
        accommodation: "住宿按区域、房型、晚数和取消政策估算。",
        food: "餐饮按用餐偏好、餐次和热门餐厅排队情况估算。",
        attractions: "景点/体验按门票、预约项目和临时展览收费估算。",
        service_reserve: "覆盖市内交通、寄存、临时休息和价格波动缓冲。",
        other: "个人购物、伴手礼和临时加项按实际发生处理。",
      };
      return reportBudgetGroups.map((group) => {
        const item = grouped.get(group.key);
        return {
          ...item,
          basis: item.basis || defaults[group.key],
          confidence: item.confidence || "待核验",
        };
      });
    }

    function parseReportDataExpectedDays(reportData = {}) {
      const duration = String(reportData.overview?.duration || "");
      const digitMatch = duration.match(/(\d+)\s*天/u);
      const chineseMatch = duration.match(/([一二三四五六七八九十])\s*天/u);
      const parsed = digitMatch
        ? Number(digitMatch[1])
        : chineseMatch
          ? parseJourneyChineseDayNumber(chineseMatch[1])
          : 0;
      const itineraryDays = Array.isArray(reportData.itinerary)
        ? reportData.itinerary.map((day) => Number(day.day_number || day.day || 0))
        : [];
      const routeDays = Array.isArray(reportData.map_routes)
        ? reportData.map_routes.map((route) => Number(route.day_number || route.day || 0))
        : [];
      const routeMapDays = Array.isArray(reportData.route_map?.days)
        ? reportData.route_map.days.map((day) => Number(day.day_number || day.day || 0))
        : [];
      return Math.max(parsed, ...itineraryDays, ...routeDays, ...routeMapDays, 0);
    }

    function getReportPlanningModeMeta(reportData = {}) {
      const mode = reportData.agency_context?.mode || "";
      if (mode === "agency_plan") {
        return {
          mode,
          label: "省心方案",
          shortLabel: "省心方案",
          icon: "fa-user-tie",
          tone: "agency",
          copy:
            "按成熟路线、服务节点、费用依据和出发前核验项组织。",
        };
      }
      if (mode === "free_planning") {
        return {
          mode,
          label: "个性化旅游规划",
          shortLabel: "个性化规划",
          icon: "fa-route",
          tone: "free",
          copy:
            "按你的偏好呈现路线、预算依据和风险提醒。",
        };
      }
      return {
        mode: "unknown",
        label: "规划方案",
        shortLabel: "规划方案",
        icon: "fa-compass",
        tone: "neutral",
        copy: "已按当前结构化信息整理路线、预算和后续核验项。",
      };
    }

    function getBudgetConfidenceTone(level = "") {
      const normalized = String(level || "").trim();
      if (/高|中高/.test(normalized)) return "strong";
      if (/中/.test(normalized)) return "medium";
      if (/低|待/.test(normalized)) return "caution";
      return "neutral";
    }

    function buildReportDataViewModel(reportData = {}) {
      const budgetConfidence = reportData.budget_confidence || {};
      const toolAudit = reportData.tool_audit_summary || {};
      const agencyContext = reportData.agency_context || {};
      const approval =
        toolAudit.approval ||
        reportData.evidence_bundle?.approval_governance ||
        {};
      const pendingChecks = normalizeReportDataList([
        ...normalizeReportDataList(budgetConfidence.verification_items),
        ...normalizeReportDataList(toolAudit.pending_checks),
      ]).filter((item, index, list) => list.indexOf(item) === index);

      return {
        mode: getReportPlanningModeMeta(reportData),
        budgetConfidence: {
          level: budgetConfidence.level || "待评估",
          tone: getBudgetConfidenceTone(budgetConfidence.level),
          confirmedItems: normalizeReportDataList(budgetConfidence.confirmed_items),
          estimatedItems: normalizeReportDataList(budgetConfidence.estimated_items),
          verificationItems: normalizeReportDataList(
            budgetConfidence.verification_items
          ),
        },
        handoff: {
          readiness: toolAudit.readiness || "可交付，预订前需核验",
          usedSources: normalizeReportDataList(toolAudit.used_sources),
          pendingChecks,
          unsupportedActions: normalizeReportDataList(toolAudit.unsupported_actions),
          toolEvents: Array.isArray(toolAudit.events) ? toolAudit.events : [],
        },
        approval: {
          approvalId: String(approval.approval_id || "").trim(),
          action: String(approval.action || "generate_order_id").trim(),
          status: String(approval.status || "none").trim(),
          pending: Boolean(approval.pending),
          requiresApproval: Boolean(approval.requires_approval),
          isBlocking: Boolean(approval.is_blocking),
          recordOnly: approval.record_only !== false,
          expiresAt: approval.expires_at || null,
          reason: String(approval.reason || "").trim(),
          boundary:
            String(approval.boundary || "").trim() ||
            "当前报告不代表真实支付、真实预订、真实锁价或履约成功。",
          unsupportedWithoutIntegration: normalizeReportDataList(
            approval.unsupported_without_integration
          ),
        },
        agency: {
          summary: String(agencyContext.summary || "").trim(),
          highlights: normalizeReportDataList(agencyContext.highlights),
          modeReason: String(agencyContext.mode_reason || "").trim(),
        },
      };
    }

    return {
      isStructuredTravelReportData,
      formatReportDataMoney,
      normalizeReportDataList,
      normalizeReportBudgetItems,
      parseReportDataExpectedDays,
      getReportPlanningModeMeta,
      buildReportDataViewModel,
    };
  }

  global.ZhiXingReportDataViewModel = {
    createReportDataViewModel,
  };
})(window);
