(function (global) {
  function getRequestCredentials() {
    return "include";
  }

  function buildApiRequestOptions(stateToken, options = {}) {
    const {
      headers = {},
      attachAuth = true,
      credentials = getRequestCredentials(),
      ...rest
    } = options;
    const mergedHeaders = { ...headers };
    if (attachAuth && stateToken) {
      mergedHeaders.Authorization = `Bearer ${stateToken}`;
    }
    return {
      ...rest,
      headers: mergedHeaders,
      credentials,
    };
  }

  async function parseJsonSafe(response) {
    try {
      return await response.json();
    } catch (error) {
      return null;
    }
  }

  async function requestJson(url, stateToken = "", options = {}) {
    const response = await fetch(
      url,
      buildApiRequestOptions(stateToken, options)
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  async function restoreSessionFromCookie({ apiBase, stateToken = "" }) {
    try {
      const response = await fetch(
        `${apiBase}/api/v1/users/me`,
        buildApiRequestOptions(stateToken, { attachAuth: false })
      );
      if (!response.ok) {
        return {
          ok: false,
          unauthorized: response.status === 401,
          status: response.status,
          user: null,
        };
      }
      return {
        ok: true,
        unauthorized: false,
        status: response.status,
        user: await response.json(),
      };
    } catch (error) {
      return {
        ok: false,
        unauthorized: false,
        status: 0,
        user: null,
        error,
      };
    }
  }

  async function submitAuthForm({ apiBase, endpoint, body, stateToken = "" }) {
    return requestJson(
      `${apiBase}${endpoint}`,
      stateToken,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        attachAuth: false,
      }
    );
  }

  async function remoteLogout({ apiBase, stateToken = "" }) {
    return fetch(
      `${apiBase}/api/v1/users/logout`,
      buildApiRequestOptions(stateToken, {
        method: "POST",
        attachAuth: false,
      })
    );
  }

  global.ZhiXingSessionApi = {
    getRequestCredentials,
    buildApiRequestOptions,
    parseJsonSafe,
    requestJson,
    restoreSessionFromCookie,
    submitAuthForm,
    remoteLogout,
  };
})(window);
