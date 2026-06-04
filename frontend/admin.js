(function () {
  const sessionApi = window.ZhiXingSessionApi;
  const governanceApi = window.ZhiXingGovernanceApi;
  const adminApi = window.ZhiXingAdminApi;

  const state = {
    token: "",
    user: null,
    selectedUserId: "",
    selectedConversationId: "",
    selectedApprovalId: "",
    selectedUserDetail: null,
    approvalEvents: [],
    approvals: [],
    approvalActionPendingId: "",
    pagination: {
      users: {
        limit: 12,
        offset: 0,
        total: 0,
      },
      conversations: {
        limit: 12,
        offset: 0,
        total: 0,
      },
      approvals: {
        limit: 12,
        offset: 0,
        total: 0,
      },
    },
    filters: {
      userQuery: "",
      userRole: "all",
      userDetailConversationQuery: "",
      userDetailConversationStatus: "all",
      conversationQuery: "",
      conversationRole: "all",
      conversationStatus: "active",
      approvalQuery: "",
      approvalStatus: "all",
    },
  };

  function getApiBase() {
    return window.location.protocol === "file:"
      ? "http://127.0.0.1:8000"
      : window.location.origin;
  }

  function normalizeRole(user = null) {
    const raw =
      user?.role ||
      user?.preferences?.role ||
      user?.profile?.role ||
      "user";
    return String(raw || "user").toLowerCase();
  }

  function canAccessAdmin(user = null) {
    return ["approver", "admin", "审批员", "管理员"].includes(
      user?.role || user?.preferences?.role || user?.profile?.role || "user"
    );
  }

  function formatDate(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
  }

  function safeText(value, fallback = "-") {
    const raw = value === null || value === undefined || value === "" ? fallback : value;
    return escapeHtml(raw);
  }

  function safeAttr(value) {
    return escapeHtml(value ?? "");
  }

  function safeStatusClass(value) {
    const normalized = String(value || "unknown")
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return normalized || "unknown";
  }

  function renderStatusChip(status = "") {
    const label = status || "unknown";
    return `<span class="status-chip ${safeStatusClass(label)}">${safeText(label)}</span>`;
  }

  function renderApprovalDecisionActions(approval) {
    if (String(approval?.status || "").toLowerCase() !== "pending") return "";
    return `
      <div class="approval-item-actions">
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="approve"
          data-approval-id="${safeAttr(approval.approval_id)}"
        >
          批准
        </button>
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="reject"
          data-approval-id="${safeAttr(approval.approval_id)}"
        >
          拒绝
        </button>
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="expire"
          data-approval-id="${safeAttr(approval.approval_id)}"
        >
          过期
        </button>
      </div>
    `;
  }

  function syncApprovalQuickFilterUi() {
    document
      .getElementById("adminApprovalQuickAll")
      ?.classList.toggle("active", state.filters.approvalStatus === "all");
    document
      .getElementById("adminApprovalQuickPending")
      ?.classList.toggle("active", state.filters.approvalStatus === "pending");
  }

  function setAdminState(title, note) {
    document.getElementById("adminUserLabel").textContent = title;
    document.getElementById("adminStateNote").textContent = note;
  }

  function renderOverview(data) {
    document.getElementById("metricUsers").textContent = data?.total_users ?? "-";
    document.getElementById("metricConversations").textContent =
      data?.total_conversations ?? "-";
    document.getElementById("metricActiveConversations").textContent =
      data?.active_conversations ?? "-";
    document.getElementById("metricPendingApprovals").textContent =
      data?.pending_approvals ?? "-";
  }

  function renderListPager(elementId, pagination, itemCount, itemLabel, target) {
    const container = document.getElementById(elementId);
    if (!container) return;
    const total = Number(pagination?.total || 0);
    const limit = Math.max(1, Number(pagination?.limit || 1));
    const offset = Math.max(0, Number(pagination?.offset || 0));
    if (!total) {
      container.innerHTML = `
        <span class="pager-summary">共 0 条${safeText(itemLabel)}</span>
        <div class="pager-actions">
          <button class="row-action-btn" type="button" disabled>上一页</button>
          <button class="row-action-btn" type="button" disabled>下一页</button>
        </div>
      `;
      return;
    }
    const start = offset + 1;
    const end = Math.min(offset + itemCount, total);
    const page = Math.floor(offset / limit) + 1;
    const pageCount = Math.max(1, Math.ceil(total / limit));
    const prevDisabled = offset <= 0 ? "disabled" : "";
    const nextDisabled = offset + itemCount >= total ? "disabled" : "";
    container.innerHTML = `
      <span class="pager-summary">
        第 ${start}-${end} 条，共 ${total} 条${safeText(itemLabel)} · 第 ${page}/${pageCount} 页
      </span>
      <div class="pager-actions">
        <button
          class="row-action-btn"
          type="button"
          data-page-target="${safeAttr(target)}"
          data-page-direction="prev"
          ${prevDisabled}
        >
          上一页
        </button>
        <button
          class="row-action-btn"
          type="button"
          data-page-target="${safeAttr(target)}"
          data-page-direction="next"
          ${nextDisabled}
        >
          下一页
        </button>
      </div>
    `;
  }

  function renderUsersLoading() {
    document.getElementById("adminUsersTable").innerHTML =
      '<tr><td colspan="6" class="empty-state">正在加载用户数据…</td></tr>';
  }

  function renderConversationsLoading() {
    document.getElementById("adminConversationsTable").innerHTML =
      '<tr><td colspan="7" class="empty-state">正在加载会话数据…</td></tr>';
  }

  function resetListPagination() {
    state.pagination.users.offset = 0;
    state.pagination.users.total = 0;
    state.pagination.conversations.offset = 0;
    state.pagination.conversations.total = 0;
    state.pagination.approvals.offset = 0;
    state.pagination.approvals.total = 0;
  }

  function renderUsers(users = []) {
    const tbody = document.getElementById("adminUsersTable");
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">当前没有可展示的用户记录。</td></tr>';
      renderListPager("adminUsersPager", state.pagination.users, 0, "用户", "users");
      renderUserDetailEmpty("当前筛选结果里没有可展开的用户。");
      return;
    }
    tbody.innerHTML = users
      .map(
        (user) => `
          <tr>
            <td><strong>${safeText(user.username)}</strong></td>
            <td>${safeText(user.email)}</td>
            <td>${renderStatusChip(user.role || "user")}</td>
            <td>${user.conversation_count ?? 0}</td>
            <td>${formatDate(user.created_at)}</td>
            <td>
              <button
                class="row-action-btn"
                type="button"
                data-user-detail-id="${safeAttr(user.id)}"
              >
                查看用户
              </button>
            </td>
          </tr>
        `
      )
      .join("");
    renderListPager(
      "adminUsersPager",
      state.pagination.users,
      users.length,
      "用户",
      "users"
    );
  }

  function renderUserDetailEmpty(message) {
    state.selectedUserDetail = null;
    document.getElementById("adminUserDetailHint").textContent = message;
    document.getElementById("adminUserRuntime").innerHTML =
      '<div class="empty-state">还没有选中用户。</div>';
    document.getElementById("adminUserApprovals").innerHTML =
      '<div class="empty-state">选中用户后显示最近审批摘要。</div>';
    document.getElementById("adminUserConversations").innerHTML =
      '<div class="empty-state">选中用户后显示最近会话摘要。</div>';
  }

  function renderUserDetailLoading() {
    document.getElementById("adminUserDetailHint").textContent =
      "正在加载用户详情…";
    document.getElementById("adminUserRuntime").innerHTML =
      '<div class="empty-state">正在整理用户概况…</div>';
    document.getElementById("adminUserApprovals").innerHTML =
      '<div class="empty-state">正在查询最近审批…</div>';
    document.getElementById("adminUserConversations").innerHTML =
      '<div class="empty-state">正在加载最近会话…</div>';
  }

  function renderUserDetail(detail) {
    const user = detail?.user || {};
    const runtime = detail?.runtime || {};
    document.getElementById("adminUserDetailHint").textContent =
      `${user.username || "-"} · ${user.email || "-"} · 注册于 ${formatDate(
        user.created_at
      )}`;
    document.getElementById("adminUserRuntime").innerHTML = `
      <div class="detail-runtime-grid">
        <div class="detail-pill">
          <strong>用户角色</strong>
          <span>${safeText(user.role || "user")}</span>
        </div>
        <div class="detail-pill">
          <strong>总会话数</strong>
          <span>${user.conversation_count ?? 0}</span>
        </div>
        <div class="detail-pill">
          <strong>活跃会话</strong>
          <span>${runtime.active_conversation_count ?? 0}</span>
        </div>
        <div class="detail-pill">
          <strong>待处理审批</strong>
          <span>${runtime.pending_approval_count ?? 0}</span>
        </div>
      </div>
      <div class="detail-badges">
        ${renderStatusChip(user.role || "user")}
        ${
          runtime.latest_conversation_at
            ? `<span class="status-chip ready">最近会话更新于 ${formatDate(
                runtime.latest_conversation_at
              )}</span>`
            : ""
        }
      </div>
    `;

    const approvals = detail?.recent_approvals || [];
    document.getElementById("adminUserApprovals").innerHTML = approvals.length
      ? approvals
          .map(
            (approval) => `
              <div class="detail-approval-card">
                <strong>${safeText(approval.label || approval.action || "审批记录")}</strong>
                <p>${safeText(approval.reason || "未填写审批原因。")}</p>
                <small>${safeText(approval.approval_id, "")} · ${formatDate(approval.created_at)}</small>
                <div class="detail-badges">
                  ${renderStatusChip(approval.status || "none")}
                </div>
                <div class="approval-item-actions">
                  <button
                    class="row-action-btn"
                    type="button"
                    data-approval-events-id="${safeAttr(approval.approval_id)}"
                  >
                    查看轨迹
                  </button>
                </div>
                ${renderApprovalDecisionActions(approval)}
              </div>
            `
          )
          .join("")
      : '<div class="empty-state">这个用户当前没有可展示的审批记录。</div>';

    const keyword = state.filters.userDetailConversationQuery.trim().toLowerCase();
    const statusFilter = state.filters.userDetailConversationStatus;
    const conversations = (detail?.recent_conversations || []).filter((conversation) => {
      const statusMatch =
        statusFilter === "all" ||
        String(conversation.status || "").toLowerCase() === statusFilter;
      const keywordMatch =
        !keyword ||
        String(conversation.title || "").toLowerCase().includes(keyword);
      return statusMatch && keywordMatch;
    });
    document.getElementById("adminUserConversations").innerHTML = conversations.length
      ? conversations
          .map(
            (conversation) => `
              <div class="detail-message">
                <strong>${safeText(conversation.title || "未命名会话")} · ${formatDate(
                  conversation.updated_at
                )}</strong>
                <p>状态：${safeText(conversation.status || "unknown")} / 消息数：${
                  conversation.message_count ?? 0
                }</p>
                <div class="detail-badges">
                  ${renderStatusChip(conversation.role || "user")}
                </div>
                <div class="approval-item-actions">
                  <button
                    class="row-action-btn"
                    type="button"
                    data-conversation-detail-id="${safeAttr(conversation.id)}"
                  >
                    打开会话详情
                  </button>
                </div>
              </div>
            `
          )
          .join("")
      : '<div class="empty-state">这个用户在当前筛选条件下没有可展示的最近会话。</div>';
  }

  function renderConversations(conversations = []) {
    const tbody = document.getElementById("adminConversationsTable");
    if (!conversations.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="empty-state">当前没有可展示的会话记录。</td></tr>';
      renderListPager(
        "adminConversationsPager",
        state.pagination.conversations,
        0,
        "会话",
        "conversations"
      );
      renderConversationDetailEmpty("当前筛选结果里没有可展开的会话。");
      return;
    }
    tbody.innerHTML = conversations
      .map(
        (conversation) => `
          <tr>
            <td><strong>${safeText(conversation.title || "未命名会话")}</strong></td>
            <td>${safeText(conversation.username)}</td>
            <td>${renderStatusChip(conversation.role || "user")}</td>
            <td>${renderStatusChip(conversation.status || "unknown")}</td>
            <td>${conversation.message_count ?? 0}</td>
            <td>${formatDate(conversation.updated_at)}</td>
            <td>
              <button
                class="row-action-btn"
                type="button"
                data-conversation-detail-id="${safeAttr(conversation.id)}"
              >
                查看详情
              </button>
            </td>
          </tr>
        `
      )
      .join("");
    renderListPager(
      "adminConversationsPager",
      state.pagination.conversations,
      conversations.length,
      "会话",
      "conversations"
    );
  }

  function renderConversationDetailEmpty(message) {
    document.getElementById("adminConversationDetailHint").textContent = message;
    document.getElementById("adminConversationRuntime").innerHTML =
      '<div class="empty-state">还没有选中会话。</div>';
    document.getElementById("adminConversationApprovals").innerHTML =
      '<div class="empty-state">选中会话后显示相关审批记录。</div>';
    document.getElementById("adminConversationMessages").innerHTML =
      '<div class="empty-state">选中会话后显示最近消息摘要。</div>';
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

  function renderApprovalEvents() {
    const container = document.getElementById("adminApprovalEvents");
    if (!state.selectedApprovalId) {
      container.innerHTML =
        '<div class="empty-state">点开一条审批记录后，这里会显示状态变化轨迹。</div>';
      return;
    }
    if (!state.approvalEvents.length) {
      container.innerHTML =
        '<div class="empty-state">这条审批记录当前没有返回事件轨迹。</div>';
      return;
    }
    container.innerHTML = state.approvalEvents
      .map(
        (event) => `
          <div class="detail-approval-card">
            <strong>${safeText(formatApprovalEventType(event.event_type))} · ${
              safeText(event.from_status || "none")
            } → ${safeText(event.to_status || "unknown")}</strong>
            <p>${safeText(event.reason || "这一步没有附加说明。")}</p>
            <small>${formatDate((event.created_at || 0) * 1000)}</small>
          </div>
        `
      )
      .join("");
  }

  function renderConversationDetailLoading() {
    document.getElementById("adminConversationDetailHint").textContent =
      "正在加载会话详情…";
    document.getElementById("adminConversationRuntime").innerHTML =
      '<div class="empty-state">正在整理运行摘要…</div>';
    document.getElementById("adminConversationApprovals").innerHTML =
      '<div class="empty-state">正在查询关联审批…</div>';
    document.getElementById("adminConversationMessages").innerHTML =
      '<div class="empty-state">正在加载最近消息…</div>';
  }

  function renderConversationDetail(detail) {
    const runtime = detail?.runtime || {};
    const conversation = detail?.conversation || {};
    document.getElementById("adminConversationDetailHint").textContent =
      `${conversation.title || "未命名会话"} · ${conversation.username || "-"} · 最近更新 ${formatDate(
        conversation.updated_at
      )}`;
    document.getElementById("adminConversationRuntime").innerHTML = `
      <div class="detail-runtime-grid">
        <div class="detail-pill">
          <strong>当前工作流</strong>
          <span>${safeText(runtime.active_workflow)}</span>
        </div>
        <div class="detail-pill">
          <strong>当前阶段</strong>
          <span>${safeText(runtime.current_step)}</span>
        </div>
        <div class="detail-pill">
          <strong>消息分布</strong>
          <span>user ${runtime.message_breakdown?.user || 0} / assistant ${
            runtime.message_breakdown?.assistant || 0
          } / system ${runtime.message_breakdown?.system || 0}</span>
        </div>
        <div class="detail-pill">
          <strong>结构化产物</strong>
          <span>旅程草案 ${runtime.has_latest_journey ? "已保存" : "未发现"} / 最终报告 ${
            runtime.has_final_report ? "已生成" : "未发现"
          }</span>
        </div>
      </div>
      <div class="detail-badges">
        ${
          runtime.latest_journey_saved_at
            ? `<span class="status-chip ready">旅程草案保存于 ${formatDate(
                runtime.latest_journey_saved_at * 1000
              )}</span>`
            : ""
        }
        ${
          runtime.latest_report_title
            ? `<span class="status-chip approved">报告：${safeText(runtime.latest_report_title)}</span>`
            : ""
        }
        <span class="status-chip ${safeStatusClass(conversation.status)}">${
          safeText(conversation.status || "unknown")
        }</span>
      </div>
    `;

    const approvals = detail?.related_approvals || [];
    document.getElementById("adminConversationApprovals").innerHTML = approvals.length
      ? approvals
          .map(
            (approval) => `
              <div class="detail-approval-card">
                <strong>${safeText(approval.label || approval.action || "审批记录")}</strong>
                <p>${safeText(approval.reason || "未填写审批原因。")}</p>
                <small>
                  ${safeText(approval.approval_id, "")} · ${safeText(approval.action)} · ${formatDate(
                    approval.created_at
                  )}
                </small>
                <div class="detail-badges">
                  ${renderStatusChip(approval.status || "none")}
                </div>
                <div class="approval-item-actions">
                  <button
                    class="row-action-btn"
                    type="button"
                    data-approval-events-id="${safeAttr(approval.approval_id)}"
                  >
                    查看轨迹
                  </button>
                </div>
                ${renderApprovalDecisionActions(approval)}
              </div>
            `
          )
          .join("")
      : '<div class="empty-state">这个会话当前没有关联审批记录。</div>';

    const messages = detail?.recent_messages || [];
    document.getElementById("adminConversationMessages").innerHTML = messages.length
      ? messages
          .map(
            (message) => `
              <div class="detail-message">
                <strong>${safeText(message.role || "unknown")} · ${formatDate(message.created_at)}</strong>
                <p>${safeText(message.content_preview || "无摘要")}</p>
                <div class="detail-badges">
                  ${message.has_journey_data ? '<span class="status-chip ready">含旅程草案</span>' : ""}
                  ${message.has_report_data ? '<span class="status-chip approved">含最终报告</span>' : ""}
                </div>
              </div>
            `
          )
          .join("")
      : '<div class="empty-state">这个会话还没有可展示的最近消息。</div>';
  }

  function renderApprovals(approvals = []) {
    const container = document.getElementById("adminApprovalsList");
    if (!approvals.length) {
      container.innerHTML = '<div class="empty-state">当前没有审批记录。</div>';
      renderListPager(
        "adminApprovalsPager",
        state.pagination.approvals,
        0,
        "审批",
        "approvals"
      );
      return;
    }
    container.innerHTML = approvals
      .map(
        (approval) => `
          <div class="approval-item">
            <h4>${safeText(approval.label || approval.action || "审批记录")}</h4>
            <p>${safeText(approval.reason || "未填写审批原因。")}</p>
            <div class="approval-meta">
              <span>${renderStatusChip(approval.status || "none")}</span>
              <span>动作：${safeText(approval.action)}</span>
              <span>创建时间：${formatDate(approval.created_at)}</span>
            </div>
            <div class="approval-item-actions">
              <button
                class="row-action-btn"
                type="button"
                data-approval-events-id="${safeAttr(approval.approval_id)}"
              >
                查看轨迹
              </button>
              ${
                approval.conversation_id
                  ? `<button
                      class="row-action-btn"
                      type="button"
                      data-approval-conversation-id="${safeAttr(approval.conversation_id)}"
                    >
                      打开关联会话
                    </button>`
                  : ""
              }
            </div>
            ${renderApprovalDecisionActions(approval)}
          </div>
        `
      )
      .join("");
    renderListPager(
      "adminApprovalsPager",
      state.pagination.approvals,
      approvals.length,
      "审批",
      "approvals"
    );
  }

  function syncFiltersFromUi() {
    state.filters.userQuery =
      document.getElementById("adminUserSearch")?.value?.trim() || "";
    state.filters.userRole =
      document.getElementById("adminUserRoleFilter")?.value || "all";
    state.filters.userDetailConversationQuery =
      document.getElementById("adminUserConversationSearch")?.value?.trim() || "";
    state.filters.userDetailConversationStatus =
      document.getElementById("adminUserConversationStatusFilter")?.value || "all";
    state.filters.conversationQuery =
      document.getElementById("adminConversationSearch")?.value?.trim() || "";
    state.filters.conversationRole =
      document.getElementById("adminConversationRoleFilter")?.value || "all";
    state.filters.conversationStatus =
      document.getElementById("adminConversationStatusFilter")?.value || "active";
    state.filters.approvalQuery =
      document.getElementById("adminApprovalSearch")?.value?.trim() || "";
    state.filters.approvalStatus =
      document.getElementById("adminApprovalStatusFilter")?.value || "all";
    syncApprovalQuickFilterUi();
  }

  async function loadConversationDetail(conversationId) {
    state.selectedConversationId = conversationId || "";
    if (!state.selectedConversationId) {
      renderConversationDetailEmpty("点开任意会话后，这里会显示运行摘要、最近消息和关联审批。");
      return;
    }
    renderConversationDetailLoading();
    try {
      const detailResult = await adminApi.fetchAdminConversationDetail({
        apiBase: getApiBase(),
        stateToken: state.token,
        conversationId: state.selectedConversationId,
      });
      if (!detailResult.response.ok) {
        throw new Error(
          detailResult.data?.detail?.message ||
            `conversation-detail-${detailResult.response.status}`
        );
      }
      renderConversationDetail(detailResult.data);
    } catch (error) {
      console.error(error);
      renderConversationDetailEmpty(
        `会话详情加载失败：${error.message || "请稍后再试。"}`
      );
    }
  }

  async function loadUserDetail(userId) {
    state.selectedUserId = userId || "";
    if (!state.selectedUserId) {
      renderUserDetailEmpty("点开任意用户后，这里会显示用户概况、最近会话和最近审批。");
      return;
    }
    renderUserDetailLoading();
    try {
      const result = await adminApi.fetchAdminUserDetail({
        apiBase: getApiBase(),
        stateToken: state.token,
        userId: state.selectedUserId,
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message || `user-detail-${result.response.status}`
        );
      }
      state.selectedUserDetail = result.data;
      renderUserDetail(result.data);
    } catch (error) {
      console.error(error);
      renderUserDetailEmpty(
        `用户详情加载失败：${error.message || "请稍后再试。"}`
      );
    }
  }

  async function loadApprovalEvents(approvalId) {
    state.selectedApprovalId = approvalId || "";
    if (!state.selectedApprovalId) {
      state.approvalEvents = [];
      renderApprovalEvents();
      return;
    }
    document.getElementById("adminApprovalEvents").innerHTML =
      '<div class="empty-state">正在加载审批事件轨迹…</div>';
    try {
      const result = await governanceApi.fetchApprovalEvents({
        apiBase: getApiBase(),
        stateToken: state.token,
        approvalId: state.selectedApprovalId,
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message || `approval-events-${result.response.status}`
        );
      }
      state.approvalEvents = Array.isArray(result.data?.events)
        ? result.data.events
        : [];
      renderApprovalEvents();
    } catch (error) {
      console.error(error);
      state.approvalEvents = [];
      document.getElementById("adminApprovalEvents").innerHTML = `
        <div class="empty-state">审批事件加载失败：${safeText(error.message || "请稍后再试。")}</div>
      `;
    }
  }

  async function decideApproval(approvalId, decision) {
    if (
      !approvalId ||
      !["approve", "reject", "expire"].includes(decision) ||
      state.approvalActionPendingId
    ) {
      return;
    }
    const decisionPath =
      decision === "approve"
        ? "approve"
        : decision === "reject"
          ? "reject"
          : "expire";
    const reasonMap = {
      approve: "人工批准：确认当前仍不触发真实支付或预订。",
      reject: "人工拒绝：真实供应链未接入。",
      expire: "",
    };
    state.approvalActionPendingId = approvalId;
    document.getElementById("adminApprovalEvents").innerHTML =
      '<div class="empty-state">正在提交审批动作…</div>';
    try {
      const result = await governanceApi.submitApprovalDecision({
        apiBase: getApiBase(),
        stateToken: state.token,
        approvalId,
        decisionPath,
        reason: reasonMap[decision],
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message ||
            result.data?.detail ||
            `approval-decision-${result.response.status}`
        );
      }
      state.selectedApprovalId = result.data?.approval_id || approvalId;
      await loadAdminApprovals();
      await loadApprovalEvents(result.data?.approval_id || approvalId);
    } catch (error) {
      console.error(error);
      document.getElementById("adminApprovalEvents").innerHTML = `
        <div class="empty-state">审批处理失败：${safeText(error.message || "请稍后再试。")}</div>
      `;
    } finally {
      state.approvalActionPendingId = "";
    }
  }

  async function loadAdminUsers({ resetOffset = false } = {}) {
    syncFiltersFromUi();
    if (resetOffset) {
      state.pagination.users.offset = 0;
    }
    renderUsersLoading();
    try {
      const result = await adminApi.fetchAdminUsers({
        apiBase: getApiBase(),
        stateToken: state.token,
        limit: state.pagination.users.limit,
        offset: state.pagination.users.offset,
        queryText: state.filters.userQuery,
        role: state.filters.userRole,
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message || `users-${result.response.status}`
        );
      }
      const users = result.data?.users || [];
      state.pagination.users.total = Number(result.data?.total || 0);
      state.pagination.users.offset = Number(result.data?.offset || 0);
      state.pagination.users.limit = Number(
        result.data?.limit || state.pagination.users.limit
      );
      if (
        !users.length &&
        state.pagination.users.total > 0 &&
        state.pagination.users.offset > 0
      ) {
        state.pagination.users.offset =
          Math.floor((state.pagination.users.total - 1) / state.pagination.users.limit) *
          state.pagination.users.limit;
        await loadAdminUsers();
        return;
      }
      renderUsers(users);
      const hasSelectedUser = users.some((item) => item.id === state.selectedUserId);
      if (hasSelectedUser) {
        await loadUserDetail(state.selectedUserId);
      } else if (users[0]?.id) {
        await loadUserDetail(users[0].id);
      } else {
        state.selectedUserId = "";
      }
    } catch (error) {
      console.error(error);
      state.pagination.users.total = 0;
      renderUsers([]);
      renderUserDetailEmpty(`用户列表加载失败：${error.message || "请稍后再试。"}`);
    }
  }

  async function loadAdminConversations({ resetOffset = false } = {}) {
    syncFiltersFromUi();
    if (resetOffset) {
      state.pagination.conversations.offset = 0;
    }
    renderConversationsLoading();
    try {
      const result = await adminApi.fetchAdminConversations({
        apiBase: getApiBase(),
        stateToken: state.token,
        limit: state.pagination.conversations.limit,
        offset: state.pagination.conversations.offset,
        status: state.filters.conversationStatus,
        queryText: state.filters.conversationQuery,
        role: state.filters.conversationRole,
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message ||
            `conversations-${result.response.status}`
        );
      }
      const conversations = result.data?.conversations || [];
      state.pagination.conversations.total = Number(result.data?.total || 0);
      state.pagination.conversations.offset = Number(result.data?.offset || 0);
      state.pagination.conversations.limit = Number(
        result.data?.limit || state.pagination.conversations.limit
      );
      if (
        !conversations.length &&
        state.pagination.conversations.total > 0 &&
        state.pagination.conversations.offset > 0
      ) {
        state.pagination.conversations.offset =
          Math.floor(
            (state.pagination.conversations.total - 1) /
              state.pagination.conversations.limit
          ) * state.pagination.conversations.limit;
        await loadAdminConversations();
        return;
      }
      renderConversations(conversations);
      const hasSelectedConversation = conversations.some(
        (item) => item.id === state.selectedConversationId
      );
      if (hasSelectedConversation) {
        await loadConversationDetail(state.selectedConversationId);
      } else if (conversations[0]?.id) {
        await loadConversationDetail(conversations[0].id);
      } else {
        state.selectedConversationId = "";
      }
    } catch (error) {
      console.error(error);
      state.pagination.conversations.total = 0;
      renderConversations([]);
      renderConversationDetailEmpty(
        `会话列表加载失败：${error.message || "请稍后再试。"}`
      );
    }
  }

  async function loadAdminApprovals({ resetOffset = false } = {}) {
    syncFiltersFromUi();
    if (resetOffset) {
      state.pagination.approvals.offset = 0;
    }
    try {
      const result = await governanceApi.fetchApprovals({
        apiBase: getApiBase(),
        stateToken: state.token,
        filter:
          state.filters.approvalStatus === "all"
            ? "all"
            : state.filters.approvalStatus,
        canRequestAll: true,
        limit: state.pagination.approvals.limit,
        offset: state.pagination.approvals.offset,
        queryText: state.filters.approvalQuery,
      });
      if (!result.response.ok) {
        throw new Error(
          result.data?.detail?.message ||
            result.data?.detail ||
            `approvals-${result.response.status}`
        );
      }
      state.approvals = result.data?.approvals || [];
      state.pagination.approvals.total = Number(result.data?.total || 0);
      state.pagination.approvals.offset = Number(result.data?.offset || 0);
      state.pagination.approvals.limit = Number(
        result.data?.limit || state.pagination.approvals.limit
      );
      if (
        !state.approvals.length &&
        state.pagination.approvals.total > 0 &&
        state.pagination.approvals.offset > 0
      ) {
        state.pagination.approvals.offset =
          Math.floor(
            (state.pagination.approvals.total - 1) /
              state.pagination.approvals.limit
          ) * state.pagination.approvals.limit;
        await loadAdminApprovals();
        return;
      }
      renderApprovals(state.approvals);
      if (
        state.selectedApprovalId &&
        state.approvals.some((item) => item.approval_id === state.selectedApprovalId)
      ) {
        await loadApprovalEvents(state.selectedApprovalId);
      } else {
        state.selectedApprovalId = "";
        state.approvalEvents = [];
        renderApprovalEvents();
      }
    } catch (error) {
      console.error(error);
      state.approvals = [];
      state.pagination.approvals.total = 0;
      renderApprovals([]);
      state.selectedApprovalId = "";
      state.approvalEvents = [];
      document.getElementById("adminApprovalEvents").innerHTML = `
        <div class="empty-state">审批记录加载失败：${safeText(error.message || "请稍后再试。")}</div>
      `;
    }
  }

  async function loadDashboard() {
    const refreshBtn = document.getElementById("refreshDashboardBtn");
    refreshBtn.disabled = true;
    syncFiltersFromUi();

    const restored = await sessionApi.restoreSessionFromCookie({
      apiBase: getApiBase(),
      stateToken: state.token,
    });
    state.user = restored.ok ? restored.user : null;

    if (!state.user) {
      setAdminState(
        "未检测到登录会话",
        "请先在旅行工作台登录，再返回这里查看后台数据。"
      );
      resetListPagination();
      renderOverview(null);
      renderUsers([]);
      renderConversations([]);
      renderApprovals([]);
      renderUserDetailEmpty("请先登录旅行工作台，再查看后台用户详情。");
      renderConversationDetailEmpty("请先登录旅行工作台，再查看后台会话详情。");
      refreshBtn.disabled = false;
      return;
    }

    const role = normalizeRole(state.user);
    if (!canAccessAdmin(state.user)) {
      setAdminState(
        `${state.user.username || "当前账号"} 无后台权限`,
        "当前账号不是审批员或管理员，因此不会加载后台管理数据。"
      );
      resetListPagination();
      renderOverview(null);
      renderUsers([]);
      renderConversations([]);
      renderApprovals([]);
      renderUserDetailEmpty("当前账号没有后台权限，无法查看用户详情。");
      renderConversationDetailEmpty("当前账号没有后台权限，无法查看会话详情。");
      refreshBtn.disabled = false;
      return;
    }

    setAdminState(
      `${state.user.username || "当前账号"} · ${role}`,
      "后台管理台已连接，下面展示脱敏后的内部管理摘要。"
    );

    try {
      const overviewResult = await adminApi.fetchAdminOverview({
        apiBase: getApiBase(),
        stateToken: state.token,
      });

      if (!overviewResult.response.ok) {
        throw new Error(
          overviewResult.data?.detail?.message ||
            `overview-${overviewResult.response.status}`
        );
      }

      renderOverview(overviewResult.data);
      await Promise.all([
        loadAdminUsers(),
        loadAdminConversations(),
        loadAdminApprovals(),
      ]);
    } catch (error) {
      console.error(error);
      setAdminState(
        `${state.user.username || "当前账号"} · ${role}`,
        `后台数据加载失败：${error.message || "请稍后再试。"}`
      );
      renderUserDetailEmpty("后台主数据加载失败，用户详情区域暂不可用。");
      renderConversationDetailEmpty("后台主数据加载失败，详情区域暂不可用。");
      state.selectedApprovalId = "";
      state.approvalEvents = [];
      state.approvals = [];
      renderApprovalEvents();
      renderApprovals([]);
    } finally {
      refreshBtn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document
      .getElementById("refreshDashboardBtn")
      .addEventListener("click", loadDashboard);
    function bindScopedFilter(id, refreshHandler) {
      const element = document.getElementById(id);
      if (!element) return;
      element.addEventListener("change", refreshHandler);
      element.addEventListener("input", (event) => {
        if (!event.target.matches("input[type='search']")) return;
        window.clearTimeout(event.target._refreshTimer);
        event.target._refreshTimer = window.setTimeout(refreshHandler, 220);
      });
    }

    ["adminUserSearch", "adminUserRoleFilter"].forEach((id) => {
      bindScopedFilter(id, () => loadAdminUsers({ resetOffset: true }));
    });
    [
      "adminConversationSearch",
      "adminConversationRoleFilter",
      "adminConversationStatusFilter",
    ].forEach((id) => {
      bindScopedFilter(id, () => loadAdminConversations({ resetOffset: true }));
    });
    ["adminUserConversationSearch", "adminUserConversationStatusFilter"].forEach((id) => {
      bindScopedFilter(id, () => {
        syncFiltersFromUi();
        if (state.selectedUserDetail) {
          renderUserDetail(state.selectedUserDetail);
        }
      });
    });
    bindScopedFilter("adminApprovalSearch", () =>
      loadAdminApprovals({ resetOffset: true })
    );
    bindScopedFilter("adminApprovalStatusFilter", () =>
      loadAdminApprovals({ resetOffset: true })
    );
    ["adminUsersPager", "adminConversationsPager", "adminApprovalsPager"].forEach((id) => {
      document.getElementById(id)?.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-page-target]");
        if (!button || button.disabled) return;
        const target = button.dataset.pageTarget;
        const direction = button.dataset.pageDirection;
        const pagination = state.pagination[target];
        if (!pagination) return;
        const nextOffset =
          direction === "prev"
            ? Math.max(0, pagination.offset - pagination.limit)
            : pagination.offset + pagination.limit;
        if (nextOffset < 0 || nextOffset >= Math.max(pagination.total, 1)) return;
        pagination.offset = nextOffset;
        if (target === "users") {
          await loadAdminUsers();
        } else if (target === "conversations") {
          await loadAdminConversations();
        } else if (target === "approvals") {
          await loadAdminApprovals();
        }
      });
    });
    document
      .getElementById("adminUsersTable")
      .addEventListener("click", async (event) => {
        const button = event.target.closest("[data-user-detail-id]");
        if (!button) return;
        await loadUserDetail(button.dataset.userDetailId);
      });
    document
      .getElementById("adminConversationsTable")
      .addEventListener("click", async (event) => {
        const button = event.target.closest("[data-conversation-detail-id]");
        if (!button) return;
        await loadConversationDetail(button.dataset.conversationDetailId);
      });
    document
      .getElementById("adminApprovalQuickAll")
      .addEventListener("click", async () => {
        document.getElementById("adminApprovalStatusFilter").value = "all";
        await loadAdminApprovals({ resetOffset: true });
      });
    document
      .getElementById("adminApprovalQuickPending")
      .addEventListener("click", async () => {
        document.getElementById("adminApprovalStatusFilter").value = "pending";
        await loadAdminApprovals({ resetOffset: true });
      });
    document.body.addEventListener("click", async (event) => {
      const decisionButton = event.target.closest("[data-approval-decision]");
      if (decisionButton) {
        await decideApproval(
          decisionButton.dataset.approvalId,
          decisionButton.dataset.approvalDecision
        );
        return;
      }
      const approvalButton = event.target.closest("[data-approval-events-id]");
      if (approvalButton) {
        await loadApprovalEvents(approvalButton.dataset.approvalEventsId);
        return;
      }
      const conversationButton = event.target.closest(
        "[data-approval-conversation-id]"
      );
      if (conversationButton) {
        await loadConversationDetail(conversationButton.dataset.approvalConversationId);
      }
    });
    document
      .getElementById("closeConversationDetailBtn")
      .addEventListener("click", () => {
        state.selectedConversationId = "";
        renderConversationDetailEmpty(
          "点开任意会话后，这里会显示运行摘要、最近消息和关联审批。"
        );
      });
    renderConversationDetailEmpty(
      "点开任意会话后，这里会显示运行摘要、最近消息和关联审批。"
    );
    renderUserDetailEmpty(
      "点开任意用户后，这里会显示用户概况、最近会话和最近审批。"
    );
    syncApprovalQuickFilterUi();
    renderApprovalEvents();
    await loadDashboard();
  });
})();
