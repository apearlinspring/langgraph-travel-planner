(function (global) {
  const sessionApi = global.ZhiXingSessionApi;
  const { requestJson } = sessionApi;

  async function fetchConversations({ apiBase, stateToken = "" }) {
    return requestJson(
      `${apiBase}/api/v1/conversations`,
      stateToken
    );
  }

  async function createConversation({ apiBase, stateToken = "", title }) {
    return requestJson(
      `${apiBase}/api/v1/conversations`,
      stateToken,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title }),
      }
    );
  }

  async function updateConversation({ apiBase, stateToken = "", id, payload }) {
    return requestJson(
      `${apiBase}/api/v1/conversations/${id}`,
      stateToken,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );
  }

  async function deleteConversation({ apiBase, stateToken = "", id }) {
    return requestJson(
      `${apiBase}/api/v1/conversations/${id}`,
      stateToken,
      {
        method: "DELETE",
      }
    );
  }

  async function fetchConversationDetail({ apiBase, stateToken = "", id }) {
    return requestJson(
      `${apiBase}/api/v1/conversations/${id}`,
      stateToken
    );
  }

  async function fetchChatHistory({ apiBase, stateToken = "", id }) {
    return requestJson(
      `${apiBase}/api/v1/chat/history/${id}`,
      stateToken
    );
  }

  async function openChatStream({ apiBase, stateToken = "", conversationId, content }) {
    return fetch(
      `${apiBase}/api/v1/chat/stream/${conversationId}`,
      sessionApi.buildApiRequestOptions(stateToken, {
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
    return requestJson(
      `${apiBase}/api/v1/chat/journey/${conversationId}`,
      stateToken,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          journey_data: journeyData,
          source: "frontend_visual_editor",
        }),
      }
    );
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
