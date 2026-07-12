(function (global) {
  const { requestJson } = global.ZhiXingSessionApi;

  async function fetchAdminOverview({ apiBase, stateToken = "" }) {
    return requestJson(
      `${apiBase}/api/v1/admin/overview`,
      stateToken
    );
  }

  async function fetchAdminUsers({
    apiBase,
    stateToken = "",
    limit = 20,
    offset = 0,
    queryText = "",
    role = "all",
  }) {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      role,
    });
    if (queryText.trim()) params.set("q", queryText.trim());
    return requestJson(
      `${apiBase}/api/v1/admin/users?${params}`,
      stateToken
    );
  }

  async function fetchAdminConversations({
    apiBase,
    stateToken = "",
    limit = 30,
    offset = 0,
    status = "active",
    queryText = "",
    role = "all",
  }) {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      status,
      role,
    });
    if (queryText.trim()) params.set("q", queryText.trim());
    return requestJson(
      `${apiBase}/api/v1/admin/conversations?${params}`,
      stateToken
    );
  }

  async function fetchAdminUserDetail({
    apiBase,
    stateToken = "",
    userId,
  }) {
    return requestJson(
      `${apiBase}/api/v1/admin/users/${encodeURIComponent(userId)}`,
      stateToken
    );
  }

  async function fetchAdminConversationDetail({
    apiBase,
    stateToken = "",
    conversationId,
  }) {
    return requestJson(
      `${apiBase}/api/v1/admin/conversations/${encodeURIComponent(conversationId)}`,
      stateToken
    );
  }

  global.ZhiXingAdminApi = {
    fetchAdminOverview,
    fetchAdminUsers,
    fetchAdminConversations,
    fetchAdminUserDetail,
    fetchAdminConversationDetail,
  };
})(window);
