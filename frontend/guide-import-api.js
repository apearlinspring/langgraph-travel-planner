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

  async function fetchGuideUrl({ apiBase, stateToken = "", url }) {
    const response = await fetch(
      `${apiBase}/api/v1/guide-import/fetch`,
      buildOptions(stateToken, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      })
    );
    return {
      response,
      data: await parseJsonSafe(response),
    };
  }

  global.ZhiXingGuideImportApi = {
    fetchGuideUrl,
  };
})(window);
