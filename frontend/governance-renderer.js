(function (global) {
  function createGovernanceRenderer(options = {}) {
    const escapeHtml =
      typeof options.escapeHtml === "function"
        ? options.escapeHtml
        : (value = "") => String(value || "");
    const redactClientText =
      typeof options.redactClientText === "function"
        ? options.redactClientText
        : (value = "", maxLength = 180) => {
            const text = String(value || "").trim();
            return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
          };
    const getStatusLabel =
      typeof options.getStatusLabel === "function"
        ? options.getStatusLabel
        : (status = "") => status || "待确认";
    const formatEpochSeconds =
      typeof options.formatEpochSeconds === "function"
        ? options.formatEpochSeconds
        : (value = "") => String(value || "未设置");

    function emptyStateHtml(message = "") {
      return `<div class="governance-empty">${escapeHtml(message)}</div>`;
    }

    function escapeAttribute(value = "") {
      return escapeHtml(value).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function renderReadinessServiceGrid(items = []) {
      return items
        .map(
          (item) => `
            <div class="readiness-service-item">
              <span>${escapeHtml(item.label)}</span>
              <strong>${escapeHtml(getStatusLabel(item.status))}</strong>
              <small>${escapeHtml(item.description)}</small>
            </div>
          `
        )
        .join("");
    }

    function renderToolAuditListHtml(events = []) {
      if (!events.length) {
        return emptyStateHtml("本轮还没有工具记录。");
      }
      return events
        .map((event) => {
          const elapsed = Number.isFinite(event.elapsedSeconds)
            ? `${event.elapsedSeconds.toFixed(2)}s`
            : "未记录";
          return `
            <article class="tool-audit-card">
              <div class="tool-audit-card-head">
                <strong>${escapeHtml(event.tool)}</strong>
                <span class="governance-status-pill ${escapeHtml(
                  event.semanticStatus
                )}">${escapeHtml(event.statusLabel)}</span>
              </div>
              <div class="tool-audit-raw-name">
                原始工具名：<code>${escapeHtml(event.rawTool)}</code>
              </div>
              <p>${escapeHtml(event.statusExplanation)}</p>
              <div class="tool-audit-meta">
                <span><i class="fa-regular fa-clock"></i>${escapeHtml(elapsed)}</span>
                <span><i class="fa-solid fa-rotate"></i>${event.retryCount} 次重试</span>
                <span><i class="fa-solid fa-file-shield"></i>${escapeHtml(
                  event.evidenceLabel
                )}</span>
                ${
                  event.reasonLabel
                    ? `<span><i class="fa-solid fa-triangle-exclamation"></i>${escapeHtml(
                        event.reasonLabel
                      )}</span>`
                    : ""
                }
              </div>
            </article>
          `;
        })
        .join("");
    }

    function renderTurnObservabilityGridHtml(item = null) {
      if (!item) {
        return emptyStateHtml(
          "完成一轮聊天后展示脱敏运行摘要，不展示个人敏感信息、密钥或完整工具输入输出。"
        );
      }
      const metrics = [
        ["状态", item.statusLabel],
        ["阶段", item.stepLabel],
        ["模式", item.planningModeLabel],
        ["首个响应片段", item.firstTokenSeconds == null ? "未记录" : `${item.firstTokenSeconds}s`],
        ["总耗时", item.totalElapsedSeconds == null ? "未记录" : `${item.totalElapsedSeconds}s`],
        ["工具调用", `${item.toolCallCount} 次`],
        ["需复查工具", `${item.toolFailureCount} 个`],
        ["兜底次数", `${item.fallbackCount} 次`],
        ["文本量估算", `${item.estimatedTotalTokens}`],
      ];
      const metricsHtml = metrics
        .map(
          ([label, value]) => `
            <div class="turn-observability-item">
              <span>${escapeHtml(label)}</span>
              <strong>${escapeHtml(value)}</strong>
            </div>
          `
        )
        .join("");
      const traceHtml = item.turnId
        ? `<div class="turn-observability-footnote">追踪码（排查用）：${escapeHtml(
            item.turnId.slice(0, 12)
          )}</div>`
        : "";
      return `${metricsHtml}${traceHtml}`;
    }

    function renderApprovalListHtml(options = {}) {
      const {
        approvals = [],
        filter = "all",
        selectedApprovalId = "",
        userPresent = false,
        loading = false,
      } = options;
      if (!userPresent) {
        return emptyStateHtml("登录后展示人工确认记录。");
      }
      if (loading) {
        return emptyStateHtml("正在同步人工确认记录…");
      }
      if (!approvals.length) {
        return emptyStateHtml(
          `当前没有${filter === "pending" ? "待人工确认" : "可展示"}记录。演示记录只说明未来真实支付、短信或客户资料导出前需要人工确认，不会真实下单。`
        );
      }
      return approvals
        .map((approval) => {
          const id = approval.approval_id || "";
          const status = approval.status || "none";
          const isPending = status === "pending";
          const isActive = selectedApprovalId === id;
          return `
            <article
              class="approval-card ${isActive ? "active" : ""}"
              data-approval-select-id="${escapeAttribute(id)}"
            >
              <div class="approval-card-head">
                <strong>${escapeHtml(
                  redactClientText(approval.label || approval.action || "需确认动作")
                )}</strong>
                <span class="governance-status-pill ${escapeHtml(status)}">${escapeHtml(
                  getStatusLabel(status)
                )}</span>
              </div>
              <p>${escapeHtml(redactClientText(approval.reason || "未填写确认理由"))}</p>
              <div class="approval-card-meta">
                <span><i class="fa-solid fa-shield-halved"></i>${
                  approval.requires_approval ? "需人工确认" : "边界记录"
                }</span>
                <span><i class="fa-regular fa-clock"></i>${escapeHtml(
                  formatEpochSeconds(approval.created_at)
                )}</span>
                <span><i class="fa-regular fa-hourglass-half"></i>${escapeHtml(
                  approval.expires_at ? formatEpochSeconds(approval.expires_at) : "无过期时间"
                )}</span>
              </div>
              <div class="approval-actions">
                <button
                  class="approval-action-btn approve"
                  type="button"
                  ${isPending ? "" : "disabled"}
                  data-approval-decision-id="${escapeAttribute(id)}"
                  data-approval-decision="approve"
                >
                  批准
                </button>
                <button
                  class="approval-action-btn reject"
                  type="button"
                  ${isPending ? "" : "disabled"}
                  data-approval-decision-id="${escapeAttribute(id)}"
                  data-approval-decision="reject"
                >
                  拒绝
                </button>
                <button
                  class="approval-action-btn expire"
                  type="button"
                  ${isPending ? "" : "disabled"}
                  data-approval-decision-id="${escapeAttribute(id)}"
                  data-approval-decision="expire"
                >
                  过期
                </button>
              </div>
            </article>
          `;
        })
        .join("");
    }

    function formatApprovalEventType(type = "") {
      const labels = {
        created: "创建",
        approved: "批准",
        rejected: "拒绝",
        expired: "过期",
        updated: "更新",
      };
      return labels[type] || type || "事件";
    }

    function renderApprovalEventList(options = {}) {
      const { selectedApprovalId = "", events = [] } = options;
      if (!selectedApprovalId) {
        return {
          className: "governance-empty",
          html: "选择一条人工确认记录后展示状态变化。",
        };
      }
      if (!events.length) {
        return {
          className: "governance-empty",
          html: "这条记录还没有返回事件。",
        };
      }
      return {
        className: "approval-event-list",
        html: events
          .map(
            (event) => `
              <div class="approval-event-item">
                <strong>${escapeHtml(formatApprovalEventType(event.event_type))} · ${escapeHtml(
                  getStatusLabel(event.from_status || "none")
                )} → ${escapeHtml(getStatusLabel(event.to_status || "unknown"))}</strong>
                <span>${escapeHtml(formatEpochSeconds(event.created_at))}</span>
                ${
                  event.reason
                    ? `<p>${escapeHtml(redactClientText(event.reason, 120))}</p>`
                    : ""
                }
              </div>
            `
          )
          .join(""),
      };
    }

    return {
      renderReadinessServiceGrid,
      renderToolAuditListHtml,
      renderTurnObservabilityGridHtml,
      renderApprovalListHtml,
      renderApprovalEventList,
    };
  }

  global.ZhiXingGovernanceRenderer = {
    createGovernanceRenderer,
  };
})(window);
