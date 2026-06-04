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

  async function fetchConversations({ apiBase, stateToken = "" }) {
    const response = await fetch(
      `${apiBase}/api/v1/conversations`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function createConversation({ apiBase, stateToken = "", title }) {
    const response = await fetch(
      `${apiBase}/api/v1/conversations`,
      buildOptions(stateToken, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title }),
      })
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function updateConversation({ apiBase, stateToken = "", id, payload }) {
    const response = await fetch(
      `${apiBase}/api/v1/conversations/${id}`,
      buildOptions(stateToken, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      })
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function deleteConversation({ apiBase, stateToken = "", id }) {
    const response = await fetch(
      `${apiBase}/api/v1/conversations/${id}`,
      buildOptions(stateToken, {
        method: "DELETE",
      })
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function fetchConversationDetail({ apiBase, stateToken = "", id }) {
    const response = await fetch(
      `${apiBase}/api/v1/conversations/${id}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function fetchChatHistory({ apiBase, stateToken = "", id }) {
    const response = await fetch(
      `${apiBase}/api/v1/chat/history/${id}`,
      buildOptions(stateToken)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function openChatStream({ apiBase, stateToken = "", conversationId, content }) {
    return fetch(
      `${apiBase}/api/v1/chat/stream/${conversationId}`,
      buildOptions(stateToken, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content }),
      })
    );
  }

  async function saveJourneyDraft({
    apiBase,
    stateToken = "",
    conversationId,
    journeyData,
  }) {
    const response = await fetch(
      `${apiBase}/api/v1/chat/journey/${conversationId}`,
      buildOptions(stateToken, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          journey_data: journeyData,
          source: "frontend_visual_editor",
        }),
      })
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  global.ZhiXingConversationApi = {
    fetchConversations,
    createConversation,
    updateConversation,
    deleteConversation,
    fetchConversationDetail,
    fetchChatHistory,
    openChatStream,
    saveJourneyDraft,
  };
})(window);
