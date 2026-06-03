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
    approvalEvents: [],
    approvalActionPendingId: "",
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

  function renderStatusChip(status = "") {
    const normalized = String(status || "unknown").toLowerCase();
    return `<span class="status-chip ${normalized}">${status || "unknown"}</span>`;
  }

  function renderApprovalDecisionActions(approval) {
    if (String(approval?.status || "").toLowerCase() !== "pending") return "";
    return `
      <div class="approval-item-actions">
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="approve"
          data-approval-id="${approval.approval_id || ""}"
        >
          批准
        </button>
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="reject"
          data-approval-id="${approval.approval_id || ""}"
        >
          拒绝
        </button>
        <button
          class="row-action-btn"
          type="button"
          data-approval-decision="expire"
          data-approval-id="${approval.approval_id || ""}"
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

  function renderUsers(users = []) {
    const tbody = document.getElementById("adminUsersTable");
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">当前没有可展示的用户记录。</td></tr>';
      renderUserDetailEmpty("当前筛选结果里没有可展开的用户。");
      return;
    }
    tbody.innerHTML = users
      .map(
        (user) => `
          <tr>
            <td><strong>${user.username || "-"}</strong></td>
            <td>${user.email || "-"}</td>
            <td>${renderStatusChip(user.role || "user")}</td>
            <td>${user.conversation_count ?? 0}</td>
            <td>${formatDate(user.created_at)}</td>
            <td>
              <button
                class="row-action-btn"
                type="button"
                data-user-detail-id="${user.id}"
              >
                查看用户
              </button>
            </td>
          </tr>
        `
      )
      .join("");
  }

  function renderUserDetailEmpty(message) {
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
          <span>${user.role || "user"}</span>
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
                <strong>${approval.label || approval.action || "审批记录"}</strong>
                <p>${approval.reason || "未填写审批原因。"}</p>
                <small>${approval.approval_id} · ${formatDate(approval.created_at)}</small>
                <div class="detail-badges">
                  ${renderStatusChip(approval.status || "none")}
                </div>
                <div class="approval-item-actions">
                  <button
                    class="row-action-btn"
                    type="button"
                    data-approval-events-id="${approval.approval_id || ""}"
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
                <strong>${conversation.title || "未命名会话"} · ${formatDate(
                  conversation.updated_at
                )}</strong>
                <p>状态：${conversation.status || "unknown"} / 消息数：${
                  conversation.message_count ?? 0
                }</p>
                <div class="detail-badges">
                  ${renderStatusChip(conversation.role || "user")}
                </div>
                <div class="approval-item-actions">
                  <button
                    class="row-action-btn"
                    type="button"
                    data-conversation-detail-id="${conversation.id}"
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
      renderConversationDetailEmpty("当前筛选结果里没有可展开的会话。");
      return;
    }
    tbody.innerHTML = conversations
      .map(
        (conversation) => `
          <tr>
            <td><strong>${conversation.title || "未命名会话"}</strong></td>
            <td>${conversation.username || "-"}</td>
            <td>${renderStatusChip(conversation.role || "user")}</td>
            <td>${renderStatusChip(conversation.status || "unknown")}</td>
            <td>${conversation.message_count ?? 0}</td>
            <td>${formatDate(conversation.updated_at)}</td>
            <td>
              <button
                class="row-action-btn"
                type="button"
                data-conversation-detail-id="${conversation.id}"
              >
                查看详情
              </button>
            </td>
          </tr>
        `
      )
      .join("");
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
            <strong>${formatApprovalEventType(event.event_type)} · ${
              event.from_status || "none"
            } → ${event.to_status || "unknown"}</strong>
            <p>${event.reason || "这一步没有附加说明。"}</p>
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
          <span>${runtime.active_workflow || "-"}</span>
        </div>
        <div class="detail-pill">
          <strong>当前阶段</strong>
          <span>${runtime.current_step || "-"}</span>
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
            ? `<span class="status-chip approved">报告：${runtime.latest_report_title}</span>`
            : ""
        }
        <span class="status-chip ${conversation.status || "unknown"}">${
          conversation.status || "unknown"
        }</span>
      </div>
    `;

    const approvals = detail?.related_approvals || [];
    document.getElementById("adminConversationApprovals").innerHTML = approvals.length
      ? approvals
          .map(
            (approval) => `
              <div class="detail-approval-card">
                <strong>${approval.label || approval.action || "审批记录"}</strong>
                <p>${approval.reason || "未填写审批原因。"}</p>
                <small>
                  ${approval.approval_id} · ${approval.action || "-"} · ${formatDate(
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
                    data-approval-events-id="${approval.approval_id || ""}"
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
                <strong>${message.role || "unknown"} · ${formatDate(message.created_at)}</strong>
                <p>${message.content_preview || "无摘要"}</p>
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
    const filteredApprovals = approvals.filter((approval) => {
      const statusMatch =
        state.filters.approvalStatus === "all" ||
        String(approval.status || "").toLowerCase() === state.filters.approvalStatus;
      const keyword = state.filters.approvalQuery.trim().toLowerCase();
      const keywordMatch =
        !keyword ||
        [approval.label, approval.action, approval.reason]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(keyword));
      return statusMatch && keywordMatch;
    });
    if (!filteredApprovals.length) {
      container.innerHTML = '<div class="empty-state">当前没有审批记录。</div>';
      return;
    }
    container.innerHTML = filteredApprovals
      .map(
        (approval) => `
          <div class="approval-item">
            <h4>${approval.label || approval.action || "审批记录"}</h4>
            <p>${approval.reason || "未填写审批原因。"}</p>
            <div class="approval-meta">
              <span>${renderStatusChip(approval.status || "none")}</span>
              <span>动作：${approval.action || "-"}</span>
              <span>创建时间：${formatDate(approval.created_at)}</span>
            </div>
            <div class="approval-item-actions">
              <button
                class="row-action-btn"
                type="button"
                data-approval-events-id="${approval.approval_id || ""}"
              >
                查看轨迹
              </button>
              ${
                approval.conversation_id
                  ? `<button
                      class="row-action-btn"
                      type="button"
                      data-approval-conversation-id="${approval.conversation_id}"
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
        <div class="empty-state">审批事件加载失败：${error.message || "请稍后再试。"}</div>
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
      await loadDashboard();
      await loadApprovalEvents(state.selectedApprovalId);
    } catch (error) {
      console.error(error);
      document.getElementById("adminApprovalEvents").innerHTML = `
        <div class="empty-state">审批处理失败：${error.message || "请稍后再试。"}</div>
      `;
    } finally {
      state.approvalActionPendingId = "";
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
      renderOverview(null);
      renderUsers([]);
      renderConversations([]);
      renderApprovals([]);
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
      renderOverview(null);
      renderUsers([]);
      renderConversations([]);
      renderApprovals([]);
      renderConversationDetailEmpty("当前账号没有后台权限，无法查看会话详情。");
      refreshBtn.disabled = false;
      return;
    }

    setAdminState(
      `${state.user.username || "当前账号"} · ${role}`,
      "后台管理台已连接，下面展示脱敏后的内部管理摘要。"
    );

      try {
      const [overviewResult, usersResult, conversationsResult, approvalsResult] =
        await Promise.all([
          adminApi.fetchAdminOverview({
            apiBase: getApiBase(),
            stateToken: state.token,
          }),
          adminApi.fetchAdminUsers({
            apiBase: getApiBase(),
            stateToken: state.token,
            limit: 12,
            queryText: state.filters.userQuery,
            role: state.filters.userRole,
          }),
          adminApi.fetchAdminConversations({
            apiBase: getApiBase(),
            stateToken: state.token,
            limit: 12,
            status: state.filters.conversationStatus,
            queryText: state.filters.conversationQuery,
            role: state.filters.conversationRole,
          }),
          governanceApi.fetchApprovals({
            apiBase: getApiBase(),
            stateToken: state.token,
            filter:
              state.filters.approvalStatus === "all"
                ? "all"
                : state.filters.approvalStatus,
            canRequestAll: true,
          }),
        ]);

      if (!overviewResult.response.ok) {
        throw new Error(
          overviewResult.data?.detail?.message ||
            `overview-${overviewResult.response.status}`
        );
      }
      if (!usersResult.response.ok) {
        throw new Error(
          usersResult.data?.detail?.message || `users-${usersResult.response.status}`
        );
      }
      if (!conversationsResult.response.ok) {
        throw new Error(
          conversationsResult.data?.detail?.message ||
            `conversations-${conversationsResult.response.status}`
        );
      }
      if (!approvalsResult.response.ok) {
        throw new Error(
          approvalsResult.data?.detail?.message ||
            `approvals-${approvalsResult.response.status}`
        );
      }

      renderOverview(overviewResult.data);
      const users = usersResult.data?.users || [];
      renderUsers(users);
      const conversations = conversationsResult.data?.conversations || [];
      renderConversations(conversations);
      renderApprovals(approvalsResult.data?.approvals || []);
      const hasSelectedUser = users.some((item) => item.id === state.selectedUserId);
      if (hasSelectedUser) {
        await loadUserDetail(state.selectedUserId);
      } else if (users[0]?.id) {
        await loadUserDetail(users[0].id);
      } else {
        state.selectedUserId = "";
      }
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
      const approvals = approvalsResult.data?.approvals || [];
      if (
        state.selectedApprovalId &&
        approvals.some((item) => item.approval_id === state.selectedApprovalId)
      ) {
        await loadApprovalEvents(state.selectedApprovalId);
      } else {
        state.selectedApprovalId = "";
        state.approvalEvents = [];
        renderApprovalEvents();
      }
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
      renderApprovalEvents();
    } finally {
      refreshBtn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document
      .getElementById("refreshDashboardBtn")
      .addEventListener("click", loadDashboard);
    [
      "adminUserSearch",
      "adminUserRoleFilter",
      "adminUserConversationSearch",
      "adminUserConversationStatusFilter",
      "adminConversationSearch",
      "adminConversationRoleFilter",
      "adminConversationStatusFilter",
      "adminApprovalSearch",
      "adminApprovalStatusFilter",
    ].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", loadDashboard);
      document.getElementById(id)?.addEventListener("input", (event) => {
        if (event.target.matches("input[type='search']")) {
          window.clearTimeout(event.target._refreshTimer);
          event.target._refreshTimer = window.setTimeout(loadDashboard, 220);
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
        await loadDashboard();
      });
    document
      .getElementById("adminApprovalQuickPending")
      .addEventListener("click", async () => {
        document.getElementById("adminApprovalStatusFilter").value = "pending";
        await loadDashboard();
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
