(function (global) {
  const { requestJson } = global.ZhiXingSessionApi;

  async function fetchGuideUrl({ apiBase, stateToken = "", url }) {
    return requestJson(
      `${apiBase}/api/v1/guide-import/fetch`,
      stateToken,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      }
    );
  }

  global.ZhiXingGuideImportApi = {
    fetchGuideUrl,
  };
})(window);
