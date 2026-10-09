(function (global) {
  const sessionApi = global.ZhiXingSessionApi;
  const conversationApi = global.ZhiXingConversationApi;

  let journeyMapAssetsPromise = null;
  let journeyAmapAssetsPromise = null;
  let journeyMapConfigPromise = null;
  let journeyMapRuntimeConfig = null;
  const journeyMapPreviewCache = new Map();

  function buildOptions(stateToken = "", options = {}) {
    return sessionApi.buildApiRequestOptions(stateToken, options);
  }

  function ensureStylesheet(href) {
    if (document.querySelector(`link[data-href="${href}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.dataset.href = href;
    document.head.appendChild(link);
  }

  function loadScriptOnce(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-src="${src}"]`);
      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", reject, { once: true });
        if (existing.dataset.loaded === "1") resolve();
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.dataset.src = src;
      script.onload = () => {
        script.dataset.loaded = "1";
        resolve();
      };
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function getFallbackJourneyMapConfig() {
    return {
      preferred_provider: "leaflet-osm",
      amap_web_js_key: "",
      amap_web_js_key_configured: false,
      fallback_provider: "leaflet-osm",
    };
  }

  async function loadJourneyMapAssets() {
    if (global.L) return global.L;
    if (!journeyMapAssetsPromise) {
      journeyMapAssetsPromise = (async () => {
        ensureStylesheet(
          "https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.css"
        );
        await loadScriptOnce(
          "https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.js"
        );
        return global.L;
      })().catch((error) => {
        journeyMapAssetsPromise = null;
        throw error;
      });
    }
    return journeyMapAssetsPromise;
  }

  async function fetchJourneyMapConfig({ apiBase, stateToken = "" }) {
    if (journeyMapRuntimeConfig) return journeyMapRuntimeConfig;
    if (!journeyMapConfigPromise) {
      journeyMapConfigPromise = (async () => {
        try {
          const response = await fetch(
            `${apiBase}/api/v1/maps/config`,
            buildOptions(stateToken)
          );
          if (!response.ok) throw new Error(`map-config-${response.status}`);
          const data = await response.json();
          journeyMapRuntimeConfig = {
            ...getFallbackJourneyMapConfig(),
            ...(data || {}),
          };
        } catch (error) {
          journeyMapRuntimeConfig = getFallbackJourneyMapConfig();
        }
        return journeyMapRuntimeConfig;
      })().finally(() => {
        journeyMapConfigPromise = null;
      });
    }
    return journeyMapConfigPromise;
  }

  async function loadAmapJourneyMapAssets(webKey = "") {
    const key = String(webKey || "").trim();
    if (!key) return null;
    if (global.AMap) return global.AMap;
    if (!journeyAmapAssetsPromise) {
      journeyAmapAssetsPromise = loadScriptOnce(
        `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(
          key
        )}&plugin=AMap.Scale,AMap.ToolBar`
      )
        .then(() => global.AMap || null)
        .catch((error) => {
          journeyAmapAssetsPromise = null;
          throw error;
        });
    }
    return journeyAmapAssetsPromise;
  }

  async function fetchJourneyMapPreview({
    apiBase,
    stateToken = "",
    payload,
  }) {
    const cacheKey = JSON.stringify(payload || {});
    const cached = journeyMapPreviewCache.get(cacheKey);
    const now = Date.now();
    if (cached?.data && now - cached.timestamp < 10 * 60 * 1000) {
      return JSON.parse(JSON.stringify(cached.data));
    }
    if (cached?.promise) {
      return cached.promise;
    }
    const requestPromise = (async () => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 12000);
      const startedAt = performance.now();
      let response;
      try {
        response = await fetch(
          `${apiBase}/api/v1/maps/preview`,
          buildOptions(stateToken, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
            signal: controller.signal,
          })
        );
        if (!response.ok) {
          throw new Error(`map-preview-${response.status}`);
        }
      } finally {
        clearTimeout(timeoutId);
      }
      const data = await response.json();
      data.client_elapsed_seconds = Number(
        ((performance.now() - startedAt) / 1000).toFixed(3)
      );
      if (data.status === "degraded") {
        console.warn("Map preview degraded", {
          elapsedSeconds: data.client_elapsed_seconds,
          serverElapsedSeconds: data.elapsed_seconds,
          message: data.message,
        });
      }
      journeyMapPreviewCache.set(cacheKey, {
        data,
        timestamp: Date.now(),
      });
      return data;
    })().catch((error) => {
      journeyMapPreviewCache.delete(cacheKey);
      if (error?.name === "AbortError") {
        console.warn("Map preview aborted after 12s", { payload });
      }
      throw error;
    });
    journeyMapPreviewCache.set(cacheKey, {
      promise: requestPromise,
      timestamp: now,
    });
    return requestPromise;
  }

  async function saveJourneyDraft({
    apiBase,
    stateToken = "",
    conversationId,
    journeyData,
  }) {
    return conversationApi.saveJourneyDraft({
      apiBase,
      stateToken,
      conversationId,
      journeyData,
    });
  }

  global.ZhiXingJourneyApi = {
    getFallbackJourneyMapConfig,
    loadJourneyMapAssets,
    fetchJourneyMapConfig,
    loadAmapJourneyMapAssets,
    fetchJourneyMapPreview,
    saveJourneyDraft,
  };
})(window);
