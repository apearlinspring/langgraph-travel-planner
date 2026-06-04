(function (global) {
  const sessionApi = global.ZhiXingSessionApi;

  async function parseJsonSafe(response) {
    try {
      return await response.json();
    } catch (error) {
      return null;
    }
  }

  function buildOptions(stateToken, options = {}) {
    return sessionApi.buildApiRequestOptions(stateToken, options);
  }

  async function fetchAdminOverview({ apiBase, stateToken = "" }) {
    const response = await fetch(
      `${apiBase}/api/v1/admin/overview`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
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
    const response = await fetch(
      `${apiBase}/api/v1/admin/users?${params}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
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
    const response = await fetch(
      `${apiBase}/api/v1/admin/conversations?${params}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function fetchAdminUserDetail({
    apiBase,
    stateToken = "",
    userId,
  }) {
    const response = await fetch(
      `${apiBase}/api/v1/admin/users/${encodeURIComponent(userId)}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function fetchAdminConversationDetail({
    apiBase,
    stateToken = "",
    conversationId,
  }) {
    const response = await fetch(
      `${apiBase}/api/v1/admin/conversations/${encodeURIComponent(conversationId)}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  global.ZhiXingAdminApi = {
    fetchAdminOverview,
    fetchAdminUsers,
    fetchAdminConversations,
    fetchAdminUserDetail,
    fetchAdminConversationDetail,
  };
})(window);
