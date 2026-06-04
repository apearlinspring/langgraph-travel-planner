(function (global) {
  const TOOL_DISPLAY_LABELS = {
    query_transport_options: "交通查询",
    query_flight_options: "航班查询",
    query_train_options: "高铁查询",
    query_driving_route: "自驾路线",
    query_hotel_options: "住宿查询",
    query_destination_info: "目的地信息",
    search_travel_info: "旅行搜索",
    search_destination_guide: "目的地攻略",
    search_food_recommendations: "餐饮建议",
    search_accommodation_info: "住宿建议",
    search_travel_tips: "旅行提示",
    search_agency_product_templates: "产品模板检索",
    search_agency_service_sop: "服务流程检索",
    search_agency_pricing_rules: "报价规则检索",
    search_agency_risk_playbook: "风险规则检索",
    search_agency_report_standards: "报告标准检索",
    record_requirement_tool: "需求整理",
    confirm_planning_mode_tool: "方案类型确认",
    set_planning_mode_tool: "方案类型记录",
    record_evidence_bundle_tool: "证据整理",
    scenic_price_lookup_tool: "门票参考查询",
    select_transport_tool: "交通方案记录",
    select_accommodation_tool: "住宿方案记录",
    generate_order_tool: "报告生成",
  };

  const TOOL_EVIDENCE_LABELS = {
    live_transport_query: "实时交通查询",
    live_hotel_search: "实时住宿查询",
    mcp_live_query: "外部服务查询",
    internal_rag_evidence: "内部知识检索",
    public_rag_evidence: "公开知识检索",
    destination_router_evidence: "目的地知识编排",
    internal_state_update: "本地状态更新",
    unknown: "证据类型待确认",
  };

  const TOOL_AUDIT_STATUS_LABELS = {
    success: "成功",
    needs_verification: "需核验",
    not_found: "未查到",
    insufficient_parameters: "参数不足",
    service_exception: "服务异常",
    skipped: "已跳过",
  };

  const TOOL_AUDIT_EXPLANATIONS = {
    success: "工具返回了可用结果。",
    needs_verification: "工具返回了内容，但仍需要人工或出发前再次核验。",
    not_found: "工具调用成功，但这次没有查到合适结果；不是系统崩溃。",
    insufficient_parameters: "本轮缺少必要参数，补齐后可以再查。",
    service_exception: "外部服务或工具执行异常，需要稍后重试。",
    skipped: "本轮按保护规则跳过了这次工具调用。",
  };

  function redactClientText(value = "", maxLength = 180) {
    const compact = String(value || "")
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[REDACTED]")
      .replace(/\b1[3-9]\d{9}\b/g, "[REDACTED]")
      .replace(/\b\d{17}[\dXx]\b/g, "[REDACTED]")
      .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+\b/gi, "Bearer [REDACTED]")
      .replace(/\beyJ[A-Za-z0-9._~+/=-]+\b/g, "[REDACTED]")
      .replace(/\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+/gi, "[REDACTED]")
      .replace(/\s+/g, " ")
      .trim();
    return compact.length > maxLength
      ? `${compact.slice(0, maxLength)}...`
      : compact;
  }

  function getToolDisplayName(toolName = "") {
    const rawName = String(toolName || "").trim();
    return TOOL_DISPLAY_LABELS[rawName] || redactClientText(rawName || "工具", 80);
  }

  function getToolEvidenceLabel(evidenceType = "") {
    const rawType = String(evidenceType || "unknown").trim();
    return TOOL_EVIDENCE_LABELS[rawType] || redactClientText(rawType, 80);
  }

  function inferToolAuditSemanticStatus(status = "", errorType = "") {
    const rawStatus = String(status || "").toLowerCase();
    const rawError = String(errorType || "").toLowerCase();
    if (rawStatus === "success") return "success";
    if (rawError === "empty_transport_result") return "not_found";
    if (rawError.startsWith("empty_") || rawError.includes("empty_or_unavailable")) {
      return "not_found";
    }
    if (rawStatus === "skipped") {
      if (
        rawError.startsWith("invalid_") ||
        rawError.includes("missing") ||
        rawError.includes("placeholder")
      ) {
        return "insufficient_parameters";
      }
      return "skipped";
    }
    if (rawStatus === "approval_required") return "skipped";
    if (rawStatus === "failed" || rawStatus === "timeout") return "service_exception";
    return "needs_verification";
  }

  function getToolAuditReasonLabel(errorType = "") {
    const rawError = String(errorType || "").trim();
    const labels = {
      empty_transport_result: "未查到合适交通结果",
      empty_hotel_result: "未查到合适住宿结果",
      empty_mcp_result: "外部服务没有返回可用内容",
      empty_rag_result: "知识检索没有返回证据",
      rag_empty_or_unavailable: "知识检索为空或降级",
      transport_result_requires_verification: "交通结果需要复查",
      mcp_result_requires_verification: "外部服务结果需要复查",
      upstream_timeout: "外部服务超时",
      duplicate_tool_call_same_turn: "同一轮重复查询已跳过",
      approval_required: "需要人工确认",
      tool_disabled: "能力尚未开放",
      invalid_transport_query_args: "交通查询参数不足",
      invalid_hotel_query_args: "住宿查询参数不足",
      invalid_destination_query_args: "目的地查询参数不足",
      invalid_rag_query_args: "检索参数不足",
      invalid_mcp_tool_args: "外部工具参数不足",
    };
    return labels[rawError] || redactClientText(rawError, 80);
  }

  function createGovernanceTools(options = {}) {
    const getStatusLabel =
      typeof options.getStatusLabel === "function"
        ? options.getStatusLabel
        : (status = "") => status || "待确认";

    function normalizeToolAuditEvent(event = {}) {
      const status = String(event.status || "unknown");
      const errorType = redactClientText(event.error_type || "", 80);
      const semanticStatus = String(
        event.semantic_status || inferToolAuditSemanticStatus(status, errorType)
      );
      const statusLabel = redactClientText(
        event.status_label ||
          TOOL_AUDIT_STATUS_LABELS[semanticStatus] ||
          getStatusLabel(status),
        80
      );
      const statusExplanation = redactClientText(
        event.status_explanation ||
          TOOL_AUDIT_EXPLANATIONS[semanticStatus] ||
          "本轮工具结果需要结合行程上下文判断。",
        160
      );
      return {
        tool: getToolDisplayName(event.tool || event.name || "unknown_tool"),
        rawTool: redactClientText(event.tool || event.name || "unknown_tool", 80),
        status,
        semanticStatus,
        statusLabel,
        statusExplanation,
        elapsedSeconds:
          event.elapsed_seconds === null || event.elapsed_seconds === undefined
            ? null
            : Number(event.elapsed_seconds),
        retryCount: Number(event.retry_count || 0),
        evidenceType: redactClientText(event.evidence_type || "unknown", 80),
        evidenceLabel: getToolEvidenceLabel(event.evidence_type || "unknown"),
        errorType,
        reasonLabel: errorType ? getToolAuditReasonLabel(errorType) : "",
        degraded:
          Boolean(event.degraded) ||
          ["failed", "timeout", "degraded", "skipped", "approval_required"].includes(
            status
          ),
        observedAt: Date.now(),
      };
    }

    return {
      redactClientText,
      getToolDisplayName,
      getToolEvidenceLabel,
      inferToolAuditSemanticStatus,
      getToolAuditReasonLabel,
      normalizeToolAuditEvent,
    };
  }

  global.ZhiXingGovernanceTools = {
    createGovernanceTools,
    redactClientText,
    getToolDisplayName,
    getToolEvidenceLabel,
    inferToolAuditSemanticStatus,
    getToolAuditReasonLabel,
  };
})(window);
