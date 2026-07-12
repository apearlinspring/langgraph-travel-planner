(function (global) {
  const { parseJsonSafe, requestJson } = global.ZhiXingSessionApi;

  async function fetchReadiness({ apiBase, signal }) {
    const response = await fetch(`${apiBase}/health/ready`, {
      signal,
      headers: { Accept: "application/json" },
    });
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function fetchApprovalEvents({ apiBase, stateToken = "", approvalId }) {
    return requestJson(
      `${apiBase}/api/v1/approvals/${encodeURIComponent(approvalId)}/events`,
      stateToken
    );
  }

  async function fetchApprovals({
    apiBase,
    stateToken = "",
    filter = "all",
    canRequestAll = false,
    limit = 30,
    offset = 0,
    queryText = "",
  }) {
    const params = new URLSearchParams();
    if (canRequestAll) params.set("scope", "all");
    if (filter && filter !== "all") params.set("status", filter);
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    if (queryText.trim()) params.set("q", queryText.trim());
    return requestJson(
      `${apiBase}/api/v1/approvals?${params}`,
      stateToken
    );
  }

  async function createDemoApproval({
    apiBase,
    stateToken = "",
    conversationId = null,
  }) {
    return requestJson(
      `${apiBase}/api/v1/approvals`,
      stateToken,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action: "real_payment",
          reason: "未来真实支付接入前必须经过人工确认",
          conversation_id: conversationId,
          metadata: {
            source: "frontend_governance_console",
            demo: true,
          },
          expires_in_seconds: 3600,
        }),
      }
    );
  }

  async function submitApprovalDecision({
    apiBase,
    stateToken = "",
    approvalId,
    decisionPath,
    reason,
  }) {
    return requestJson(
      `${apiBase}/api/v1/approvals/${encodeURIComponent(approvalId)}/${decisionPath}`,
      stateToken,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: reason ? JSON.stringify({ reason }) : undefined,
      }
    );
  }

  global.ZhiXingGovernanceApi = {
    fetchReadiness,
    fetchApprovalEvents,
    fetchApprovals,
    createDemoApproval,
    submitApprovalDecision,
  };
})(window);
