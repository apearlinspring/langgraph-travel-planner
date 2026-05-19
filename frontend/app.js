// === 逻辑代码保持不变，仅适配样式类名 ===

      let state = {
        token: localStorage.getItem("token") || "",
        user: JSON.parse(localStorage.getItem("user") || "null"),
        currentConversationId: null,
        conversations: [],
        isLoading: false,
        isAuthLoading: false,
        serviceStatus: "checking",
        lastHealthCheckAt: 0,
        readiness: {
          status: "checking",
          payload: null,
          checkedAt: 0,
        },
        governance: {
          approvalFilter: "all",
          approvals: [],
          approvalEvents: [],
          selectedApprovalId: null,
          isApprovalLoading: false,
          toolAuditEvents: [],
          turnObservability: null,
        },
        plannerCollapsed: localStorage.getItem("zhixing-planner-collapsed") === "1",
        mobileChatFocus: false,
        editingConversationId: null,
        renamingConversationId: null,
      };
      let toastTimer = null;
      let streamingScrollFrame = null;
      const composerDraftKey = "zhixing-composer-draft";
      const plannerDraftKey = "zhixing-planner-draft";
      const plannerCollapseKey = "zhixing-planner-collapsed";

      function getDraftStorageScope() {
        return state.user?.id || state.user?.username || "guest";
      }

      function getScopedStorageKey(baseKey) {
        return `${baseKey}:${getDraftStorageScope()}`;
      }

      function readDraftStorage(baseKey) {
        return (
          localStorage.getItem(getScopedStorageKey(baseKey)) ??
          localStorage.getItem(baseKey)
        );
      }

      function writeDraftStorage(baseKey, value) {
        localStorage.setItem(getScopedStorageKey(baseKey), value);
      }

      function clearDraftStorage(baseKey) {
        localStorage.removeItem(getScopedStorageKey(baseKey));
        localStorage.removeItem(baseKey);
      }

      const getDefaultApiBase = () =>
        window.location.protocol === "file:"
          ? "http://localhost:8000"
          : ["localhost", "127.0.0.1"].includes(window.location.hostname) &&
              window.location.port !== "8000"
            ? "http://127.0.0.1:8000"
          : window.location.origin;

      const getApiBase = () =>
        document.getElementById("apiBase").value || getDefaultApiBase();

      const shouldShowApiConfig = () =>
        window.location.protocol === "file:" ||
        ["localhost", "127.0.0.1"].includes(window.location.hostname);

      const getCurrentConversation = () =>
        state.conversations.find((conv) => conv.id === state.currentConversationId);

      const isMobileViewport = () => window.innerWidth <= 900;
      let journeyMapAssetsPromise = null;
      let journeyAmapAssetsPromise = null;
      let journeyMapConfigPromise = null;
      let journeyMapRuntimeConfig = null;
      const journeyMapInstances = new WeakMap();
      const journeyMapPreviewCache = new Map();
      const DEFAULT_CONVERSATION_TITLE = "新行程";

      function serializeMapPayload(payload) {
        return encodeURIComponent(JSON.stringify(payload));
      }

      function parseMapPayload(raw = "") {
        try {
          return JSON.parse(decodeURIComponent(raw));
        } catch (error) {
          return null;
        }
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

      function ensureStylesheet(href) {
        if (document.querySelector(`link[data-href="${href}"]`)) return;
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = href;
        link.dataset.href = href;
        document.head.appendChild(link);
      }

      async function loadJourneyMapAssets() {
        if (window.L) return window.L;
        if (!journeyMapAssetsPromise) {
          journeyMapAssetsPromise = (async () => {
            ensureStylesheet(
              "https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.min.css"
            );
            await loadScriptOnce(
              "https://cdn.bootcdn.net/ajax/libs/leaflet/1.9.4/leaflet.js"
            );
            return window.L;
          })().catch((error) => {
            journeyMapAssetsPromise = null;
            throw error;
          });
        }
        return journeyMapAssetsPromise;
      }

      function getFallbackJourneyMapConfig() {
        return {
          preferred_provider: "leaflet-osm",
          amap_web_js_key: "",
          amap_web_js_key_configured: false,
          fallback_provider: "leaflet-osm",
        };
      }

      async function fetchJourneyMapConfig() {
        if (journeyMapRuntimeConfig) return journeyMapRuntimeConfig;
        if (!journeyMapConfigPromise) {
          journeyMapConfigPromise = (async () => {
            try {
              const response = await fetch(`${getApiBase()}/api/v1/maps/config`, {
                headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
              });
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
        if (window.AMap) return window.AMap;
        if (!journeyAmapAssetsPromise) {
          journeyAmapAssetsPromise = loadScriptOnce(
            `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(
              key
            )}&plugin=AMap.Scale,AMap.ToolBar`
          )
            .then(() => window.AMap || null)
            .catch((error) => {
              journeyAmapAssetsPromise = null;
              throw error;
            });
        }
        return journeyAmapAssetsPromise;
      }

      async function fetchJourneyMapPreview(payload) {
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
          let response;
          try {
            response = await fetch(`${getApiBase()}/api/v1/maps/preview`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
              },
              body: JSON.stringify(payload),
              signal: controller.signal,
            });
            if (!response.ok) {
              throw new Error(`map-preview-${response.status}`);
            }
          } finally {
            clearTimeout(timeoutId);
          }
          const data = await response.json();
          journeyMapPreviewCache.set(cacheKey, {
            data,
            timestamp: Date.now(),
          });
          return data;
        })().catch((error) => {
          journeyMapPreviewCache.delete(cacheKey);
          throw error;
        });
        journeyMapPreviewCache.set(cacheKey, {
          promise: requestPromise,
          timestamp: now,
        });
        return requestPromise;
      }

      function buildBoundsFromPoints(L, points = []) {
        if (!points.length) return null;
        return L.latLngBounds(points.map((point) => [point.lat, point.lng]));
      }

      function moveJourneyMapToBounds(map, bounds, options = {}) {
        if (!map || !bounds?.isValid?.()) return false;
        const { padding = [26, 26], animate = false } = options;
        if (bounds.engine === "amap") {
          const overlays = (bounds.overlays || [])
            .map((item) => item?.overlay || item)
            .filter(Boolean);
          if (!overlays.length || typeof map.setFitView !== "function") return false;
          map.setFitView(overlays, false, [
            padding[1] || 26,
            padding[0] || 26,
            padding[1] || 26,
            padding[0] || 26,
          ]);
          return true;
        }
        if (animate && typeof map.flyToBounds === "function") {
          map.flyToBounds(bounds, { padding, duration: 0.65, easeLinearity: 0.25 });
        } else {
          map.fitBounds(bounds, { padding });
        }
        return true;
      }

      function getAmapPosition(point) {
        return [Number(point.lng), Number(point.lat)];
      }

      function buildAmapBoundsFromLayers(layers = []) {
        const overlays = layers
          .map((item) => item?.overlay || item)
          .filter(Boolean);
        return {
          engine: "amap",
          overlays,
          isValid() {
            return overlays.length > 0;
          },
        };
      }

      function shouldUseAmapJourneyMap(preview, mapConfig) {
        const webKey = String(mapConfig?.amap_web_js_key || "").trim();
        if (!webKey) return false;
        return (
          preview?.provider === "amap-js" ||
          mapConfig?.preferred_provider === "amap-js"
        );
      }

      function fitJourneyMapState(entry, mode = "all") {
        if (!entry?.map) return;
        const { map, allBounds, routeBounds, highlightBounds } = entry;
        const padding = [26, 26];
        if (mode === "route" && routeBounds?.isValid()) {
          moveJourneyMapToBounds(map, routeBounds, { padding });
          return;
        }
        if (mode === "highlights" && highlightBounds?.isValid()) {
          moveJourneyMapToBounds(map, highlightBounds, { padding });
          return;
        }
        if (allBounds?.isValid()) {
          moveJourneyMapToBounds(map, allBounds, { padding });
        }
      }

      function focusJourneyMapTarget(entry, target = "destination") {
        if (!entry?.map) return;
        if (/^highlight:\d+$/.test(target)) {
          const index = Number(target.split(":")[1]);
          const marker = entry.markersByKind?.highlight?.[index];
          const point = entry.highlightPoints?.[index];
          if (!marker || !point) return;
          entry.map.flyTo([point.lat, point.lng], Math.max(entry.map.getZoom(), 12), {
            duration: 0.7,
          });
          marker.openPopup?.();
          activateJourneyHighlightCard(entry.shell, index);
          return;
        }
        if (target === "highlights") {
          fitJourneyMapState(entry, "highlights");
          entry.markersByKind?.highlight?.[0]?.openPopup?.();
          activateJourneyHighlightCard(entry.shell, 0);
          return;
        }
        if (target === "route") {
          if (entry.activeDayKey && entry.activeDayKey !== "all") {
            const selectedLayer = entry.dayLayers?.find((layer) => layer.key === entry.activeDayKey);
            if (selectedLayer?.bounds?.isValid()) {
              moveJourneyMapToBounds(entry.map, selectedLayer.bounds, {
                padding: [30, 30],
                animate: true,
              });
              return;
            }
          }
          fitJourneyMapState(entry, "route");
          entry.markersByKind?.destination?.[0]?.openPopup?.();
          return;
        }
        const point = entry.pointsByKind?.[target];
        if (!point) return;
        entry.map.flyTo([point.lat, point.lng], Math.max(entry.map.getZoom(), 11), {
          duration: 0.7,
        });
        entry.markersByKind?.[target]?.[0]?.openPopup?.();
      }

      function activateJourneyHighlightCard(shell, activeIndex = 0) {
        shell
          ?.querySelectorAll(".journey-highlight-card")
          .forEach((card) =>
            card.classList.toggle(
              "active",
              Number(card.dataset.highlightIndex || "-1") === activeIndex
            )
          );
      }

      function normalizeJourneyMatchText(text = "") {
        return String(text || "")
          .toLowerCase()
          .replace(/[^\p{L}\p{N}]+/gu, "")
          .trim();
      }

      function resolveJourneyPlanHighlightIndexes(plan, highlightPoints = []) {
        if (!plan || !Array.isArray(highlightPoints) || !highlightPoints.length) return [];
        const tokens = [...(plan.highlights || []), ...(plan.waypoints || [])]
          .map((item) => normalizeJourneyMatchText(item))
          .filter(Boolean);
        if (!tokens.length) return [];

        const matched = [];
        highlightPoints.forEach((point, index) => {
          const haystacks = [point?.name, point?.address, point?.label]
            .map((item) => normalizeJourneyMatchText(item))
            .filter(Boolean);
          const hit = tokens.some((token) =>
            haystacks.some(
              (field) => field === token || field.includes(token) || token.includes(field)
            )
          );
          if (hit) matched.push(index);
        });
        return [...new Set(matched)];
      }

      function activateJourneyBottomStop(shell, dayKey = "", stopIndex = 0, options = {}) {
        if (!shell || !dayKey) return null;
        const normalizedIndex = Number.isFinite(Number(stopIndex)) ? Number(stopIndex) : 0;
        const targetMeta = `${dayKey}:${normalizedIndex}`;
        shell
          .querySelectorAll(".journey-map-stage-stop.active")
          .forEach((item) => item.classList.remove("active"));
        shell
          .querySelectorAll(".journey-map-bottom-stop.active")
          .forEach((item) => item.classList.remove("active"));
        shell
          .querySelectorAll("[data-journey-day-card].active")
          .forEach((item) => item.classList.remove("active"));

        const stopButton = [...shell.querySelectorAll(".journey-map-stage-stop[data-map-day-stop]")]
          .find((button) => button.dataset.mapDayStop === targetMeta);
        if (!stopButton) return null;
        stopButton.classList.add("active");
        const stopRow = stopButton.closest(".journey-map-bottom-stop");
        stopRow?.classList.add("active");
        const dayCard = stopButton.closest("[data-journey-day-card]");
        dayCard?.classList.add("active");

        const drawer = shell.querySelector(".journey-map-bottom-drawer");
        if (drawer?.classList.contains("is-collapsed") && options.expandDrawer !== false) {
          drawer.classList.remove("is-collapsed");
          syncJourneyMapToggleLabels(shell);
        }
        if (options.scroll !== false) {
          (stopRow || stopButton).scrollIntoView({
            behavior: "smooth",
            block: "nearest",
            inline: "center",
          });
        }
        return stopButton;
      }

      function focusJourneyDayStop(entry, dayKey = "all", stopIndex = 0) {
        if (!entry?.map) return;
        const selectedLayer = entry.dayLayers?.find((layer) => layer.key === dayKey);
        const marker = selectedLayer?.markers?.[stopIndex];
        const point = selectedLayer?.points?.[stopIndex];
        if (!marker || !point) {
          if (dayKey && dayKey !== "all") {
            setJourneyMapDaySelection(entry, dayKey);
          }
          return;
        }
        if (entry.activeDayKey !== dayKey) {
          setJourneyMapDaySelection(entry, dayKey);
        }
        activateJourneyBottomStop(entry.shell, dayKey, stopIndex);
        entry.map.flyTo([point.lat, point.lng], Math.max(entry.map.getZoom(), 12), {
          duration: 0.7,
        });
        marker.openPopup?.();
        showJourneyPoiSheet(entry, dayKey, stopIndex);
      }

      function hideJourneyPoiSheet(shell) {
        const sheet = shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        sheet.hidden = true;
        sheet.classList.remove("show");
      }

      function getPoiVerificationText(stop = {}, point = {}) {
        if (stop?.map_verified || /amap/i.test(String(stop?.verification_status || ""))) {
          return "高德地点已核验";
        }
        if (stop?.coordinate_estimated || /estimated/i.test(String(stop?.verification_status || ""))) {
          return "估算落点 · 待核验";
        }
        if (point?.address || stop?.lng || stop?.lat) {
          return "地图坐标已返回";
        }
        return "地图点位待核验";
      }

      function getPoiVerificationTone(text = "") {
        if (/高德|已核验|已返回/.test(String(text || ""))) return "ready";
        if (/估算|待/.test(String(text || ""))) return "pending";
        return "";
      }

      function normalizeJourneyPoiAsStop(poi = {}, fallback = {}) {
        return {
          id: poi.id || "",
          name: poi.name || "",
          city: poi.city || fallback.city || "",
          type: poi.type || fallback.type || "attraction",
          type_label: poi.type_label || poi.type || fallback.type_label || "地点",
          time_range: poi.suggested_time || poi.time_range || fallback.time_range || "",
          description: poi.description || "",
          duration_minutes: poi.duration_minutes || fallback.duration_minutes || "",
          estimated_cost: poi.estimated_cost || "待核验",
          reservation_note:
            poi.reservation_note || "开放、预约、票价和道路情况出发前二次核验。",
          verification_status: poi.verification_status || "",
          verification_note: poi.verification_note || "",
          map_verified: Boolean(poi.map_verified),
          coordinate_estimated: Boolean(poi.coordinate_estimated),
          address: poi.address || "",
          amap_type: poi.amap_type || "",
          amap_source_name: poi.amap_source_name || "",
          tags: Array.isArray(poi.tags) ? poi.tags : [],
          image_url: poi.image_url || "",
          map_query: poi.map_query || [poi.city, poi.name].filter(Boolean).join(" "),
          lng: typeof poi.lng === "number" ? poi.lng : null,
          lat: typeof poi.lat === "number" ? poi.lat : null,
        };
      }

      function getJourneyReplacementCandidates(workbench, dayPlans, dayKey, stopIndex) {
        const original = parseMapPayload(workbench?.dataset.journeyData || "") || {};
        const allPois = [
          ...(Array.isArray(original.alternative_pois) ? original.alternative_pois : []),
          ...(Array.isArray(original.pois) ? original.pois : []),
        ].filter(Boolean);
        const day = (dayPlans || []).find((item) => item.key === dayKey);
        const current = day?.stops?.[stopIndex];
        if (!current || !allPois.length) return [];
        const activeIds = new Set(
          (dayPlans || []).flatMap((item) =>
            (item.stops || []).map((stop) => stop.id).filter(Boolean)
          )
        );
        const currentName = normalizeJourneyMatchText(current.name || "");
        const currentCity = normalizeJourneyMatchText(current.city || day?.city || "");
        const currentType = normalizeJourneyMatchText(current.type_label || current.type || "");
        return allPois
          .filter((poi) => {
            const poiName = normalizeJourneyMatchText(poi.name || "");
            if (!poiName || poiName === currentName) return false;
            if (poi.id && activeIds.has(poi.id)) return false;
            return true;
          })
          .map((poi) => {
            const city = normalizeJourneyMatchText(poi.city || "");
            const type = normalizeJourneyMatchText(poi.type_label || poi.type || "");
            const score =
              (city && currentCity && city === currentCity ? 4 : 0) +
              (type && currentType && type === currentType ? 3 : 0) +
              (poi.map_verified ? 2 : 0) +
              (poi.coordinate_estimated ? 1 : 0);
            return { poi, score };
          })
          .sort((left, right) => right.score - left.score)
          .map((item) => item.poi);
      }

      function getJourneyPoiPool(workbench) {
        const original = parseMapPayload(workbench?.dataset.journeyData || "") || {};
        return [
          ...(Array.isArray(original.alternative_pois) ? original.alternative_pois : []),
          ...(Array.isArray(original.pois) ? original.pois : []),
        ].filter((poi) => poi && typeof poi === "object");
      }

      function resolveJourneyRecommendationPoi(workbench, point = {}) {
        const targetName = normalizeJourneyMatchText(point.name || point.label || "");
        const matched = getJourneyPoiPool(workbench).find((poi) => {
          const poiName = normalizeJourneyMatchText(poi.name || "");
          return (
            poiName &&
            targetName &&
            (poiName === targetName || poiName.includes(targetName) || targetName.includes(poiName))
          );
        });
        const fallback = {
          name: point.name || point.label || "推荐点",
          city: point.address || "",
          type_label: point.kind === "recommendation" ? "推荐点" : "看点",
          description: point.address || "推荐点详情待补充。",
          map_query: [point.address, point.name || point.label].filter(Boolean).join(" "),
          lng: typeof point.lng === "number" ? point.lng : null,
          lat: typeof point.lat === "number" ? point.lat : null,
          verification_status: "map_preview_point",
          reservation_note: "开放、预约、票价和道路情况出发前二次核验。",
        };
        return normalizeJourneyPoiAsStop(matched || fallback, fallback);
      }

      function getJourneyRecommendationTargetDay(entry) {
        const activeDayKey = entry?.activeDayKey && entry.activeDayKey !== "all"
          ? entry.activeDayKey
          : "";
        return (
          entry?.dayPlans?.find((day) => day.key === activeDayKey) ||
          entry?.dayPlans?.[0] ||
          null
        );
      }

      function resetJourneyPoiSheetActions(sheet) {
        const replaceButton = sheet?.querySelector("[data-poi-sheet-action='replace'], [data-poi-sheet-action='add-recommendation']");
        const verifyButton = sheet?.querySelector("[data-poi-sheet-action='verify']");
        const keepButton = sheet?.querySelector("[data-poi-sheet-action='keep'], [data-poi-sheet-action='replace-recommendation']");
        if (replaceButton) {
          replaceButton.dataset.poiSheetAction = "replace";
          replaceButton.dataset.replacementPoiId = "";
          replaceButton.textContent = "替换这个点";
        }
        if (verifyButton) {
          verifyButton.dataset.poiSheetAction = "verify";
          verifyButton.textContent = "核验门票交通";
        }
        if (keepButton) {
          keepButton.dataset.poiSheetAction = "keep";
          keepButton.textContent = "保留继续规划";
        }
      }

      function showJourneyPoiSheet(entry, dayKey = "all", stopIndex = 0) {
        const sheet = entry?.shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        resetJourneyPoiSheetActions(sheet);
        sheet.dataset.poiMode = "stop";
        delete sheet.dataset.recommendationPoi;
        delete sheet.dataset.recommendationDayKey;
        const dayPlan = entry.dayPlans?.find((day) => day.key === dayKey);
        const stop = dayPlan?.stops?.[stopIndex];
        const point = entry.dayLayers?.find((layer) => layer.key === dayKey)?.points?.[stopIndex];
        if (!stop && !point) return;

        const title = stop?.name || point?.name || "地点详情";
        const meta = [
          dayPlan?.label,
          stop?.type_label || stop?.type,
          stop?.time_range,
        ].filter(Boolean);
        const durationText = stop?.duration_minutes
          ? `建议停留 ${stop.duration_minutes} 分钟`
          : "停留时间待核验";
        const addressText = stop?.address || point?.address || stop?.map_query || "";
        const verificationText = getPoiVerificationText(stop, point);
        const typeText = stop?.amap_type || stop?.type_label || stop?.type || "";
        const proofItems = [
          { label: verificationText, tone: getPoiVerificationTone(verificationText) },
          { label: addressText, tone: "" },
          { label: typeText, tone: "" },
          ...(Array.isArray(stop?.tags)
            ? stop.tags.slice(0, 2).map((tag) => ({ label: tag, tone: "" }))
            : []),
        ].filter(Boolean);
        sheet.dataset.poiTitle = title;
        sheet.dataset.poiDayLabel = dayPlan?.label || "";
        sheet.dataset.poiDayKey = dayKey;
        sheet.dataset.poiStopIndex = String(stopIndex);
        const workbench = sheet.closest(".visual-journey-workbench");
        const replacement = getJourneyReplacementCandidates(
          workbench,
          entry.dayPlans || [],
          dayKey,
          stopIndex
        )[0];
        const replaceButton = sheet.querySelector("[data-poi-sheet-action='replace']");
        if (replaceButton) {
          replaceButton.dataset.replacementPoiId = replacement?.id || "";
          replaceButton.textContent = replacement?.name
            ? `替换为${replacement.name}`
            : "寻找替换点";
        }
        const media = sheet.querySelector(".journey-poi-bottom-media");
        const imageUrl = String(stop?.image_url || "").trim();
        if (media) {
          media.classList.toggle("has-image", /^https?:\/\//i.test(imageUrl));
          media.style.backgroundImage = /^https?:\/\//i.test(imageUrl)
            ? `url("${imageUrl.replace(/"/g, "%22")}")`
            : "";
          media.querySelector("span")?.replaceChildren(
            document.createTextNode(getVisualPoiInitial(title))
          );
        }
        sheet.querySelector("[data-poi-sheet-title]")?.replaceChildren(
          document.createTextNode(title)
        );
        sheet.querySelector("[data-poi-sheet-meta]")?.replaceChildren(
          document.createTextNode(meta.join(" · ") || "地点信息待核验")
        );
        sheet.querySelector("[data-poi-sheet-desc]")?.replaceChildren(
          document.createTextNode(stop?.description || point?.address || "地点介绍待补充。")
        );
        sheet.querySelector("[data-poi-sheet-duration]")?.replaceChildren(
          document.createTextNode(durationText)
        );
        sheet.querySelector("[data-poi-sheet-cost]")?.replaceChildren(
          document.createTextNode(stop?.estimated_cost || "费用待核验")
        );
        sheet.querySelector("[data-poi-sheet-note]")?.replaceChildren(
          document.createTextNode(
            stop?.verification_note ||
              stop?.reservation_note ||
              "开放、预约、票价和道路情况出发前二次核验。"
          )
        );
        const proof = sheet.querySelector("[data-poi-sheet-proof]");
        if (proof) {
          proof.innerHTML = proofItems
            .slice(0, 5)
            .filter((item) => item.label)
            .map(
              (item) =>
                `<span class="${escapeHtml(item.tone || "")}">${escapeHtml(
                  item.label
                )}</span>`
            )
            .join("");
        }
        sheet.hidden = false;
        requestAnimationFrame(() => sheet.classList.add("show"));
      }

      function showJourneyRecommendationSheet(entry, point = {}) {
        const sheet = entry?.shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        resetJourneyPoiSheetActions(sheet);
        const workbench = sheet.closest(".visual-journey-workbench");
        const candidate = resolveJourneyRecommendationPoi(workbench, point);
        const targetDay = getJourneyRecommendationTargetDay(entry);
        if (!candidate || !targetDay) return;

        const title = candidate.name || point.name || "推荐点";
        const targetLabel = targetDay.label || targetDay.title || "当天";
        const addressText = candidate.address || point.address || candidate.map_query || "";
        const verificationText = getPoiVerificationText(candidate, point);
        const proofItems = [
          { label: "地图推荐点", tone: "ready" },
          { label: verificationText, tone: getPoiVerificationTone(verificationText) },
          { label: addressText, tone: "" },
          { label: candidate.type_label || candidate.type || "", tone: "" },
          ...(Array.isArray(candidate.tags)
            ? candidate.tags.slice(0, 2).map((tag) => ({ label: tag, tone: "" }))
            : []),
        ].filter(Boolean);

        sheet.dataset.poiMode = "recommendation";
        sheet.dataset.poiTitle = title;
        sheet.dataset.poiDayLabel = targetLabel;
        sheet.dataset.poiDayKey = "";
        sheet.dataset.poiStopIndex = "-1";
        sheet.dataset.recommendationDayKey = targetDay.key || "";
        sheet.dataset.recommendationPoi = serializeMapPayload(candidate);

        const addButton = sheet.querySelector("[data-poi-sheet-action='replace']");
        if (addButton) {
          addButton.dataset.poiSheetAction = "add-recommendation";
          addButton.textContent = `加入${targetLabel}`;
        }
        const replaceButton = sheet.querySelector("[data-poi-sheet-action='keep']");
        if (replaceButton) {
          replaceButton.dataset.poiSheetAction = "replace-recommendation";
          replaceButton.textContent = "替换当天首点";
        }

        const media = sheet.querySelector(".journey-poi-bottom-media");
        const imageUrl = String(candidate.image_url || "").trim();
        if (media) {
          media.classList.toggle("has-image", /^https?:\/\//i.test(imageUrl));
          media.style.backgroundImage = /^https?:\/\//i.test(imageUrl)
            ? `url("${imageUrl.replace(/"/g, "%22")}")`
            : "";
          media.querySelector("span")?.replaceChildren(
            document.createTextNode(getVisualPoiInitial(title))
          );
        }
        sheet.querySelector("[data-poi-sheet-title]")?.replaceChildren(
          document.createTextNode(title)
        );
        sheet.querySelector("[data-poi-sheet-meta]")?.replaceChildren(
          document.createTextNode([targetLabel, candidate.type_label || candidate.type, candidate.time_range].filter(Boolean).join(" · ") || "推荐点待核验")
        );
        sheet.querySelector("[data-poi-sheet-desc]")?.replaceChildren(
          document.createTextNode(candidate.description || point.address || "推荐点详情待补充。")
        );
        sheet.querySelector("[data-poi-sheet-duration]")?.replaceChildren(
          document.createTextNode(
            candidate.duration_minutes
              ? `建议停留 ${candidate.duration_minutes} 分钟`
              : "停留时间待核验"
          )
        );
        sheet.querySelector("[data-poi-sheet-cost]")?.replaceChildren(
          document.createTextNode(candidate.estimated_cost || "费用待核验")
        );
        sheet.querySelector("[data-poi-sheet-note]")?.replaceChildren(
          document.createTextNode(
            candidate.verification_note ||
              candidate.reservation_note ||
              "开放、预约、票价和道路情况出发前二次核验。"
          )
        );
        const proof = sheet.querySelector("[data-poi-sheet-proof]");
        if (proof) {
          proof.innerHTML = proofItems
            .slice(0, 5)
            .filter((item) => item.label)
            .map(
              (item) =>
                `<span class="${escapeHtml(item.tone || "")}">${escapeHtml(item.label)}</span>`
            )
            .join("");
        }
        sheet.hidden = false;
        requestAnimationFrame(() => sheet.classList.add("show"));
      }

      function replaceJourneyPoiFromSheet(sheet, button) {
        const shell = sheet?.closest(".journey-live-map-shell");
        const workbench = sheet?.closest(".visual-journey-workbench");
        const dayKey = sheet?.dataset?.poiDayKey || "";
        const stopIndex = Number(sheet?.dataset?.poiStopIndex || "-1");
        if (!shell || !workbench || !dayKey || !Number.isInteger(stopIndex)) return false;
        const dayPlans = cloneJourneyDayPlans(shell).map(normalizeJourneyDayPlanStops);
        const day = dayPlans.find((item) => item.key === dayKey);
        if (!day || !Array.isArray(day.stops) || !day.stops[stopIndex]) return false;
        const candidates = getJourneyReplacementCandidates(workbench, dayPlans, dayKey, stopIndex);
        const candidateId = button?.dataset?.replacementPoiId || "";
        const candidate =
          candidates.find((poi) => poi.id && poi.id === candidateId) || candidates[0];
        if (!candidate) return false;
        const previousName = day.stops[stopIndex].name || "当前地点";
        day.stops[stopIndex] = normalizeJourneyPoiAsStop(candidate, day.stops[stopIndex]);
        const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
        updateVisualJourneyPoiCards(workbench, normalizedDayPlans);
        refreshJourneyMapAfterEdit(shell, normalizedDayPlans);
        saveEditedJourneyDraft(workbench, normalizedDayPlans);
        showToast(`已将 ${previousName} 替换为 ${candidate.name}`);
        return true;
      }

      function applyJourneyRecommendationFromSheet(sheet, options = {}) {
        const shell = sheet?.closest(".journey-live-map-shell");
        const workbench = sheet?.closest(".visual-journey-workbench");
        const dayKey = sheet?.dataset?.recommendationDayKey || "";
        const candidate = parseMapPayload(sheet?.dataset?.recommendationPoi || "");
        if (!shell || !workbench || !dayKey || !candidate?.name) return false;

        const dayPlans = cloneJourneyDayPlans(shell).map(normalizeJourneyDayPlanStops);
        const day = dayPlans.find((item) => item.key === dayKey);
        if (!day || !Array.isArray(day.stops)) return false;

        const normalizedCandidate = normalizeJourneyPoiAsStop(candidate, {
          city: day.city || "",
        });
        const duplicateIndex = day.stops.findIndex(
          (stop) =>
            (normalizedCandidate.id && stop.id === normalizedCandidate.id) ||
            normalizeJourneyMatchText(stop.name || "") ===
              normalizeJourneyMatchText(normalizedCandidate.name || "")
        );
        if (duplicateIndex >= 0) {
          focusJourneyDayStop(
            journeyMapInstances.get(shell.querySelector(".journey-live-map[data-map-payload]")),
            dayKey,
            duplicateIndex
          );
          showToast(`${normalizedCandidate.name} 已在当天路线中`);
          return true;
        }

        const activeMeta = parseJourneyStopMeta(
          shell.querySelector(".journey-map-bottom-stop.active .journey-map-stage-stop")?.dataset
            ?.mapDayStop || ""
        );
        const activeIndex =
          activeMeta?.dayKey === dayKey && Number.isInteger(activeMeta.stopIndex)
            ? activeMeta.stopIndex
            : -1;

        if (options.replace) {
          const replaceIndex = activeIndex >= 0 ? activeIndex : 0;
          if (!day.stops[replaceIndex]) return false;
          const previousName = day.stops[replaceIndex].name || "当天首点";
          day.stops[replaceIndex] = normalizedCandidate;
          showToast(`已将 ${previousName} 替换为 ${normalizedCandidate.name}`);
        } else {
          const insertIndex = activeIndex >= 0 ? activeIndex + 1 : day.stops.length;
          day.stops.splice(insertIndex, 0, normalizedCandidate);
          showToast(`已把 ${normalizedCandidate.name} 加入 ${day.label || "当天"}`);
        }

        const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
        updateVisualJourneyPoiCards(workbench, normalizedDayPlans);
        refreshJourneyMapAfterEdit(shell, normalizedDayPlans);
        saveEditedJourneyDraft(workbench, normalizedDayPlans);
        return true;
      }

      function handleJourneyPoiSheetAction(button) {
        const action = button?.dataset?.poiSheetAction || "";
        const sheet = button?.closest(".journey-poi-bottom-sheet");
        const title = sheet?.dataset?.poiTitle || "这个地点";
        const dayLabel = sheet?.dataset?.poiDayLabel || "当天";
        if (action === "replace" && replaceJourneyPoiFromSheet(sheet, button)) {
          return;
        }
        if (
          action === "add-recommendation" &&
          applyJourneyRecommendationFromSheet(sheet, { replace: false })
        ) {
          return;
        }
        if (
          action === "replace-recommendation" &&
          applyJourneyRecommendationFromSheet(sheet, { replace: true })
        ) {
          return;
        }
        const prompts = {
          replace: `把${dayLabel}的「${title}」替换成同片区、更适合当前节奏的备选地点，并同步刷新地图路线。`,
          "add-recommendation": `把推荐点「${title}」加入${dayLabel}，并同步刷新地图路线。`,
          "replace-recommendation": `用推荐点「${title}」替换${dayLabel}当前不合适的地点，并同步刷新地图路线。`,
          verify: `继续核验「${title}」的开放时间、门票/预约，以及它和前后地点之间的交通距离与时长。`,
          keep: `我想保留「${title}」，请基于当前可视化旅程继续补交通、酒店、预算和最终报告所需信息。`,
        };
        const prompt = prompts[action];
        if (!prompt) return;
        appendToComposer(prompt, "replace");
        setRuntimeStatus("已把地点调整请求填入输入框", "online");
      }

      function renderJourneyDayInsight(entry) {
        if (!entry?.shell) return;
        const activeDayKey = entry.activeDayKey || "all";
        const activeMode = entry.dayDisplayMode || "solo";
        const insightTitle = entry.shell.querySelector(".journey-map-day-insight-title");
        const insightCopy = entry.shell.querySelector(".journey-map-day-insight-copy");
        const insightList = entry.shell.querySelector(".journey-map-day-insight-points");
        if (!insightTitle || !insightCopy || !insightList) return;

        if (activeDayKey === "all") {
          const overviewRoute = entry.routeStops
            .map((item) => item.value)
            .filter((item) => item && !/待/.test(item))
            .join(" → ");
          insightTitle.textContent = "当前查看总览路线";
          insightCopy.textContent =
            overviewRoute ||
            "先把出发、目的地、交通和落脚点定住，后面再继续展开成完整的分日路线。";
          insightList.innerHTML = entry.routeStops
            .map(
              (stop) => `
                <li>
                  <span>${escapeHtml(stop.label)}</span>
                  <strong>${escapeHtml(stop.value)}</strong>
                </li>
              `
            )
            .join("");
          return;
        }

        const selectedLayer = entry.dayLayers.find((layer) => layer.key === activeDayKey);
        const selectedPlan =
          entry.dayPlans.find((day) => day.key === activeDayKey) ||
          entry.dayPlans.find((day) => day.label === selectedLayer?.label);
        const waypoints = selectedPlan?.waypoints?.length
          ? selectedPlan.waypoints
          : selectedLayer?.points?.map((point) => point.name || point.address || point.label) || [];
        const highlights = selectedPlan?.highlights?.length ? selectedPlan.highlights : [];
        const matchedHighlightIndexes = resolveJourneyPlanHighlightIndexes(
          selectedPlan,
          entry.highlightPoints
        );

        insightTitle.textContent = `${selectedLayer?.label || "当日"} · ${
          activeMode === "solo" ? "单独显示" : "突出显示"
        }`;
        insightCopy.textContent =
          selectedPlan?.note ||
          `${selectedLayer?.label || "这一天"}的路线节点已经高亮出来了，你可以继续看当天怎么走、住哪里、看什么。`;
        insightList.innerHTML = [
          ...waypoints.slice(0, 5).map(
            (point, index) => `
              <li>
                <button
                  class="journey-map-stage-stop journey-map-stage-stop--inline"
                  type="button"
                  data-map-day-stop="${escapeHtml(activeDayKey)}:${index}"
                >
                  <span>${index + 1 < 10 ? `0${index + 1}` : index + 1}</span>
                  <strong>${escapeHtml(point)}</strong>
                  <small>${escapeHtml(selectedLayer?.label || "当日路线")}</small>
                </button>
              </li>
            `
          ),
          ...highlights.slice(0, 2).map(
            (item, index) => `
              <li class="highlight">
                <span>景</span>
                <strong>${escapeHtml(item)}</strong>
              </li>
            `
          ),
        ].join("");
        insightList.querySelectorAll("li.highlight").forEach((item, index) => {
          const highlightText = item.querySelector("strong")?.textContent?.trim();
          if (!highlightText) return;
          item.innerHTML = `
            <button
              class="journey-map-stage-stop journey-map-stage-stop--inline"
              type="button"
              data-map-focus="highlight:${matchedHighlightIndexes[index] ?? 0}"
            >
              <span>景</span>
              <strong>${escapeHtml(highlightText)}</strong>
              <small>${escapeHtml(selectedLayer?.label || "沿途看点")}</small>
            </button>
          `;
        });
      }

      function setJourneyMapStyle(entry, style = "standard") {
        if (!entry?.map) return;
        if (entry.engine === "amap") {
          const amapStyles = {
            standard: "amap://styles/normal",
            terrain: "amap://styles/fresh",
            calm: "amap://styles/whitesmoke",
          };
          entry.map.setMapStyle?.(amapStyles[style] || amapStyles.standard);
          entry.activeLayerKey = style;
          return;
        }
        if (!entry.baseLayers) return;
        const nextLayer = entry.baseLayers[style] || entry.baseLayers.standard;
        if (!nextLayer || entry.activeLayerKey === style) return;
        Object.values(entry.baseLayers).forEach((layer) => {
          if (entry.map.hasLayer(layer)) {
            entry.map.removeLayer(layer);
          }
        });
        nextLayer.addTo(entry.map);
        entry.activeLayerKey = style;
      }

      function buildJourneyMapIcon(L, kind = "highlight") {
        const kindClass = `kind-${kind}`;
        const symbol = kind === "highlight" ? "★" : kind === "recommendation" ? "+" : "●";
        return L.divIcon({
          className: `journey-live-marker ${kindClass}`,
          html: `<span>${symbol}</span>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        });
      }

      function buildJourneyDayMapIcon(
        L,
        text = "1",
        color = "",
        dayKey = "",
        stopIndex = 0
      ) {
        const safeColor = escapeHtml(color || "#18b6a4");
        const mapStopAttr = dayKey
          ? ` data-map-day-stop="${escapeHtml(`${dayKey}:${stopIndex}`)}"`
          : "";
        return L.divIcon({
          className: "journey-live-marker kind-day leaflet-journey-day-marker",
          html: `<span${mapStopAttr} style="background:${safeColor};box-shadow:0 0 0 2px ${safeColor}">${escapeHtml(text)}</span>`,
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        });
      }

      const JOURNEY_DAY_COLORS = [
        "#ffd08a",
        "#8fd3c1",
        "#9fb8ff",
        "#f2a8b5",
        "#c9e37f",
        "#f7c66f",
      ];

      function getJourneyDayColor(index = 0) {
        return JOURNEY_DAY_COLORS[index % JOURNEY_DAY_COLORS.length];
      }

      function isJourneyRecommendationPoint(point = {}) {
        return point.kind === "highlight" || point.kind === "recommendation";
      }

      function getJourneyRecommendationMarkers(entry) {
        return [
          ...(entry?.markersByKind?.highlight || []),
          ...(entry?.markersByKind?.recommendation || []),
        ];
      }

      function setJourneyLayerOpacity(layer, opacity) {
        if (!layer) return;
        if (typeof layer.setOpacity === "function") {
          layer.setOpacity(opacity);
          return;
        }
        if (typeof layer.setOptions === "function") {
          layer.setOptions({
            opacity,
            strokeOpacity: opacity,
            fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
          });
          return;
        }
        if (typeof layer.setStyle === "function") {
          layer.setStyle({
            opacity,
            fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
          });
        }
      }

      function getJourneySegmentLabelViewOpacity({
        isOverview = true,
        isSelected = false,
        activeMode = "solo",
        labelIndex = 0,
      } = {}) {
        if (isOverview) {
          return labelIndex === 0 ? 0.95 : 0;
        }
        if (activeMode === "solo") {
          return isSelected ? 0.98 : 0;
        }
        return isSelected ? 0.98 : 0;
      }

      function updateJourneyDayButtons(shell, activeDay = "all", activeMode = "solo") {
        shell?.querySelectorAll(".journey-map-day-btn").forEach((btn) => {
          const isActive = (btn.dataset.mapDay || "all") === activeDay;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", String(isActive));
        });
        shell?.querySelectorAll(".journey-map-day-mode-btn").forEach((btn) => {
          const isActive = (btn.dataset.mapDayMode || "solo") === activeMode;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", String(isActive));
        });
      }

      function applyJourneyDayView(entry) {
        if (!entry?.dayLayers?.length) return;
        const activeDayKey = entry.activeDayKey || "all";
        const activeMode = entry.dayDisplayMode || "solo";
        const isOverview = activeDayKey === "all";
        const selectedPlan = entry.dayPlans?.find((day) => day.key === activeDayKey);
        const selectedHighlightIndexes = new Set(
          resolveJourneyPlanHighlightIndexes(selectedPlan, entry.highlightPoints)
        );

        entry.dayLayers.forEach((layer) => {
          const isSelected = layer.key === activeDayKey;
          const opacity = isOverview
            ? 0.92
            : activeMode === "solo"
              ? (isSelected ? 0.96 : 0)
              : (isSelected ? 0.98 : 0.18);
          layer.markers.forEach((marker) => setJourneyLayerOpacity(marker, opacity));
          (layer.segmentLabels || []).forEach((label, labelIndex) => {
            const labelOpacity = getJourneySegmentLabelViewOpacity({
              isOverview,
              isSelected,
              activeMode,
              labelIndex,
            });
            setJourneyLayerOpacity(label, labelOpacity);
          });
          setJourneyLayerOpacity(layer.dayBadge, opacity);
          setJourneyLayerOpacity(layer.polyline, opacity);
          if (typeof layer.polyline?.setStyle === "function") {
            layer.polyline.setStyle({
              weight: isOverview ? 4 : isSelected ? 5 : 3,
            });
          }
        });

        const baseOpacity = isOverview ? 1 : activeMode === "solo" ? 0 : 0.32;
        entry.markers.forEach((marker) => setJourneyLayerOpacity(marker, baseOpacity));
        if (entry.routeLine?.setStyle) {
          entry.routeLine.setStyle({
            opacity: baseOpacity,
            weight: isOverview ? 4 : 3,
          });
        }
        getJourneyRecommendationMarkers(entry).forEach((marker, index) => {
          const opacity = isOverview
            ? 0.95
            : selectedHighlightIndexes.size
              ? selectedHighlightIndexes.has(index)
                ? 0.98
                : activeMode === "solo"
                  ? 0.08
                  : 0.22
              : activeMode === "solo"
                ? 0.18
                : 0.38;
          setJourneyLayerOpacity(marker, opacity);
        });
        if (entry.recommendationsVisible === false) {
          getJourneyRecommendationMarkers(entry).forEach((marker) =>
            setJourneyLayerOpacity(marker, 0)
          );
        }

        const selectedLayer = entry.dayLayers.find((layer) => layer.key === activeDayKey);
        if (entry.shell) {
          entry.shell.dataset.activeDay = activeDayKey;
          entry.shell.dataset.dayMode = activeMode;
        }
        const metaValue = entry.shell?.querySelector(".journey-live-map-meta-value");
        if (metaValue) {
          metaValue.textContent = isOverview
            ? `已定位 ${entry.points.length} 个路线地点`
            : `${selectedLayer?.label || "当日"}已切换为${
                activeMode === "solo" ? "单日路线" : "重点路线"
              }`;
        }
        renderJourneyDayInsight(entry);
        updateJourneyDayButtons(entry.shell, activeDayKey, activeMode);
        syncJourneyRecommendationButtons(entry);
      }

      function syncJourneyRecommendationButtons(entry) {
        const visible = entry?.recommendationsVisible !== false;
        const count = getJourneyRecommendationMarkers(entry).length;
        entry?.shell
          ?.querySelectorAll('[data-map-action="recommendations"]')
          .forEach((button) => {
            button.classList.toggle("active", visible);
            button.setAttribute("aria-pressed", String(visible));
            button.textContent = visible ? "隐藏推荐点" : count ? `推荐点 ${count}` : "推荐点";
          });
      }

      function setJourneyMapDaySelection(entry, dayKey = "all") {
        if (!entry) return;
        if (dayKey !== "all" && !entry.dayLayers?.some((layer) => layer.key === dayKey)) {
          return;
        }
        entry.activeDayKey = dayKey || "all";
        applyJourneyDayView(entry);
        if (dayKey === "all") {
          entry.shell
            ?.querySelectorAll(".journey-map-stage-stop.active, .journey-map-bottom-stop.active, [data-journey-day-card].active")
            .forEach((item) => item.classList.remove("active"));
          fitJourneyMapState(entry, "all");
          return;
        }
        const selectedLayer = entry.dayLayers?.find((layer) => layer.key === dayKey);
        activateJourneyBottomStop(entry.shell, dayKey, 0, {
          expandDrawer: false,
          scroll: false,
        });
        if (selectedLayer?.bounds?.isValid()) {
          moveJourneyMapToBounds(entry.map, selectedLayer.bounds, {
            padding: [30, 30],
            animate: true,
          });
          selectedLayer.markers?.[0]?.openPopup?.();
        }
      }

      function setJourneyMapDayMode(entry, mode = "solo") {
        if (!entry) return;
        entry.dayDisplayMode = mode === "fade" ? "fade" : "solo";
        applyJourneyDayView(entry);
      }

      function toggleJourneyRecommendations(entry) {
        if (!entry) return;
        entry.recommendationsVisible = entry.recommendationsVisible === false;
        applyJourneyDayView(entry);
      }

      function registerJourneyMapEntry(node, entry) {
        const shell = entry.shell;
        const availableDayKeys = new Set(
          (entry.dayLayers || []).map((layer) => layer.key)
        );
        shell?.querySelectorAll(".journey-map-day-btn").forEach((button) => {
          const key = button.dataset.mapDay || "all";
          const enabled = key === "all" || availableDayKeys.has(key);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = key !== "all" && !enabled;
        });
        const dayModes = shell?.querySelector(".journey-map-floating-modes");
        if (dayModes) {
          dayModes.hidden = availableDayKeys.size <= 1;
        }
        const enabledFocusTargets = new Set([
          ...Object.keys(entry.pointsByKind || {}),
          ...(entry.recommendationPoints?.length ? ["highlights"] : []),
          ...(entry.routePoints?.length >= 2 ? ["route"] : []),
        ]);
        shell?.querySelectorAll(".journey-map-focus-btn").forEach((button) => {
          const focusTarget = button.dataset.mapFocus || "";
          const enabled =
            !focusTarget ||
            enabledFocusTargets.has(focusTarget) ||
            /^highlight:\d+$/.test(focusTarget);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = !enabled;
        });
        shell?.querySelectorAll(".journey-map-action-btn").forEach((button) => {
          const action = button.dataset.mapAction || "";
          const enabled =
            action === "expand" ||
            action === "toggle-tools" ||
            action === "toggle-sidebar" ||
            action === "toggle-bottom-drawer" ||
            (action === "recommendations" && entry.recommendationPoints?.length > 0) ||
            (action === "route" && entry.routePoints?.length >= 2) ||
            (action === "highlights" && entry.recommendationPoints?.length > 0);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = !enabled;
        });
        syncJourneyMapToggleLabels(shell);
        journeyMapInstances.set(node, entry);
        node
          .closest(".journey-live-map-shell")
          ?.querySelector(".journey-live-map-meta-value")
          ?.replaceChildren(
            document.createTextNode(
              entry.engine === "amap"
                ? `高德地图已定位 ${entry.points.length} 个地点`
                : `已定位 ${entry.points.length} 个路线地点`
            )
          );
        applyJourneyDayView(entry);
        node.dataset.mapReady = "1";
        node.dataset.mapProvider = entry.engine || "leaflet";
        setTimeout(() => {
          if (typeof entry.map?.invalidateSize === "function") {
            entry.map.invalidateSize();
          } else {
            entry.map?.resize?.();
          }
        }, 80);
      }

      function buildAmapMarkerContent(kind = "highlight", text = "●", color = "") {
        const node = document.createElement("div");
        node.className = `journey-live-marker amap-journey-marker kind-${kind}`;
        node.innerHTML = `<span>${escapeHtml(text)}</span>`;
        if (color) {
          node.style.borderColor = color;
          node.style.color = color;
        }
        return node;
      }

      function getJourneySegmentLabel(segment = {}) {
        const distance = String(segment.distance_text || "").trim();
        const duration = String(segment.duration_text || "").trim();
        if (!distance && !duration) return "";
        if (distance && duration && !/待/.test(`${distance}${duration}`)) {
          return `${distance} · ${duration}`;
        }
        if (/待/.test(`${distance}${duration}`)) {
          return "路线待核验";
        }
        return distance || duration;
      }

      function getJourneyShortDayLabel(day = {}, index = 0) {
        const raw = String(day.label || day.date || "").trim();
        const dateMatch = raw.match(/(\d{1,2})[-/.月](\d{1,2})/);
        if (dateMatch) return `${dateMatch[1].padStart(2, "0")}.${dateMatch[2].padStart(2, "0")}`;
        const dayMatch = raw.match(/Day\s*(\d+)/i);
        if (dayMatch) return `D${dayMatch[1]}`;
        if (raw && raw.length <= 7) return raw;
        return `D${index + 1}`;
      }

      function getJourneySegmentLabelParts(segment = {}, day = {}, dayIndex = 0) {
        const metric = getJourneySegmentLabel(segment);
        if (!metric) return null;
        return {
          day: getJourneyShortDayLabel(day, dayIndex),
          metric,
        };
      }

      function getJourneySegmentLabelTone(segment = {}) {
        const statusText = [
          segment.confidence,
          segment.source,
          segment.verification_note,
          segment.distance_text,
          segment.duration_text,
        ]
          .filter(Boolean)
          .join(" ");
        if (/amap_driving|高德/i.test(statusText) && !/待/.test(statusText)) {
          return "verified";
        }
        if (/estimated|估算/i.test(statusText)) {
          return "estimated";
        }
        return "pending";
      }

      function getJourneySegmentLabelOffset(segmentIndex = 0, dayIndex = 0) {
        const offsets = [
          { x: 0, y: -18 },
          { x: 32, y: -38 },
          { x: -30, y: -4 },
          { x: 50, y: -54 },
          { x: -48, y: 8 },
          { x: 16, y: 14 },
          { x: -18, y: -44 },
        ];
        const index =
          Math.abs(Number(segmentIndex) || 0) + Math.abs(Number(dayIndex) || 0) * 2;
        return offsets[index % offsets.length];
      }

      function getJourneyMidpoint(left, right) {
        if (!left || !right) return null;
        const lng = (Number(left.lng) + Number(right.lng)) / 2;
        const lat = (Number(left.lat) + Number(right.lat)) / 2;
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
        return { lng, lat };
      }

      function wrapAmapLayer(overlay, options = {}) {
        const { contentNode = null, infoWindow = null, map = null, point = null } = options;
        return {
          __journeyMapEngine: "amap",
          overlay,
          setOpacity(opacity) {
            if (typeof overlay?.setOpacity === "function") {
              overlay.setOpacity(opacity);
            }
            if (contentNode?.style) {
              contentNode.style.opacity = String(opacity);
            }
            if (typeof overlay?.setOptions === "function") {
              overlay.setOptions({
                strokeOpacity: opacity,
                fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
              });
            }
          },
          setStyle(style = {}) {
            if (typeof overlay?.setOptions !== "function") return;
            overlay.setOptions({
              strokeOpacity: style.opacity,
              fillOpacity:
                typeof style.fillOpacity === "number" ? style.fillOpacity : undefined,
              strokeWeight: style.weight,
              strokeColor: style.color,
            });
          },
          openPopup() {
            if (infoWindow && map && point) {
              infoWindow.open(map, getAmapPosition(point));
            }
          },
        };
      }

      function createAmapJourneyMarker(AMap, map, point, options = {}) {
        const kind = options.kind || point.kind || "highlight";
        const contentNode = buildAmapMarkerContent(
          kind,
          options.text || (kind === "highlight" ? "★" : "●"),
          options.color || ""
        );
        if (options.dayKey) {
          contentNode.dataset.mapDayStop = `${options.dayKey}:${options.stopIndex || 0}`;
        }
        const marker = new AMap.Marker({
          position: getAmapPosition(point),
          content: contentNode,
          offset: new AMap.Pixel(-11, -11),
          zIndex: options.zIndex || 100,
        });
        marker.setMap(map);
        const infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -18),
          content: `
            <div class="amap-journey-popup">
              <strong>${escapeHtml(point.label || options.label || "地点")}</strong>
              <span>${escapeHtml(point.address || point.name || "")}</span>
            </div>
          `,
        });
        marker.on?.("click", () => {
          infoWindow.open(map, marker.getPosition());
          options.onClick?.();
        });
        return wrapAmapLayer(marker, { contentNode, infoWindow, map, point });
      }

      function createAmapJourneyPolyline(AMap, map, points, options = {}) {
        const path = (points || [])
          .map((point) => getAmapPosition(point))
          .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
        if (path.length < 2) return null;
        const polyline = new AMap.Polyline({
          path,
          strokeColor: options.color || "#16b8aa",
          strokeWeight: options.weight || 5,
          strokeOpacity: options.opacity ?? 0.9,
          strokeStyle: options.dashed ? "dashed" : "solid",
          lineJoin: "round",
          lineCap: "round",
          zIndex: options.zIndex || 80,
        });
        polyline.setMap(map);
        return wrapAmapLayer(polyline);
      }

      function createAmapJourneySegmentLabel(
        AMap,
        map,
        left,
        right,
        segment,
        color,
        segmentIndex = 0,
        day = {},
        dayIndex = 0
      ) {
        const labelParts = getJourneySegmentLabelParts(segment, day, dayIndex);
        const midpoint = getJourneyMidpoint(left, right);
        if (!labelParts || !midpoint) return null;
        const tone = getJourneySegmentLabelTone(segment);
        const offset = getJourneySegmentLabelOffset(segmentIndex, dayIndex);
        const contentNode = document.createElement("div");
        contentNode.className = `amap-journey-segment-label ${tone}`;
        contentNode.innerHTML = `<strong>${escapeHtml(labelParts.day)}</strong><span>${escapeHtml(labelParts.metric)}</span>`;
        contentNode.title =
          segment?.verification_note ||
          (tone === "verified" ? "高德路线已核验" : "距离/时长待二次核验");
        contentNode.style.borderColor = color;
        const marker = new AMap.Marker({
          position: [midpoint.lng, midpoint.lat],
          content: contentNode,
          offset: new AMap.Pixel(-58 + offset.x, offset.y),
          zIndex: 160,
        });
        marker.setMap(map);
        return wrapAmapLayer(marker, { contentNode });
      }

      function getJourneyDayBadgeLabel(day = {}, index = 0) {
        const label = String(day.label || "").trim();
        if (label && !/^day\s*\d+$/i.test(label)) return label;
        return `Day ${index + 1}`;
      }

      function createAmapJourneyDayBadge(AMap, map, point, day, color, index = 0) {
        if (!point) return null;
        const contentNode = document.createElement("div");
        contentNode.className = "amap-journey-day-badge";
        contentNode.style.borderColor = color;
        contentNode.innerHTML = `
          <strong>${escapeHtml(getJourneyDayBadgeLabel(day, index))}</strong>
          <span>${escapeHtml((day.points || []).length ? `${(day.points || []).length}站` : "路线")}</span>
        `;
        const badgeOffsets = [
          [-18, -58],
          [16, -70],
          [-66, -42],
          [24, -34],
          [-54, -72],
        ];
        const [offsetX, offsetY] = badgeOffsets[Math.abs(Number(index) || 0) % badgeOffsets.length];
        const marker = new AMap.Marker({
          position: getAmapPosition(point),
          content: contentNode,
          offset: new AMap.Pixel(offsetX, offsetY),
          zIndex: 170,
        });
        marker.setMap(map);
        return wrapAmapLayer(marker, { contentNode });
      }

      async function renderAmapJourneyMap(node, payload, preview, mapConfig) {
        const AMap = await loadAmapJourneyMapAssets(mapConfig?.amap_web_js_key);
        if (!AMap) throw new Error("amap-sdk-unavailable");
        const points = Array.isArray(preview?.points) ? preview.points : [];
        if (!points.length) throw new Error("map-preview-empty");

        node.innerHTML = "";
        node.classList.add("journey-live-map--amap");
        const map = new AMap.Map(node, {
          zoom: 8,
          viewMode: "2D",
          resizeEnable: true,
          mapStyle: "amap://styles/normal",
        });
        map.invalidateSize = () => map.resize?.();
        map.flyTo = ([lat, lng], zoom = 11) => {
          map.setZoomAndCenter(zoom, [lng, lat]);
          return map;
        };
        if (AMap.Scale) map.addControl(new AMap.Scale());
        if (AMap.ToolBar) {
          map.addControl(
            new AMap.ToolBar({
              position: { right: "12px", top: "12px" },
            })
          );
        }

        const orderedKinds = ["origin", "destination", "stay"];
        const routePoints = points
          .filter((point) => orderedKinds.includes(point.kind))
          .sort((a, b) => orderedKinds.indexOf(a.kind) - orderedKinds.indexOf(b.kind));
        const highlightPoints = points.filter((point) => point.kind === "highlight");
        const recommendationPoints = points.filter(isJourneyRecommendationPoint);
        const pointsByKind = Object.fromEntries(
          routePoints.map((point) => [point.kind, point])
        );
        const markersByKind = {};
        const shell = node.closest(".journey-live-map-shell");
        let entry = null;

        const markers = points.map((point) => {
          const highlightIndex =
            point.kind === "highlight" ? markersByKind.highlight?.length || 0 : 0;
          const marker = createAmapJourneyMarker(AMap, map, point, {
            kind: point.kind,
            text: point.kind === "highlight" ? "★" : point.kind === "recommendation" ? "+" : "●",
            onClick:
              point.kind === "recommendation"
                ? () => {
                    if (entry) showJourneyRecommendationSheet(entry, point);
                  }
                : point.kind === "highlight"
                ? () => {
                    activateJourneyHighlightCard(shell, highlightIndex);
                  }
                : null,
          });
          if (!markersByKind[point.kind]) markersByKind[point.kind] = [];
          markersByKind[point.kind].push(marker);
          return marker;
        });

        const routeLine =
          routePoints.length >= 2
            ? createAmapJourneyPolyline(AMap, map, routePoints, {
                color: "#d6a56c",
                weight: 5,
                dashed: true,
                zIndex: 70,
              })
            : null;

        const dayLayers = (Array.isArray(preview?.days) ? preview.days : [])
          .map((day, index) => {
            const dayPoints = Array.isArray(day?.points) ? day.points : [];
            if (!dayPoints.length) return null;
            const color = getJourneyDayColor(index);
            const dayMarkers = dayPoints.map((point, pointIndex) =>
              createAmapJourneyMarker(AMap, map, point, {
                kind: "day",
                text: String(pointIndex + 1),
                color,
                zIndex: 130 + index,
                label: day.label || `Day ${index + 1}`,
                dayKey: day.key || `day-${index + 1}`,
                stopIndex: pointIndex,
                onClick: () => {
                  if (entry) {
                    focusJourneyDayStop(entry, day.key || `day-${index + 1}`, pointIndex);
                  }
                },
              })
            );
            const polyline = createAmapJourneyPolyline(AMap, map, dayPoints, {
              color,
              weight: 5,
              zIndex: 90 + index,
            });
            const dayBadge = createAmapJourneyDayBadge(
              AMap,
              map,
              dayPoints[0],
              day,
              color,
              index
            );
            const segmentLabels = (Array.isArray(day?.segments) ? day.segments : [])
              .map((segment, segmentIndex) =>
                createAmapJourneySegmentLabel(
                  AMap,
                  map,
                  dayPoints[segmentIndex],
                  dayPoints[segmentIndex + 1],
                  segment,
                  color,
                  segmentIndex,
                  day,
                  index
                )
              )
              .filter(Boolean);
            return {
              key: day.key || `day-${index + 1}`,
              label: day.label || `Day ${index + 1}`,
              points: dayPoints,
              markers: dayMarkers,
              dayBadge,
              segmentLabels,
              polyline,
              bounds: buildAmapBoundsFromLayers([...dayMarkers, dayBadge, polyline, ...segmentLabels].filter(Boolean)),
            };
          })
          .filter(Boolean);

        const allBounds = buildAmapBoundsFromLayers([
          ...markers,
          routeLine,
          ...dayLayers.flatMap((layer) => [...layer.markers, layer.dayBadge, layer.polyline, ...(layer.segmentLabels || [])]),
        ].filter(Boolean));
        const dayBounds = buildAmapBoundsFromLayers(
          dayLayers.flatMap((layer) => [...layer.markers, layer.dayBadge, layer.polyline, ...(layer.segmentLabels || [])]).filter(Boolean)
        );
        const routeBounds = buildAmapBoundsFromLayers([
          ...orderedKinds.flatMap((kind) => markersByKind[kind] || []),
          routeLine,
        ].filter(Boolean));
        const highlightBounds = buildAmapBoundsFromLayers([
          ...(markersByKind.highlight || []),
          ...(markersByKind.recommendation || []),
        ]);
        if (points.length === 1) {
          map.setZoomAndCenter(11, getAmapPosition(points[0]));
        } else {
          fitJourneyMapState(
            {
              map,
              allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
              routeBounds,
              highlightBounds,
            },
            "all"
          );
        }

        entry = {
          engine: "amap",
          map,
          baseLayers: null,
          activeLayerKey: "standard",
          shell,
          points,
          pointsByKind,
          markersByKind,
          routePoints,
          highlightPoints,
          recommendationPoints,
          markers,
          routeLine,
          dayLayers,
          dayPlans: parseMapPayload(shell?.dataset.dayPlans || "") || [],
          routeStops: parseMapPayload(shell?.dataset.routeStops || "") || [],
          activeDayKey: "all",
          dayDisplayMode: "solo",
          recommendationsVisible: false,
          allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
          routeBounds,
          highlightBounds,
        };
        registerJourneyMapEntry(node, entry);
      }

      async function hydrateJourneyMap(node) {
        if (!node || node.dataset.mapReady === "1" || node.dataset.mapReady === "loading") {
          return;
        }
        const payload = parseMapPayload(node.dataset.mapPayload || "");
        if (!payload) {
          node.dataset.mapReady = "error";
          node.innerHTML = '<div class="journey-live-map-state error">路线地图载入失败</div>';
          return;
        }

        node.dataset.mapReady = "loading";
        node.innerHTML = '<div class="journey-live-map-state loading">正在定位行程路线的关键地点…</div>';

        try {
          const preview = await fetchJourneyMapPreview(payload);
          const points = Array.isArray(preview?.points) ? preview.points : [];
          if (!points.length) {
            throw new Error("map-preview-empty");
          }

          const mapConfig =
            preview?.provider === "amap-js"
              ? await fetchJourneyMapConfig()
              : getFallbackJourneyMapConfig();
          if (shouldUseAmapJourneyMap(preview, mapConfig)) {
            try {
              await renderAmapJourneyMap(node, payload, preview, mapConfig);
              return;
            } catch (amapError) {
              node.classList.remove("journey-live-map--amap");
              console.warn("AMap journey map failed, falling back to Leaflet", amapError);
            }
          }

          const L = await loadJourneyMapAssets();
          node.innerHTML = "";
          node.classList.remove("journey-live-map--amap");
          const map = L.map(node, {
            zoomControl: true,
            scrollWheelZoom: false,
            attributionControl: true,
          });
          const baseLayers = {
            standard: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
              maxZoom: 18,
              attribution: "&copy; OpenStreetMap contributors",
            }),
            terrain: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
              maxZoom: 17,
              attribution: "Map data: &copy; OpenTopoMap contributors",
            }),
            calm: L.tileLayer(
              "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
              {
                maxZoom: 19,
                attribution: "&copy; CARTO & OpenStreetMap contributors",
              }
            ),
          };
          baseLayers.standard.addTo(map);

          const orderedKinds = ["origin", "destination", "stay"];
          const routePoints = points
            .filter((point) => orderedKinds.includes(point.kind))
            .sort((a, b) => orderedKinds.indexOf(a.kind) - orderedKinds.indexOf(b.kind));
          const highlightPoints = points.filter((point) => point.kind === "highlight");
          const recommendationPoints = points.filter(isJourneyRecommendationPoint);
          const pointsByKind = Object.fromEntries(
            routePoints.map((point) => [point.kind, point])
          );
          const markersByKind = {};
          const shell = node.closest(".journey-live-map-shell");
          let entry = null;

          const latLngs = [];
          const markers = [];
          points.forEach((point) => {
            const marker = L.marker([point.lat, point.lng], {
              icon: buildJourneyMapIcon(L, point.kind),
            }).addTo(map);
            marker.bindPopup(
              `<strong>${escapeHtml(point.label)}</strong><br>${escapeHtml(
                point.address || point.name
              )}`
            );
            if (point.kind === "highlight") {
              const highlightIndex = markersByKind.highlight?.length || 0;
              marker.on("click", () => {
                activateJourneyHighlightCard(shell, highlightIndex);
              });
            } else if (point.kind === "recommendation") {
              marker.on("click", () => {
                if (entry) showJourneyRecommendationSheet(entry, point);
              });
            }
            latLngs.push([point.lat, point.lng]);
            markers.push(marker);
            if (!markersByKind[point.kind]) markersByKind[point.kind] = [];
            markersByKind[point.kind].push(marker);
          });

          let routeLine = null;
          if (routePoints.length >= 2) {
            const routeLatLngs = routePoints.map((point) => [point.lat, point.lng]);
            routeLine = L.polyline(routeLatLngs, {
              color: "#d6a56c",
              weight: 4,
              opacity: 0.9,
              dashArray: "10 8",
            }).addTo(map);
          }

          const dayLayers = (Array.isArray(preview?.days) ? preview.days : [])
            .map((day, index) => {
              const dayPoints = Array.isArray(day?.points) ? day.points : [];
              if (!dayPoints.length) return null;
              const color = getJourneyDayColor(index);
              const markers = dayPoints.map((point, pointIndex) => {
                const dayKey = day.key || `day-${index + 1}`;
                const marker = L.marker([point.lat, point.lng], {
                  icon: buildJourneyDayMapIcon(
                    L,
                    String(pointIndex + 1),
                    color,
                    dayKey,
                    pointIndex
                  ),
                }).addTo(map);
                const markerElement = marker.getElement?.() || marker._icon || marker._element;
                if (markerElement?.dataset) {
                  markerElement.dataset.mapDayStop = `${dayKey}:${pointIndex}`;
                }
                marker.bindPopup(
                  `<strong>${escapeHtml(day.label || `Day ${index + 1}`)}</strong><br>${escapeHtml(
                    point.address || point.name
                  )}`
                );
                marker.on("click", () => {
                  if (entry) {
                    focusJourneyDayStop(entry, dayKey, pointIndex);
                  }
                });
                return marker;
              });
              const dayLatLngs = dayPoints.map((point) => [point.lat, point.lng]);
              const polyline =
                dayLatLngs.length >= 2
                  ? L.polyline(dayLatLngs, {
                      color,
                      weight: 4,
                      opacity: 0.92,
                    }).addTo(map)
                  : null;
              const firstPoint = dayPoints[0];
              const dayBadge = firstPoint
                ? L.marker([firstPoint.lat, firstPoint.lng], {
                    icon: L.divIcon({
                      className: "leaflet-journey-day-badge",
                      html: `<span style="border-color:${escapeHtml(color)}"><strong>${escapeHtml(
                        getJourneyDayBadgeLabel(day, index)
                      )}</strong><small>${escapeHtml(dayPoints.length ? `${dayPoints.length}站` : "路线")}</small></span>`,
                      iconSize: [118, 42],
                      iconAnchor: [
                        [18, -18, 66, -24, 54][Math.abs(index) % 5],
                        [52, 64, 42, 34, 70][Math.abs(index) % 5],
                      ],
                    }),
                    interactive: false,
                  }).addTo(map)
                : null;
              const segmentLabels = (Array.isArray(day?.segments) ? day.segments : [])
                .map((segment, segmentIndex) => {
                  const midpoint = getJourneyMidpoint(
                    dayPoints[segmentIndex],
                    dayPoints[segmentIndex + 1]
                  );
                  const labelParts = getJourneySegmentLabelParts(segment, day, index);
                  if (!midpoint || !labelParts) return null;
                  const tone = getJourneySegmentLabelTone(segment);
                  const offset = getJourneySegmentLabelOffset(segmentIndex, index);
                  return L.marker([midpoint.lat, midpoint.lng], {
                    icon: L.divIcon({
                      className: "leaflet-journey-segment-label",
                      html: `<span class="${escapeHtml(tone)}" style="border-color:${escapeHtml(color)}" title="${escapeHtml(
                        segment?.verification_note ||
                          (tone === "verified" ? "高德路线已核验" : "距离/时长待二次核验")
                      )}"><strong>${escapeHtml(labelParts.day)}</strong><small>${escapeHtml(
                        labelParts.metric
                      )}</small></span>`,
                      iconSize: [160, 40],
                      iconAnchor: [80 - offset.x, 20 - offset.y],
                    }),
                    interactive: false,
                  }).addTo(map);
                })
                .filter(Boolean);
              return {
                key: day.key || `day-${index + 1}`,
                label: day.label || `Day ${index + 1}`,
                points: dayPoints,
                markers,
                dayBadge,
                segmentLabels,
                polyline,
                bounds: buildBoundsFromPoints(L, dayPoints),
              };
            })
            .filter(Boolean);

          const allBounds = buildBoundsFromPoints(L, points);
          const routeBounds = buildBoundsFromPoints(L, routePoints);
          const highlightBounds = buildBoundsFromPoints(L, recommendationPoints);
          const dayBounds = buildBoundsFromPoints(
            L,
            dayLayers.flatMap((layer) => layer.points || [])
          );
          if (latLngs.length === 1) {
            map.setView(latLngs[0], 11);
          } else {
            fitJourneyMapState(
              {
                map,
                allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
                routeBounds,
                highlightBounds,
              },
              "all"
            );
          }

          entry = {
            map,
            baseLayers,
            activeLayerKey: "standard",
            shell,
            points,
            pointsByKind,
            markersByKind,
            routePoints,
            highlightPoints,
            recommendationPoints,
            markers,
            routeLine,
            dayLayers,
            dayPlans: parseMapPayload(shell?.dataset.dayPlans || "") || [],
            routeStops: parseMapPayload(shell?.dataset.routeStops || "") || [],
            activeDayKey: "all",
            dayDisplayMode: "solo",
            recommendationsVisible: false,
            allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
            routeBounds,
            highlightBounds,
          };
          registerJourneyMapEntry(node, entry);
        } catch (error) {
          node.dataset.mapReady = "error";
          node.innerHTML =
            '<div class="journey-live-map-state error">暂时没能定位到路线地图，请先查看文字方案。</div>';
        }
      }

      function hydrateJourneyMaps(root = document) {
        root
          .querySelectorAll(".journey-live-map[data-map-payload]")
          .forEach((node) => hydrateJourneyMap(node));
      }

      function scheduleJourneyMapHydration(root = document) {
        requestAnimationFrame(() => hydrateJourneyMaps(root));
      }

      function closeJourneyMapModal() {
        const modal = document.getElementById("journeyMapModal");
        if (!modal) return;
        modal.classList.remove("show");
        modal.setAttribute("aria-hidden", "true");
        document.body.classList.remove("journey-map-modal-open");
      }

      function openJourneyMapModalFromButton(button) {
        const shell = button.closest(".journey-live-map-shell");
        const sourceMap = shell?.querySelector(".journey-live-map[data-map-payload]");
        const modal = document.getElementById("journeyMapModal");
        const modalShell = document.getElementById("journeyMapModalShell");
        const modalDays = document.getElementById("journeyMapModalDays");
        if (!shell || !sourceMap || !modal) return;
        const payload = sourceMap.dataset.mapPayload || "";
        const title = shell.dataset.mapTitle || "路线地图";
        const dayPlans = parseMapPayload(shell.dataset.dayPlans || "") || [];
        const modalTitle = modal.querySelector(".journey-map-modal-title");
        const modalMap = modal.querySelector(".journey-live-map-modal-canvas");
        if (!modalTitle || !modalMap) return;
        modalTitle.textContent = title;
        if (modalShell) {
          modalShell.dataset.mapTitle = title;
          modalShell.dataset.dayPlans = shell.dataset.dayPlans || "[]";
          modalShell.dataset.routeStops = shell.dataset.routeStops || "[]";
          modalShell.dataset.activeDay = "all";
          modalShell.dataset.dayMode = "solo";
        }
        if (modalDays) {
          modalDays.innerHTML = `
            <button class="journey-map-day-btn active" type="button" data-map-day="all" aria-pressed="true" title="查看全程总览">
              <span>总览</span><small>全程</small>
            </button>
            ${dayPlans
              .map(
                (day, index) => `
                  <button class="journey-map-day-btn" type="button" data-map-day="${escapeHtml(
                    day.key || `day-${index + 1}`
                  )}" aria-pressed="false" title="${escapeHtml(day.label || `Day ${index + 1}`)}">
                    <span>${escapeHtml(day.label || `Day ${index + 1}`)}</span>
                    <small>单日</small>
                  </button>
                `
              )
              .join("")}
          `;
        }
        modalMap.dataset.mapPayload = payload;
        modalMap.dataset.dayPlans = shell.dataset.dayPlans || "[]";
        modalMap.dataset.routeStops = shell.dataset.routeStops || "[]";
        modalMap.dataset.mapReady = "";
        modalMap.innerHTML =
          '<div class="journey-live-map-state loading">正在准备大图地图…</div>';
        modal.classList.add("show");
        modal.setAttribute("aria-hidden", "false");
        document.body.classList.add("journey-map-modal-open");
        hydrateJourneyMap(modalMap);
      }

      function syncJourneyMapToggleLabels(shell) {
        if (!shell) return;
        const toolsCollapsed = shell.classList.contains("journey-map-tools-collapsed");
        shell
          .querySelectorAll('[data-map-action="toggle-tools"]')
          .forEach((button) => {
            button.textContent = toolsCollapsed ? "地图工具" : "收起工具";
            button.title = toolsCollapsed ? "展开地图工具" : "收起地图工具";
            button.setAttribute("aria-expanded", String(!toolsCollapsed));
          });

        const sidebarCollapsed = shell.classList.contains(
          "journey-map-sidebar-collapsed"
        );
        shell
          .querySelectorAll('[data-map-action="toggle-sidebar"]')
          .forEach((button) => {
            button.textContent = sidebarCollapsed ? "展开路线说明" : "收起路线说明";
            button.title = sidebarCollapsed ? "展开路线说明" : "收起路线说明";
            button.setAttribute("aria-expanded", String(!sidebarCollapsed));
          });

        const bottomDrawer = shell.querySelector(".journey-map-bottom-drawer");
        const drawerCollapsed = bottomDrawer?.classList.contains("is-collapsed");
        shell
          .querySelectorAll('[data-map-action="toggle-bottom-drawer"]')
          .forEach((button) => {
            button.textContent = drawerCollapsed ? "展开" : "收起";
            button.title = drawerCollapsed ? "展开分日路线" : "收起分日路线";
            button.setAttribute("aria-expanded", String(!drawerCollapsed));
          });
      }

      function handleJourneyMapAction(button) {
        if (button.disabled) return;
        const action = button.dataset.mapAction || "";
        const shell = button.closest(".journey-live-map-shell");
        if (action === "toggle-tools") {
          shell?.classList.toggle("journey-map-tools-collapsed");
          syncJourneyMapToggleLabels(shell);
          return;
        }
        if (action === "toggle-sidebar") {
          shell?.classList.toggle("journey-map-sidebar-collapsed");
          syncJourneyMapToggleLabels(shell);
          const mapNode = shell?.querySelector(".journey-live-map[data-map-payload]");
          const entry = mapNode ? journeyMapInstances.get(mapNode) : null;
          setTimeout(() => entry?.map?.invalidateSize(), 80);
          return;
        }
        if (action === "toggle-bottom-drawer") {
          const drawer = shell?.querySelector(".journey-map-bottom-drawer");
          drawer?.classList.toggle("is-collapsed");
          syncJourneyMapToggleLabels(shell);
          const mapNode = shell?.querySelector(".journey-live-map[data-map-payload]");
          const entry = mapNode ? journeyMapInstances.get(mapNode) : null;
          setTimeout(() => entry?.map?.invalidateSize(), 80);
          return;
        }
        if (action === "expand") {
          openJourneyMapModalFromButton(button);
          return;
        }

        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        if (action === "recommendations") {
          toggleJourneyRecommendations(entry);
          return;
        }
        if (action === "highlights") {
          entry.recommendationsVisible = true;
          applyJourneyDayView(entry);
        }
        fitJourneyMapState(entry, action === "highlights" ? "highlights" : "route");

        shell.querySelectorAll(".journey-map-action-btn").forEach((btn) => {
          const shouldActivate =
            btn.dataset.mapAction === action &&
            (action === "route" || action === "highlights");
          btn.classList.toggle("active", shouldActivate);
          if (
            btn.dataset.mapAction === "route" ||
            btn.dataset.mapAction === "highlights"
          ) {
            btn.setAttribute("aria-pressed", String(shouldActivate));
          }
        });
      }

      function handleJourneyMapStyle(button) {
        if (button.disabled) return;
        const style = button.dataset.mapStyle || "standard";
        const shell = button.closest(".journey-live-map-shell");
        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        setJourneyMapStyle(entry, style);

        shell.querySelectorAll(".journey-map-style-btn").forEach((btn) => {
          const isActive = btn === button;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", String(isActive));
        });
      }

      function handleJourneyMapFocus(button) {
        if (button.disabled) return;
        const focus = button.dataset.mapFocus || "destination";
        const shell = button.closest(".journey-live-map-shell");
        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        focusJourneyMapTarget(entry, focus);

        shell.querySelectorAll(".journey-map-focus-btn").forEach((btn) => {
          btn.classList.toggle("active", btn === button);
        });
      }

      function handleJourneyMapDay(button) {
        if (button.disabled) return;
        const dayKey = button.dataset.mapDay || "all";
        const shell = button.closest(".journey-live-map-shell");
        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        setJourneyMapDaySelection(entry, dayKey);
      }

      function handleJourneyMapDayMode(button) {
        if (button.disabled) return;
        const mode = button.dataset.mapDayMode || "solo";
        const shell = button.closest(".journey-live-map-shell");
        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        setJourneyMapDayMode(entry, mode);
      }

      function handleJourneyMapStageStop(button) {
        const stopMeta = button.dataset.mapDayStop || "";
        const shell = button.closest(".journey-live-map-shell");
        const node = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);

        if (stopMeta.includes(":")) {
          const [dayKey, stopIndexText] = stopMeta.split(":");
          const stopIndex = Number(stopIndexText);
          activateJourneyBottomStop(shell, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
          focusJourneyDayStop(entry, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
          return;
        }

        const focusTarget = button.dataset.mapFocus || "";
        if (focusTarget) {
          focusJourneyMapTarget(entry, focusTarget);
        }
      }

      function focusJourneyMapFromPlan(button, target = "destination") {
        const plan = button.closest(".travel-plan");
        const shell = plan?.querySelector(".journey-live-map-shell");
        const node = plan?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        shell?.scrollIntoView({ behavior: "smooth", block: "start" });
        const entry = journeyMapInstances.get(node);
        focusJourneyMapTarget(entry, target);
        if (target === "stay") {
          showToast("已定位到落脚点和周边参考");
        } else if (target === "highlights") {
          showToast("已定位到沿途看点");
        } else {
          showToast("已定位到路线地图");
        }
      }

      function focusJourneyMapDayFromPlan(button) {
        const dayKey = button.dataset.mapDayFocus || "all";
        const plan = button.closest(".travel-plan");
        const node = plan?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return;
        const entry = journeyMapInstances.get(node);
        setJourneyMapDaySelection(entry, dayKey);
      }

      function getVisualJourneyMapEntry(control) {
        const workbench = control.closest(".visual-journey-workbench");
        const node = workbench?.querySelector(".journey-live-map[data-map-payload]");
        if (!node) return null;
        return journeyMapInstances.get(node) || null;
      }

      function getJourneyMapShellFromControl(control) {
        return (
          control.closest(".journey-live-map-shell") ||
          control.closest(".visual-journey-workbench")?.querySelector(".journey-live-map-shell")
        );
      }

      function parseJourneyStopMeta(value = "") {
        if (!String(value || "").includes(":")) return null;
        const [dayKey, stopIndexText] = String(value).split(":");
        const stopIndex = Number(stopIndexText);
        if (!dayKey || Number.isNaN(stopIndex)) return null;
        return { dayKey, stopIndex };
      }

      function cloneJourneyDayPlans(shell) {
        return JSON.parse(
          JSON.stringify(parseMapPayload(shell?.dataset.dayPlans || "") || [])
        );
      }

      function normalizeJourneyDayPlanStops(dayPlan) {
        const stops = Array.isArray(dayPlan.stops)
          ? dayPlan.stops
          : (dayPlan.waypoints || []).map((name) => ({ name }));
        const waypoints = stops
          .map((stop) => cleanJourneyLocationValue(stop?.name || ""))
          .filter(Boolean);
        return {
          ...dayPlan,
          stops,
          waypoints,
        };
      }

      function getJourneyDayRouteStatus(day = {}) {
        const segments = Array.isArray(day.segments) ? day.segments : [];
        if (!segments.length) {
          return {
            tone: "pending",
            label: "路线参考",
            detail: "路程时间行前确认",
          };
        }
        const metricReadyCount = segments.filter((segment) => {
          const metricText = [segment.distance_text, segment.duration_text]
            .filter(Boolean)
            .join(" ");
          return metricText && !/待|needs|unknown/i.test(metricText);
        }).length;
        const verifiedCount = segments.filter(
          (segment) => String(segment.confidence || "") === "amap_driving"
        ).length;
        const estimatedCount = segments.filter((segment) =>
          /estimated|估算/i.test(
            [segment.confidence, segment.source, segment.verification_note]
              .filter(Boolean)
              .join(" ")
          )
        ).length;
        const missingCount = Math.max(segments.length - metricReadyCount, 0);
        if (verifiedCount === segments.length) {
          return {
            tone: "ready",
            label: "路线已核验",
            detail: `${segments.length} 段路程已返回高德距离/时长`,
          };
        }
        if (verifiedCount || estimatedCount || metricReadyCount) {
          return {
            tone: "pending",
            label: verifiedCount ? "部分路线已回填" : "路线已估算",
            detail: `${verifiedCount} 段已核验，${estimatedCount} 段参考估算，${missingCount} 段行前确认`,
          };
        }
        return {
          tone: "pending",
          label: "路线参考",
          detail: `${segments.length} 段路程时间行前确认`,
        };
      }

      function getJourneyDayWeatherStatus(day = {}) {
        const weather = day.weather && typeof day.weather === "object" ? day.weather : {};
        const summary = String(weather.summary || "").trim();
        const city = String(weather.city || day.city || "").trim();
        if (!summary) {
          return {
            tone: "pending",
            label: city ? `${city}天气提示` : "天气提示",
            detail: "出发前确认",
          };
        }
        return {
          tone: /待|needs/i.test(String(weather.confidence || summary))
            ? "pending"
            : "ready",
          label: city ? `${city}天气` : "天气",
          detail: summary,
        };
      }

      function renderJourneyDayStatusChips(day = {}) {
        const routeStatus = getJourneyDayRouteStatus(day);
        const weatherStatus = getJourneyDayWeatherStatus(day);
        const poiCount = Array.isArray(day.pois)
          ? day.pois.length
          : Array.isArray(day.stops)
          ? day.stops.length
          : Array.isArray(day.waypoints)
          ? day.waypoints.length
          : 0;
        return `
          <span class="journey-day-status-chips">
            <span class="journey-status-chip ready">
              <i class="fa-solid fa-location-dot"></i> ${poiCount || 0} 个地点
            </span>
            <span class="journey-status-chip ${escapeHtml(routeStatus.tone)}">
              <i class="fa-solid fa-route"></i> ${escapeHtml(routeStatus.label)}
            </span>
            <span class="journey-status-chip ${escapeHtml(weatherStatus.tone)}" title="${escapeHtml(
              weatherStatus.detail
            )}">
              <i class="fa-solid fa-cloud-sun"></i> ${escapeHtml(weatherStatus.label)}
            </span>
          </span>
        `;
      }

      function buildVisualJourneyStats(journeyData = {}) {
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const pois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const segments = Array.isArray(journeyData.segments) ? journeyData.segments : [];
        const pendingChecks = Array.isArray(journeyData.pending_checks)
          ? journeyData.pending_checks
          : [];
        const routeNeedsCheck =
          !segments.length ||
          segments.some((segment) =>
            /待|needs|fallback|unknown|estimated|估算/i.test(
              [segment.confidence, segment.distance_text, segment.duration_text]
                .filter(Boolean)
                .join(" ")
            )
          );
        const verifiedRouteCount = segments.filter(
          (segment) => String(segment.confidence || "") === "amap_driving"
        ).length;
        const estimatedRouteCount = segments.filter((segment) =>
          /estimated|估算/i.test(
            [segment.confidence, segment.source, segment.verification_note]
              .filter(Boolean)
              .join(" ")
          )
        ).length;
        const cityCount = new Set(
          pois.map((poi) => String(poi.city || "").trim()).filter(Boolean)
        ).size;
        return [
          {
            icon: "fa-calendar-days",
            label: "天数",
            value: `${days.length || journeyData.overview?.duration_days || 0} 天`,
            tone: "ready",
          },
          {
            icon: "fa-map-pin",
            label: "地点",
            value: `${pois.length} 个${cityCount ? ` · ${cityCount} 城` : ""}`,
            tone: "ready",
          },
          {
            icon: "fa-route",
            label: "路线",
            value:
              routeNeedsCheck && (verifiedRouteCount || estimatedRouteCount)
                ? `${verifiedRouteCount} 段核验 · ${estimatedRouteCount} 段估算`
                : routeNeedsCheck
                ? "路程时间行前确认"
                : "已返回路段",
            tone: routeNeedsCheck ? "pending" : "ready",
          },
          {
            icon: "fa-clipboard-check",
            label: "待核验",
            value: `${pendingChecks.length || 0} 项`,
            tone: pendingChecks.length ? "pending" : "ready",
          },
        ];
      }

      function renderVisualJourneyStats(journeyData = {}) {
        return `
          <div class="visual-journey-stats">
            ${buildVisualJourneyStats(journeyData)
              .map(
                (item) => `
                  <div class="visual-journey-stat ${escapeHtml(item.tone)}">
                    <span><i class="fa-solid ${escapeHtml(item.icon)}"></i> ${escapeHtml(
                  item.label
                )}</span>
                    <strong>${escapeHtml(item.value)}</strong>
                  </div>
                `
              )
              .join("")}
          </div>
        `;
      }

      function getVisualPoiInitial(name = "") {
        const normalized = String(name || "").trim();
        return normalized ? normalized.slice(0, 1) : "点";
      }

      function renderVisualPoiMedia(poi = {}, index = 0, compact = false) {
        const imageUrl = String(poi.image_url || "").trim();
        if (/^https?:\/\//i.test(imageUrl)) {
          return `
            <figure class="visual-poi-media${compact ? " compact" : ""}">
              <img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(poi.name || "地点图片")}" loading="lazy">
            </figure>
          `;
        }
        const palette = [
          "lake",
          "temple",
          "mountain",
          "city",
          "forest",
          "street",
        ][index % 6];
        return `
          <figure class="visual-poi-media visual-poi-media--fallback ${palette}${
            compact ? " compact" : ""
          }">
            <span>${escapeHtml(getVisualPoiInitial(poi.name))}</span>
          </figure>
        `;
      }

      function getVisualPoiVerificationBadge(poi = {}) {
        const statusText = String(poi.verification_status || "").trim();
        if (poi.map_verified || /amap/i.test(statusText)) {
          return { tone: "ready", label: "高德核验" };
        }
        if (poi.coordinate_estimated || /estimated/i.test(statusText)) {
          return { tone: "pending", label: "估算落点" };
        }
        if (typeof poi.lng === "number" && typeof poi.lat === "number") {
          return { tone: "ready", label: "坐标可用" };
        }
        return { tone: "pending", label: "待核验" };
      }

      function destroyJourneyMapEntry(node) {
        const entry = node ? journeyMapInstances.get(node) : null;
        try {
          entry?.map?.destroy?.();
          entry?.map?.remove?.();
        } catch (error) {
          // 地图实例销毁失败时继续重建，避免一次异常卡住编辑体验。
        }
        if (node) journeyMapInstances.delete(node);
      }

      function renderJourneyBottomDrawerDays(dayPlans = []) {
        return dayPlans
          .map(
            (day, dayIndex) => `
              <article data-journey-day-card="${escapeHtml(day.key || `day-${dayIndex + 1}`)}">
                <button
                  class="journey-map-day-btn"
                  type="button"
                  data-map-day="${escapeHtml(day.key)}"
                  aria-pressed="false"
                >
                  <span>${escapeHtml(day.label || `Day ${dayIndex + 1}`)}</span>
                  <small>${escapeHtml(day.title || day.note || "当天路线")}</small>
                </button>
                ${renderJourneyDayStatusChips(day)}
                <div>
                  ${(day.waypoints || [])
                    .slice(0, 6)
                    .map(
                      (waypoint, waypointIndex) => `
                        <div class="journey-map-bottom-stop">
                          <button
                            class="journey-map-stage-stop journey-map-stage-stop--inline"
                            type="button"
                            data-map-day-stop="${escapeHtml(day.key)}:${waypointIndex}"
                          >
                            <span>${waypointIndex + 1}</span>
                            <strong>${escapeHtml(waypoint)}</strong>
                          </button>
                          <div class="journey-map-stop-edit-actions">
                            <button
                              type="button"
                              data-journey-edit-action="up"
                              data-map-day-stop="${escapeHtml(day.key)}:${waypointIndex}"
                              title="上移这个地点"
                              ${waypointIndex === 0 ? "disabled" : ""}
                            >↑</button>
                            <button
                              type="button"
                              data-journey-edit-action="down"
                              data-map-day-stop="${escapeHtml(day.key)}:${waypointIndex}"
                              title="下移这个地点"
                              ${waypointIndex >= (day.waypoints || []).length - 1 ? "disabled" : ""}
                            >↓</button>
                            <button
                              type="button"
                              data-journey-edit-action="delete"
                              data-map-day-stop="${escapeHtml(day.key)}:${waypointIndex}"
                              title="删除这个地点"
                            >×</button>
                          </div>
                        </div>
                      `
                    )
                    .join("")}
                </div>
              </article>
            `
          )
          .join("");
      }

      function refreshJourneyMapAfterEdit(shell, dayPlans) {
        const mapNode = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!shell || !mapNode) return;
        const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
        const payload = parseMapPayload(mapNode.dataset.mapPayload || "") || {};
        payload.days = normalizedDayPlans.map((day) => ({
          key: day.key,
          label: day.label,
          waypoints: day.waypoints,
          stops: day.stops || [],
          segments: buildEditedJourneySegments(day.dayNumber || 1, day.stops || []),
        }));
        shell.dataset.dayPlans = serializeMapPayload(normalizedDayPlans);
        mapNode.dataset.mapPayload = serializeMapPayload(payload);
        const drawerDays = shell.querySelector(".journey-map-bottom-days");
        if (drawerDays) {
          drawerDays.innerHTML = renderJourneyBottomDrawerDays(normalizedDayPlans);
        }
        destroyJourneyMapEntry(mapNode);
        mapNode.dataset.mapReady = "";
        mapNode.innerHTML =
          '<div class="journey-live-map-state loading">正在按新顺序刷新路线…</div>';
        hideJourneyPoiSheet(shell);
        hydrateJourneyMap(mapNode);
      }

      function updateVisualJourneyPoiCards(workbench, dayPlans) {
        if (!workbench) return;
        const activeIds = new Set(
          dayPlans.flatMap((day) => (day.stops || []).map((stop) => stop.id).filter(Boolean))
        );
        if (!activeIds.size) return;
        workbench.querySelectorAll(".visual-poi-card[data-poi-id]").forEach((card) => {
          const poiId = card.dataset.poiId || "";
          const visible = !poiId || activeIds.has(poiId);
          card.hidden = !visible;
          const stopRef = dayPlans
            .flatMap((day) =>
              (day.stops || []).map((stop, index) => ({
                dayKey: day.key,
                index,
                id: stop.id,
              }))
            )
            .find((item) => item.id === poiId);
          if (stopRef) {
            card
              .querySelectorAll("[data-map-day-stop]")
              .forEach((button) => {
                button.dataset.mapDayStop = `${stopRef.dayKey}:${stopRef.index}`;
              });
          }
        });
      }

      function buildEditedJourneySegments(dayNumber, pois = []) {
        const segments = [];
        for (let index = 0; index < Math.max(pois.length - 1, 0); index += 1) {
          const left = pois[index];
          const right = pois[index + 1];
          segments.push({
            id: `d${dayNumber}-s${index + 1}`,
            day_number: dayNumber,
            from_poi_id: left.id || "",
            to_poi_id: right.id || "",
            from_name: left.name || "",
            to_name: right.name || "",
            mode: "driving",
            distance_text: "待高德路线核验",
            duration_text: "待高德路线核验",
            confidence: "needs_live_route",
          });
        }
        return segments;
      }

      function buildJourneyDataFromEditedPlans(workbench, dayPlans) {
        const original = parseMapPayload(workbench?.dataset.journeyData || "") || {};
        if (original.version !== "journey_plan.v1") return null;
        const normalizedPlans = dayPlans.map(normalizeJourneyDayPlanStops);
        const days = (Array.isArray(original.days) ? original.days : []).map((day) => {
          const planKey = `visual-day-${day.day_number || 1}`;
          const plan = normalizedPlans.find((item) => item.key === planKey);
          if (!plan) return day;
          const pois = (plan.stops || []).map((stop, index) => ({
            ...normalizeJourneyPoiAsStop(stop, { city: day.city || "" }),
            id: stop.id || `d${day.day_number || 1}-p${index + 1}`,
            day_number: day.day_number || plan.dayNumber || 1,
            order: index + 1,
            suggested_time: stop.time_range || stop.suggested_time || "",
          }));
          return {
            ...day,
            summary: pois.map((poi) => poi.name).filter(Boolean).join(" · "),
            pois,
            segments: buildEditedJourneySegments(day.day_number || plan.dayNumber || 1, pois),
          };
        });
        const activePois = days.flatMap((day) => day.pois || []);
        const activeIds = new Set(activePois.map((poi) => poi.id).filter(Boolean));
        const originalPois = Array.isArray(original.pois) ? original.pois : [];
        const inactiveOriginalPois = originalPois.filter(
          (poi) => !poi.id || !activeIds.has(poi.id)
        );
        const pois = [...activePois, ...inactiveOriginalPois];
        const segments = days.flatMap((day) => day.segments || []);
        return {
          ...original,
          days,
          pois,
          segments,
          source_summary: {
            ...(original.source_summary || {}),
            edited_by_user: true,
          },
        };
      }

      async function saveEditedJourneyDraft(workbench, dayPlans) {
        if (!state.token || !state.currentConversationId || !workbench) return;
        const journeyData = buildJourneyDataFromEditedPlans(workbench, dayPlans);
        if (!journeyData) return;
        workbench.dataset.journeyData = serializeMapPayload(journeyData);
        try {
          const response = await fetch(
            `${getApiBase()}/api/v1/chat/journey/${state.currentConversationId}`,
            {
              method: "PATCH",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${state.token}`,
              },
              body: JSON.stringify({
                journey_data: journeyData,
                source: "frontend_visual_editor",
              }),
            }
          );
          if (!response.ok) throw new Error(`journey-save-${response.status}`);
          showToast("路线草案已保存");
        } catch (error) {
          console.error(error);
          showToast("路线已本地更新，保存到会话失败", true);
        }
      }

      function handleJourneyEditAction(button) {
        if (button.disabled) return;
        const action = button.dataset.journeyEditAction || "";
        const meta = parseJourneyStopMeta(button.dataset.mapDayStop || "");
        const shell = getJourneyMapShellFromControl(button);
        if (!action || !meta || !shell) return;
        const dayPlans = cloneJourneyDayPlans(shell).map(normalizeJourneyDayPlanStops);
        const day = dayPlans.find((item) => item.key === meta.dayKey);
        if (!day || !Array.isArray(day.stops)) return;
        const index = meta.stopIndex;
        if (index < 0 || index >= day.stops.length) return;

        if (action === "delete") {
          if (day.stops.length <= 1) {
            showToast("当天至少保留一个地点", true);
            return;
          }
          day.stops.splice(index, 1);
        } else if (action === "up" && index > 0) {
          [day.stops[index - 1], day.stops[index]] = [day.stops[index], day.stops[index - 1]];
        } else if (action === "down" && index < day.stops.length - 1) {
          [day.stops[index], day.stops[index + 1]] = [day.stops[index + 1], day.stops[index]];
        } else {
          return;
        }
        const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
        updateVisualJourneyPoiCards(
          button.closest(".visual-journey-workbench"),
          normalizedDayPlans
        );
        refreshJourneyMapAfterEdit(shell, normalizedDayPlans);
        saveEditedJourneyDraft(
          button.closest(".visual-journey-workbench"),
          normalizedDayPlans
        );
        showToast("已更新当天路线顺序");
      }

      function handleVisualJourneyDayFocus(button) {
        const dayKey = button.dataset.mapDayFocus || "all";
        const entry = getVisualJourneyMapEntry(button);
        if (!entry) return;
        setJourneyMapDaySelection(entry, dayKey);
        button
          .closest(".visual-journey-workbench")
          ?.querySelector(".journey-live-map-shell")
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }

      function handleVisualJourneyPoiFocus(button) {
        const stopMeta = button.dataset.mapDayStop || "";
        const entry = getVisualJourneyMapEntry(button);
        if (!entry) return;
        if (stopMeta.includes(":")) {
          const [dayKey, stopIndexText] = stopMeta.split(":");
          const stopIndex = Number(stopIndexText);
          focusJourneyDayStop(entry, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
        }
        button
          .closest(".visual-journey-workbench")
          ?.querySelector(".journey-live-map-shell")
          ?.scrollIntoView({ behavior: "smooth", block: "center" });
      }

      function showIntroOverlay() {
        const intro = document.getElementById("introOverlay");
        if (!intro) return;
        intro.classList.remove("hidden");
        document.body.classList.add("intro-active");
      }

      function hideIntroOverlay() {
        const intro = document.getElementById("introOverlay");
        if (!intro) return;
        intro.classList.add("hidden");
        document.body.classList.remove("intro-active");
      }

      function enterAuthPortal() {
        hideIntroOverlay();
        showAuthOverlay();
        requestAnimationFrame(() => {
          document.getElementById("username")?.focus();
        });
      }

      function handleIntroKeydown(event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          enterAuthPortal();
        }
      }

      function persistComposerDraft() {
        const input = document.getElementById("chatInput");
        if (!input) return;
        writeDraftStorage(composerDraftKey, input.value || "");
      }

      function persistPlannerDraft() {
        const payload = {
          origin: document.getElementById("plannerOrigin")?.value || "",
          destination:
            document.getElementById("plannerDestination")?.value || "",
          date: document.getElementById("plannerDate")?.value || "",
          days: document.getElementById("plannerDays")?.value || "",
          travelers: document.getElementById("plannerTravelers")?.value || "",
          budget: document.getElementById("plannerBudget")?.value || "",
          transport: document.getElementById("plannerTransport")?.value || "",
          stay: document.getElementById("plannerStay")?.value || "",
          style: document.getElementById("plannerStyle")?.value || "",
        };
        writeDraftStorage(plannerDraftKey, JSON.stringify(payload));
        updatePlannerAssistStrip();
      }

      function restoreDrafts() {
        const composerDraft = readDraftStorage(composerDraftKey);
        if (composerDraft) {
          const input = document.getElementById("chatInput");
          if (input && !input.value) {
            input.value = composerDraft;
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 120) + "px";
          }
        }

        const plannerDraft = readDraftStorage(plannerDraftKey);
        if (plannerDraft) {
          try {
            const parsed = JSON.parse(plannerDraft);
            document.getElementById("plannerOrigin").value = parsed.origin || "";
            document.getElementById("plannerDestination").value =
              parsed.destination || "";
            document.getElementById("plannerDate").value = parsed.date || "";
            document.getElementById("plannerDays").value = parsed.days || "";
            document.getElementById("plannerTravelers").value =
              parsed.travelers || "";
            document.getElementById("plannerBudget").value = parsed.budget || "";
            document.getElementById("plannerTransport").value =
              parsed.transport || "";
            document.getElementById("plannerStay").value = parsed.stay || "";
            document.getElementById("plannerStyle").value = parsed.style || "";
          } catch (error) {}
        }
      }

      function resetComposerDraft(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        const input = document.getElementById("chatInput");
        if (input) {
          input.value = "";
          input.style.height = "auto";
        }
        clearDraftStorage(composerDraftKey);
        if (!silent) {
          setRuntimeStatus("输入草稿已重置", "online");
        }
      }

      function applyPlannerPanelState() {
        const panel = document.querySelector(".planner-panel");
        const toggleBtn = document.getElementById("plannerToggleBtn");
        const panelBody = document.getElementById("plannerPanelBody");
        if (!panel || !toggleBtn || !panelBody) return;
        panel.classList.toggle("collapsed", state.plannerCollapsed);
        panelBody.hidden = state.plannerCollapsed;
        toggleBtn.setAttribute("aria-expanded", String(!state.plannerCollapsed));
        toggleBtn.innerHTML = state.plannerCollapsed
          ? '<i class="fa-solid fa-angle-down"></i> 展开辅助栏'
          : '<i class="fa-solid fa-angle-up"></i> 收起辅助栏';
      }

      function togglePlannerPanel(forceCollapsed) {
        state.plannerCollapsed =
          typeof forceCollapsed === "boolean"
            ? forceCollapsed
            : !state.plannerCollapsed;
        localStorage.setItem(plannerCollapseKey, state.plannerCollapsed ? "1" : "0");
        applyPlannerPanelState();
      }

      function setMobileChatFocus(enabled) {
        const shouldFocus = Boolean(enabled && isMobileViewport() && state.token);
        state.mobileChatFocus = shouldFocus;
        document.body.classList.toggle("mobile-chat-focus", shouldFocus);
      }

      function exitMobileChatFocus() {
        setMobileChatFocus(false);
      }

      function setRuntimeStatus(label, tone = "idle") {
        const el = document.getElementById("assistantStatus");
        if (!el) return;
        el.textContent = label;
        el.className = `assistant-status ${tone}`.trim();
      }

      function updateEndpointTone(tone = "idle") {
        const endpointHint = document.getElementById("endpointHint");
        if (!endpointHint) return;
        endpointHint.className = "endpoint-pill";
        if (tone === "warning") endpointHint.classList.add("warning");
        if (tone === "error") endpointHint.classList.add("error");
      }

      function setServiceBanner({
        visible = false,
        tone = "loading",
        title = "",
        text = "",
        meta = "",
      } = {}) {
        const banner = document.getElementById("serviceBanner");
        if (!banner) return;
        banner.className = `service-banner ${visible ? "show" : ""} ${
          tone || ""
        }`.trim();
        document.getElementById("serviceBannerTitle").textContent = title;
        document.getElementById("serviceBannerText").textContent = text;
        document.getElementById("serviceBannerMeta").textContent = meta;
      }

      function setAuthServiceHint(message, tone = "loading") {
        const hint = document.getElementById("authServiceHint");
        if (!hint) return;
        hint.textContent = message;
        hint.className = `auth-service-hint ${tone}`.trim();
      }

      function setAuthFeedback(message, tone = "info") {
        const el = document.getElementById("authFeedback");
        if (!el) return;
        if (!message) {
          el.className = "auth-feedback";
          el.textContent = "";
          return;
        }
        el.textContent = message;
        el.className = `auth-feedback show ${tone}`.trim();
      }

      function setFieldError(field, message = "") {
        const input = document.getElementById(field);
        const error = document.getElementById(`${field}Error`);
        const wrapper = input?.closest(".form-group");
        if (wrapper) {
          wrapper.classList.toggle("error", Boolean(message));
        }
        if (error) {
          error.textContent = message;
        }
      }

      function clearAuthErrors() {
        ["username", "email", "password"].forEach((field) =>
          setFieldError(field, "")
        );
        setAuthFeedback("", "info");
      }

      function validateAuthForm(isRegister) {
        clearAuthErrors();
        const username = document.getElementById("username").value.trim();
        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;
        let firstInvalidField = null;

        if (username.length < 2) {
          setFieldError("username", "用户名至少需要 2 个字符。");
          firstInvalidField ||= "username";
        }

        if (password.length < 6) {
          setFieldError("password", "密码至少需要 6 位。");
          firstInvalidField ||= "password";
        }

        if (isRegister) {
          if (!email) {
            setFieldError("email", "注册时需要填写邮箱。");
            firstInvalidField ||= "email";
          } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            setFieldError("email", "邮箱格式看起来不正确，请再检查一下。");
            firstInvalidField ||= "email";
          }
        }

        if (firstInvalidField) {
          document.getElementById(firstInvalidField)?.focus();
          setAuthFeedback("请先补全表单信息，再继续操作。", "error");
          return null;
        }

        return {
          username,
          email,
          password,
        };
      }

      function isServiceUsable() {
        return state.serviceStatus === "ready" || state.serviceStatus === "degraded";
      }

      function getStatusLabel(status = "") {
        const labels = {
          ready: "就绪",
          degraded: "降级可用",
          not_ready: "未就绪",
          checking: "检查中",
          error: "连接失败",
          idle: "待开始",
          ok: "正常",
          pending: "待确认",
          approved: "已批准",
          rejected: "已拒绝",
          expired: "已过期",
          failed: "失败",
          none: "记录",
          completed: "已完成",
          running: "运行中",
          success: "成功",
          needs_verification: "需核验",
          not_found: "未查到",
          insufficient_parameters: "参数不足",
          service_exception: "服务异常",
          skipped: "已跳过",
          pending_confirmation: "待确认",
          requirement_collection: "需求收集",
          destination_recommendation: "目的地推荐",
          transport_planning: "交通规划",
          accommodation_planning: "住宿规划",
          food_planning: "餐饮规划",
          itinerary_generation: "行程生成",
          budget_summarization: "预算汇总",
          order_generation: "报告生成",
          free_planning: "个性化旅游规划",
          agency_plan: "省心方案",
          unknown: "待确认",
        };
        return labels[status] || status || "待确认";
      }

      function getReadinessStatusCopy(status = "") {
        if (status === "ready") return "对话、报告和行程进度都可演示。";
        if (status === "degraded") return "核心规划可继续，部分外部查询可能需要稍后复查。";
        if (status === "not_ready") return "关键能力尚未就绪，暂不开放登录、聊天或确认动作。";
        if (status === "error") return "暂时无法连接服务，需要稍后重试。";
        return "正在确认当前可用能力。";
      }

      function formatEpochSeconds(value) {
        if (value === null || value === undefined || value === "") return "未设置";
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return String(value);
        return formatClock(new Date(numeric * 1000));
      }

      function setPillStatus(el, status, fallbackText = "") {
        if (!el) return;
        el.textContent = fallbackText || getStatusLabel(status);
        el.className = `governance-status-pill ${status || "idle"}`.trim();
      }

      const READINESS_ITEM_LABELS = {
        checkpointer: "会话进度",
        store: "长期偏好",
        mcp: "外部查询",
        session_lock: "会话保护",
        approval_governance: "下单保护",
        postgres: "业务数据",
        redis: "会话保护",
      };

      function normalizeReadinessStatus(service = {}) {
        const rawStatus = String(service.status || (service.ready ? "ready" : "checking"));
        if (rawStatus === "healthy" || rawStatus === "ok") return "ready";
        if (rawStatus === "unavailable" || rawStatus === "missing") return "not_ready";
        if (rawStatus === "error") return "not_ready";
        return rawStatus || "checking";
      }

      function combineReadinessStatuses(statuses = []) {
        if (statuses.some((status) => status === "not_ready")) return "not_ready";
        if (statuses.some((status) => status === "degraded")) return "degraded";
        if (statuses.length && statuses.every((status) => status === "ready")) return "ready";
        return "checking";
      }

      function formatReadinessName(name = "") {
        return READINESS_ITEM_LABELS[name] || String(name || "待确认能力");
      }

      function summarizeReadinessServices(services = {}) {
        const checkpointerStatus = normalizeReadinessStatus(services.checkpointer);
        const storeStatus = normalizeReadinessStatus(services.store);
        const mcpStatus = normalizeReadinessStatus(services.mcp);
        const sessionLockStatus = normalizeReadinessStatus(services.session_lock);
        const approvalStatus = normalizeReadinessStatus(services.approval_governance);
        const coreStatus = combineReadinessStatuses([checkpointerStatus, storeStatus]);
        const protectionStatus = combineReadinessStatuses([sessionLockStatus, approvalStatus]);
        return [
          {
            key: "core",
            label: "对话与报告",
            status: coreStatus,
            description: "对话续接、阶段进度、报告生成",
          },
          {
            key: "memory",
            label: "长期偏好",
            status: storeStatus,
            description: "用户偏好可用于后续建议",
          },
          {
            key: "external",
            label: "外部服务",
            status: mcpStatus,
            description: "天气、地图、交通、酒店等查询能力",
          },
          {
            key: "human_boundary",
            label: "下单保护",
            status: protectionStatus,
            description: "当前只记录边界，不会真实支付或下单",
          },
        ];
      }

      function readinessSummaryLines(data = {}, status = "") {
        const services = data.services || {};
        const items = summarizeReadinessServices(services);
        const available = items
          .filter((item) => item.status === "ready" || item.status === "degraded")
          .map((item) => item.label);
        const mcpStatus = normalizeReadinessStatus(services.mcp);
        const approval = services.approval_governance || {};
        const approvalReady = normalizeReadinessStatus(approval) === "ready";
        const missing = Array.isArray(data.missing_required)
          ? data.missing_required.map(formatReadinessName)
          : [];
        const degraded = Array.isArray(data.degraded_optional)
          ? data.degraded_optional.map(formatReadinessName)
          : [];
        const attention = [
          ...missing.map((item) => `${item}未就绪`),
          ...degraded.map((item) => `${item}需复查`),
          ...(data.startup_complete === false ? ["服务仍在启动中"] : []),
        ];
        const turn = state.governance?.turnObservability || {};
        const planningMode =
          state.governance?.turnObservability?.planningModeLabel ||
          getStatusLabel(turn.planning_mode || "pending_confirmation");
        const calledServices = Number(turn.toolCallCount || turn.tool_call_count || 0);
        return [
          `<span>方案类型：${escapeHtml(planningMode)}</span>`,
          `<span>已确认信息：${escapeHtml(
            turn.step ? "正在随对话更新" : "待你补充出发地、时间、人数和预算"
          )}</span>`,
          `<span>长期偏好：${escapeHtml(
            available.includes("长期偏好") ? "已接入，可用于后续建议" : "登录后逐步沉淀"
          )}</span>`,
          `<span>已使用服务：${escapeHtml(
            calledServices ? `${calledServices} 次查询或整理` : "本轮暂未使用外部查询"
          )}</span>`,
          `<span>外部服务：${escapeHtml(
            mcpStatus === "ready"
              ? "天气、地图、交通、酒店等查询可用"
              : mcpStatus === "degraded"
                ? "部分查询能力不稳定，结果会提示核验"
                : mcpStatus === "not_ready"
                  ? "暂不可用，可先生成草案"
                  : "正在检测"
          )}</span>`,
          `<span>重要提醒：${escapeHtml(
            approvalReady
              ? approval.persistent
                ? "当前不会自动支付、发短信或下单"
                : "当前不会自动支付、发短信或下单"
              : "当前不会自动支付、发短信或下单"
          )}</span>`,
          `<span>待关注：${escapeHtml(attention.length ? attention.join("、") : "无")}</span>`,
        ];
      }

      function readinessCurrentStageLabel() {
        const turn = state.governance?.turnObservability || {};
        return (
          state.governance?.turnObservability?.stepLabel ||
          getStatusLabel(turn.step || "requirement_collection")
        );
      }

      function renderReadinessPanel(payload = null) {
        const data = payload || state.readiness.payload || {};
        const status = data.status || state.readiness.status || "checking";
        const statusPill = document.getElementById("readinessStatusPill");
        const title = document.getElementById("readinessTitle");
        const summary = document.getElementById("readinessSummary");
        const grid = document.getElementById("readinessServiceGrid");

        setPillStatus(statusPill, status, getStatusLabel(status));

        if (title) {
          title.textContent = `当前阶段：${readinessCurrentStageLabel()}`;
        }

        if (summary) {
          summary.innerHTML = readinessSummaryLines(data, status).join("");
        }

        if (grid) {
          grid.innerHTML = summarizeReadinessServices(data.services || {})
            .map(
              (item) => `
                <div class="readiness-service-item">
                  <span>${escapeHtml(item.label)}</span>
                  <strong>${escapeHtml(getStatusLabel(item.status))}</strong>
                  <small>${escapeHtml(item.description)}</small>
                </div>
              `
            )
            .join("");
        }
        syncGovernanceDebugVisibility();
      }

      function getCurrentUserRole() {
        return (
          state.user?.role ||
          state.user?.preferences?.role ||
          state.user?.profile?.role ||
          "user"
        );
      }

      function canShowAdvisorDebug() {
        return ["advisor", "approver", "admin", "debug"].includes(getCurrentUserRole());
      }

      function syncGovernanceDebugVisibility() {
        const details = document.getElementById("governanceDetails");
        if (!details) return;
        const visible = canShowAdvisorDebug();
        details.hidden = !visible;
        if (!visible) {
          details.open = false;
        }
      }

      function canRequestAllApprovals() {
        return ["approver", "admin"].includes(getCurrentUserRole());
      }

      function redactClientText(value = "", maxLength = 180) {
        const compact = String(value || "")
          .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[REDACTED]")
          .replace(/\b1[3-9]\d{9}\b/g, "[REDACTED]")
          .replace(/\b\d{17}[\dXx]\b/g, "[REDACTED]")
          .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+\b/gi, "Bearer [REDACTED]")
          .replace(/\beyJ[A-Za-z0-9._~+/=-]+\b/g, "[REDACTED]")
          .replace(/\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+/gi, "[REDACTED]")
          .replace(/\s+/g, " ")
          .trim();
        return compact.length > maxLength
          ? `${compact.slice(0, maxLength)}...`
          : compact;
      }

      const TOOL_DISPLAY_LABELS = {
        query_transport_options: "交通查询",
        query_flight_options: "航班查询",
        query_train_options: "高铁查询",
        query_driving_route: "自驾路线",
        query_hotel_options: "住宿查询",
        query_destination_info: "目的地信息",
        search_travel_info: "旅行搜索",
        search_destination_guide: "目的地攻略",
        search_food_recommendations: "餐饮建议",
        search_accommodation_info: "住宿建议",
        search_travel_tips: "旅行提示",
        search_agency_product_templates: "产品模板检索",
        search_agency_service_sop: "服务流程检索",
        search_agency_pricing_rules: "报价规则检索",
        search_agency_risk_playbook: "风险规则检索",
        search_agency_report_standards: "报告标准检索",
        generate_order_tool: "报告生成",
      };

      const TOOL_EVIDENCE_LABELS = {
        live_transport_query: "实时交通查询",
        live_hotel_search: "实时住宿查询",
        mcp_live_query: "外部服务查询",
        internal_rag_evidence: "内部知识检索",
        public_rag_evidence: "公开知识检索",
        destination_router_evidence: "目的地知识编排",
        internal_state_update: "本地状态更新",
        unknown: "证据类型待确认",
      };

      const TOOL_AUDIT_STATUS_LABELS = {
        success: "成功",
        needs_verification: "需核验",
        not_found: "未查到",
        insufficient_parameters: "参数不足",
        service_exception: "服务异常",
        skipped: "已跳过",
      };

      const TOOL_AUDIT_EXPLANATIONS = {
        success: "工具返回了可用结果。",
        needs_verification: "工具返回了内容，但仍需要人工或出发前再次核验。",
        not_found: "工具调用成功，但这次没有查到合适结果；不是系统崩溃。",
        insufficient_parameters: "本轮缺少必要参数，补齐后可以再查。",
        service_exception: "外部服务或工具执行异常，需要稍后重试。",
        skipped: "本轮按保护规则跳过了这次工具调用。",
      };

      function getToolDisplayName(toolName = "") {
        const rawName = String(toolName || "").trim();
        return TOOL_DISPLAY_LABELS[rawName] || redactClientText(rawName || "工具", 80);
      }

      function getToolEvidenceLabel(evidenceType = "") {
        const rawType = String(evidenceType || "unknown").trim();
        return TOOL_EVIDENCE_LABELS[rawType] || redactClientText(rawType, 80);
      }

      function inferToolAuditSemanticStatus(status = "", errorType = "") {
        const rawStatus = String(status || "").toLowerCase();
        const rawError = String(errorType || "").toLowerCase();
        if (rawStatus === "success") return "success";
        if (rawError === "empty_transport_result") return "not_found";
        if (rawError.startsWith("empty_") || rawError.includes("empty_or_unavailable")) {
          return "not_found";
        }
        if (rawStatus === "skipped") {
          if (
            rawError.startsWith("invalid_") ||
            rawError.includes("missing") ||
            rawError.includes("placeholder")
          ) {
            return "insufficient_parameters";
          }
          return "skipped";
        }
        if (rawStatus === "approval_required") return "skipped";
        if (rawStatus === "failed" || rawStatus === "timeout") return "service_exception";
        return "needs_verification";
      }

      function getToolAuditReasonLabel(errorType = "") {
        const rawError = String(errorType || "").trim();
        const labels = {
          empty_transport_result: "未查到合适交通结果",
          empty_hotel_result: "未查到合适住宿结果",
          empty_mcp_result: "外部服务没有返回可用内容",
          empty_rag_result: "知识检索没有返回证据",
          rag_empty_or_unavailable: "知识检索为空或降级",
          transport_result_requires_verification: "交通结果需要复查",
          mcp_result_requires_verification: "外部服务结果需要复查",
          upstream_timeout: "外部服务超时",
          duplicate_tool_call_same_turn: "同一轮重复查询已跳过",
          approval_required: "需要人工确认",
          tool_disabled: "能力尚未开放",
          invalid_transport_query_args: "交通查询参数不足",
          invalid_hotel_query_args: "住宿查询参数不足",
          invalid_destination_query_args: "目的地查询参数不足",
          invalid_rag_query_args: "检索参数不足",
          invalid_mcp_tool_args: "外部工具参数不足",
        };
        return labels[rawError] || redactClientText(rawError, 80);
      }

      function normalizeToolAuditEvent(event = {}) {
        const status = String(event.status || "unknown");
        const errorType = redactClientText(event.error_type || "", 80);
        const semanticStatus = String(
          event.semantic_status || inferToolAuditSemanticStatus(status, errorType)
        );
        const statusLabel = redactClientText(
          event.status_label ||
            TOOL_AUDIT_STATUS_LABELS[semanticStatus] ||
            getStatusLabel(status),
          80
        );
        const statusExplanation = redactClientText(
          event.status_explanation ||
            TOOL_AUDIT_EXPLANATIONS[semanticStatus] ||
            "本轮工具结果需要结合行程上下文判断。",
          160
        );
        return {
          tool: getToolDisplayName(event.tool || event.name || "unknown_tool"),
          rawTool: redactClientText(event.tool || event.name || "unknown_tool", 80),
          status,
          semanticStatus,
          statusLabel,
          statusExplanation,
          elapsedSeconds:
            event.elapsed_seconds === null || event.elapsed_seconds === undefined
              ? null
              : Number(event.elapsed_seconds),
          retryCount: Number(event.retry_count || 0),
          evidenceType: redactClientText(event.evidence_type || "unknown", 80),
          evidenceLabel: getToolEvidenceLabel(event.evidence_type || "unknown"),
          errorType,
          reasonLabel: errorType ? getToolAuditReasonLabel(errorType) : "",
          degraded:
            Boolean(event.degraded) ||
            ["failed", "timeout", "degraded", "skipped", "approval_required"].includes(
              status
            ),
          observedAt: Date.now(),
        };
      }

      function rememberToolAuditEvent(event = {}) {
        const normalized = normalizeToolAuditEvent(event);
        const key = [
          normalized.tool,
          normalized.status,
          normalized.evidenceType,
          normalized.errorType,
        ].join("|");
        const existingIndex = state.governance.toolAuditEvents.findIndex(
          (item) => [item.tool, item.status, item.evidenceType, item.errorType].join("|") === key
        );
        if (existingIndex >= 0) {
          state.governance.toolAuditEvents[existingIndex] = normalized;
        } else {
          state.governance.toolAuditEvents.unshift(normalized);
        }
        state.governance.toolAuditEvents = state.governance.toolAuditEvents.slice(0, 20);
        renderToolAuditList();
      }

      function normalizeObservabilityField(value = "", fallback = "pending_confirmation") {
        const text = String(value || "").trim();
        if (!text || text.toLowerCase() === "unknown") return fallback;
        return text;
      }

      function rememberTurnObservability(event = {}) {
        const observability = event.observability || event;
        if (!observability || typeof observability !== "object") return;
        const step = normalizeObservabilityField(
          observability.step || observability.current_step,
          "requirement_collection"
        );
        const planningMode = normalizeObservabilityField(
          observability.planning_mode,
          "pending_confirmation"
        );
        const status = normalizeObservabilityField(observability.status, "completed");
        const degradationStatus = normalizeObservabilityField(
          observability.degradation_status,
          "ok"
        );
        state.governance.turnObservability = {
          turnId: redactClientText(observability.turn_id || "", 80),
          status,
          statusLabel: getStatusLabel(status),
          step,
          stepLabel: getStatusLabel(step),
          planningMode,
          planningModeLabel: getStatusLabel(planningMode),
          firstTokenSeconds: observability.first_token_seconds,
          totalElapsedSeconds: observability.total_elapsed_seconds,
          toolCallCount: Number(observability.tool_call_count || 0),
          toolFailureCount: Number(observability.tool_failure_count || 0),
          fallbackCount: Number(observability.fallback_count || 0),
          degradationStatus,
          degradationLabel: getStatusLabel(degradationStatus),
          estimatedTotalTokens: Number(observability.estimated_total_tokens || 0),
        };
        renderReadinessPanel();
        renderTurnObservability();
      }

      function renderToolAuditList() {
        const count = document.getElementById("toolAuditCount");
        const list = document.getElementById("toolAuditList");
        const events = state.governance.toolAuditEvents;
        if (count) count.textContent = String(events.length);
        if (!list) return;
        if (!events.length) {
          list.innerHTML =
            '<div class="governance-empty">本轮还没有工具记录。</div>';
          return;
        }
        list.innerHTML = events
          .map((event) => {
            const elapsed = Number.isFinite(event.elapsedSeconds)
              ? `${event.elapsedSeconds.toFixed(2)}s`
              : "未记录";
            return `
              <article class="tool-audit-card">
                <div class="tool-audit-card-head">
                  <strong>${escapeHtml(event.tool)}</strong>
                  <span class="governance-status-pill ${escapeHtml(
                    event.semanticStatus
                  )}">${escapeHtml(event.statusLabel)}</span>
                </div>
                <p>${escapeHtml(event.statusExplanation)}</p>
                <div class="tool-audit-meta">
                  <span><i class="fa-regular fa-clock"></i>${escapeHtml(elapsed)}</span>
                  <span><i class="fa-solid fa-rotate"></i>${event.retryCount} 次重试</span>
                  <span><i class="fa-solid fa-file-shield"></i>${escapeHtml(event.evidenceLabel)}</span>
                  ${
                    event.reasonLabel
                      ? `<span><i class="fa-solid fa-triangle-exclamation"></i>${escapeHtml(
                          event.reasonLabel
                        )}</span>`
                      : ""
                  }
                </div>
              </article>
            `;
          })
          .join("");
      }

      function renderTurnObservability() {
        const grid = document.getElementById("turnObservabilityGrid");
        const pill = document.getElementById("turnStatusPill");
        const item = state.governance.turnObservability;
        if (!grid) return;
        if (!item) {
          setPillStatus(pill, "idle", "待开始");
          grid.innerHTML = `
            <div class="governance-empty">
              完成一轮聊天后展示脱敏运行摘要，不展示个人敏感信息、密钥或完整工具输入输出。
            </div>
          `;
          return;
        }
        setPillStatus(pill, item.degradationStatus, item.degradationLabel);
        const metrics = [
          ["状态", item.statusLabel],
          ["阶段", item.stepLabel],
          ["模式", item.planningModeLabel],
          ["首个响应片段", item.firstTokenSeconds == null ? "未记录" : `${item.firstTokenSeconds}s`],
          ["总耗时", item.totalElapsedSeconds == null ? "未记录" : `${item.totalElapsedSeconds}s`],
          ["工具调用", `${item.toolCallCount} 次`],
          ["需复查工具", `${item.toolFailureCount} 个`],
          ["兜底次数", `${item.fallbackCount} 次`],
          ["文本量估算", `${item.estimatedTotalTokens}`],
        ];
        const metricsHtml = metrics
          .map(
            ([label, value]) => `
              <div class="turn-observability-item">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value)}</strong>
              </div>
            `
          )
          .join("");
        const traceHtml = item.turnId
          ? `<div class="turn-observability-footnote">追踪码（排查用）：${escapeHtml(
              item.turnId.slice(0, 12)
            )}</div>`
          : "";
        grid.innerHTML = `${metricsHtml}${traceHtml}`;
      }

      function renderApprovalList() {
        const list = document.getElementById("approvalList");
        if (!list) return;
        const filter = state.governance.approvalFilter;
        const approvals = state.governance.approvals.filter((approval) =>
          filter === "pending" ? approval.status === "pending" : true
        );
        document.querySelectorAll(".approval-filter-btn").forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.approvalFilter === filter);
        });

        if (!state.token) {
          list.innerHTML = '<div class="governance-empty">登录后展示人工确认记录。</div>';
          return;
        }
        if (state.governance.isApprovalLoading) {
          list.innerHTML = '<div class="governance-empty">正在同步人工确认记录…</div>';
          return;
        }
        if (!approvals.length) {
          list.innerHTML = `
            <div class="governance-empty">
              当前没有${filter === "pending" ? "待人工确认" : "可展示"}记录。演示记录只说明未来真实支付、短信或客户资料导出前需要人工确认，不会真实下单。
            </div>
          `;
          return;
        }

        list.innerHTML = approvals
          .map((approval) => {
            const id = approval.approval_id || "";
            const status = approval.status || "none";
            const isPending = status === "pending";
            const isActive = state.governance.selectedApprovalId === id;
            return `
              <article
                class="approval-card ${isActive ? "active" : ""}"
                onclick="selectApprovalRecord('${escapeHtml(id)}')"
              >
                <div class="approval-card-head">
                  <strong>${escapeHtml(redactClientText(approval.label || approval.action || "需确认动作"))}</strong>
                  <span class="governance-status-pill ${escapeHtml(status)}">${escapeHtml(
                    getStatusLabel(status)
                  )}</span>
                </div>
                <p>${escapeHtml(redactClientText(approval.reason || "未填写确认理由"))}</p>
                <div class="approval-card-meta">
                  <span><i class="fa-solid fa-shield-halved"></i>${approval.requires_approval ? "需人工确认" : "边界记录"}</span>
                  <span><i class="fa-regular fa-clock"></i>${escapeHtml(
                    formatEpochSeconds(approval.created_at)
                  )}</span>
                  <span><i class="fa-regular fa-hourglass-half"></i>${escapeHtml(
                    approval.expires_at ? formatEpochSeconds(approval.expires_at) : "无过期时间"
                  )}</span>
                </div>
                <div class="approval-actions">
                  <button
                    class="approval-action-btn approve"
                    type="button"
                    ${isPending ? "" : "disabled"}
                    onclick="decideApproval('${escapeHtml(id)}', 'approve', event)"
                  >
                    批准
                  </button>
                  <button
                    class="approval-action-btn reject"
                    type="button"
                    ${isPending ? "" : "disabled"}
                    onclick="decideApproval('${escapeHtml(id)}', 'reject', event)"
                  >
                    拒绝
                  </button>
                  <button
                    class="approval-action-btn expire"
                    type="button"
                    ${isPending ? "" : "disabled"}
                    onclick="decideApproval('${escapeHtml(id)}', 'expire', event)"
                  >
                    过期
                  </button>
                </div>
              </article>
            `;
          })
          .join("");
      }

      function renderApprovalEvents() {
        const list = document.getElementById("approvalEventsList");
        if (!list) return;
        const events = state.governance.approvalEvents || [];
        if (!state.governance.selectedApprovalId) {
          list.className = "governance-empty";
          list.innerHTML = "选择一条人工确认记录后展示状态变化。";
          return;
        }
        if (!events.length) {
          list.className = "governance-empty";
          list.innerHTML = "这条记录还没有返回事件。";
          return;
        }
        list.className = "approval-event-list";
        const formatApprovalEventType = (type = "") => {
          const labels = {
            created: "创建",
            approved: "批准",
            rejected: "拒绝",
            expired: "过期",
            updated: "更新",
          };
          return labels[type] || type || "事件";
        };
        list.innerHTML = events
          .map(
            (event) => `
              <div class="approval-event-item">
                <strong>${escapeHtml(formatApprovalEventType(event.event_type))} · ${escapeHtml(
                  getStatusLabel(event.from_status || "none")
                )} → ${escapeHtml(getStatusLabel(event.to_status || "unknown"))}</strong>
                <span>${escapeHtml(formatEpochSeconds(event.created_at))}</span>
                ${
                  event.reason
                    ? `<p>${escapeHtml(redactClientText(event.reason, 120))}</p>`
                    : ""
                }
              </div>
            `
          )
          .join("");
      }

      async function loadApprovalEvents(approvalId) {
        if (!approvalId || !state.token || !isServiceUsable()) {
          state.governance.approvalEvents = [];
          renderApprovalEvents();
          return;
        }
        try {
          const response = await fetch(
            `${getApiBase()}/api/v1/approvals/${encodeURIComponent(approvalId)}/events`,
            {
              headers: { Authorization: `Bearer ${state.token}` },
            }
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          state.governance.approvalEvents = Array.isArray(data.events)
            ? data.events
            : [];
        } catch (error) {
          state.governance.approvalEvents = [];
          showToast("人工确认事件同步失败", true);
        }
        renderApprovalEvents();
      }

      async function loadApprovals({ silent = true } = {}) {
        if (!state.token || !isServiceUsable()) {
          state.governance.approvals = [];
          state.governance.approvalEvents = [];
          renderApprovalList();
          renderApprovalEvents();
          return;
        }
        state.governance.isApprovalLoading = true;
        syncUiAvailability();
        renderApprovalList();
        const params = new URLSearchParams();
        if (canRequestAllApprovals()) params.set("scope", "all");
        if (state.governance.approvalFilter === "pending") {
          params.set("status", "pending");
        }
        try {
          const response = await fetch(`${getApiBase()}/api/v1/approvals?${params}`, {
            headers: { Authorization: `Bearer ${state.token}` },
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          state.governance.approvals = Array.isArray(data.approvals)
            ? data.approvals
            : [];
          if (
            state.governance.selectedApprovalId &&
            !state.governance.approvals.some(
              (approval) => approval.approval_id === state.governance.selectedApprovalId
            )
          ) {
            state.governance.selectedApprovalId = null;
          }
          state.governance.selectedApprovalId ||=
            state.governance.approvals[0]?.approval_id || null;
          if (!silent) showToast("进度台已刷新");
        } catch (error) {
          state.governance.approvals = [];
          state.governance.selectedApprovalId = null;
          if (!silent) showToast("人工确认记录同步失败", true);
        } finally {
          state.governance.isApprovalLoading = false;
          syncUiAvailability();
          renderApprovalList();
          await loadApprovalEvents(state.governance.selectedApprovalId);
        }
      }

      async function refreshGovernanceConsole(options = {}) {
        const silent = Boolean(options?.silent);
        await checkServiceHealth({ silent, reason: "governance-refresh" });
        renderToolAuditList();
        renderTurnObservability();
        await loadApprovals({ silent });
      }

      async function setApprovalFilter(filter = "all") {
        state.governance.approvalFilter = filter === "pending" ? "pending" : "all";
        await loadApprovals({ silent: true });
      }

      async function selectApprovalRecord(approvalId) {
        state.governance.selectedApprovalId = approvalId;
        renderApprovalList();
        await loadApprovalEvents(approvalId);
      }

      async function createDemoApproval() {
        if (!(await ensureServiceReady("创建人工确认记录"))) return;
        if (!state.token) {
          showToast("请先登录后再创建人工确认记录。", true);
          return;
        }
        state.governance.isApprovalLoading = true;
        syncUiAvailability();
        try {
          const response = await fetch(`${getApiBase()}/api/v1/approvals`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${state.token}`,
            },
            body: JSON.stringify({
              action: "real_payment",
              reason: "未来真实支付接入前必须经过人工确认",
              conversation_id: state.currentConversationId,
              metadata: {
                source: "frontend_governance_console",
                demo: true,
              },
              expires_in_seconds: 3600,
            }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(data?.detail?.message || `HTTP ${response.status}`);
          }
          state.governance.selectedApprovalId = data.approval_id;
          showToast("人工确认演示记录已创建，不会触发真实支付或下单。");
          await loadApprovals({ silent: true });
        } catch (error) {
          showToast("演示记录创建失败，请确认人工确认记录服务可用。", true);
        } finally {
          state.governance.isApprovalLoading = false;
          syncUiAvailability();
        }
      }

      async function decideApproval(approvalId, decision, event) {
        event?.stopPropagation();
        if (!(await ensureServiceReady("处理人工确认"))) return;
        if (!approvalId || !["approve", "reject", "expire"].includes(decision)) return;
        const decisionPath =
          decision === "approve" ? "approve" : decision === "reject" ? "reject" : "expire";
        const decisionCopy = {
          approve: "人工批准：确认当前仍不触发真实支付或预订。",
          reject: "人工拒绝：真实供应链未接入。",
          expire: "",
        };
        try {
          const response = await fetch(
            `${getApiBase()}/api/v1/approvals/${encodeURIComponent(
              approvalId
            )}/${decisionPath}`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${state.token}`,
              },
              body:
                decision === "expire"
                  ? undefined
                  : JSON.stringify({ reason: decisionCopy[decision] }),
            }
          );
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            const message =
              data?.detail?.message ||
              data?.detail ||
              "当前账号没有处理权限，或人工确认记录状态已变化。";
            throw new Error(redactClientText(message));
          }
          state.governance.selectedApprovalId = data.approval_id || approvalId;
          showToast(`人工确认记录已${decision === "approve" ? "批准" : decision === "reject" ? "拒绝" : "过期"}`);
          await loadApprovals({ silent: true });
        } catch (error) {
          showToast(error.message || "人工确认处理失败", true);
        }
      }

      function syncUiAvailability() {
        const healthy = isServiceUsable();
        const input = document.getElementById("chatInput");
        const sendBtn = document.getElementById("sendBtn");
        const authBtn = document.getElementById("authBtn");
        const newChatBtn = document.getElementById("newChatBtn");
        const retryBtn = document.getElementById("retryHealthBtn");
        const governanceRefreshBtn = document.getElementById("governanceRefreshBtn");
        const createDemoApprovalBtn = document.getElementById("createDemoApprovalBtn");
        const inputWrapper = document.querySelector(".chat-input-wrapper");

        if (input) {
          input.disabled = !healthy || state.isLoading;
        }
        if (inputWrapper) {
          inputWrapper.classList.toggle(
            "disabled",
            !healthy || state.isLoading
          );
        }
        if (sendBtn) {
          sendBtn.disabled = !healthy || state.isLoading;
        }
        if (newChatBtn) {
          newChatBtn.disabled = !healthy;
        }
        if (authBtn) {
          authBtn.disabled = state.isAuthLoading || !healthy;
        }
        if (retryBtn) {
          retryBtn.disabled = state.serviceStatus === "checking";
        }
        if (governanceRefreshBtn) {
          governanceRefreshBtn.disabled = state.serviceStatus === "checking";
        }
        if (createDemoApprovalBtn) {
          createDemoApprovalBtn.disabled =
            !healthy || !state.token || state.governance.isApprovalLoading;
        }
        document.querySelectorAll("[data-planner-control='true']").forEach((el) => {
          el.disabled = !healthy;
        });
        updateEndpointUI();
      }

      async function checkServiceHealth({
        silent = false,
        reason = "startup",
      } = {}) {
        if (state.serviceStatus === "checking") {
          syncUiAvailability();
        }

        if (!silent) {
          setRuntimeStatus("正在连接服务", "loading");
          updateEndpointTone("warning");
          setAuthServiceHint("正在检查服务状态，确认就绪后即可登录或注册。", "loading");
          setServiceBanner({
            visible: true,
            tone: "loading",
            title: "正在检查服务状态",
            text:
              reason === "startup"
                ? "页面正在确认后端和工具链是否就绪，请稍候。"
                : "正在重新连接服务，请稍候。",
            meta: "正在检测中",
          });
        }

        state.serviceStatus = "checking";
        syncUiAvailability();

        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 8000);
          const response = await fetch(`${getApiBase()}/health/ready`, {
            signal: controller.signal,
            headers: { Accept: "application/json" },
          });
          clearTimeout(timeoutId);

          const data = await response.json().catch(() => null);
          if (!data?.status) {
            throw new Error(`HTTP ${response.status}`);
          }

          state.readiness = {
            status: data.status,
            payload: data,
            checkedAt: Date.now(),
          };
          renderReadinessPanel(data);

          if (data.status === "ready" && data.startup_complete) {
            state.serviceStatus = "ready";
            state.lastHealthCheckAt = Date.now();
            setRuntimeStatus(state.token ? "已连接" : "服务就绪", "online");
            updateEndpointTone("idle");
            setAuthServiceHint(
              "服务已就绪，可以登录、创建会话并开始规划行程。",
              "online"
            );
            setServiceBanner({
              visible: false,
              tone: "success",
              title: "",
              text: "",
              meta: "",
            });
            syncUiAvailability();
            return true;
          }

          if (data.status === "degraded" && data.startup_complete) {
            state.serviceStatus = "degraded";
            state.lastHealthCheckAt = Date.now();
            setRuntimeStatus(state.token ? "已连接 · 降级" : "服务降级可用", "online");
            updateEndpointTone("warning");
            setAuthServiceHint(
              "核心服务可用，但部分外部能力降级；聊天、人工确认和报告边界仍可继续查看。",
              "online"
            );
            setServiceBanner({
              visible: true,
              tone: "loading",
              title: "服务降级可用",
              text: getReadinessStatusCopy("degraded"),
              meta: `检查时间：${formatClock(new Date())}`,
            });
            syncUiAvailability();
            return true;
          }

          state.serviceStatus = "not_ready";
          state.lastHealthCheckAt = Date.now();
          setRuntimeStatus("服务未就绪", "error");
          updateEndpointTone("error");
          setAuthServiceHint(
            "后端关键能力尚未就绪，暂时不能登录、聊天或处理人工确认。",
            "error"
          );
          setServiceBanner({
            visible: true,
            tone: "error",
            title: "服务尚未就绪",
            text: getReadinessStatusCopy("not_ready"),
            meta: `检查时间：${formatClock(new Date())}`,
          });
          syncUiAvailability();
          return false;
        } catch (error) {
          state.serviceStatus = "error";
          state.readiness = {
            status: "error",
            payload: null,
            checkedAt: Date.now(),
          };
          renderReadinessPanel({ status: "error", services: {} });
          setRuntimeStatus("服务暂不可用", "error");
          updateEndpointTone("error");
          setAuthServiceHint(
            "当前无法连接后端服务，请稍后重试或点击“重新检查”。",
            "error"
          );
          setServiceBanner({
            visible: true,
            tone: "error",
            title: "服务连接出现波动",
            text:
              "当前无法确认后端是否就绪。你可以稍后重试，或点击右侧按钮重新检查。",
            meta:
              state.lastHealthCheckAt > 0
                ? `上次成功检查：${formatClock(
                    new Date(state.lastHealthCheckAt)
                  )}`
                : "尚未完成首次健康检查",
          });
          syncUiAvailability();
          if (!silent) {
            showToast("服务暂时不可用，请稍后重试。", true);
          }
          return false;
        }
      }

      async function ensureServiceReady(actionLabel = "继续操作") {
        if (isServiceUsable()) return true;
        const ok = await checkServiceHealth({ silent: false, reason: actionLabel });
        if (!ok) {
          showToast(`服务尚未就绪，暂时无法${actionLabel}。`, true);
        }
        return ok;
      }

      async function retryHealthCheck() {
        await checkServiceHealth({ silent: false, reason: "manual-retry" });
      }

      function updateSessionOverview() {
        const current = getCurrentConversation();
        const conversationCountChip = document.getElementById(
          "conversationCountChip"
        );
        const activeConversationChip = document.getElementById(
          "activeConversationChip"
        );
        const chatTitle = document.getElementById("chatTitle");
        const chatSubtitle = document.getElementById("chatSubtitle");
        const tripOverview = document.getElementById("tripOverview");
        const total = state.conversations.length;

        if (conversationCountChip) {
          conversationCountChip.innerHTML = `<i class="fa-regular fa-folder-open"></i> ${total} 个行程`;
        }

        if (activeConversationChip) {
          activeConversationChip.innerHTML = current
            ? `<i class="fa-solid fa-location-arrow"></i> ${escapeHtml(
                current.title || "当前会话"
              )}`
            : '<i class="fa-regular fa-compass"></i> 未选择行程';
        }

        if (chatTitle) {
          chatTitle.classList.toggle("renameable", Boolean(current));
          chatTitle.title = current ? "双击可修改行程名称" : "行程助手";
        }

        if (chatSubtitle) {
          chatSubtitle.textContent = current
            ? `当前会话最近更新于 ${formatConversationStamp(
                current.updated_at || current.created_at
              )}`
            : "把出发地、时间、人数和预算告诉我，我会按步骤整理成一份旅游规划报告。";
        }

        if (tripOverview) {
          tripOverview.innerHTML = current
            ? `
                <span class="overview-chip primary">
                  <i class="fa-solid fa-route"></i> ${escapeHtml(
                    current.title || "新行程"
                  )}
                </span>
                <span class="overview-chip">
                  <i class="fa-regular fa-clock"></i> ${formatRelativeTime(
                    current.updated_at || current.created_at
                  )}
                </span>
              `
            : `
                <span class="overview-chip primary">
                  <i class="fa-solid fa-route"></i> 未选择行程
                </span>
                <span class="overview-chip">
                  <i class="fa-regular fa-pen-to-square"></i> 随时可以开始
                </span>
              `;
        }
      }

      function updateEndpointUI() {
        const endpoint = getApiBase();
        const endpointHint = document.getElementById("endpointHint");
        const composerHint = document.getElementById("composerHint");
        const apiConfig = document.querySelector(".api-config");

        if (apiConfig) {
          apiConfig.classList.toggle("hidden", !shouldShowApiConfig());
        }

        if (endpointHint) {
          const hostLabel =
            window.location.protocol === "file:"
              ? "本地调试模式"
              : "当前站点";
          endpointHint.innerHTML = `<i class="fa-solid fa-globe"></i> ${hostLabel}: ${escapeHtml(
            endpoint
          )}`;
        }

        if (composerHint) {
          if (state.serviceStatus === "error") {
            composerHint.textContent =
              "服务暂不可用，建议先点击“重新检查”确认后再继续操作";
          } else if (state.serviceStatus === "not_ready") {
            composerHint.textContent =
              "服务尚未就绪，请等待后端核心依赖完成初始化";
          } else if (state.serviceStatus === "degraded") {
            composerHint.textContent =
              "部分能力降级，可继续使用核心规划并留意右侧进度提示";
          } else if (state.serviceStatus === "checking") {
            composerHint.textContent =
              "正在检测服务状态，确认就绪后会自动开放发送和新建会话";
          } else {
            composerHint.textContent = shouldShowApiConfig()
              ? `当前接口地址：${endpoint}`
              : "部署环境已自动使用当前域名，无需手动配置接口地址";
          }
        }
      }

      function setSendButtonLoading(isLoading) {
        const sendBtn = document.getElementById("sendBtn");
        if (!sendBtn) return;
        sendBtn.classList.toggle("loading", isLoading);
        sendBtn.innerHTML = isLoading
          ? '<i class="fa-solid fa-spinner"></i>'
          : '<i class="fa-regular fa-paper-plane"></i>';
        syncUiAvailability();
      }

      function getWelcomeMarkup() {
        return `
                <div class="welcome-screen">
              <div class="welcome-logo"><i class="fa-solid fa-paper-plane"></i></div>
              <h3 class="welcome-title">欢迎使用 知行</h3>
              <p class="welcome-text">直接告诉我这次想去哪、几天、几个人、预算和偏好，我会按步骤整理目的地、交通、住宿，并在最后形成一份旅游规划报告。</p>
                    <div class="welcome-suggestions">
                        <button class="suggestion-btn" onclick="applySuggestion('我想从北京出发，端午去成都玩 4 天，2 个人，预算 5000 元，喜欢美食和慢节奏。')">周末城市小旅行</button>
                        <button class="suggestion-btn" onclick="applySuggestion('帮我规划一次去云南的 7 天亲子旅行，暑假出发，预算 12000 元。')">亲子长线行程</button>
                        <button class="suggestion-btn" onclick="applySuggestion('我想先看看 3 个适合海边度假的目的地，预算 8000 元以内。')">先做目的地推荐</button>
                    </div>
                </div>
            `;
      }

      function updatePlannerSummary(message) {
        const el = document.getElementById("plannerSummary");
        if (el) {
          el.textContent = message;
        }
      }

      function updatePlannerAssistStrip() {
        const strip = document.getElementById("plannerAssistStrip");
        const panel = document.querySelector(".planner-panel");
        if (!strip) return;
        const fields = readPlannerFields();
        const checks = [
          { key: "origin", label: "出发地", required: true },
          { key: "destination", label: "目的地", required: true },
          { key: "days", label: "天数", required: true },
          { key: "budget", label: "预算", required: false },
          { key: "travelers", label: "人数", required: false },
          { key: "style", label: "偏好", required: false },
        ];
        const requiredFilled = checks.filter(
          (item) => item.required && fields[item.key]
        ).length;
        const ready = requiredFilled >= checks.filter((item) => item.required).length;
        panel?.classList.toggle("planner-panel-ready", ready);
        strip.innerHTML = checks
          .map((item) => {
            const filled = Boolean(fields[item.key]);
            const tone = filled ? "filled" : item.required ? "missing" : "optional";
            const icon = filled ? "fa-circle-check" : "fa-circle";
            return `
              <span class="planner-assist-chip ${tone}">
                <i class="fa-regular ${icon}"></i>
                ${escapeHtml(item.label)}${!item.required && !filled ? "可选" : ""}
              </span>
            `;
          })
          .join("");
        [
          ["plannerOrigin", fields.origin],
          ["plannerDestination", fields.destination],
          ["plannerDate", fields.date],
          ["plannerDays", fields.days],
          ["plannerTravelers", fields.travelers],
          ["plannerBudget", fields.budget],
          ["plannerTransport", fields.transport],
          ["plannerStay", fields.stay],
          ["plannerStyle", fields.style],
        ].forEach(([id, value]) => {
          document
            .getElementById(id)
            ?.closest(".planner-field")
            ?.classList.toggle("filled", Boolean(value));
        });
      }

      function appendToComposer(text, mode = "replace") {
        const input = document.getElementById("chatInput");
        const current = input.value.trim();
        input.value =
          mode === "append" && current ? `${current}\n${text}` : text;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
        input.focus();
        persistComposerDraft();
      }

      function applySuggestion(text) {
        appendToComposer(text, "replace");
        updatePlannerSummary("这组需求已经填入输入框，可以直接发送；我会先确认你想要省心方案还是个性化旅游规划。");
        setRuntimeStatus("需求已填入，可以直接发送", "online");
      }

      function appendPlannerStyle(value) {
        const input = document.getElementById("plannerStyle");
        const current = input.value
          .split(/[，,\s]+/)
          .map((item) => item.trim())
          .filter(Boolean);
        if (!current.includes(value)) {
          current.push(value);
        }
        input.value = current.join("、");
        persistPlannerDraft();
        updatePlannerSummary(`已加入偏好关键词：${current.join("、")}`);
      }

      function fillPlannerTemplate(kind) {
        const templates = {
          weekend: {
            origin: "北京",
            destination: "成都",
            date: "本周末",
            days: "3天2晚",
            travelers: "2人",
            budget: "5000元以内",
            transport: "高铁或飞机都可以，少折腾优先",
            stay: "市中心，吃饭方便",
            style: "美食慢游、轻松、不赶行程",
          },
          family: {
            origin: "上海",
            destination: "云南",
            date: "暑假",
            days: "5天4晚",
            travelers: "2大1小",
            budget: "12000元左右",
            transport: "飞行时间别太折腾，市内交通轻松",
            stay: "亲子友好，卫生安静",
            style: "亲子出游、轻松、自然体验",
          },
        };
        const picked = templates[kind];
        if (!picked) return;
        document.getElementById("plannerOrigin").value = picked.origin;
        document.getElementById("plannerDestination").value = picked.destination;
        document.getElementById("plannerDate").value = picked.date;
        document.getElementById("plannerDays").value = picked.days;
        document.getElementById("plannerTravelers").value = picked.travelers;
        document.getElementById("plannerBudget").value = picked.budget;
        document.getElementById("plannerTransport").value = picked.transport;
        document.getElementById("plannerStay").value = picked.stay;
        document.getElementById("plannerStyle").value = picked.style;
        persistPlannerDraft();
        updatePlannerSummary("模板已填入，可以选择省心方案，也可以选择个性化旅游规划。");
      }

      function readPlannerFields() {
        return {
          origin: document.getElementById("plannerOrigin").value.trim(),
          destination: document
            .getElementById("plannerDestination")
            .value.trim(),
          date: document.getElementById("plannerDate").value.trim(),
          days: document.getElementById("plannerDays").value.trim(),
          travelers: document
            .getElementById("plannerTravelers")
            .value.trim(),
          budget: document.getElementById("plannerBudget").value.trim(),
          transport: document.getElementById("plannerTransport").value.trim(),
          stay: document.getElementById("plannerStay").value.trim(),
          style: document.getElementById("plannerStyle").value.trim(),
        };
      }

      function buildPlannerOpening({ origin, destination }) {
        if (origin && destination) return `我想从${origin}出发去${destination}`;
        if (destination) return `我想去${destination}旅行`;
        if (origin) return `我想从${origin}出发规划一次旅行`;
        return "我想规划一次旅行";
      }

      function composePlannerDraft(mode = "personalized") {
        const {
          origin,
          destination,
          date,
          days,
          travelers,
          budget,
          transport,
          stay,
          style,
        } = readPlannerFields();

        const parts = [
          buildPlannerOpening({ origin, destination }),
          date ? `，出发时间大概是${date}` : "",
          days ? `，行程预计${days}` : "",
          travelers ? `，同行人数是${travelers}` : "",
          budget ? `，预算希望控制在${budget}` : "",
          transport ? `，交通偏好是${transport}` : "",
          stay ? `，住宿偏好是${stay}` : "",
          style ? `，偏好是${style}` : "",
        ];

        const modeInstruction =
          mode === "agency"
            ? "。请按“现成省心方案”来做：优先匹配成熟路线样板，直接给交通、住宿商圈、门票参考、餐饮和服务边界；价格只按参考价和待核验口径说明，不承诺实时锁价。"
            : "。请按“个性化旅游规划”来做：先判断需求是否完整；如果已经足够，请继续完成目的地、交通、住宿、预算、每日路线，并在最后整理成专属于我的个性化旅游规划报告。交通和住宿可以结合可用工具做真实查询与对比。";
        parts.push(modeInstruction);

        const draft = parts.join("");
        appendToComposer(draft, "replace");
        updatePlannerSummary(
          mode === "agency"
            ? "省心方案草稿已放进输入框：会优先匹配成熟路线，并说明价格待核验边界。"
            : "个性化旅游规划草稿已放进输入框：会继续补齐交通、住宿、预算和最终报告。"
        );
        setRuntimeStatus(
          mode === "agency" ? "省心方案草稿已整理" : "个性化规划草稿已整理",
          "online"
        );
      }

      function resetPlannerDraft(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        [
          "plannerOrigin",
          "plannerDestination",
          "plannerDate",
          "plannerDays",
          "plannerTravelers",
          "plannerBudget",
          "plannerTransport",
          "plannerStay",
          "plannerStyle",
        ].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.value = "";
        });
        clearDraftStorage(plannerDraftKey);
        updatePlannerAssistStrip();
        updatePlannerSummary(
          silent
            ? "可以先选一种规划方式；如果你只写旅行需求，我会先帮你确认要省心方案还是个性化旅游规划。"
            : "行程摘要已清空。你可以重新填写，也可以直接在下面描述需求。"
        );
      }

      function resetConversationDrafts(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        resetComposerDraft({ silent: true });
        resetPlannerDraft({ silent });
      }

      function isDefaultConversationTitle(title = "") {
        const normalized = (title || "").trim();
        return !normalized || normalized === DEFAULT_CONVERSATION_TITLE;
      }

      async function updateConversationTitle(id, title, options = {}) {
        const nextTitle = (title || "").trim();
        if (!id || !nextTitle) return false;
        const response = await fetch(`${getApiBase()}/api/v1/conversations/${id}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${state.token}`,
          },
          body: JSON.stringify({ title: nextTitle }),
        });
        if (!response.ok) {
          throw new Error(`conversation-title-${response.status}`);
        }
        const data = await response.json();
        const current = state.conversations.find((conv) => conv.id === id);
        if (current) current.title = data.title || nextTitle;
        if (state.editingConversationId === id) {
          state.editingConversationId = null;
        }
        if (state.currentConversationId === id) {
          const chatTitle = document.getElementById("chatTitle");
          if (chatTitle) {
            chatTitle.classList.remove("editing");
            chatTitle.textContent = data.title || nextTitle;
          }
        }
        renderConversationsList();
        updateSessionOverview();
        if (!options?.silent) {
          showToast("行程名称已更新");
        }
        return true;
      }

      function sanitizeConversationTitleSegment(value = "") {
        return String(value || "")
          .replace(
            /^(?:\u4ece|\u53bb|\u5230|\u5f80|\u60f3\u53bb|\u51c6\u5907\u53bb|\u8ba1\u5212\u53bb)\s*/u,
            ""
          )
          .replace(
            /\s*(?:\u51fa\u53d1|\u6e38\u73a9|\u65c5\u884c|\u65c5\u6e38|\u770b\u770b|\u901b\u901b|\u4f4f\u51e0\u665a|\u73a9\u51e0\u5929|\u73a9\u51e0\u591c)\s*$/u,
            ""
          )
          .replace(/[\uFF0C\u3002\uFF1B\u3001,.!?]+/gu, " ")
          .replace(/\s+/g, " ")
          .trim();
      }

      function extractTitleDays(text = "") {
        const normalized = String(text || "").replace(/\s+/g, "");
        const match = normalized.match(
          /(\d+\u5929\d+[\u665a\u591c]|\u4e00\u5929\u4e00\u591c|\u4e24\u5929\u4e00\u591c|\u4e09\u5929\u4e24\u591c|\u56db\u5929\u4e09\u591c|\u4e94\u5929\u56db\u591c|\u516d\u5929\u4e94\u591c|\u4e03\u5929\u516d\u591c)/u
        );
        return match ? match[1] : "";
      }

      function generateConversationTitle(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return DEFAULT_CONVERSATION_TITLE;

        const routeMatch = normalized.match(
          /\u4ece\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})\s*(?:\u51fa\u53d1)?\s*(?:\u53bb|\u5230)\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})/u
        );
        const destinationMatch = normalized.match(
          /(?:\u53bb|\u5230)\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})(?:\u65c5\u6e38|\u65c5\u884c|\u6e38\u73a9|\u73a9|\u901b|\u770b\u770b)?/u
        );
        const dayText = extractTitleDays(normalized);
        const styleTag = /\u60c5\u4fa3/u.test(normalized)
          ? "\u60c5\u4fa3"
          : /\u4eb2\u5b50/u.test(normalized)
          ? "\u4eb2\u5b50"
          : /\u7f8e\u98df/u.test(normalized)
          ? "\u7f8e\u98df"
          : /\u4eba\u6587/u.test(normalized)
          ? "\u4eba\u6587"
          : "";

        if (routeMatch?.[1] && routeMatch?.[2]) {
          const origin = sanitizeConversationTitleSegment(routeMatch[1]);
          const destination = sanitizeConversationTitleSegment(routeMatch[2]);
          return [`${origin} → ${destination}`, dayText, styleTag]
            .filter(Boolean)
            .join(" · ")
            .slice(0, 24);
        }

        if (destinationMatch?.[1]) {
          const destination = sanitizeConversationTitleSegment(destinationMatch[1]);
          return [destination, dayText, styleTag]
            .filter(Boolean)
            .join(" · ")
            .slice(0, 24);
        }

        const summary = normalized
          .replace(
            /^(?:\u6211\u60f3|\u5e2e\u6211|\u8bf7\u5e2e\u6211|\u9ebb\u70e6\u5e2e\u6211|\u60f3\u8981|\u8ba1\u5212|\u51c6\u5907)\s*/u,
            ""
          )
          .split(/[\u3002\uFF01\uFF1F.!?]/u)[0]
          .trim()
          .slice(0, 24);
        return summary || DEFAULT_CONVERSATION_TITLE;
      }

      async function maybeAutoNameCurrentConversation(text = "") {
        const conversationId = state.currentConversationId;
        if (!conversationId) return;
        const current = getCurrentConversation();
        if (current && !isDefaultConversationTitle(current.title)) return;
        const nextTitle = generateConversationTitle(text);
        if (!nextTitle || isDefaultConversationTitle(nextTitle)) return;
        try {
          await updateConversationTitle(conversationId, nextTitle, { silent: true });
        } catch (error) {
          console.error(error);
        }
      }

      function formatClock(value = new Date()) {
        const date = value instanceof Date ? value : new Date(value);
        const hh = String(date.getHours()).padStart(2, "0");
        const mm = String(date.getMinutes()).padStart(2, "0");
        return `${hh}:${mm}`;
      }

      function formatInlineText(text) {
        return escapeHtml(text)
          .replace(/`([^`]+)`/g, '<span class="inline-code">$1</span>')
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      }

      function sanitizeAssistantOutputText(text = "") {
        const visibleText = stripAssistantThinkingBlocks(text);
        const hiddenLinePatterns = [
          /^(requirement_collection|destination_selection|transport_planning|accommodation_planning|order_generation|report_generation)$/i,
          /^(收集需求|需求收集|当前阶段|当前步骤|阶段切换|状态更新|流程推进)$/u,
          /^(进入|切换到).{0,18}阶段$/u,
          /^(tool_call|工具调用|调用工具)[:：]?\s*/i,
          /^(理解|收到|明白|好的)$/u,
        ];
        return visibleText
          .split("\n")
          .filter((line) => {
            const trimmed = line.trim();
            if (!trimmed) return true;
            if (/^-{1,3}$/.test(trimmed) || /^---+$/.test(trimmed)) return false;
            return !hiddenLinePatterns.some((pattern) => pattern.test(trimmed));
          })
          .join("\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();
      }

      function getLongestTagPrefixSuffix(text = "", tag = "") {
        const lowerText = String(text || "").toLowerCase();
        const maxSize = Math.min(tag.length - 1, lowerText.length);
        for (let size = maxSize; size > 0; size -= 1) {
          if (tag.startsWith(lowerText.slice(-size))) {
            return size;
          }
        }
        return 0;
      }

      function createAssistantThinkingFilter() {
        const openTag = "<think>";
        const closeTag = "</think>";
        let buffer = "";
        let insideThinking = false;

        return {
          feed(value = "") {
            buffer += String(value || "");
            const chunks = [];

            while (buffer) {
              const lowerBuffer = buffer.toLowerCase();
              if (insideThinking) {
                const closeIndex = lowerBuffer.indexOf(closeTag);
                if (closeIndex >= 0) {
                  buffer = buffer.slice(closeIndex + closeTag.length);
                  insideThinking = false;
                  continue;
                }
                const keepSize = getLongestTagPrefixSuffix(buffer, closeTag);
                buffer = keepSize ? buffer.slice(-keepSize) : "";
                break;
              }

              const openIndex = lowerBuffer.indexOf(openTag);
              if (openIndex >= 0) {
                chunks.push(buffer.slice(0, openIndex));
                buffer = buffer.slice(openIndex + openTag.length);
                insideThinking = true;
                continue;
              }

              const keepSize = getLongestTagPrefixSuffix(buffer, openTag);
              if (keepSize) {
                chunks.push(buffer.slice(0, -keepSize));
                buffer = buffer.slice(-keepSize);
              } else {
                chunks.push(buffer);
                buffer = "";
              }
              break;
            }

            return chunks.join("");
          },
          finish() {
            if (insideThinking) {
              buffer = "";
              insideThinking = false;
              return "";
            }
            if (buffer && openTag.startsWith(buffer.toLowerCase())) {
              buffer = "";
              return "";
            }
            const remainder = buffer;
            buffer = "";
            return remainder;
          },
        };
      }

      function stripAssistantThinkingBlocks(text = "") {
        const thinkingFilter = createAssistantThinkingFilter();
        return thinkingFilter.feed(text) + thinkingFilter.finish();
      }

      function splitAssistantBlocks(text) {
        return sanitizeAssistantOutputText(text)
          .replace(/\r\n/g, "\n")
          .split(/\n{2,}/)
          .map((block) => block.trim())
          .filter(Boolean);
      }

      function normalizeSectionTitle(title = "") {
        return title
          .replace(/^#{1,3}\s+/, "")
          .replace(/^\*\*(.+?)\*\*$/, "$1")
          .replace(/^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]+\s*/u, "")
          .replace(/[：:]\s*$/, "")
          .trim();
      }

      function isEmbeddedSectionHeading(line = "") {
        const normalized = normalizeSectionTitle(
          line
            .replace(/^[-*•]\s*/, "")
            .replace(/（.*$/, "")
            .replace(/\(.*$/, "")
            .trim()
        );
        if (!normalized || normalized.length > 26) return false;
        return /^(预算|交通|住宿|住宿推荐|住哪里|玩法建议|玩法|行程安排|每日安排|目的地|提醒|下一步)/.test(
          normalized
        );
      }

      function looksLikeDecisionPrompt(text = "") {
        return /想跟你确认|确认一下|请确认|你觉得|要不要|是否|还是你想|可以直接告诉我|你更想|更合适吗|看看其他备选|哪个方向/u.test(
          text
        );
      }

      function inferSectionMetaFromBody(lines = []) {
        const bodyText = lines.join(" ");
        if (looksLikeDecisionPrompt(bodyText)) {
          return { tone: "next", icon: "fa-circle-question" };
        }
        if (/高铁|火车|自驾|大巴|公交|航班|车程|打车|高速|车站|出发|到达/.test(bodyText)) {
          return { tone: "transport", icon: "fa-train-subway" };
        }
        if (/住宿|酒店|民宿|温泉|私汤|住在|客栈|房型|每晚/.test(bodyText)) {
          return { tone: "stay", icon: "fa-bed" };
        }
        if (/预算|费用|花费|价格|每人|总共/.test(bodyText)) {
          return { tone: "budget", icon: "fa-wallet" };
        }
        if (/玩法|景点|适合|行程|打卡|游览|放松|亲水|徒步|温泉|眉县|太白山/.test(bodyText)) {
          return { tone: "overview", icon: "fa-map-location-dot" };
        }
        return null;
      }

      function expandStructuredTravelBlocks(blocks = []) {
        const expanded = [];
        blocks.forEach((block) => {
          const normalizedBlock = block
            .replace(
              /([^\n])\s+((?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?\s*)?\*\*[^*\n]{2,18}\*\*[：:])/gu,
              "$1\n$2"
            )
            .replace(
              /([^\n])\s+((?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?\s*)?(交通建议|住宿选址|行程基调|住宿推荐|交通方案|玩法建议|行程安排|预算建议)[：:])/gu,
              "$1\n$2"
            );
          const lines = normalizedBlock
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          let current = [];
          lines.forEach((line, index) => {
            const shouldStartNew =
              index > 0 &&
              isEmbeddedSectionHeading(line) &&
              current.length > 0;
            if (shouldStartNew) {
              expanded.push(current.join("\n"));
              current = [line];
              return;
            }
            current.push(line);
          });
          if (current.length) {
            expanded.push(current.join("\n"));
          }
        });
        return expanded;
      }

      function getTravelSectionMeta(title) {
        const normalized = normalizeSectionTitle(title).toLowerCase();
        const contains = (...keywords) =>
          keywords.some((keyword) => normalized.includes(keyword));

        if (looksLikeDecisionPrompt(normalized)) {
          return { tone: "next", icon: "fa-circle-question" };
        }
        if (
          contains(
            "概览",
            "总览",
            "方案",
            "推荐理由",
            "行程安排",
            "每日安排",
            "一句话定位",
            "为什么适合你",
            "适合你"
          )
        ) {
          return { tone: "overview", icon: "fa-map-location-dot" };
        }
        if (contains("目的地", "城市", "景点", "路线")) {
          return { tone: "overview", icon: "fa-location-dot" };
        }
        if (contains("交通", "航班", "火车", "高铁", "大交通", "出发")) {
          return { tone: "transport", icon: "fa-train-subway" };
        }
        if (contains("住宿", "酒店", "民宿", "住哪里")) {
          return { tone: "stay", icon: "fa-bed" };
        }
        if (contains("预算", "费用", "花费", "价格", "成本")) {
          return { tone: "budget", icon: "fa-wallet" };
        }
        if (contains("美食", "餐饮", "吃")) {
          return { tone: "food", icon: "fa-utensils" };
        }
        if (contains("提醒", "注意", "避坑", "贴士", "须知")) {
          return { tone: "warning", icon: "fa-triangle-exclamation" };
        }
        if (contains("下一步", "接下来", "行动", "后续")) {
          return { tone: "next", icon: "fa-arrow-right" };
        }
        return null;
      }

      function cleanJourneyLocationValue(value = "") {
        return value
          .replace(/^[-*#\s]+/, "")
          .replace(/[📍✅⚠️✨🌤️]/g, "")
          .replace(/^(需求很完整|信息基本齐了|现在先把|我已经按你的要求查到|我先帮你梳理确认一下)[！!：:\s]*/g, "")
          .replace(/\s*[·•｜|].*$/, "")
          .replace(/(一句话定位|为什么适合你|适合你|两个小提醒|小提醒|提醒|建议)$/g, "")
          .replace(/\s+/g, " ")
          .trim();
      }

      function splitTableCells(line) {
        return line
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((cell) => cell.trim());
      }

      function isMarkdownTable(lines) {
        if (lines.length < 2) return false;
        if (!lines[0].includes("|") || !lines[1].includes("|")) return false;
        const dividerCells = splitTableCells(lines[1]);
        return (
          dividerCells.length > 0 &&
          dividerCells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")))
        );
      }

      function getMarkdownTableSpan(lines, startIndex = 0) {
        const rest = lines.slice(startIndex);
        if (!isMarkdownTable(rest)) return 0;
        let endIndex = startIndex + 2;
        while (endIndex < lines.length && lines[endIndex].includes("|")) {
          endIndex += 1;
        }
        return endIndex - startIndex;
      }

      function renderMarkdownTable(lines) {
        const headers = splitTableCells(lines[0]);
        const rows = lines
          .slice(2)
          .map(splitTableCells)
          .filter((cells) => cells.some(Boolean));

        if (!headers.length || !rows.length) {
          return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
        }

        if (isTransportTable(headers)) {
          return renderTransportTable(headers, rows);
        }

        return `
          <div class="message-table-wrap">
            <table class="message-table">
              <thead>
                <tr>${headers
                  .map((header) => `<th>${formatInlineText(header)}</th>`)
                  .join("")}</tr>
              </thead>
              <tbody>
                ${rows
                  .map(
                    (cells) => `<tr>${headers
                      .map(
                        (_, index) =>
                          `<td>${formatInlineText(cells[index] || "")}</td>`
                      )
                      .join("")}</tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
      }

      function normalizeTransportHeader(header = "") {
        const normalized = header.replace(/\s+/g, "").toLowerCase();
        if (
          normalized.includes("车次") ||
          normalized.includes("车次/航班") ||
          normalized.includes("航班") ||
          normalized.includes("班次") ||
          normalized.includes("方案")
        ) {
          return "code";
        }
        if (
          normalized.includes("出发时间") ||
          normalized.includes("到达时间") ||
          normalized.includes("出发→到达") ||
          normalized.includes("出发->到达") ||
          normalized.includes("时间")
        ) {
          return "schedule";
        }
        if (normalized.includes("耗时") || normalized.includes("历时")) {
          return "duration";
        }
        if (
          normalized.includes("票价") ||
          normalized.includes("价格") ||
          normalized.includes("费用") ||
          normalized.includes("二等座") ||
          normalized.includes("一等座") ||
          normalized.includes("商务座")
        ) {
          return "price";
        }
        if (
          normalized.includes("推荐理由") ||
          normalized.includes("备注") ||
          normalized.includes("说明") ||
          normalized.includes("建议")
        ) {
          return "reason";
        }
        if (normalized.includes("余票") || normalized.includes("舱位")) {
          return "inventory";
        }
        return "extra";
      }

      function isTransportTable(headers = []) {
        const mapped = headers.map(normalizeTransportHeader);
        const hasCode = mapped.includes("code");
        const hasCoreInfo =
          mapped.includes("schedule") ||
          mapped.includes("duration") ||
          mapped.includes("price");
        return hasCode && hasCoreInfo;
      }

      function detectTransportCardKind(code = "", reason = "") {
        const source = `${code} ${reason}`.toUpperCase();
        if (
          /^(G|D|C|K|T|Z)\d+/.test(code.toUpperCase()) ||
          source.includes("高铁") ||
          source.includes("火车")
        ) {
          return { label: "铁路方案", icon: "fa-train-subway" };
        }
        if (
          /^[A-Z]{2}\d+/.test(code.toUpperCase()) ||
          source.includes("航班") ||
          source.includes("飞机")
        ) {
          return { label: "航班方案", icon: "fa-plane-departure" };
        }
        if (source.includes("自驾") || source.includes("驾车")) {
          return { label: "自驾方案", icon: "fa-car-side" };
        }
        return { label: "交通方案", icon: "fa-route" };
      }

      function splitScheduleText(text = "") {
        const compact = text.replace(/\s+/g, " ").trim();
        const parts = compact.split(/\s*(?:→|->|➜|至)\s*/);
        if (parts.length >= 2) {
          return {
            departure: parts[0].trim(),
            arrival: parts.slice(1).join(" → ").trim(),
          };
        }
        return { departure: compact, arrival: "" };
      }

      function renderTransportTable(headers, rows) {
        const keyOrder = headers.map(normalizeTransportHeader);
        const cards = rows.map((cells) => {
          const entry = {};
          headers.forEach((header, index) => {
            const key = keyOrder[index];
            const value = cells[index] || "";
            if (key === "extra") {
              if (!entry.extra) entry.extra = [];
              if (value) {
                entry.extra.push({ label: header, value });
              }
              return;
            }
            if (entry[key]) {
              entry[key] = `${entry[key]} ${value}`.trim();
            } else {
              entry[key] = value;
            }
          });

          const kind = detectTransportCardKind(entry.code || "", entry.reason || "");
          const schedule = splitScheduleText(entry.schedule || "");
          const recommendationTone =
            /(推荐|首选|优先)/.test(entry.reason || "") ? "recommended" : "";

          return `
            <article class="transport-option-card ${recommendationTone}">
              <div class="transport-option-head">
                <div class="transport-option-kind">
                  <i class="fa-solid ${kind.icon}"></i>
                  <span>${kind.label}</span>
                </div>
                <div class="transport-option-code">${formatInlineText(entry.code || "待确认")}</div>
              </div>
              <div class="transport-option-times">
                <div class="transport-stop">
                  <span class="transport-stop-label">出发</span>
                  <strong>${formatInlineText(schedule.departure || "待确认")}</strong>
                </div>
                <div class="transport-stop-arrow">
                  <i class="fa-solid fa-arrow-right-long"></i>
                </div>
                <div class="transport-stop">
                  <span class="transport-stop-label">到达</span>
                  <strong>${formatInlineText(schedule.arrival || "待确认")}</strong>
                </div>
              </div>
              <div class="transport-option-meta">
                ${
                  entry.duration
                    ? `<span class="transport-meta-pill"><i class="fa-regular fa-clock"></i> ${formatInlineText(
                        entry.duration
                      )}</span>`
                    : ""
                }
                ${
                  entry.price
                    ? `<span class="transport-meta-pill price"><i class="fa-solid fa-yen-sign"></i> ${formatInlineText(
                        entry.price
                      )}</span>`
                    : ""
                }
                ${
                  entry.inventory
                    ? `<span class="transport-meta-pill"><i class="fa-solid fa-ticket"></i> ${formatInlineText(
                        entry.inventory
                      )}</span>`
                    : ""
                }
              </div>
              ${
                entry.reason
                  ? `<div class="transport-option-reason">${formatInlineText(entry.reason)}</div>`
                  : ""
              }
              ${
                entry.extra?.length
                  ? `<dl class="transport-extra-list">${entry.extra
                      .map(
                        (item) => `
                          <div class="transport-extra-item">
                            <dt>${formatInlineText(item.label)}</dt>
                            <dd>${formatInlineText(item.value)}</dd>
                          </div>
                        `
                      )
                      .join("")}</dl>`
                  : ""
              }
            </article>
          `;
        });

        return `<div class="transport-options-board">${cards.join("")}</div>`;
      }

      function renderAssistantLineGroup(lines) {
        if (!lines.length) return "";

        if (isMarkdownTable(lines)) {
          return renderMarkdownTable(lines);
        }

        if (lines.every((line) => /^[-*•]\s+/.test(line))) {
          return `<ul>${lines
            .map(
              (line) =>
                `<li>${formatInlineText(line.replace(/^[-*•]\s+/, ""))}</li>`
            )
            .join("")}</ul>`;
        }

        if (lines.every((line) => /^\d+\.\s+/.test(line))) {
          return `<ol>${lines
            .map(
              (line) =>
                `<li>${formatInlineText(line.replace(/^\d+\.\s+/, ""))}</li>`
            )
            .join("")}</ol>`;
        }

        if (/^#{1,3}\s+/.test(lines[0])) {
          const title = lines[0].replace(/^#{1,3}\s+/, "");
          const bodyLines = lines.slice(1);
          return `${title ? `<h4>${formatInlineText(title)}</h4>` : ""}${
            bodyLines.length
              ? `<p>${bodyLines.map((line) => formatInlineText(line)).join("<br>")}</p>`
              : ""
          }`;
        }

        return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
      }

      function renderAssistantLines(lines) {
        if (!lines.length) return "";

        const chunks = [];
        let current = [];
        const flushCurrent = () => {
          if (!current.length) return;
          chunks.push(renderAssistantLineGroup(current));
          current = [];
        };

        for (let index = 0; index < lines.length; index += 1) {
          const tableSpan = getMarkdownTableSpan(lines, index);
          if (tableSpan) {
            flushCurrent();
            chunks.push(renderMarkdownTable(lines.slice(index, index + tableSpan)));
            index += tableSpan - 1;
            continue;
          }
          current.push(lines[index]);
        }

        flushCurrent();
        return chunks.join("");
      }

      function renderAssistantFallback(blocks) {
        return `<div class="travel-fallback">${blocks
          .map((block) => {
            const lines = block
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean);
            return renderAssistantLines(lines);
          })
          .join("")}</div>`;
      }

      function truncateJourneyNote(text = "", fallback = "等待你继续补充细节") {
        const normalized = text.replace(/\s+/g, " ").trim();
        if (!normalized) return fallback;
        return normalized.length > 42 ? `${normalized.slice(0, 42)}…` : normalized;
      }

      function extractJourneyCityPairFromConversationTitle(title = "") {
        const normalized = (title || "").replace(/\s+/g, " ").trim();
        if (!normalized || isDefaultConversationTitle(normalized)) return null;
        const coreTitle = normalized.split("·")[0].trim();
        return extractJourneyCityPair(coreTitle);
      }

      function splitJourneyFragments(text = "") {
        return text
          .replace(/\s+/g, " ")
          .split(/[。！？；\n]/)
          .map((part) => part.trim())
          .filter((part) => part.length >= 4 && part.length <= 36);
      }

      function extractJourneyHighlights(sections) {
        const highlightKeywords = [
          "山",
          "海",
          "湖",
          "江",
          "河",
          "岛",
          "古镇",
          "老街",
          "夜市",
          "温泉",
          "寺",
          "博物馆",
          "公园",
          "书店",
          "营地",
          "民宿",
          "美食",
          "小吃",
          "日落",
          "咖啡",
          "亲水",
          "徒步",
          "骑行",
          "露营",
        ];
        const pool = sections
          .filter((section) => ["overview", "stay", "next"].includes(section.tone))
          .flatMap((section) => splitJourneyFragments(section.rawLines.join(" ")));

        const scored = pool
          .map((fragment) => ({
            fragment,
            score: highlightKeywords.reduce(
              (count, keyword) => count + (fragment.includes(keyword) ? 1 : 0),
              0
            ),
          }))
          .sort((a, b) => b.score - a.score || a.fragment.length - b.fragment.length);

        const picked = [];
        scored.forEach(({ fragment }) => {
          const normalized = fragment.replace(/[：:]/g, " ").trim();
          if (
            !normalized ||
            picked.some((item) => item.includes(normalized) || normalized.includes(item))
          ) {
            return;
          }
          picked.push(normalized);
        });

        return picked.slice(0, 4);
      }

      function inferHighlightTheme(text = "") {
        if (/温泉|亲水|湖|江|河|海/.test(text)) return "亲水放松";
        if (/古镇|老街|博物馆|寺|书店/.test(text)) return "人文慢游";
        if (/山|徒步|骑行|营地|露营/.test(text)) return "户外探索";
        if (/美食|小吃|夜市|咖啡/.test(text)) return "在地风味";
        return "值得停留";
      }

      function buildJourneyHighlightCards(highlights = []) {
        return highlights.map((text, index) => {
          const normalized = text.replace(/\s+/g, " ").trim();
          const title = normalized.length > 14 ? `${normalized.slice(0, 14)}…` : normalized;
          const note =
            normalized.length > 36
              ? `${normalized.slice(0, 36)}…`
              : normalized || "适合继续展开玩法、停留时长和拍照点。";
          return {
            index,
            title,
            note,
            theme: inferHighlightTheme(normalized),
          };
        });
      }

      function getKnownCityNearbyPlaces(destination = "") {
        const city = cleanJourneyLocationValue(destination);
        const presets = [
          {
            test: /南京|金陵/u,
            places: [
              ["主要景点", "夫子庙秦淮风光带", "fa-landmark"],
              ["热闹商业街", "新街口商圈", "fa-store"],
              ["美食小吃", "老门东美食街", "fa-bowl-food"],
            ],
          },
          {
            test: /成都|蓉城/u,
            places: [
              ["主要景点", "武侯祠", "fa-landmark"],
              ["热闹商业街", "春熙路", "fa-store"],
              ["美食小吃", "宽窄巷子", "fa-bowl-food"],
            ],
          },
          {
            test: /西安|长安/u,
            places: [
              ["主要景点", "西安城墙", "fa-landmark"],
              ["热闹商业街", "钟楼商圈", "fa-store"],
              ["美食小吃", "回民街", "fa-bowl-food"],
            ],
          },
          {
            test: /北京/u,
            places: [
              ["主要景点", "故宫博物院", "fa-landmark"],
              ["热闹商业街", "王府井", "fa-store"],
              ["美食小吃", "簋街", "fa-bowl-food"],
            ],
          },
          {
            test: /上海/u,
            places: [
              ["主要景点", "外滩", "fa-landmark"],
              ["热闹商业街", "南京东路步行街", "fa-store"],
              ["美食小吃", "云南南路美食街", "fa-bowl-food"],
            ],
          },
          {
            test: /杭州/u,
            places: [
              ["主要景点", "西湖", "fa-landmark"],
              ["热闹商业街", "湖滨银泰", "fa-store"],
              ["美食小吃", "河坊街", "fa-bowl-food"],
            ],
          },
          {
            test: /长沙/u,
            places: [
              ["主要景点", "橘子洲", "fa-landmark"],
              ["热闹商业街", "五一广场", "fa-store"],
              ["美食小吃", "坡子街", "fa-bowl-food"],
            ],
          },
        ];
        return presets.find((preset) => preset.test.test(city))?.places || [];
      }

      function buildStayNearbyHighlights(previewState = {}) {
        const destination = cleanJourneyLocationValue(
          previewState.cityPair?.destination || previewState.destinationSection?.title || ""
        );
        const presetPlaces = getKnownCityNearbyPlaces(destination);
        if (presetPlaces.length) {
          return presetPlaces.map(([label, name, icon]) => ({
            label,
            name,
            icon,
            query: destination && !name.includes(destination) ? `${destination} ${name}` : name,
          }));
        }
        const picked = [];
        const push = (label, pattern, icon, fallback) => {
          const hit = (previewState.highlights || []).find((item) => pattern.test(item));
          const name = cleanJourneyLocationValue(hit || fallback || "");
          if (!name) return;
          picked.push({
            label,
            name,
            icon,
            query: destination && !name.includes(destination) ? `${destination} ${name}` : name,
          });
        };
        push("主要景点", /景区|景点|公园|博物馆|寺|山|湖|江|河|古镇/u, "fa-landmark", `${destination} 主要景点`);
        push("热闹商业街", /商圈|步行街|夜市|老街|街区|广场/u, "fa-store", `${destination} 商业街`);
        push("美食小吃", /美食|小吃|餐|夜市|咖啡|甜品/u, "fa-bowl-food", `${destination} 小吃街`);
        return picked.filter((item) => item.name && !/待确认|待补充/.test(item.name));
      }

      function extractJourneyRhythm(summaryBlocks, sections) {
        const rhythmLines = [];
        const directRhythmLines = [...summaryBlocks.flat(), ...sections.flatMap((section) => section.rawLines)]
          .map((line) => line.trim())
          .filter(Boolean)
          .filter((line) =>
            /day\s*\d+|第.天|上午|中午|下午|傍晚|晚上|早上|行程|安排/i.test(line)
          );

        directRhythmLines.forEach((line) => {
          const normalized = line.replace(/^[-*•]\s*/, "").trim();
          if (
            normalized &&
            !rhythmLines.some((item) => item.includes(normalized) || normalized.includes(item))
          ) {
            rhythmLines.push(normalized);
          }
        });

        if (rhythmLines.length >= 3) {
          return rhythmLines.slice(0, 3);
        }

        const overviewSection =
          sections.find((section) => section.title.includes("行程") || section.title.includes("安排")) ||
          sections.find((section) => section.tone === "overview");
        const fallbackFragments = splitJourneyFragments(
          overviewSection?.rawLines?.join(" ") || summaryBlocks.flat().join(" ")
        );

        fallbackFragments.forEach((fragment) => {
          if (
            fragment &&
            !rhythmLines.some((item) => item.includes(fragment) || fragment.includes(item))
          ) {
            rhythmLines.push(fragment);
          }
        });

        return rhythmLines.slice(0, 3);
      }

      function hasJourneyClarificationSignal(text = "") {
        return /确认一下|想跟你确认|哪个更合适|还是.*预算|想先了解|更精准|会影响|待补充|待确认|请先帮我判断|请先确认|方便|是否完整|告诉我|大概想什么时候|从哪个城市出发|继续补充/.test(
          text
        );
      }

      function hasJourneyPlanSignal(text = "", sections = [], highlights = [], rhythm = []) {
        if (sections.some((section) => ["stay", "warning", "next", "food"].includes(section.tone))) {
          return true;
        }
        if (highlights.length >= 2 || rhythm.length >= 2) {
          return true;
        }
        return /推荐|路线|行程|安排|玩法|景点|入住|住宿|酒店|民宿|车次|航班|美食|看点|打卡|游览/.test(
          text
        );
      }

      function parseJourneyChineseDayNumber(value = "") {
        if (/^\d+$/.test(value)) return Number(value);
        const mapping = {
          "\u4e00": 1,
          "\u4e8c": 2,
          "\u4e09": 3,
          "\u56db": 4,
          "\u4e94": 5,
          "\u516d": 6,
          "\u4e03": 7,
          "\u516b": 8,
          "\u4e5d": 9,
          "\u5341": 10,
        };
        if (value === "\u5341") return 10;
        if (value.startsWith("\u5341")) {
          return 10 + (mapping[value.slice(1)] || 0);
        }
        if (value.endsWith("\u5341")) {
          return (mapping[value[0]] || 0) * 10;
        }
        if (value.includes("\u5341")) {
          const [tens, ones] = value.split("\u5341");
          return (mapping[tens] || 0) * 10 + (mapping[ones] || 0);
        }
        return mapping[value] || 0;
      }

      function normalizeJourneyDayHeading(text = "") {
        return String(text || "")
          .replace(/^#{1,6}\s+/, "")
          .replace(/^\*\*/, "")
          .replace(/\*\*$/, "")
          .replace(/^[-*•]\s*/, "")
          .replace(/^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]+\s*/u, "")
          .trim();
      }

      function parseJourneyDayNumber(text = "") {
        const normalized = normalizeJourneyDayHeading(text);
        const dayMatch = normalized.match(/\bday\s*(\d+)\b/i);
        if (dayMatch) return Number(dayMatch[1]);
        const chineseMatch = normalized.match(/^第\s*([一二三四五六七八九十\d]+)\s*天/);
        if (chineseMatch) {
          return parseJourneyChineseDayNumber(chineseMatch[1]);
        }
        return 0;
      }

      function splitJourneyWaypoints(text = "") {
        const cleaned = (text || "")
          .replace(/^#{1,3}\s+/, "")
          .replace(/^.*?[|｜]/, "")
          .replace(/^\s*(?:day)\s*\d+\s*/i, "")
          .replace(/^\s*第\s*[一二三四五六七八九十\d]+\s*天\s*/, "")
          .replace(/（[^）]*）|\([^)]*\)/g, " ")
          .replace(/\s+/g, " ")
          .trim();

        return cleaned
          .split(/(?:→|->|—|–|·|\/|、|,|，|\s{2,})+/)
          .map((item) => item.trim())
          .map((item) => item.replace(/^[|｜:：-]+|[|｜:：-]+$/g, "").trim())
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
      }

      function extractJourneyDayPlansFromLines(lines = []) {
        const plans = [];
        let current = null;
        const flush = () => {
          if (!current?.dayNumber) return;
          const routeSeed =
            current.rawLines.find((line) => /(?:→|->|—|－|至|到)/.test(line)) || current.title;
          const note = truncateJourneyNote(
            current.rawLines.slice(1).join(" "),
            "这一天的节奏会在后续继续细化。"
          );
          plans.push({
            key: `day-${current.dayNumber}`,
            dayNumber: current.dayNumber,
            label: `Day ${current.dayNumber}`,
            title: current.title,
            waypoints: splitJourneyWaypoints(routeSeed),
            highlights: extractJourneyHighlights([
              {
                title: current.title,
                rawLines: current.rawLines,
              },
            ]).slice(0, 3),
            note,
          });
          current = null;
        };

        lines.forEach((rawLine) => {
          const line = (rawLine || "").trim();
          if (!line || /^[-*]{3,}$/.test(line)) return;
          const dayNumber = parseJourneyDayNumber(line);
          if (dayNumber) {
            flush();
            current = {
              dayNumber,
              title: line,
              rawLines: [line],
            };
            return;
          }
          if (current) {
            current.rawLines.push(line);
          }
        });

        flush();
        return plans;
      }

      function extractJourneyDayPlans(sections = [], summaryBlocks = []) {
        const sectionPlans = sections
          .map((section) => {
            const dayNumber = parseJourneyDayNumber(
              section.title || section.rawLines?.[0] || ""
            );
            if (!dayNumber) return null;
            const routeTitle = section.title || section.rawLines?.[0] || "";
            const waypoints = splitJourneyWaypoints(routeTitle);
            return {
              key: `day-${dayNumber}`,
              dayNumber,
              label: `Day ${dayNumber}`,
              title: routeTitle,
              waypoints,
              highlights: extractJourneyHighlights([section]).slice(0, 3),
              note: truncateJourneyNote(
                (section.rawLines || []).slice(1).join(" "),
                "\u8fd9\u4e00\u5929\u7684\u8282\u594f\u4f1a\u5728\u540e\u7eed\u7ee7\u7eed\u7ec6\u5316\u3002"
              ),
            };
          })
          .filter(Boolean)
          .sort((left, right) => left.dayNumber - right.dayNumber);
        const lineFallbackPlans = extractJourneyDayPlansFromLines([
          ...summaryBlocks.flat(),
          ...sections.flatMap((section) => [section.title, ...(section.rawLines || [])]),
        ]);
        const mergedPlans = new Map();
        [...lineFallbackPlans, ...sectionPlans].forEach((plan) => {
          const existing = mergedPlans.get(plan.dayNumber);
          if (!existing) {
            mergedPlans.set(plan.dayNumber, plan);
            return;
          }
          mergedPlans.set(plan.dayNumber, {
            ...existing,
            ...plan,
            waypoints:
              plan.waypoints?.length && !plan.waypoints.every((item) => /^\*{0,2}day/i.test(item))
                ? plan.waypoints
                : existing.waypoints,
            highlights: plan.highlights?.length ? plan.highlights : existing.highlights,
            note: plan.note?.length ? plan.note : existing.note,
          });
        });
        return Array.from(mergedPlans.values())
          .sort((left, right) => left.dayNumber - right.dayNumber)
          .slice(0, 7);
      }

      function resolveTravelCardMapFocus(section, previewState) {
        if (!previewState?.shouldRender) {
          return "";
        }
        if (parseJourneyDayNumber(section.title || "")) {
          return "";
        }
        if (section.tone === "stay" && !/待补充|待确认/.test(section.title)) {
          return "stay";
        }
        if (section.tone === "food") {
          return previewState.highlightCards.length ? "highlights" : "";
        }
        if (section.tone === "overview") {
          return "destination";
        }
        return "";
      }

      function isJourneyPlaceholderValue(value = "") {
        const normalized = (value || "").trim();
        return (
          !normalized ||
          /待确认|待继续|待补充|待比较|待定|后面继续补/.test(normalized)
        );
      }

      function buildJourneyAtlasTitle(previewState, previewStops = []) {
        const origin = cleanJourneyLocationValue(
          previewState?.cityPair?.origin || previewStops[0]?.value || ""
        );
        const destination = cleanJourneyLocationValue(
          previewState?.cityPair?.destination || previewStops[1]?.value || ""
        );
        if (!isJourneyPlaceholderValue(origin) && !isJourneyPlaceholderValue(destination)) {
          return `${origin} → ${destination}`;
        }
        if (!isJourneyPlaceholderValue(destination)) {
          return destination;
        }
        return "行程路线";
      }

      function renderJourneyAtlas(previewState, previewStops, previewMetrics) {
        const { cityPair, highlights, highlightCards, dayPlans } = previewState;
        const stayNearbyHighlights = buildStayNearbyHighlights(previewState);
        const mapHighlightQueries = [
          ...stayNearbyHighlights.map((item) => item.query),
          ...highlights,
        ]
          .map((item) => cleanJourneyLocationValue(item || ""))
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
        const routeStops = [
          { ...previewStops[0], target: "origin" },
          { ...previewStops[1], target: "destination" },
          { ...previewStops[2], target: "route" },
          { ...previewStops[3], target: "stay" },
        ].map((item) => ({
          ...item,
          value: cleanJourneyLocationValue(item.value || ""),
          disabled: isJourneyPlaceholderValue(cleanJourneyLocationValue(item.value || "")),
        }));
        const validRouteStops = routeStops.filter((item) => !item.disabled);
        const atlasTitle = buildJourneyAtlasTitle(previewState, previewStops);
        const hasDayView = dayPlans.length >= 1;
        const hasLiveMapPayload =
          hasDayView ||
          mapHighlightQueries.length >= 2 ||
          (previewState.recommendations || []).some(
            (item) => item && Number.isFinite(Number(item.lng)) && Number.isFinite(Number(item.lat))
          );
        const mapPayload = serializeMapPayload({
          origin: cityPair?.origin || routeStops[0]?.value || "",
          destination: cityPair?.destination || routeStops[1]?.value || "",
          stay: routeStops[3]?.disabled ? "" : routeStops[3]?.value || "",
          highlights: mapHighlightQueries,
          recommendations: previewState.recommendations || [],
          days: dayPlans.map((day) => ({
            key: day.key,
            label: day.label,
            waypoints: day.waypoints,
            stops: day.stops || [],
            segments: day.segments || [],
          })),
        });
        const summaryChips = [
          ...previewMetrics.slice(0, 3),
          {
            icon: "fa-calendar-days",
            label: "分日状态",
            value: hasDayView ? `已拆成 ${dayPlans.length} 天` : "先显示总览",
          },
        ];

        const isImmersive = previewState.mapExperience === "immersive";
        return `
          <section class="journey-map-studio${
            isImmersive ? " journey-map-studio--immersive" : ""
          }">
            <div class="journey-map-studio-brief">
              ${summaryChips
                .map(
                  (item) => `
                    <div class="journey-map-studio-brief-item">
                      <span class="journey-map-studio-brief-label">
                        <i class="fa-solid ${item.icon}"></i> ${escapeHtml(item.label)}
                      </span>
                      <strong>${escapeHtml(item.value)}</strong>
                    </div>
                  `
                )
                .join("")}
            </div>
            <div
              class="journey-live-map-shell journey-live-map-shell--studio${
                isImmersive ? " journey-live-map-shell--immersive" : ""
              } journey-map-tools-collapsed journey-map-sidebar-collapsed${
                hasDayView ? "" : " journey-live-map-shell--overview-only"
              }"
              data-map-title="${escapeHtml(atlasTitle)}"
              data-day-plans="${serializeMapPayload(dayPlans)}"
              data-route-stops="${serializeMapPayload(validRouteStops)}"
            >
              <div class="journey-live-map-head">
                <div class="journey-live-map-head-copy">
                  <span class="journey-map-shell-kicker">
                    <i class="fa-solid fa-route"></i> 路线地图
                  </span>
                  <strong>${escapeHtml(atlasTitle)}</strong>
                  <span>${
                    hasDayView
                      ? "直接在地图里切换总览和每天的路线，沿途景点会同步高亮。"
                      : "当前显示路线总览。"
                  }</span>
                </div>
              </div>
              <div class="journey-live-map-shell-body journey-live-map-shell-body--studio">
                <div class="journey-map-stage">
                  <div class="journey-map-title-pill">
                    <strong>${escapeHtml(atlasTitle)}</strong>
                    <span>${escapeHtml(
                      hasDayView ? `${dayPlans.length} 天路线` : "路线总览"
                    )}</span>
                  </div>
                  <div class="journey-map-floating-panel">
                    <div class="journey-map-floating-actions journey-map-floating-summary">
                      <button class="journey-map-action-btn secondary" type="button" data-map-action="toggle-tools" aria-expanded="false" title="展开地图工具">地图工具</button>
                      <button class="journey-map-action-btn secondary" type="button" data-map-action="expand" title="放大查看地图">放大</button>
                    </div>
                    <div class="journey-map-floating-days">
                      <button
                        class="journey-map-day-btn active"
                        type="button"
                        data-map-day="all"
                        aria-pressed="true"
                        title="查看整段路线总览"
                      >
                        <span>总览</span>
                        <small>全程</small>
                      </button>
                      ${dayPlans
                        .map(
                          (day, index) => `
                            <button class="journey-map-day-btn" type="button" data-map-day="${escapeHtml(
                              day.key
                            )}" data-map-day-label="${escapeHtml(
                              day.label || `Day ${index + 1}`
                            )}" aria-pressed="false" title="${escapeHtml(
                              `${day.label || `Day ${index + 1}`} · ${Math.max(
                                day.waypoints?.length || 0,
                                day.highlights?.length || 0,
                                1
                              )} 站`
                            )}">
                              <span>${escapeHtml(day.label || `Day ${index + 1}`)}</span>
                              <small>${Math.max(day.waypoints?.length || 0, day.highlights?.length || 0, 1)}站</small>
                            </button>
                          `
                        )
                        .join("")}
                      ${
                        hasDayView
                          ? ""
                          : `<span class="journey-map-passive-pill">日程规划中</span>`
                      }
                    </div>
                    ${
                      hasDayView
                        ? ""
                        : ""
                    }
                    <div class="journey-map-floating-actions">
                      <button class="journey-map-action-btn active" type="button" data-map-action="route" aria-pressed="true" title="聚焦路线主线">路线</button>
                      <button class="journey-map-action-btn" type="button" data-map-action="highlights" aria-pressed="false" title="聚焦沿途景点">景点</button>
                      <button class="journey-map-action-btn" type="button" data-map-action="recommendations" aria-pressed="false" title="显示或隐藏地图推荐点">推荐点</button>
                    </div>
                    <div class="journey-map-floating-actions journey-live-map-styles">
                      <button class="journey-map-style-btn active" type="button" data-map-style="standard" aria-pressed="true" title="标准底图">标准</button>
                      <button class="journey-map-style-btn" type="button" data-map-style="terrain" aria-pressed="false" title="更强调地形层次">地形</button>
                      <button class="journey-map-style-btn" type="button" data-map-style="calm" aria-pressed="false" title="更轻的清爽底图">清爽</button>
                    </div>
                  </div>
                  ${
                    hasLiveMapPayload
                      ? `
                  <div class="journey-live-map" data-map-payload="${mapPayload}">
                    <div class="journey-live-map-state loading">正在准备地图…</div>
                  </div>`
                      : `
                  <div class="journey-live-map journey-live-map--static">
                    <div class="journey-live-map-state">行程路线会在每日安排明确后显示地图。</div>
                  </div>`
                  }
                  <div class="journey-live-map-footer">
                    <div class="journey-live-map-meta">
                      <span class="journey-live-map-meta-label">路线状态</span>
                      <span class="journey-live-map-meta-value">${
                        hasLiveMapPayload ? "定位路线中" : "待补充具体点位"
                      }</span>
                    </div>
                    <div class="journey-map-focus-rail">
                      ${validRouteStops
                        .map(
                          (stop) => `
                            <button class="journey-map-focus-btn" type="button" data-map-focus="${escapeHtml(
                              stop.target
                            )}">
                              ${escapeHtml(stop.label)}
                            </button>
                          `
                        )
                        .join("")}
                      ${
                        highlightCards.length
                          ? '<button class="journey-map-focus-btn" type="button" data-map-focus="highlights">聚焦看点</button>'
                          : ""
                      }
                    </div>
                  </div>
                  ${
                    hasDayView
                      ? `
                          <div class="journey-map-bottom-drawer">
                            <span class="journey-map-bottom-handle"></span>
                            <div class="journey-map-bottom-head">
                              <div>
                                <strong>分日路线</strong>
                                <small>可调顺序，地图即时刷新</small>
                              </div>
                              <button
                                class="journey-map-bottom-toggle journey-map-action-btn secondary"
                                type="button"
                                data-map-action="toggle-bottom-drawer"
                                aria-expanded="true"
                                title="收起分日路线"
                              >
                                收起
                              </button>
                            </div>
                            <div class="journey-map-bottom-days">
                              ${renderJourneyBottomDrawerDays(dayPlans)}
                            </div>
                          </div>
                        `
                      : ""
                  }
                  <div class="journey-poi-bottom-sheet" hidden>
                    <span class="journey-poi-bottom-handle"></span>
                    <button
                      class="journey-poi-bottom-close"
                      type="button"
                      data-poi-sheet-close="true"
                      title="收起地点详情"
                    >
                      ×
                    </button>
                    <figure class="journey-poi-bottom-media">
                      <span>点</span>
                    </figure>
                    <div class="journey-poi-bottom-content">
                      <small data-poi-sheet-meta>地点信息待核验</small>
                      <strong data-poi-sheet-title>地点详情</strong>
                      <p data-poi-sheet-desc>地点介绍待补充。</p>
                      <div class="journey-poi-bottom-meta">
                        <span data-poi-sheet-duration>停留时间待核验</span>
                        <span data-poi-sheet-cost>费用待核验</span>
                      </div>
                      <div class="journey-poi-bottom-proof" data-poi-sheet-proof></div>
                      <em data-poi-sheet-note>开放、预约、票价和道路情况出发前二次核验。</em>
                      <div class="journey-poi-bottom-actions">
                        <button type="button" data-poi-sheet-action="replace">替换这个点</button>
                        <button type="button" data-poi-sheet-action="verify">核验门票交通</button>
                        <button type="button" data-poi-sheet-action="keep">保留继续规划</button>
                      </div>
                    </div>
                  </div>
                  <button class="journey-map-sidebar-open journey-map-action-btn secondary" type="button" data-map-action="toggle-sidebar" aria-expanded="false" title="展开路线说明">展开路线说明</button>
                </div>
                <aside class="journey-map-sidebar">
                  <div class="journey-map-sidebar-toolbar">
                    <span>路线说明</span>
                    <button class="journey-map-sidebar-toggle journey-map-action-btn secondary" type="button" data-map-action="toggle-sidebar" aria-expanded="true" title="收起路线说明">收起路线说明</button>
                  </div>
                  <div class="journey-map-sidebar-card intro">
                    <div class="journey-map-sidebar-head">
                      <span>路线概览</span>
                      <strong>${hasDayView ? `${dayPlans.length} 天` : "总览"}</strong>
                    </div>
                    <div class="journey-map-sidebar-copy">
                      <strong>${escapeHtml(atlasTitle)}</strong>
                      <p>${
                        hasDayView
                          ? "切换到某一天看当天路线，再根据沿途景点继续细化玩法、交通和落脚点。"
                          : "当前显示路线总览，已识别的地点会先汇总在这里。"
                      }</p>
                    </div>
                  </div>
                  ${
                    hasDayView
                      ? `
                          <div class="journey-map-sidebar-card">
                            <div class="journey-map-sidebar-head">
                              <span>当前日程视角</span>
                              <strong class="journey-map-day-insight-title">当前查看总览路线</strong>
                            </div>
                            <p class="journey-map-day-insight-copy">
                              先看整段路线，再切换到某一天查看当天怎么走。
                            </p>
                            <ul class="journey-map-day-insight-points">
                              ${validRouteStops
                                .map(
                                  (stop) => `
                                    <li>
                                      <span>${escapeHtml(stop.label)}</span>
                                      <strong>${escapeHtml(stop.value)}</strong>
                                    </li>
                                  `
                                )
                                .join("")}
                            </ul>
                          </div>
                        `
                      : `
                          <div class="journey-map-sidebar-card compact">
                            <div class="journey-map-sidebar-head">
                              <span>当前日程视角</span>
                              <strong>总览模式</strong>
                            </div>
                            <p class="journey-map-day-insight-copy">
                              当前显示整段路线总览。
                            </p>
                          </div>
                        `
                  }
                  <div class="journey-map-sidebar-card">
                    <div class="journey-map-sidebar-head">
                      <span>关键节点</span>
                      <strong>点一下联动地图</strong>
                    </div>
                    <div class="journey-map-route-list">
                      ${validRouteStops
                        .map(
                          (stop) => `
                            <button
                              class="journey-map-focus-btn journey-map-route-stop"
                              type="button"
                              data-map-focus="${escapeHtml(stop.target)}"
                            >
                              <div class="journey-map-route-stop-head">
                                <span class="journey-stop-label">
                                  <i class="fa-solid ${stop.icon}"></i> ${escapeHtml(stop.label)}
                                </span>
                              </div>
                              <strong class="journey-map-route-stop-value">${escapeHtml(stop.value)}</strong>
                              <span class="journey-map-route-stop-note">${escapeHtml(stop.note)}</span>
                            </button>
                          `
                        )
                        .join("")}
                    </div>
                  </div>
                  ${
                    stayNearbyHighlights.length
                      ? `
                          <div class="journey-map-sidebar-card">
                            <div class="journey-map-sidebar-head">
                              <span>住宿周边</span>
                              <strong>落脚点怎么选</strong>
                            </div>
                            <div class="journey-map-nearby-grid">
                              ${stayNearbyHighlights
                                .map(
                                  (item) => `
                                    <button
                                      class="journey-map-focus-btn journey-map-nearby-card"
                                      type="button"
                                      data-map-focus="highlights"
                                    >
                                      <span><i class="fa-solid ${escapeHtml(item.icon)}"></i>${escapeHtml(
                                        item.label
                                      )}</span>
                                      <strong>${escapeHtml(item.name)}</strong>
                                    </button>
                                  `
                                )
                                .join("")}
                            </div>
                          </div>
                        `
                      : ""
                  }
                  ${
                    highlightCards.length
                      ? `
                          <div class="journey-map-sidebar-card">
                            <div class="journey-map-sidebar-head">
                              <span>沿途看点</span>
                              <strong>点卡片同步定位</strong>
                            </div>
                            <div class="journey-map-highlight-list">
                              ${highlightCards
                                .slice(0, 4)
                                .map(
                                  (item) => `
                                    <button
                                      class="journey-map-focus-btn journey-highlight-card ${
                                        item.index === 0 ? "active" : ""
                                      }"
                                      type="button"
                                      data-map-focus="highlight:${item.index}"
                                      data-highlight-index="${item.index}"
                                    >
                                      <div class="journey-highlight-card-head">
                                        <span class="journey-highlight-card-theme">${escapeHtml(
                                          item.theme
                                        )}</span>
                                        <span class="journey-map-inline-link">地图定位</span>
                                      </div>
                                      <strong>${escapeHtml(item.title)}</strong>
                                      <p>${escapeHtml(item.note)}</p>
                                    </button>
                                  `
                                )
                                .join("")}
                            </div>
                          </div>
                        `
                      : ""
                  }
                </aside>
              </div>
            </div>
          </section>
        `;
      }

      function renderJourneyPreview(previewState) {
        if (!previewState?.shouldRender) {
          return "";
        }
        const {
          cityPair,
          destinationSection,
          transportSection,
          staySection,
          budgetSection,
        } = previewState;
        const previewMetrics = [
          {
            icon: "fa-route",
            label: "主路线",
            value:
              cityPair?.origin && cityPair?.destination
                ? `${cityPair.origin} → ${cityPair.destination}`
                : cityPair?.destination || "待继续确认路线",
          },
          {
            icon: "fa-train-subway",
            label: "优先交通",
            value: transportSection?.title || "待继续比较交通方式",
          },
          {
            icon: "fa-bed",
            label: "落脚节奏",
            value: staySection?.title || "待继续补住宿区域",
          },
          {
            icon: "fa-wallet",
            label: "预算感知",
            value: budgetSection?.title || "后面会继续细化预算",
          },
        ];

        const previewStops = [
          {
            label: "出发",
            icon: "fa-location-crosshairs",
            value: cleanJourneyLocationValue(cityPair?.origin || "待确认出发地"),
            note: cityPair?.origin
              ? "从这里出发，后面我会继续补齐更细的时间和方式。"
              : "告诉我从哪里走，我会把整段路线串得更完整。",
          },
          {
            label: "目的地",
            icon: "fa-map-pin",
            value: cleanJourneyLocationValue(
              cityPair?.destination || destinationSection?.title || "待确认目的地"
            ),
            note: truncateJourneyNote(
              destinationSection?.rawLines?.join(" "),
              "这里会放最值得去的点、适合你的玩法和整体氛围。"
            ),
          },
          {
            label: "交通",
            icon: "fa-train-subway",
            value: cleanJourneyLocationValue(transportSection?.title || "交通待定"),
            note: truncateJourneyNote(
              transportSection?.rawLines?.join(" "),
              "我会继续比较高铁、自驾、航班或其他更合适的方式。"
            ),
          },
          {
            label: "落脚点",
            icon: "fa-bed",
            value: cleanJourneyLocationValue(staySection?.title || "住宿待补充"),
            note: truncateJourneyNote(
              staySection?.rawLines?.join(" "),
              "后面我会把住哪里更省心、更顺路也一起整理进去。"
            ),
          },
        ];
        const atlasHtml = renderJourneyAtlas(
          previewState,
          previewStops,
          previewMetrics
        );

        const isImmersive = previewState.mapExperience === "immersive";
        return `
          <section class="journey-preview-board${
            isImmersive ? " journey-preview-board--immersive" : ""
          }">
            <div class="journey-preview-head">
              <div class="journey-preview-title">
                <strong>路线预览</strong>
                <span>先看整段路线，也可以切换到具体某一天，沿途景点会同步高亮。</span>
              </div>
              <div class="journey-preview-badge">
                <i class="fa-solid fa-map-location-dot"></i> ${
                  isImmersive ? "沉浸地图" : "轻量地图预览"
                }
              </div>
            </div>
            ${atlasHtml}
          </section>
        `;
      }

      function extractJourneyCityPair(text = "") {
        const normalized = (text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return null;
        const cleanRouteCity = (value = "") =>
          sanitizeConversationTitleSegment(value)
            .split(/[！!：:，,。；;、]/)
            .map((part) => part.trim())
            .filter(Boolean)
            .pop()
            ?.replace(/^(行程概览|旅行计划|方案概览|路线|主路线)\s*[：:]?\s*/u, "")
            .trim() || "";

        const labeledOrigin = normalized.match(
          /(?:\u51fa\u53d1\u5730|\u51fa\u53d1)[：:]\s*([^\s，。；、\n]{1,12})/u
        )?.[1];
        const labeledDestination = normalized.match(
          /(?:\u76ee\u7684\u5730|\u76ee\u7684\u5730\u70b9|\u76ee\u7684\u57ce\u5e02)[：:]\s*([^\s，。；、\n]{1,12})/u
        )?.[1];
        if (labeledOrigin || labeledDestination) {
          return {
            origin: sanitizeConversationTitleSegment(labeledOrigin || ""),
            destination: sanitizeConversationTitleSegment(labeledDestination || ""),
          };
        }

        const routeMatch = normalized.match(
          /\u4ece\s*([^\s，。；、]{1,12})\s*(?:\u51fa\u53d1)?\s*(?:\u53bb|\u5230)\s*([^\s，。；、]{1,12})/u
        );
        if (routeMatch) {
          return {
            origin: sanitizeConversationTitleSegment(routeMatch[1]),
            destination: sanitizeConversationTitleSegment(routeMatch[2]),
          };
        }

        const arrowMatch = normalized.match(
          /([^\s，。；、]{1,12})\s*(?:→|->)\s*([^\s，。；、]{1,12})/u
        );
        if (arrowMatch) {
          return {
            origin: cleanRouteCity(arrowMatch[1]),
            destination: cleanRouteCity(arrowMatch[2]),
          };
        }

        return null;
      }

      function extractJourneyPrimaryOrigin(text = "") {
        const normalized = (text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return "";
        return (
          normalized.match(/(?:\u51fa\u53d1\u5730|\u51fa\u53d1)[：:]\s*([^\s，。；、\n]{1,12})/u)?.[1] ||
          normalized.match(/\u4ece\s*([^\s，。；、]{1,12})\s*(?:\u51fa\u53d1|\u53bb|\u5230)/u)?.[1] ||
          ""
        );
      }

      function extractJourneyPrimaryDestination(text = "") {
        const normalized = (text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return "";
        return (
          normalized.match(
            /(?:\u76ee\u7684\u5730|\u76ee\u7684\u5730\u70b9|\u76ee\u7684\u57ce\u5e02)[：:]\s*([^\s，。；、\n]{1,12})/u
          )?.[1] ||
          normalized.match(/(?:\u53bb|\u5230)\s*([^\s，。；、]{1,12})(?:\u65c5\u6e38|\u65c5\u884c|\u6e38\u73a9|\u73a9)?/u)?.[1] ||
          ""
        );
      }

      function buildJourneyPreviewState(summaryBlocks, sections) {
        const summaryText = summaryBlocks.flat().join(" ").replace(/\s+/g, " ").trim();
        const sectionText = sections
          .flatMap((section) => [section.title, ...section.rawLines])
          .join(" ")
          .replace(/\s+/g, " ")
          .trim();
        const combinedText = [summaryText, sectionText].filter(Boolean).join(" ").trim();
        const overviewSection = sections.find((section) => section.tone === "overview");
        const overviewText = overviewSection
          ? [overviewSection.title, ...overviewSection.rawLines].join(" ").replace(/\s+/g, " ").trim()
          : "";
        const conversationTitlePair = extractJourneyCityPairFromConversationTitle(
          getCurrentConversation()?.title || ""
        );
        const cityPair =
          conversationTitlePair ||
          extractJourneyCityPair(summaryText) ||
          extractJourneyCityPair(overviewText) ||
          extractJourneyCityPair(combinedText) ||
          (() => {
            const origin =
              extractJourneyPrimaryOrigin(summaryText) ||
              extractJourneyPrimaryOrigin(overviewText) ||
              extractJourneyPrimaryOrigin(combinedText);
            const destination =
              extractJourneyPrimaryDestination(summaryText) ||
              extractJourneyPrimaryDestination(overviewText) ||
              extractJourneyPrimaryDestination(combinedText);
            return origin || destination ? { origin, destination } : null;
          })();

        const destinationSection =
          overviewSection || {
            tone: "overview",
            title: cityPair?.destination || "待确认目的地",
            rawLines: splitJourneyFragments(summaryText || combinedText).slice(0, 3),
          };
        const transportSection = sections.find((section) => section.tone === "transport");
        const staySection = sections.find((section) => section.tone === "stay");
        const budgetSection = sections.find((section) => section.tone === "budget");
        const highlights = extractJourneyHighlights(sections);
        const highlightCards = buildJourneyHighlightCards(highlights);
        const rhythm = extractJourneyRhythm(summaryBlocks, sections);
        const dayPlans = extractJourneyDayPlans(sections, summaryBlocks);
        const hasClarificationSignal = hasJourneyClarificationSignal(combinedText);
        const hasPlanSignal = hasJourneyPlanSignal(
          combinedText,
          sections,
          highlights,
          rhythm
        );
        const hasConcreteRoutePayload =
          (
            sections.some((section) => section.tone === "transport") ||
            /高铁|火车|自驾|大巴|公交|航班|车程|打车/u.test(combinedText)
          ) &&
          (
            sections.some((section) => ["overview", "stay"].includes(section.tone)) ||
            /住宿|酒店|民宿|景点|玩法|美食/u.test(combinedText)
          );
        const shouldRender =
          (sections.length >= 2 || dayPlans.length >= 1 || hasConcreteRoutePayload) &&
          hasPlanSignal &&
          (!hasClarificationSignal || hasConcreteRoutePayload);

        return {
          combinedText,
          cityPair,
          destinationSection,
          transportSection,
          staySection,
          budgetSection,
          highlights,
          highlightCards,
          rhythm,
          dayPlans,
          shouldRender,
        };
      }

      function shouldRenderJourneyPreviewBlock(previewState = {}, sections = []) {
        if (!previewState?.shouldRender) return false;

        const combinedText = previewState.combinedText || "";
        const tones = new Set(sections.map((section) => section.tone).filter(Boolean));
        const dayCount = previewState.dayPlans?.length || 0;
        const hasDayPlanSignal =
          dayCount >= 2 ||
          /(?:Day\s*\d+|\u7b2c\s*[一二三四五六七八九十\d]+\s*\u5929)/iu.test(
            combinedText
          );
        const hasReportSignal =
          /(?:\u6700\u7ec8|\u5b8c\u6574|\u62a5\u544a|\u6210\u7a3f|\u9884\u7b97\u660e\u7ec6|\u6bcf\u65e5\u884c\u7a0b|\u8def\u7ebf\u56fe|\u5730\u56fe\u8def\u7ebf|\u89c4\u5212\u5b8c\u6210)/u.test(
            combinedText
          );
        const hasStrongClarification =
          hasJourneyClarificationSignal(combinedText) &&
          /[？?]|(?:\u786e\u8ba4|\u8fd8\u662f|\u54ea\u4e2a|\u662f\u5426|\u8981\u4e0d\u8981|\u60f3\u8ddf\u4f60\u786e\u8ba4|\u8865\u5145)/u.test(
            combinedText
          );

        const hasCoreRouteCards =
          tones.has("overview") &&
          tones.has("transport") &&
          (tones.has("stay") || tones.has("schedule") || tones.has("scenic"));
        const hasConcreteRouteCopy =
          /(?:\u4ea4\u901a|\u9ad8\u94c1|\u706b\u8f66|\u822a\u73ed|\u81ea\u9a7e|\u8def\u7ebf)/u.test(
            combinedText
          ) &&
          /(?:\u4f4f\u5bbf|\u9152\u5e97|\u6c11\u5bbf|\u666f\u70b9|\u884c\u7a0b|\u7f8e\u98df)/u.test(
            combinedText
          );

        if (hasStrongClarification && !hasReportSignal) return false;
        if (!hasReportSignal && !hasDayPlanSignal) return false;
        if (hasDayPlanSignal) {
          return dayCount >= 2 || hasReportSignal || hasConcreteRouteCopy;
        }

        return hasReportSignal
          ? hasCoreRouteCards || hasConcreteRouteCopy
          : hasCoreRouteCards && hasConcreteRouteCopy && !hasStrongClarification;
      }

      function hasTravelReportSignal(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return false;
        const hasFinalSignal =
          /(?:最终|完整|成品|报告|个性化旅游规划|旅行方案报告|规划完成)/u.test(
            normalized
          );
        const sectionHits = [
          /(?:行程概览|旅行计划|方案概览|总览)/u,
          /(?:预算明细|费用明细|预算匹配|总预算|人均)/u,
          /(?:每日行程|分日行程|Day\s*\d+|第\s*[一二三四五六七八九十\d]+\s*天)/iu,
          /(?:景点地图|路线地图|地图|路线预览)/u,
          /(?:天气|风险|注意事项|关键假设|贴士)/u,
        ].filter((pattern) => pattern.test(normalized)).length;
        return hasFinalSignal && sectionHits >= 2;
      }

      function getReportSectionMeta(title = "", bodyLines = []) {
        const normalized = normalizeSectionTitle(title);
        const bodyText = bodyLines.join(" ");
        const contains = (...keywords) =>
          keywords.some(
            (keyword) => normalized.includes(keyword) || bodyText.includes(keyword)
          );

        if (looksLikeDecisionPrompt(`${normalized} ${bodyText}`)) {
          return { tone: "next", icon: "fa-circle-question", label: "需要你确认" };
        }
        if (contains("概览", "总览", "旅行计划", "方案", "行程摘要")) {
          return { tone: "overview", icon: "fa-passport", label: "行程概览" };
        }
        if (contains("交付", "核验清单", "用户下一步", "下一步")) {
          return { tone: "handoff", icon: "fa-list-check", label: "交付清单" };
        }
        if (contains("置信度", "待核验", "可追溯", "兜底估算")) {
          return { tone: "budget-confidence", icon: "fa-clipboard-check", label: "预算核验" };
        }
        if (contains("预算", "费用", "花费", "明细", "人均", "总计")) {
          return { tone: "budget", icon: "fa-wallet", label: "预算明细" };
        }
        if (contains("每日", "分日", "Day", "第", "日程")) {
          return { tone: "daily", icon: "fa-calendar-days", label: "每日行程" };
        }
        if (contains("地图", "路线", "景点")) {
          return { tone: "map", icon: "fa-map-location-dot", label: "路线地图" };
        }
        if (contains("交通", "航班", "火车", "高铁", "自驾")) {
          return { tone: "transport", icon: "fa-train-subway", label: "交通住宿" };
        }
        if (contains("住宿", "酒店", "民宿", "落脚")) {
          return { tone: "stay", icon: "fa-bed", label: "交通住宿" };
        }
        if (contains("天气", "风险", "提醒", "注意", "假设", "预约")) {
          return { tone: "warning", icon: "fa-cloud-sun", label: "天气风险" };
        }
        if (contains("美食", "餐饮", "吃")) {
          return { tone: "food", icon: "fa-utensils", label: "美食体验" };
        }
        return getTravelSectionMeta(normalized);
      }

      function extractTravelReportSections(blocks = []) {
        const summaryBlocks = [];
        const sections = [];

        blocks.forEach((block) => {
          const lines = block
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          const firstLine = lines[0];
          const headingCandidate = normalizeSectionTitle(firstLine);
          const inlineMatch = headingCandidate.match(/^([^：:]{2,18})[：:]\s*(.+)$/);
          const sectionTitle = inlineMatch ? inlineMatch[1] : headingCandidate;
          const bodyLines = [
            ...(inlineMatch?.[2] ? [inlineMatch[2].trim()] : []),
            ...lines.slice(1),
          ].filter(Boolean);
          const preliminaryMeta = getReportSectionMeta(sectionTitle, bodyLines);
          const isHeading =
            /^#{1,3}\s+/.test(firstLine) ||
            /^\*\*.+\*\*$/.test(firstLine) ||
            Boolean(inlineMatch) ||
            isEmbeddedSectionHeading(firstLine) ||
            (Boolean(preliminaryMeta) &&
              (/[：:]$/.test(firstLine) || headingCandidate.length <= 18));
          const meta = isHeading ? preliminaryMeta : null;

          if (!meta || !bodyLines.length) {
            summaryBlocks.push(lines);
            return;
          }

          const travelMeta =
            meta.tone === "daily" || meta.tone === "map"
              ? { tone: "overview", icon: meta.icon }
              : { tone: meta.tone, icon: meta.icon };
          sections.push({
            ...travelMeta,
            reportTone: meta.tone,
            reportLabel: meta.label || normalizeSectionTitle(sectionTitle),
            title: normalizeSectionTitle(sectionTitle),
            rawLines: bodyLines,
            bodyHtml: renderReportSectionBody(meta.tone, bodyLines),
          });
        });

        return { summaryBlocks, sections };
      }

      function extractReportExpectedDayCount(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        const digitMatch = normalized.match(/(\d+)\s*天/u);
        if (digitMatch) return Number(digitMatch[1]);
        const chineseMatch = normalized.match(/([一二三四五六七八九十])\s*天/u);
        return chineseMatch ? parseJourneyChineseDayNumber(chineseMatch[1]) : 0;
      }

      function extractReportDayGroups(lines = []) {
        const groups = [];
        let current = null;

        lines.forEach((line) => {
          const normalized = normalizeJourneyDayHeading(line);
          const dayMatch = normalized.match(
            /^(Day\s*\d+|第\s*[一二三四五六七八九十\d]+\s*天)[：:\s-]*(.*)$/iu
          );
          if (dayMatch) {
            current = {
              label: dayMatch[1],
              title: dayMatch[2] || "当天安排",
              lines: [],
            };
            groups.push(current);
            return;
          }
          if (current) {
            current.lines.push(normalized);
          }
        });

        return groups;
      }

      function normalizeReportAmount(value = "") {
        const normalized = String(value || "").replace(/\s+/g, "");
        if (!normalized) return "";
        return normalized.startsWith("¥") ? normalized : normalized.replace(/^￥/, "¥");
      }

      function getBudgetItemMeta(label = "") {
        if (/交通|车票|机票|高铁|火车|航班|打车/u.test(label)) {
          return {
            icon: "fa-train-subway",
            note: "往返大交通、市内换乘或临时打车，出发前还要核验实时票价与余票。",
          };
        }
        if (/住宿|酒店|民宿|客栈|房/u.test(label)) {
          return {
            icon: "fa-bed",
            note: "按晚数、房间数和住宿档位估算，最终以可订房源价格为准。",
          };
        }
        if (/餐|美食|吃|饮/u.test(label)) {
          return {
            icon: "fa-utensils",
            note: "覆盖正餐、特色小吃和咖啡甜品，保留一点弹性更舒服。",
          };
        }
        if (/景点|门票|体验|项目|游船|展馆/u.test(label)) {
          return {
            icon: "fa-ticket",
            note: "含门票、预约项目和体验活动，热门项目建议提前确认。",
          };
        }
        if (/服务|预留|机动|缓冲/u.test(label)) {
          return {
            icon: "fa-shield-heart",
            note: "覆盖市内交通、寄存、临时休息和价格波动缓冲。",
          };
        }
        if (/人均/u.test(label)) {
          return {
            icon: "fa-user-group",
            note: "按当前人数均摊后的参考值，方便判断预算压力。",
            featured: true,
          };
        }
        if (/总计|合计|总预算|总额|预算/u.test(label)) {
          return {
            icon: "fa-calculator",
            note: "当前方案的总预算估算，后续改交通或住宿会同步变化。",
            featured: true,
          };
        }
        return {
          icon: "fa-wallet",
          note: "机动费用、寄存、临时休息和其他小额弹性支出。",
        };
      }

      function extractReportBudgetItems(lines = [], combinedText = "") {
        const source = [lines.join(" "), combinedText].filter(Boolean).join(" ");
        const normalized = source.replace(/\s+/g, " ");
        const pattern =
          /(交通|大交通|市内交通|住宿|酒店|民宿|餐饮|美食|吃饭|景点体验|景点|门票|体验|服务\/预留|服务|预留|其他|机动|总计|合计|总预算|预算)[：:\s|，,、]*([¥￥]?\s*\d[\d,.]*\s*元?)/gu;
        const picked = [];
        const seen = new Set();
        let match;
        while ((match = pattern.exec(normalized))) {
          const label = match[1].replace(/预算$/, "总计");
          const amount = normalizeReportAmount(match[2]);
          const key = `${label}-${amount}`;
          if (!amount || seen.has(key)) continue;
          seen.add(key);
          picked.push({
            label,
            amount,
            ...getBudgetItemMeta(label),
          });
        }
        return picked.slice(0, 8);
      }

      function renderReportBudgetBreakdown(lines = [], combinedText = "") {
        const items = extractReportBudgetItems(lines, combinedText);
        if (!items.length) {
          return renderAssistantLines(lines);
        }

        return `
          <div class="travel-report-budget-grid">
            ${items
              .map(
                (item) => `
                  <article class="travel-report-budget-item ${
                    item.featured ? "featured" : ""
                  }">
                    <div class="travel-report-budget-icon">
                      <i class="fa-solid ${item.icon}"></i>
                    </div>
                    <div>
                      <span>${escapeHtml(item.label)}</span>
                      <strong>${escapeHtml(item.amount)}</strong>
                      <p>${escapeHtml(item.note)}</p>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>
        `;
      }

      function getReportRouteWaypoints(day = {}, fallback = {}) {
        const waypoints = Array.isArray(day.waypoints) ? day.waypoints : [];
        const cleaned = waypoints
          .map((item) => cleanJourneyLocationValue(item))
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index);
        if (cleaned.length >= 2) return cleaned.slice(0, 6);
        return [
          fallback.origin,
          ...(cleaned.length ? cleaned : []),
          fallback.destination,
        ]
          .map((item) => cleanJourneyLocationValue(item || ""))
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
      }

      function renderReportRouteSketch(waypoints = [], label = "当天路线") {
        const points = [
          [18, 72],
          [34, 42],
          [50, 58],
          [66, 30],
          [82, 46],
          [88, 22],
        ];
        const picked = waypoints.slice(0, points.length);
        if (!picked.length) {
          return `
            <div class="travel-report-route-sketch empty">
              <div class="travel-report-route-empty">这一天的路线点还没被识别出来，后续补齐完整日程后会形成静态路线图。</div>
            </div>
          `;
        }
        const svgPoints = picked
          .map((_, index) => `${points[index][0]},${points[index][1]}`)
          .join(" ");
        return `
          <div class="travel-report-route-sketch" aria-label="${escapeHtml(label)}">
            <svg viewBox="0 0 100 82" preserveAspectRatio="none" aria-hidden="true">
              <polyline points="${svgPoints}" fill="none" stroke="#24a6a1" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            ${picked
              .map((point, index) => {
                const [x, y] = points[index];
                return `
                  <div class="travel-report-route-node" style="--x:${x}%; --y:${y}%;">
                    <span>${index + 1}</span>
                    <strong>${escapeHtml(point)}</strong>
                  </div>
                `;
              })
              .join("")}
          </div>
        `;
      }

      function getReportDataFromOptions(options = {}) {
        return (
          options.reportData ||
          options.extraInfo?.report_data ||
          options.extra_info?.report_data ||
          null
        );
      }

      function getJourneyDataFromOptions(options = {}) {
        return (
          options.journeyData ||
          options.extraInfo?.journey_data ||
          options.extra_info?.journey_data ||
          null
        );
      }

      function getPlanningTraceFromOptions(options = {}) {
        const trace =
          options.planningTrace ||
          options.extraInfo?.planning_trace ||
          options.extra_info?.planning_trace ||
          [];
        return Array.isArray(trace) ? trace : [];
      }

      function isVisualJourneyData(journeyData) {
        return (
          journeyData &&
          typeof journeyData === "object" &&
          journeyData.version === "journey_plan.v1" &&
          Array.isArray(journeyData.days)
        );
      }

      function isStructuredTravelReportData(reportData) {
        return (
          reportData &&
          typeof reportData === "object" &&
          reportData.version === "travel_report.v1" &&
          reportData.overview
        );
      }

      function formatReportDataMoney(value) {
        if (typeof value !== "number" || Number.isNaN(value)) return "";
        return `${Math.round(value).toLocaleString("zh-CN")} 元`;
      }

      function renderReportDataList(items = [], emptyText = "待补充") {
        const list = (Array.isArray(items) ? items : [])
          .map((item) => String(item || "").trim())
          .filter(Boolean);
        if (!list.length) return `<p>${escapeHtml(emptyText)}</p>`;
        return `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
      }

      function normalizeReportDataList(items = []) {
        return (Array.isArray(items) ? items : [])
          .map((item) => String(item || "").trim())
          .filter(Boolean);
      }

      const REPORT_BUDGET_GROUPS = [
        { key: "transport", label: "交通", icon: "fa-train-subway" },
        { key: "accommodation", label: "住宿", icon: "fa-bed" },
        { key: "food", label: "餐饮", icon: "fa-utensils" },
        { key: "attractions", label: "景点/体验", icon: "fa-ticket" },
        { key: "service_reserve", label: "服务/预留", icon: "fa-shield-heart" },
        { key: "other", label: "其他", icon: "fa-wallet" },
      ];

      function reportBudgetGroupKey(item = {}) {
        const source = `${item.key || item.category || ""} ${item.label || ""}`.toLowerCase();
        if (/transport|traffic|交通|高铁|航班|机票|火车/.test(source)) return "transport";
        if (/accommodation|hotel|lodging|住宿|酒店|民宿|房/.test(source)) return "accommodation";
        if (/food|dining|meal|餐|美食|小吃/.test(source)) return "food";
        if (/attraction|scenic|sight|experience|景点|门票|体验|游船/.test(source)) return "attractions";
        if (/service|reserve|contingency|buffer|misc|服务|预留|机动/.test(source)) return "service_reserve";
        return "other";
      }

      function normalizeReportBudgetItems(budget = {}) {
        const grouped = new Map(
          REPORT_BUDGET_GROUPS.map((group) => [
            group.key,
            {
              ...group,
              amount: 0,
              basis: "",
              confidence: "",
            },
          ])
        );
        (Array.isArray(budget.items) ? budget.items : []).forEach((item) => {
          if (!item || typeof item !== "object") return;
          const group = grouped.get(reportBudgetGroupKey(item)) || grouped.get("other");
          if (typeof item.amount === "number" && !Number.isNaN(item.amount)) {
            group.amount += item.amount;
          }
          if (item.basis && !group.basis) group.basis = String(item.basis);
          if (item.confidence && !group.confidence) group.confidence = String(item.confidence);
        });

        const fieldFallbacks = {
          transport: "transport",
          accommodation: "accommodation",
          food: "food",
          attractions: "attractions",
          service_reserve: budget.service_reserve !== undefined ? "service_reserve" : "misc",
          other: "other",
        };
        Object.entries(fieldFallbacks).forEach(([groupKey, budgetKey]) => {
          const group = grouped.get(groupKey);
          const value = budget[budgetKey];
          if (group && !group.amount && typeof value === "number" && !Number.isNaN(value)) {
            group.amount = value;
          }
        });

        const defaults = {
          transport: "交通票价、余票和退改签规则需在正式预订前复核。",
          accommodation: "住宿按区域、房型、晚数和取消政策估算。",
          food: "餐饮按用餐偏好、餐次和热门餐厅排队情况估算。",
          attractions: "景点/体验按门票、预约项目和临时展览收费估算。",
          service_reserve: "覆盖市内交通、寄存、临时休息和价格波动缓冲。",
          other: "个人购物、伴手礼和临时加项按实际发生处理。",
        };
        return REPORT_BUDGET_GROUPS.map((group) => {
          const item = grouped.get(group.key);
          return {
            ...item,
            basis: item.basis || defaults[group.key],
            confidence: item.confidence || "待核验",
          };
        });
      }

      function parseReportDataExpectedDays(reportData = {}) {
        const duration = String(reportData.overview?.duration || "");
        const digitMatch = duration.match(/(\d+)\s*天/u);
        const chineseMatch = duration.match(/([一二三四五六七八九十])\s*天/u);
        const parsed = digitMatch
          ? Number(digitMatch[1])
          : chineseMatch
          ? parseJourneyChineseDayNumber(chineseMatch[1])
          : 0;
        const itineraryDays = Array.isArray(reportData.itinerary)
          ? reportData.itinerary.map((day) => Number(day.day_number || day.day || 0))
          : [];
        const routeDays = Array.isArray(reportData.map_routes)
          ? reportData.map_routes.map((route) => Number(route.day_number || route.day || 0))
          : [];
        const routeMapDays = Array.isArray(reportData.route_map?.days)
          ? reportData.route_map.days.map((day) => Number(day.day_number || day.day || 0))
          : [];
        return Math.max(parsed, ...itineraryDays, ...routeDays, ...routeMapDays, 0);
      }

      function routePointName(point = "") {
        if (point && typeof point === "object") {
          return String(point.name || point.label || point.title || "").trim();
        }
        return String(point || "").trim();
      }

      function normalizeRouteMapDayPoints(routeMapDay = {}, route = {}) {
        const typedPoints = Array.isArray(routeMapDay.points) ? routeMapDay.points : [];
        if (typedPoints.length) {
          return typedPoints
            .map((point) => ({
              name: routePointName(point),
              typeLabel: point.type_label || point.type || "路线点",
              description: point.description || point.note || "",
            }))
            .filter((point) => point.name);
        }
        return normalizeReportDataList(routeMapDay.route_points || route.route_points || []).map(
          (name) => ({
            name,
            typeLabel: "路线点",
            description: "当天路线节点，后续可继续细化停留时间。",
          })
        );
      }

      function buildReportDataJourneyPreviewState(reportData = {}) {
        const overview = reportData.overview || {};
        const routeLabel = overview.route_label || "路线总览";
        const routes = Array.isArray(reportData.map_routes) ? reportData.map_routes : [];
        const routeMapDays = Array.isArray(reportData.route_map?.days)
          ? reportData.route_map.days
          : [];
        const dailyRoutes = routeMapDays.length
          ? routeMapDays
          : routes.map((route) => ({
              day_number: route.day_number,
              summary: route.summary,
              route_points: route.route_points || [],
              points: [],
            }));
        const dayPlans = dailyRoutes
          .map((routeDay, index) => {
            const matchedRoute =
              routes.find(
                (route) =>
                  Number(route.day_number || 0) === Number(routeDay.day_number || 0)
              ) || {};
            const points = normalizeRouteMapDayPoints(routeDay, matchedRoute)
              .map((point) => cleanJourneyLocationValue(point.name || ""))
              .filter(Boolean);
            if (!points.length) return null;
            const dayNumber = Number(routeDay.day_number || matchedRoute.day_number || index + 1);
            return {
              key: `report-day-${dayNumber}`,
              dayNumber,
              label: `Day ${dayNumber}`,
              title: routeDay.summary || matchedRoute.summary || `Day ${dayNumber}`,
              waypoints: points,
              highlights: points.slice(0, 3),
              note: routeDay.summary || matchedRoute.summary || points.join(" → "),
            };
          })
          .filter(Boolean)
          .sort((left, right) => left.dayNumber - right.dayNumber);
        const allWaypoints = dayPlans
          .flatMap((day) => day.waypoints || [])
          .filter((item, index, list) => item && list.indexOf(item) === index);
        if (!allWaypoints.length) return { shouldRender: false };

        const cityPair =
          extractJourneyCityPair(routeLabel) ||
          (allWaypoints.length >= 2
            ? {
                origin: allWaypoints[0],
                destination: allWaypoints[allWaypoints.length - 1],
              }
            : { origin: "", destination: allWaypoints[0] || routeLabel });
        return {
          combinedText: [
            routeLabel,
            reportData.transport?.summary,
            reportData.accommodation?.summary,
            allWaypoints.join(" "),
          ]
            .filter(Boolean)
            .join(" "),
          cityPair,
          destinationSection: {
            tone: "overview",
            title: routeLabel,
            rawLines: [
              overview.duration ? `行程天数：${overview.duration}` : "",
              overview.people ? `出行人数：${overview.people}` : "",
              ...(overview.travel_styles || []),
            ].filter(Boolean),
          },
          transportSection: {
            tone: "transport",
            title: reportData.transport?.summary || "交通待核验",
            rawLines: [reportData.transport?.summary || ""].filter(Boolean),
          },
          staySection: {
            tone: "stay",
            title: reportData.accommodation?.summary || "住宿待核验",
            rawLines: [reportData.accommodation?.summary || ""].filter(Boolean),
          },
          budgetSection: {
            tone: "budget",
            title: formatReportDataMoney(reportData.budget?.total) || "预算待核验",
            rawLines: [],
          },
          highlights: allWaypoints.slice(1, 5),
          highlightCards: buildJourneyHighlightCards(allWaypoints.slice(1, 5)),
          rhythm: dayPlans.map((day) => day.note).slice(0, 3),
          dayPlans,
          shouldRender: true,
        };
      }

      function renderReportRoutePointChips(points = []) {
        if (!points.length) return "";
        return `
          <div class="travel-report-route-point-chips">
            ${points
              .slice(0, 6)
              .map(
                (point) => `
                  <span class="travel-report-route-point-chip">
                    <strong>${escapeHtml(point.typeLabel || "路线点")}</strong>
                    ${escapeHtml(point.name)}
                  </span>
                `
              )
              .join("")}
          </div>
        `;
      }

      function getReportPlanningModeMeta(reportData = {}) {
        const mode = reportData.agency_context?.mode || "";
        if (mode === "agency_plan") {
          return {
            mode,
            label: "省心方案",
            shortLabel: "省心方案",
            icon: "fa-user-tie",
            tone: "agency",
            copy:
              "按成熟路线、服务节点、费用依据和出发前核验项组织。",
          };
        }
        if (mode === "free_planning") {
          return {
            mode,
            label: "个性化旅游规划",
            shortLabel: "个性化规划",
            icon: "fa-route",
            tone: "free",
            copy:
              "按你的偏好呈现路线、预算依据和风险提醒。",
          };
        }
        return {
          mode: "unknown",
          label: "规划方案",
          shortLabel: "规划方案",
          icon: "fa-compass",
          tone: "neutral",
          copy: "已按当前结构化信息整理路线、预算和后续核验项。",
        };
      }

      function getBudgetConfidenceTone(level = "") {
        const normalized = String(level || "").trim();
        if (/高|中高/.test(normalized)) return "strong";
        if (/中/.test(normalized)) return "medium";
        if (/低|待/.test(normalized)) return "caution";
        return "neutral";
      }

      function buildReportDataViewModel(reportData = {}) {
        const budgetConfidence = reportData.budget_confidence || {};
        const toolAudit = reportData.tool_audit_summary || {};
        const agencyContext = reportData.agency_context || {};
        const approval =
          toolAudit.approval ||
          reportData.evidence_bundle?.approval_governance ||
          {};
        const pendingChecks = normalizeReportDataList([
          ...normalizeReportDataList(budgetConfidence.verification_items),
          ...normalizeReportDataList(toolAudit.pending_checks),
        ]).filter((item, index, list) => list.indexOf(item) === index);

        return {
          mode: getReportPlanningModeMeta(reportData),
          budgetConfidence: {
            level: budgetConfidence.level || "待评估",
            tone: getBudgetConfidenceTone(budgetConfidence.level),
            confirmedItems: normalizeReportDataList(budgetConfidence.confirmed_items),
            estimatedItems: normalizeReportDataList(budgetConfidence.estimated_items),
            verificationItems: normalizeReportDataList(
              budgetConfidence.verification_items
            ),
          },
          handoff: {
            readiness: toolAudit.readiness || "可交付，预订前需核验",
            usedSources: normalizeReportDataList(toolAudit.used_sources),
            pendingChecks,
            unsupportedActions: normalizeReportDataList(toolAudit.unsupported_actions),
            toolEvents: Array.isArray(toolAudit.events) ? toolAudit.events : [],
          },
          approval: {
            approvalId: String(approval.approval_id || "").trim(),
            action: String(approval.action || "generate_order_id").trim(),
            status: String(approval.status || "none").trim(),
            pending: Boolean(approval.pending),
            requiresApproval: Boolean(approval.requires_approval),
            isBlocking: Boolean(approval.is_blocking),
            recordOnly: approval.record_only !== false,
            expiresAt: approval.expires_at || null,
            reason: String(approval.reason || "").trim(),
            boundary:
              String(approval.boundary || "").trim() ||
              "当前报告不代表真实支付、真实预订、真实锁价或履约成功。",
            unsupportedWithoutIntegration: normalizeReportDataList(
              approval.unsupported_without_integration
            ),
          },
          agency: {
            summary: String(agencyContext.summary || "").trim(),
            highlights: normalizeReportDataList(agencyContext.highlights),
            modeReason: String(agencyContext.mode_reason || "").trim(),
          },
        };
      }

      function renderReportDataInsightGroup({
        title = "",
        items = [],
        emptyText = "待补充",
        icon = "fa-circle-check",
        tone = "",
      } = {}) {
        const list = normalizeReportDataList(items);
        return `
          <div class="travel-report-insight-group ${tone}">
            <div class="travel-report-insight-group-head">
              <i class="fa-solid ${escapeHtml(icon)}"></i>
              <span>${escapeHtml(title)}</span>
            </div>
            ${
              list.length
                ? `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
                : `<p>${escapeHtml(emptyText)}</p>`
            }
          </div>
        `;
      }

      function renderReportDataBudgetConfidence(viewModel) {
        const confidence = viewModel.budgetConfidence;
        return `
          <div class="travel-report-confidence travel-report-confidence--${escapeHtml(
            confidence.tone
          )}">
            <div class="travel-report-confidence-head">
              <span>预算置信度</span>
              <strong>${escapeHtml(confidence.level)}</strong>
              <p>把已确认价格、规则估算和出发前需要复核的项目分开看，避免把估算误当成锁价。</p>
            </div>
            <div class="travel-report-insight-grid">
              ${renderReportDataInsightGroup({
                title: "已确认 / 可追溯",
                items: confidence.confirmedItems,
                emptyText: "暂无已确认价格，正式预订前都需要二次核验。",
                icon: "fa-circle-check",
                tone: "confirmed",
              })}
              ${renderReportDataInsightGroup({
                title: "规则估算",
                items: confidence.estimatedItems,
                emptyText: "暂无估算项。",
                icon: "fa-calculator",
                tone: "estimated",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验",
                items: confidence.verificationItems,
                emptyText: "正式预订或出发前复核票价、酒店、景点开放和天气。",
                icon: "fa-clipboard-check",
                tone: "verification",
              })}
            </div>
          </div>
        `;
      }

      function renderReportDataHandoffPanel(viewModel) {
        return `
          <div class="travel-report-handoff">
            <div class="travel-report-handoff-status">
              <span>交付状态</span>
              <strong>${escapeHtml(viewModel.handoff.readiness)}</strong>
            </div>
            <div class="travel-report-insight-grid compact">
              ${renderReportDataInsightGroup({
                title: "已用依据",
                items: viewModel.handoff.usedSources,
                emptyText: "来源摘要待补充。",
                icon: "fa-file-shield",
                tone: "sources",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验清单",
                items: viewModel.handoff.pendingChecks,
                emptyText: "暂无额外待核验项。",
                icon: "fa-list-check",
                tone: "verification",
              })}
              ${renderReportDataInsightGroup({
                title: "不支持承诺",
                items: viewModel.handoff.unsupportedActions,
                emptyText: "暂无额外限制说明。",
                icon: "fa-ban",
                tone: "unsupported",
              })}
            </div>
          </div>
        `;
      }

      function renderReportDataGovernancePanel(viewModel) {
        const approval = viewModel.approval || {};
        const unsupported = [
          "不接真实支付，不生成支付链接。",
          "不接真实预订、短信、客服或供应链下单。",
          "不承诺真实库存、真实锁价或履约成功。",
          ...normalizeReportDataList(approval.unsupportedWithoutIntegration),
        ].filter((item, index, list) => list.indexOf(item) === index);
        const statusText = approval.requiresApproval
          ? approval.pending
            ? "等待人工确认"
            : getStatusLabel(approval.status)
          : "边界记录";
        return `
          <div class="travel-report-governance">
            <div class="travel-report-governance-status">
              <div>
                <span>确认状态</span>
                <strong>${escapeHtml(statusText)}</strong>
              </div>
              <div>
                <span>动作</span>
                <strong>${escapeHtml(approval.action || "需确认动作")}</strong>
              </div>
              <div>
                <span>阻塞</span>
                <strong>${approval.isBlocking ? "阻塞真实动作" : "当前不阻塞报告交付"}</strong>
              </div>
            </div>
            <div class="travel-report-governance-boundary">
              <strong>确认边界</strong>
              <p>${escapeHtml(approval.boundary)}</p>
              ${renderReportDataList(unsupported, "暂无额外不可承诺项。")}
            </div>
          </div>
        `;
      }

      function renderReportDataBudgetItems(budget = {}) {
        const items = normalizeReportBudgetItems(budget);
        const total = formatReportDataMoney(budget.total);

        return `
          <div class="travel-report-budget-table-wrap">
            <table class="travel-report-budget-table">
              <thead>
                <tr>
                  <th>类别</th>
                  <th>金额</th>
                  <th>依据</th>
                </tr>
              </thead>
              <tbody>
                ${items
                  .map(
                    (item) => `
                      <tr>
                        <th scope="row">
                          <i class="fa-solid ${escapeHtml(item.icon || "fa-wallet")}"></i>
                          ${escapeHtml(item.label || "预算项")}
                        </th>
                        <td>${escapeHtml(formatReportDataMoney(item.amount) || "待核验")}</td>
                        <td>${escapeHtml(item.basis || "出发前需要二次核验")}</td>
                      </tr>
                    `
                  )
                  .join("")}
              </tbody>
            </table>
            <div class="travel-report-budget-total-line">
              <span>当前估算合计</span>
              <strong>${escapeHtml(total || "待核验")}</strong>
            </div>
            ${budget.fit ? `<p class="travel-report-budget-fit">${escapeHtml(budget.fit)}</p>` : ""}
          </div>
        `;
      }

      function isPlaceholderReportDay(day = {}) {
        const text = [
          day.title,
          day.theme,
          day.route_summary,
          ...(Array.isArray(day.time_blocks) ? day.time_blocks : []),
          ...(Array.isArray(day.risk_notes) ? day.risk_notes : []),
        ]
          .filter(Boolean)
          .join(" ");
        return (
          day.missing ||
          /待补齐当天安排|这一天还没有|待补齐路线|路线补齐\s*Day|行程明细待补充|地图路线补齐/u.test(
            text
          )
        );
      }

      function renderReportDailyNotReadyState() {
        return `
          <div class="travel-report-empty-state">
            <strong>正式每日行程尚未生成</strong>
            <p>请先确认出发城市和出发日期，再生成可交付报告；我会把每天玩法、餐饮、住宿和动线补齐后再展示这里。</p>
          </div>
        `;
      }

      function renderReportDataDailyItinerary(
        days = [],
        mapRoutes = [],
        routeMap = {},
        expectedDayCount = 0
      ) {
        const safeDays = (Array.isArray(days) ? days : []).filter(
          (day) => !isPlaceholderReportDay(day)
        );
        const safeRoutes = Array.isArray(mapRoutes) ? mapRoutes : [];
        const routeMapDays = Array.isArray(routeMap?.days) ? routeMap.days : [];
        if (!safeDays.length) return renderReportDailyNotReadyState();
        const routeByDay = new Map(
          safeRoutes.map((route) => [
            Number(route.day_number || route.day || 0),
            route,
          ])
        );
        const routeMapByDay = new Map(
          routeMapDays.map((day) => [Number(day.day_number || day.day || 0), day])
        );
        const dayByNumber = new Map(
          safeDays.map((day, index) => [
            Number(day.day_number || day.day || index + 1),
            day,
          ])
        );
        const entries = safeDays
          .map((day, index) => ({
            ...day,
            day_number: Number(day.day_number || day.day || index + 1),
            missing: false,
          }))
          .sort((left, right) => Number(left.day_number || 0) - Number(right.day_number || 0));

        return `
          <div class="travel-report-days">
            ${entries
              .map((day) => {
                const route = routeByDay.get(Number(day.day_number || 0)) || day.route || {};
                const routeMapDay = routeMapByDay.get(Number(day.day_number || 0)) || {};
                const routeSummary =
                  routeMapDay.summary ||
                  route.summary ||
                  day.route?.summary ||
                  day.route_summary ||
                  "";
                const routePoints = normalizeRouteMapDayPoints(routeMapDay, route);
                const timeBlocks = Array.isArray(day.time_blocks)
                  ? day.time_blocks
                  : [];
                const meals = Array.isArray(day.meals) ? day.meals : [];
                const riskNotes = Array.isArray(day.risk_notes)
                  ? day.risk_notes
                  : [];
                return `
                  <article class="travel-report-day ${day.missing ? "missing" : ""}">
                    <div class="travel-report-day-badge">Day ${escapeHtml(
                      day.day_number || ""
                    )}</div>
                    <div class="travel-report-day-main">
                      <h5>${escapeHtml(day.title || "当天安排")}</h5>
                      ${
                        routeSummary
                          ? `<p class="travel-report-route-line">${escapeHtml(
                              routeSummary
                            )}</p>`
                          : ""
                      }
                      ${renderReportDataList(timeBlocks.slice(0, 4), "当天时段待补充")}
                      ${
                        meals.length
                          ? `<p><strong>餐饮：</strong>${escapeHtml(
                              meals.slice(0, 3).join("；")
                            )}</p>`
                          : ""
                      }
                      ${
                        day.plan_b
                          ? `<p><strong>Plan B：</strong>${escapeHtml(day.plan_b)}</p>`
                          : ""
                      }
                      ${
                        riskNotes.length
                          ? `<p><strong>当天提醒：</strong>${escapeHtml(
                              riskNotes.slice(0, 2).join("；")
                            )}</p>`
                          : ""
                      }
                    </div>
                    <div class="travel-report-day-map">
                      <div class="travel-report-day-map-head">
                        <span>${escapeHtml(day.missing ? "待补齐路线" : "分日路线")}</span>
                        <strong>${escapeHtml(
                          routeMapDay.summary || route.summary || routeSummary || "路线待核验"
                        )}</strong>
                      </div>
                      ${renderReportRouteSketch(
                        routePoints.map((point) => point.name),
                        `Day ${day.day_number || ""}`
                      )}
                      ${renderReportRoutePointChips(routePoints)}
                    </div>
                  </article>
                `;
              })
              .join("")}
          </div>
        `;
      }

      function renderReportDataMapDigest(reportData = {}) {
        const previewState = buildReportDataJourneyPreviewState(reportData);
        if (!previewState.shouldRender) return "";
        return renderJourneyPreview(previewState);
      }

      function renderReportDataCard({
        tone = "summary",
        icon = "fa-file-lines",
        label = "",
        title = "",
        body = "",
      }) {
        return `
          <section class="travel-report-card ${tone}">
            <div class="travel-report-card-head">
              <span class="travel-report-card-icon">
                <i class="fa-solid ${icon}"></i>
              </span>
              <div>
                <div class="travel-report-card-label">${escapeHtml(label || title)}</div>
                <h4>${escapeHtml(title)}</h4>
              </div>
            </div>
            <div class="travel-report-card-body">${body}</div>
          </section>
        `;
      }

      function renderTravelReportFromData(reportData, options = {}) {
        if (!isStructuredTravelReportData(reportData)) return null;

        const viewMode = options.view || reportData.default_view || "customer";
        const showAdvisorSections = viewMode === "advisor" || viewMode === "debug";
        const overview = reportData.overview || {};
        const budget = reportData.budget || {};
        const viewModel = buildReportDataViewModel(reportData);
        const routeLabel = overview.route_label || "专属旅程";
        const dayCount = overview.duration || "分日规划";
        const expectedDayCount = parseReportDataExpectedDays(reportData);
        const budgetLabel =
          formatReportDataMoney(budget.total) ||
          reportData.budget_confidence?.level ||
          "预算已估算";
        const mapDigest = !options?.suppressJourneyPreview
          ? renderReportDataMapDigest(reportData)
          : "";

        return `
          <div class="travel-report travel-report--${escapeHtml(
            viewModel.mode.tone
          )}" data-report-source="structured" data-planning-mode="${escapeHtml(
            viewModel.mode.mode
          )}">
            <div class="travel-report-hero">
              <div class="travel-report-kicker">
                <i class="fa-solid ${escapeHtml(viewModel.mode.icon)}"></i>
                ${escapeHtml(viewModel.mode.label)}
              </div>
              <h3>${escapeHtml(routeLabel)}</h3>
              <p>${escapeHtml(viewModel.mode.copy)}</p>
              <div class="travel-report-metrics">
                <span><i class="fa-solid ${escapeHtml(
                  viewModel.mode.icon
                )}"></i>${escapeHtml(viewModel.mode.shortLabel)}</span>
                <span><i class="fa-solid fa-route"></i>${escapeHtml(routeLabel)}</span>
                <span><i class="fa-regular fa-calendar"></i>${escapeHtml(dayCount)}</span>
                <span><i class="fa-solid fa-wallet"></i>${escapeHtml(budgetLabel)}</span>
              </div>
              <div class="travel-report-actions">
                <button type="button" data-report-action="tweak">
                  <i class="fa-solid fa-pen-nib"></i> 继续微调
                </button>
                <button type="button" data-report-action="map">
                  <i class="fa-solid fa-map-location-dot"></i> 查看路线地图
                </button>
                <button type="button" data-report-action="export">
                  <i class="fa-solid fa-file-export"></i> 导出报告
                </button>
              </div>
            </div>
            <div class="travel-report-grid">
              ${renderReportDataCard({
                tone: "summary",
                icon: "fa-compass",
                label: "行程概览",
                title: "你的旅行骨架",
                body: renderReportDataList([
                  overview.people ? `出行人数：${overview.people}` : "",
                  overview.travel_styles?.length
                    ? `主题偏好：${overview.travel_styles.join("、")}`
                    : "",
                  overview.special_needs
                    ? `特殊需求：${overview.special_needs}`
                    : "",
                ]),
              })}
              ${renderReportDataCard({
                tone: "transport",
                icon: "fa-train-subway",
                label: "交通与住宿",
                title: "出行与落脚建议",
                body: renderReportDataList([
                  reportData.transport?.summary
                    ? `交通：${reportData.transport.summary}`
                    : "",
                  reportData.accommodation?.summary
                    ? `住宿：${reportData.accommodation.summary}`
                    : "",
                  reportData.food_preferences?.summary
                    ? `餐饮：${reportData.food_preferences.summary}`
                    : "",
                ]),
              })}
              ${renderReportDataCard({
                tone: "daily",
                icon: "fa-calendar-days",
                label: "每日行程",
                title: "按天执行",
                body: renderReportDataDailyItinerary(
                  reportData.itinerary,
                  reportData.map_routes,
                  reportData.route_map,
                  expectedDayCount
                ),
              })}
              ${renderReportDataCard({
                tone: "budget",
                icon: "fa-wallet",
                label: "费用拆分",
                title: "预算明细与依据",
                body: renderReportDataBudgetItems(budget),
              })}
              ${renderReportDataCard({
                tone: "warning",
                icon: "fa-triangle-exclamation",
                label: "风险提醒",
                title: "重要提醒",
                body: `
                  ${renderReportDataList(reportData.risks, "风险提醒待补充")}
                `,
              })}
              ${renderReportDataCard({
                tone: "summary",
                icon: "fa-shield-heart",
                label: "方案依据",
                title:
                  viewModel.mode.mode === "free_planning"
                    ? "规划依据与执行提醒"
                    : "服务标准与交付依据",
                body: renderReportDataList([
                  viewModel.agency.summary || "",
                  viewModel.agency.modeReason
                    ? `模式依据：${viewModel.agency.modeReason}`
                    : "",
                  ...viewModel.agency.highlights,
                ]),
              })}
              ${
                showAdvisorSections
                  ? `
                    ${renderReportDataCard({
                      tone: "confidence",
                      icon: "fa-gauge-high",
                      label: "预算核验",
                      title: "置信度与价格边界",
                      body: renderReportDataBudgetConfidence(viewModel),
                    })}
                    ${renderReportDataCard({
                      tone: "handoff",
                      icon: "fa-list-check",
                      label: "交付清单",
                      title: "顾问核验与下一步",
                      body: renderReportDataHandoffPanel(viewModel),
                    })}
                    ${renderReportDataCard({
                      tone: "governance",
                      icon: "fa-shield-halved",
                      label: "治理边界",
                      title: "人工确认与不可承诺项",
                      body: renderReportDataGovernancePanel(viewModel),
                    })}
                  `
                  : ""
              }
            </div>
            ${mapDigest ? `<div class="travel-report-map">${mapDigest}</div>` : ""}
          </div>
        `;
      }

      function buildReportDayEntries(lines = [], previewState = {}, expectedDayCount = 0) {
        const groups = extractReportDayGroups(lines);
        const planMap = new Map(
          (previewState.dayPlans || []).map((plan) => [plan.dayNumber, plan])
        );
        const entries = [];
        groups.forEach((group, index) => {
          const dayNumber =
            parseJourneyDayNumber(group.label) ||
            parseJourneyDayNumber(group.title) ||
            index + 1;
          const plan = planMap.get(dayNumber);
          entries.push({
            ...group,
            dayNumber,
            label: `Day ${dayNumber}`,
            title: group.title || plan?.title || "当天安排",
            lines: group.lines,
            plan,
            missing: false,
          });
        });

        return entries.sort((left, right) => left.dayNumber - right.dayNumber);
      }

      function renderReportDayTimeline(lines = [], options = {}) {
        const { previewState = {}, expectedDayCount = 0, routeLabel = "" } = options;
        const entries = buildReportDayEntries(lines, previewState, expectedDayCount);

        if (!entries.length) {
          if (/待补齐当天安排|这一天还没有|待补齐路线|行程明细待补充/u.test(lines.join(" "))) {
            return renderReportDailyNotReadyState();
          }
          return renderAssistantLines(lines);
        }

        const fallbackRoute = {
          origin: previewState.cityPair?.origin || "",
          destination: previewState.cityPair?.destination || "",
        };

        return `<div class="travel-report-days">${entries
          .map(
            (day) => `
              <article class="travel-report-day ${day.missing ? "missing" : ""}">
                <div class="travel-report-day-badge">${formatInlineText(day.label)}</div>
                <div class="travel-report-day-main">
                  <h5>${formatInlineText(day.title)}</h5>
                  ${
                    day.lines.length
                      ? `<div class="travel-report-day-copy">${renderAssistantLines(
                          day.lines
                        )}</div>`
                      : ""
                  }
                </div>
                <div class="travel-report-day-map">
                  <div class="travel-report-day-map-head">
                    <span>${escapeHtml(day.missing ? "待补齐路线" : "当天路线")}</span>
                    <strong>${escapeHtml(routeLabel || day.title || "路线示意")}</strong>
                  </div>
                  ${renderReportRouteSketch(
                    getReportRouteWaypoints(day.plan || day, fallbackRoute),
                    day.title
                  )}
                </div>
              </article>
            `
          )
          .join("")}</div>`;
      }

      function renderReportSectionBody(tone, lines = [], options = {}) {
        if (tone === "daily") return renderReportDayTimeline(lines, options);
        if (tone === "budget") {
          return renderReportBudgetBreakdown(lines, options.combinedText || "");
        }
        return renderAssistantLines(lines);
      }

      function extractReportMetric(text = "", pattern, fallback = "待补充") {
        const match = String(text || "").match(pattern);
        return match?.[1] || fallback;
      }

      function buildReportDefaultWarningSection(combinedText = "") {
        const hasWeatherHint = /雨|雪|热|冷|高温|台风|天气|温差|端午|暑期|节假日/u.test(
          combinedText
        );
        const lines = [
          hasWeatherHint
            ? "出发前 24-48 小时重新核验天气、景点开放状态和预约名额，遇到高温、降雨或节假日客流时优先执行室内/低强度备选。"
            : "出发前 24-48 小时重新核验天气、交通票价、酒店入住政策和景点预约名额。",
          "每天保留 1-2 小时机动时间，热门餐厅、博物馆、夜游和演出类项目尽量提前预约。",
          "预算里的交通、住宿和门票价格会随日期波动，正式下单前需要再做一次实时确认。",
        ];
        return {
          tone: "warning",
          reportTone: "warning",
          icon: "fa-cloud-sun",
          reportLabel: "天气风险",
          title: "天气与风险提醒",
          rawLines: lines,
        };
      }

      function renderTravelReportMapDigest(previewState = {}, routeLabel = "") {
        if (!previewState?.shouldRender) return "";
        return renderJourneyPreview(previewState);
      }

      function renderTravelReport(blocks, options = {}) {
        const expandedBlocks = expandStructuredTravelBlocks(blocks);
        const combinedText = expandedBlocks.join("\n\n");
        if (!hasTravelReportSignal(combinedText)) return null;

        const { summaryBlocks, sections } = extractTravelReportSections(expandedBlocks);
        if (sections.length < 2) return null;

        const cityPair =
          extractJourneyCityPair(combinedText) ||
          extractJourneyCityPairFromConversationTitle(getCurrentConversation()?.title || "");
        const routeLabel =
          cityPair?.origin && cityPair?.destination
            ? `${cityPair.origin} → ${cityPair.destination}`
            : cityPair?.destination || "专属旅程";
        const expectedDayCount = extractReportExpectedDayCount(combinedText);
        const dayCount = extractReportMetric(
          combinedText,
          /(\d+\s*天\s*\d*\s*[晚夜]?|[一二三四五六七八九十]\s*天\s*[一二三四五六七八九十]?\s*[晚夜]?)/u,
          "分日规划"
        );
        const budgetLabel =
          extractReportMetric(
            combinedText,
            /(?:总计|总预算|合计)[^\d]{0,12}([\d,.]+\s*元)/u,
            ""
          ) ||
          extractReportMetric(
            combinedText,
            /预算(?:希望|控制|范围)?[^\d]{0,12}([\d,.]+\s*元)/u,
            "预算已估算"
          );
        const summaryHtml = summaryBlocks.length
          ? renderAssistantLines(summaryBlocks.flat())
          : "";
        const previewState = buildJourneyPreviewState(summaryBlocks, sections);
        const reportSections = [...sections];
        if (
          !reportSections.some(
            (section) => (section.reportTone || section.tone) === "warning"
          )
        ) {
          reportSections.push(buildReportDefaultWarningSection(combinedText));
        }
        const renderOptions = {
          combinedText,
          expectedDayCount,
          previewState,
          routeLabel,
        };
        const shouldRenderMap =
          !options?.suppressJourneyPreview &&
          (Boolean(renderTravelReportMapDigest(previewState, routeLabel)) ||
            shouldRenderJourneyPreviewBlock(previewState, sections));

        return `
          <div class="travel-report">
            <div class="travel-report-hero">
              <div class="travel-report-kicker">
                <i class="fa-solid fa-file-signature"></i> 个性化旅游规划报告
              </div>
              <h3>${escapeHtml(routeLabel)}</h3>
              <p>我把当前已经确认的交通、住宿、预算和每日安排整理成一份可查看、可继续微调的旅行报告。</p>
              <div class="travel-report-metrics">
                <span><i class="fa-solid fa-route"></i>${escapeHtml(routeLabel)}</span>
                <span><i class="fa-regular fa-calendar"></i>${escapeHtml(dayCount)}</span>
                <span><i class="fa-solid fa-wallet"></i>${escapeHtml(budgetLabel)}</span>
              </div>
              <div class="travel-report-actions">
                <button type="button" data-report-action="tweak">
                  <i class="fa-solid fa-pen-nib"></i> 继续微调
                </button>
                <button type="button" data-report-action="map">
                  <i class="fa-solid fa-map-location-dot"></i> 查看路线地图
                </button>
                <button type="button" data-report-action="export">
                  <i class="fa-solid fa-file-export"></i> 导出报告
                </button>
              </div>
            </div>
            ${
              summaryHtml
                ? `<div class="travel-report-summary">${summaryHtml}</div>`
                : ""
            }
            <div class="travel-report-grid">
              ${reportSections
                .filter((section) => (section.reportTone || section.tone) !== "map")
                .map(
                  (section) => {
                    const sectionTone = section.reportTone || section.tone;
                    const sectionTitle =
                      sectionTone === "budget"
                        ? "预算拆分与依据"
                        : section.title;
                    const sectionLabel =
                      sectionTone === "budget"
                        ? "费用拆分"
                        : section.reportLabel || section.title;
                    return `
                    <section class="travel-report-card ${section.reportTone || section.tone}">
                      <div class="travel-report-card-head">
                        <span class="travel-report-card-icon">
                          <i class="fa-solid ${section.icon}"></i>
                        </span>
                        <div>
                          <div class="travel-report-card-label">${escapeHtml(sectionLabel)}</div>
                          <h4>${escapeHtml(sectionTitle)}</h4>
                        </div>
                      </div>
                      <div class="travel-report-card-body">${renderReportSectionBody(
                        sectionTone,
                        section.rawLines,
                        renderOptions
                      )}</div>
                    </section>
                  `;
                  }
                )
                .join("")}
            </div>
            ${
              shouldRenderMap
                ? `<div class="travel-report-map">${renderTravelReportMapDigest(
                    previewState,
                    routeLabel
                  )}</div>`
                : ""
            }
          </div>
        `;
      }

      function buildTravelReportFilename(report) {
        const title =
          report.querySelector(".travel-report-hero h3")?.textContent?.trim() ||
          getCurrentConversation()?.title ||
          "专属旅程";
        const safeTitle = title
          .replace(/[\\/:*?"<>|]/g, "-")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 40);
        return `知行-${safeTitle || "专属旅程"}-旅游报告.html`;
      }

      function collectLoadedExportStyles() {
        const chunks = [];
        Array.from(document.styleSheets || []).forEach((sheet) => {
          try {
            const rules = Array.from(sheet.cssRules || []);
            if (rules.length) {
              chunks.push(rules.map((rule) => rule.cssText).join("\n"));
            }
          } catch (error) {
            // 跨域图标样式可能不可读；导出只需要保留本地报告样式。
          }
        });
        return chunks.join("\n");
      }

      async function loadExportStyles() {
        const loadedStyles = collectLoadedExportStyles();
        if (loadedStyles) return loadedStyles;
        if (window.location.protocol === "file:") return "";
        try {
          const response = await fetch("./styles.css", { cache: "no-store" });
          if (response.ok) {
            return await response.text();
          }
        } catch (error) {
          console.warn("Failed to load export styles", error);
        }
        return "";
      }

      function prepareReportCloneForExport(report) {
        const clone = report.cloneNode(true);
        clone
          .querySelectorAll(
            [
              ".travel-report-actions",
              ".journey-map-action-btn",
              ".journey-map-style-btn",
              ".journey-map-focus-btn",
              ".journey-map-day-btn",
              ".journey-map-day-mode-btn",
              ".travel-card-link-btn",
              "button",
            ].join(",")
          )
          .forEach((node) => node.remove());
        return clone;
      }

      function buildStandaloneReportHtml(report, stylesText = "") {
        const reportClone = prepareReportCloneForExport(report);
        const title =
          reportClone.querySelector(".travel-report-hero h3")?.textContent?.trim() ||
          "知行旅游报告";
        const generatedAt = new Date().toLocaleString("zh-CN", {
          hour12: false,
        });
        const stylesheetLinks = stylesText
          ? ""
          : Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
              .map((link) => link.href)
              .filter((href) => href && /styles\.css|font-awesome|fontawesome/i.test(href))
              .map((href) => `<link rel="stylesheet" href="${escapeHtml(href)}" />`)
              .join("\n");

        return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(title)} - 知行旅游报告</title>
    <link rel="stylesheet" href="https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    ${stylesheetLinks}
    <style>
      ${stylesText}
      body {
        margin: 0;
        min-height: 100vh;
        padding: 34px;
        background:
          radial-gradient(circle at top left, rgba(194, 142, 92, 0.14), transparent 34%),
          linear-gradient(135deg, #f7f3ea, #eef6f3);
        color: #2c3e50;
      }
      .report-export-shell {
        max-width: 1120px;
        margin: 0 auto;
      }
      .report-export-meta {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: center;
        margin-bottom: 16px;
        color: rgba(26, 77, 84, 0.72);
        font-size: 13px;
      }
      .message.assistant .message-text {
        max-width: none;
      }
      .travel-report-actions,
      button {
        display: none !important;
      }
      @media print {
        body {
          background: #fff;
          padding: 0;
        }
        .report-export-meta {
          padding: 16px 18px 0;
        }
      }
    </style>
  </head>
  <body>
    <main class="report-export-shell">
      <div class="report-export-meta">
        <strong>知行 ZhiXing 旅游报告</strong>
        <span>导出时间：${escapeHtml(generatedAt)}</span>
      </div>
      <section class="message assistant">
        <div class="message-text">
          ${reportClone.outerHTML}
        </div>
      </section>
    </main>
  </body>
</html>`;
      }

      async function exportTravelReport(report) {
        const stylesText = await loadExportStyles();
        const html = buildStandaloneReportHtml(report, stylesText);
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = buildTravelReportFilename(report);
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }

      function handleTravelReportAction(button) {
        const report = button.closest(".travel-report");
        const action = button.dataset.reportAction || "";
        if (!report || !action) return;

        if (action === "tweak") {
          appendToComposer(
            "我想基于这份旅游报告继续微调：请先帮我列出可以调整的方向，比如交通、住宿、每日行程顺序、预算或景点取舍。",
            "replace"
          );
          setRuntimeStatus("已准备继续微调报告", "online");
          showToast("已把微调指令放到输入框");
          return;
        }

        if (action === "map") {
          const map = report.querySelector(".travel-report-map, .journey-live-map-shell");
          if (!map) {
            showToast("这份报告暂时还没有可视化路线地图。", true);
            return;
          }
          map.scrollIntoView({ behavior: "smooth", block: "start" });
          showToast("已定位到路线地图");
          return;
        }

        if (action === "export") {
          exportTravelReport(report)
            .then(() => showToast("旅游报告文件已开始导出"))
            .catch((error) => {
              console.error(error);
              showToast("导出失败，请稍后重试。", true);
          });
        }
      }

      function normalizeTravelBudgetTitle(title = "") {
        return /预算|费用|花费|价格|成本/u.test(title) ? "预算参考" : normalizeSectionTitle(title);
      }

      function stripDisplayListPrefix(line = "") {
        return String(line || "")
          .replace(/^[-*•]\s*/, "")
          .replace(/^\d+\.\s*/, "")
          .trim();
      }

      function extractTravelBudgetRows(lines = []) {
        const compactLines = lines
          .map((line) => line.trim())
          .filter((line) => line && !/^-{1,3}$/.test(line));

        const tableStart = compactLines.findIndex((_, index) =>
          Boolean(getMarkdownTableSpan(compactLines, index))
        );
        const tableSpan =
          tableStart >= 0 ? getMarkdownTableSpan(compactLines, tableStart) : 0;
        if (tableStart >= 0 && tableSpan) {
          const tableLines = compactLines.slice(tableStart, tableStart + tableSpan);
          const rows = tableLines
            .slice(2)
            .map(splitTableCells)
            .filter((cells) => cells.some(Boolean))
            .map((cells) => ({
              label: stripDisplayListPrefix(cells[0] || "费用项"),
              amount: (cells[1] || cells[cells.length - 1] || "待核验").trim(),
              note: cells.slice(2).filter(Boolean).join("；"),
            }));
          return rows.filter((row) => row.label && row.amount);
        }

        const joined = compactLines.join("；");
        const rows = [];
        const pattern =
          /(交通|大交通|往返|住宿|酒店|民宿|餐饮|美食|门票|游船|景点|体验|市内交通|服务\/预留|服务|预留|伴手礼|其他|机动|合计|总计)[^~￥¥\d]{0,14}([~约￥¥]?\s*\d[\d,.]*(?:\s*[-~]\s*\d[\d,.]*)?\s*元?)/gu;
        let match;
        while ((match = pattern.exec(joined))) {
          const label = match[1].replace(/往返$/, "交通");
          const amount = match[2].replace(/\s+/g, "");
          const key = `${label}-${amount}`;
          if (!amount || rows.some((row) => `${row.label}-${row.amount}` === key)) continue;
          rows.push({ label, amount, note: "" });
        }
        return rows.slice(0, 8);
      }

      function getTravelBudgetIcon(label = "") {
        if (/交通|往返|高铁|火车|航班|机票|车/u.test(label)) return "fa-train-subway";
        if (/住宿|酒店|民宿|房/u.test(label)) return "fa-bed";
        if (/餐|美食|吃/u.test(label)) return "fa-utensils";
        if (/门票|景点|游船|体验/u.test(label)) return "fa-ticket";
        if (/服务|预留|机动|缓冲/u.test(label)) return "fa-shield-heart";
        if (/合计|总计|预算/u.test(label)) return "fa-calculator";
        return "fa-wallet";
      }

      function renderTravelBudgetCardBody(lines = [], reminderLines = []) {
        const rows = extractTravelBudgetRows(lines);
        const reminders = reminderLines
          .map(stripDisplayListPrefix)
          .filter(Boolean)
          .slice(0, 4);
        if (!rows.length) {
          return `
            <div class="travel-budget-layout">
              <div class="travel-budget-main">${renderAssistantLines(lines)}</div>
              ${
                reminders.length
                  ? `<aside class="travel-budget-reminders">
                      <span>出发前确认</span>
                      <ul>${reminders
                        .map((item) => `<li>${formatInlineText(item)}</li>`)
                        .join("")}</ul>
                    </aside>`
                  : ""
              }
            </div>
          `;
        }

        const totalRow =
          rows.find((row) => /合计|总计|总预算|预算/u.test(row.label)) ||
          rows[rows.length - 1];
        return `
          <div class="travel-budget-layout">
            <div class="travel-budget-main">
              <div class="travel-budget-total">
                <span>当前估算</span>
                <strong>${escapeHtml(totalRow.amount || "待核验")}</strong>
              </div>
              <div class="travel-budget-rows">
                ${rows
                  .filter((row) => row !== totalRow || rows.length === 1)
                  .map(
                    (row) => `
                      <div class="travel-budget-row">
                        <span class="travel-budget-row-icon">
                          <i class="fa-solid ${getTravelBudgetIcon(row.label)}"></i>
                        </span>
                        <div>
                          <strong>${escapeHtml(row.label)}</strong>
                          ${row.note ? `<small>${formatInlineText(row.note)}</small>` : ""}
                        </div>
                        <em>${escapeHtml(row.amount || "待核验")}</em>
                      </div>
                    `
                  )
                  .join("")}
              </div>
            </div>
            <aside class="travel-budget-reminders">
              <span>出发前确认</span>
              ${
                reminders.length
                  ? `<ul>${reminders
                      .map((item) => `<li>${formatInlineText(item)}</li>`)
                      .join("")}</ul>`
                  : `<p>交通票价、住宿价格和热门项目名额会随日期变化，正式出发前再核验一次。</p>`
              }
            </aside>
          </div>
        `;
      }

      function renderStructuredTravelPlan(blocks, options = {}) {
        const expandedBlocks = expandStructuredTravelBlocks(blocks);
        const summaryBlocks = [];
        const sections = [];

        expandedBlocks.forEach((block) => {
          const lines = block
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          const isHeadingBlock = /^#{1,3}\s+/.test(lines[0]);
          const isBoldHeadingBlock = /^\*\*.+\*\*$/.test(lines[0]);
          const headingCandidate = lines[0].replace(/^#{1,3}\s+/, "").trim();
          const looksLikeSectionHeading = isEmbeddedSectionHeading(lines[0]);
          const inlineMatch = headingCandidate.match(/^([^：:]{2,16})[：:]\s*(.+)$/);
          const shouldTreatAsSection =
            Boolean(inlineMatch) ||
            isHeadingBlock ||
            isBoldHeadingBlock ||
            looksLikeSectionHeading ||
            headingCandidate.length <= 18;
          if (!shouldTreatAsSection) {
            summaryBlocks.push(lines);
            return;
          }
          const sectionTitle = inlineMatch ? inlineMatch[1] : headingCandidate;
          const bodyLines = [
            ...(inlineMatch && inlineMatch[2] ? [inlineMatch[2].trim()] : []),
            ...lines.slice(1),
          ].filter(Boolean);
          const meta =
            getTravelSectionMeta(sectionTitle) ||
            inferSectionMetaFromBody(bodyLines);

          if (!meta) {
            summaryBlocks.push(lines);
            return;
          }

          if (!bodyLines.length) {
            return;
          }

          sections.push({
            ...meta,
            title: normalizeSectionTitle(sectionTitle),
            bodyHtml: renderAssistantLines(bodyLines),
            rawLines: bodyLines,
          });
        });

        const journeyPreviewState = buildJourneyPreviewState(summaryBlocks, sections);
        const shouldRenderTravelCards = sections.length >= 2;
        const shouldRenderJourneyPreview =
          !options?.suppressJourneyPreview &&
          shouldRenderJourneyPreviewBlock(journeyPreviewState, sections);
        if (!shouldRenderTravelCards && !shouldRenderJourneyPreview) {
          return null;
        }
        const summaryHtml = summaryBlocks.length
          ? renderAssistantLines(summaryBlocks.flat())
          : "";
        const journeyPreviewHtml = shouldRenderJourneyPreview
          ? renderJourneyPreview(journeyPreviewState)
          : "";
        const budgetReminderLines = sections
          .filter((section) => section.tone === "warning")
          .flatMap((section) => section.rawLines || []);
        const hasBudgetCard = sections.some((section) => section.tone === "budget");
        const displaySections =
          hasBudgetCard && budgetReminderLines.length
            ? sections.filter((section) => section.tone !== "warning")
            : sections;

        return `
          <div class="travel-plan">
            ${
              shouldRenderTravelCards
                ? `
                    <div class="travel-grid">
                      ${displaySections
                        .map((section) => {
                          const sectionMapFocus = resolveTravelCardMapFocus(
                            section,
                            journeyPreviewState
                          );
                          const isBudgetSection = section.tone === "budget";
                          const sectionTitle = isBudgetSection
                            ? normalizeTravelBudgetTitle(section.title)
                            : section.title;
                          const sectionBodyHtml = isBudgetSection
                            ? renderTravelBudgetCardBody(section.rawLines, budgetReminderLines)
                            : section.bodyHtml;
                          const mapButtonLabel =
                            sectionMapFocus === "stay" ? "看周边" : "看地图";
                          return `
                            <section class="travel-card ${section.tone}${
                              isBudgetSection && budgetReminderLines.length ? " with-reminders" : ""
                            }"${
                              sectionMapFocus ? ` data-map-focus="${sectionMapFocus}"` : ""
                            }>
                              <div class="travel-card-head">
                                <div class="travel-card-head-main">
                                  <div class="travel-card-icon">
                                    <i class="fa-solid ${section.icon}"></i>
                                  </div>
                                  <div class="travel-card-title">${escapeHtml(sectionTitle)}</div>
                                </div>
                                ${
                                  sectionMapFocus
                                    ? `
                                        <button
                                          class="travel-card-link-btn"
                                          type="button"
                                          data-map-focus="${sectionMapFocus}"
                                        >
                                          ${escapeHtml(mapButtonLabel)}
                                        </button>
                                      `
                                    : ""
                                }
                              </div>
                              <div class="travel-card-body">${sectionBodyHtml}</div>
                            </section>
                          `;
                        })
                        .join("")}
                    </div>
                  `
                : ""
            }
            ${journeyPreviewHtml}
            ${
              summaryHtml
                ? `<div class="travel-summary">
                    <div class="travel-summary-label">
                      <i class="fa-solid fa-compass-drafting"></i> 行程摘要
                    </div>
                    <div class="travel-summary-copy">${summaryHtml}</div>
                  </div>`
                : ""
            }
          </div>
        `;
      }

      function buildVisualJourneyPreviewState(journeyData = {}) {
        if (!isVisualJourneyData(journeyData)) return { shouldRender: false };
        const overview = journeyData.overview || {};
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const allPois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const alternativePois = Array.isArray(journeyData.alternative_pois)
          ? journeyData.alternative_pois
          : [];
        const dayPlans = days
          .map((day, index) => {
            const pois = Array.isArray(day.pois) ? day.pois : [];
            const waypoints = pois
              .map((poi) => cleanJourneyLocationValue(poi.name || ""))
              .filter(Boolean);
            if (!waypoints.length) return null;
            return {
              key: `visual-day-${day.day_number || index + 1}`,
              dayNumber: day.day_number || index + 1,
              label: day.date
                ? `${String(day.date).slice(5)} ${day.weekday || ""}`.trim()
                : `Day ${day.day_number || index + 1}`,
              title: day.title || `Day ${day.day_number || index + 1}`,
              waypoints,
              stops: pois.map((poi) => ({
                id: poi.id || "",
                name: poi.name || "",
                city: poi.city || "",
                type: poi.type || "attraction",
                type_label: poi.type_label || poi.type || "地点",
                time_range: poi.suggested_time || "",
                description: poi.description || "",
                duration_minutes: poi.duration_minutes || "",
                estimated_cost: poi.estimated_cost || "",
                reservation_note: poi.reservation_note || "",
                verification_status: poi.verification_status || "",
                verification_note: poi.verification_note || "",
                map_verified: Boolean(poi.map_verified),
                coordinate_estimated: Boolean(poi.coordinate_estimated),
                address: poi.address || "",
                amap_type: poi.amap_type || "",
                amap_source_name: poi.amap_source_name || "",
                tags: Array.isArray(poi.tags) ? poi.tags : [],
                image_url: poi.image_url || "",
                map_query: poi.map_query || "",
                lng: typeof poi.lng === "number" ? poi.lng : null,
                lat: typeof poi.lat === "number" ? poi.lat : null,
              })),
              highlights: waypoints.slice(0, 3),
              note: day.summary || waypoints.join(" → "),
              city: day.city || "",
              weather: day.weather || null,
              segments: Array.isArray(day.segments) ? day.segments : [],
              routeStatus: getJourneyDayRouteStatus(day),
              weatherStatus: getJourneyDayWeatherStatus(day),
            };
          })
          .filter(Boolean);
        if (!dayPlans.length) return { shouldRender: false };
        const destination = overview.destination || dayPlans[0]?.waypoints?.[0] || "";
        const recommendations = alternativePois
          .map((poi) => normalizeJourneyPoiAsStop(poi, { city: destination }))
          .filter((poi) => cleanJourneyLocationValue(poi.name || ""))
          .slice(0, 8);
        const origin = overview.route_label?.includes("进")
          ? overview.route_label.split("进")[0]
          : "";
        return {
          combinedText: [
            overview.title,
            overview.summary,
            allPois.map((poi) => poi.name).join(" "),
            recommendations.map((poi) => poi.name).join(" "),
          ]
            .filter(Boolean)
            .join(" "),
          cityPair: {
            origin: origin || dayPlans[0]?.waypoints?.[0] || "",
            destination,
          },
          destinationSection: {
            tone: "overview",
            title: overview.title || `${destination}旅程草案`,
            rawLines: [
              overview.summary,
              overview.date_range ? `日期：${overview.date_range}` : "",
              overview.route_label ? `路线：${overview.route_label}` : "",
            ].filter(Boolean),
          },
          transportSection: {
            tone: "transport",
            title: "交通待后续核验",
            rawLines: ["大交通、城际交通和实时路况会在后续继续核验。"],
          },
          staySection: {
            tone: "stay",
            title: "住宿待后续核验",
            rawLines: ["住宿区域和真实酒店候选会在旅程草案确认后继续补齐。"],
          },
          budgetSection: {
            tone: "budget",
            title: "预算待核验",
            rawLines: [],
          },
          highlights: allPois.map((poi) => poi.name).filter(Boolean).slice(0, 6),
          highlightCards: buildJourneyHighlightCards(
            allPois.map((poi) => poi.name).filter(Boolean).slice(0, 6)
          ),
          recommendations,
          rhythm: days.map((day) => day.summary || day.title || "").filter(Boolean).slice(0, 3),
          dayPlans,
          mapExperience: "immersive",
          shouldRender: true,
        };
      }

      function renderPlanningTrace(trace = []) {
        const items = (Array.isArray(trace) ? trace : []).filter(Boolean);
        if (!items.length || !canShowAdvisorDebug()) return "";
        return `
          <details class="planning-trace-panel" open>
            <summary>
              <span>规划过程</span>
              <strong>${items.length} 步完成</strong>
            </summary>
            <div class="planning-trace-list">
              ${items
                .map((item) => {
                  const status = item.status || "completed";
                  return `
                    <div class="planning-trace-item ${escapeHtml(status)}">
                      <span class="planning-trace-icon">${
                        status === "completed" ? "✓" : "·"
                      }</span>
                      <div>
                        <strong>${escapeHtml(item.title || item.phase || "规划步骤")}</strong>
                        <p>${escapeHtml(item.detail || "")}</p>
                        <small>${[
                          item.city,
                          item.date_range,
                          item.count ? `${item.count} 项` : "",
                        ]
                          .filter(Boolean)
                          .map(escapeHtml)
                          .join(" · ")}</small>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </details>
        `;
      }

      function renderVisualPoiDetails(pois = []) {
        if (!pois.length) return "";
        return `
          <div class="visual-poi-grid">
            ${pois
              .slice(0, 14)
              .map((poi, index) => {
                const verification = getVisualPoiVerificationBadge(poi);
                const evidenceItems = [
                  verification.label,
                  poi.address || poi.map_query,
                  poi.amap_type,
                ].filter(Boolean);
                return `
                  <details class="visual-poi-card" data-poi-id="${escapeHtml(poi.id || "")}"${
                  index === 0 ? " open" : ""
                }>
                    <summary>
                      <span>${index + 1}</span>
                      <div>
                        <strong>${escapeHtml(poi.name || "地点待确认")}</strong>
                        <small>${escapeHtml(
                          [poi.city, poi.type_label || poi.type, poi.suggested_time]
                            .filter(Boolean)
                            .join(" · ")
                        )}</small>
                      </div>
                    </summary>
                    ${renderVisualPoiMedia(poi, index)}
                    <div class="visual-poi-evidence">
                      ${evidenceItems
                        .slice(0, 3)
                        .map(
                          (item, itemIndex) =>
                            `<span class="${itemIndex === 0 ? escapeHtml(verification.tone) : ""}">${escapeHtml(
                              item
                            )}</span>`
                        )
                        .join("")}
                    </div>
                    <p>${escapeHtml(poi.description || "地点介绍待补充。")}</p>
                    <div class="visual-poi-meta">
                      <span>停留 ${escapeHtml(String(poi.duration_minutes || "待核验"))} 分钟</span>
                      <span>${escapeHtml(poi.estimated_cost || "费用待核验")}</span>
                      ${
                        Array.isArray(poi.tags) && poi.tags.length
                          ? `<span>${escapeHtml(poi.tags.slice(0, 2).join(" · "))}</span>`
                          : ""
                      }
                    </div>
                    <div class="visual-poi-actions">
                      <button
                        class="visual-poi-focus-btn"
                        type="button"
                        data-map-day-stop="visual-day-${escapeHtml(
                          String(poi.day_number || 1)
                        )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                      >
                        地图定位
                      </button>
                      <button
                        type="button"
                        data-journey-edit-action="up"
                        data-map-day-stop="visual-day-${escapeHtml(
                          String(poi.day_number || 1)
                        )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                      >
                        上移
                      </button>
                      <button
                        type="button"
                        data-journey-edit-action="down"
                        data-map-day-stop="visual-day-${escapeHtml(
                          String(poi.day_number || 1)
                        )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                      >
                        下移
                      </button>
                      <button
                        type="button"
                        data-journey-edit-action="delete"
                        data-map-day-stop="visual-day-${escapeHtml(
                          String(poi.day_number || 1)
                        )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                      >
                        删除
                      </button>
                      <button type="button" disabled>打卡</button>
                    </div>
                    <em>${escapeHtml(
                      poi.reservation_note || "开放、预约和票价出发前二次核验。"
                    )}</em>
                  </details>
                `;
              })
              .join("")}
          </div>
        `;
      }

      function renderVisualJourneyWorkbench(journeyData, options = {}) {
        if (!isVisualJourneyData(journeyData)) return "";
        const overview = journeyData.overview || {};
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const pois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const previewState = buildVisualJourneyPreviewState(journeyData);
        const atlas = previewState.shouldRender ? renderJourneyPreview(previewState) : "";
        return `
          <section
            class="visual-journey-workbench"
            data-journey-data="${serializeMapPayload(journeyData)}"
          >
            <div class="visual-journey-head">
              <div>
                <span>可视化旅程草案</span>
                <strong>${escapeHtml(overview.title || "经典路线")}</strong>
                <p>${escapeHtml(overview.summary || "先生成地图路线，再继续核验交通、酒店和预算。")}</p>
              </div>
              <div class="visual-journey-badges">
                <span>${escapeHtml(overview.date_range || "日期待确认")}</span>
                <span>${escapeHtml(String(overview.duration_days || days.length || "多"))} 天</span>
                <span>${escapeHtml(overview.route_label || "路线待核验")}</span>
              </div>
            </div>
            ${renderVisualJourneyStats(journeyData)}
            ${renderPlanningTrace(getPlanningTraceFromOptions(options))}
            ${atlas}
            <div class="visual-day-strip">
              ${days
                .map(
                  (day) => `
                    <article>
                      <button
                        class="visual-day-focus-btn"
                        type="button"
                        data-map-day-focus="visual-day-${escapeHtml(String(day.day_number || 1))}"
                      >
                      <span>${escapeHtml(day.date ? String(day.date).slice(5) : `Day ${day.day_number}`)}</span>
                      <strong>${escapeHtml(day.title || day.summary || "当天安排")}</strong>
                      <p>${escapeHtml(day.summary || "")}</p>
                      ${renderJourneyDayStatusChips(day)}
                      </button>
                    </article>
                  `
                )
                .join("")}
            </div>
            ${renderVisualPoiDetails(pois)}
            <div class="visual-journey-pending">
              ${(journeyData.pending_checks || [])
                .map((item) => `<span>${escapeHtml(item)}</span>`)
                .join("")}
            </div>
          </section>
        `;
      }

      function renderAssistantText(text, options = {}) {
        const structuredReport = renderTravelReportFromData(
          getReportDataFromOptions(options),
          options
        );
        if (structuredReport) return structuredReport;

        const journeyData = getJourneyDataFromOptions(options);
        if (isVisualJourneyData(journeyData)) {
          return renderVisualJourneyWorkbench(journeyData, options);
        }

        if (!text) return "";
        const blocks = splitAssistantBlocks(text);
        return (
          renderTravelReport(blocks, options) ||
          renderStructuredTravelPlan(blocks, options) ||
          renderAssistantFallback(blocks)
        );
      }

      function renderMessageText(role, text, options = {}) {
        if (role === "assistant") {
          return renderAssistantText(text, options);
        }
        return escapeHtml(text);
      }

      function buildMessageMarkup(role, text, timestamp = new Date(), options = {}) {
        return `
                <div class="message-avatar"><i class="fa-solid ${
                  role === "user" ? "fa-user" : "fa-compass"
                }"></i></div>
                <div class="message-content">
                    <div class="message-text">${renderMessageText(
                      role,
                      text,
                      options
                    )}</div>
                    <div class="message-time">${formatClock(timestamp)}</div>
                </div>
            `;
      }

      document.addEventListener("DOMContentLoaded", async () => {
        const apiBaseInput = document.getElementById("apiBase");
        apiBaseInput.value = getDefaultApiBase();
        apiBaseInput.addEventListener("input", updateEndpointUI);
        window.addEventListener("resize", () => {
          if (!isMobileViewport()) {
            setMobileChatFocus(false);
          } else if (state.currentConversationId && state.mobileChatFocus) {
            setMobileChatFocus(true);
          }
        });
        window.addEventListener("online", () =>
          checkServiceHealth({ silent: true, reason: "browser-online" })
        );
        document.addEventListener("click", (event) => {
          const reportActionBtn = event.target.closest("[data-report-action]");
          if (reportActionBtn) {
            handleTravelReportAction(reportActionBtn);
            return;
          }

          const actionBtn = event.target.closest(".journey-map-action-btn");
          if (actionBtn) {
            handleJourneyMapAction(actionBtn);
            return;
          }

          const styleBtn = event.target.closest(".journey-map-style-btn");
          if (styleBtn) {
            handleJourneyMapStyle(styleBtn);
            return;
          }

          const focusBtn = event.target.closest(".journey-map-focus-btn");
          if (focusBtn) {
            handleJourneyMapFocus(focusBtn);
            return;
          }

          const dayBtn = event.target.closest(".journey-map-day-btn");
          if (dayBtn) {
            handleJourneyMapDay(dayBtn);
            return;
          }

          const dayModeBtn = event.target.closest(".journey-map-day-mode-btn");
          if (dayModeBtn) {
            handleJourneyMapDayMode(dayModeBtn);
            return;
          }

          const cardLinkBtn = event.target.closest(".travel-card-link-btn");
          if (cardLinkBtn) {
            focusJourneyMapFromPlan(
              cardLinkBtn,
              cardLinkBtn.dataset.mapFocus || "destination"
            );
            return;
          }

          const rhythmFocusBtn = event.target.closest(".journey-rhythm-focus-btn");
          if (rhythmFocusBtn) {
            focusJourneyMapFromPlan(
              rhythmFocusBtn,
              rhythmFocusBtn.dataset.mapFocus || "destination"
            );
            return;
          }

          const dayFocusBtn = event.target.closest(".journey-day-map-btn");
          if (dayFocusBtn) {
            focusJourneyMapDayFromPlan(dayFocusBtn);
            return;
          }

          const visualDayFocusBtn = event.target.closest(".visual-day-focus-btn");
          if (visualDayFocusBtn) {
            handleVisualJourneyDayFocus(visualDayFocusBtn);
            return;
          }

          const visualPoiFocusBtn = event.target.closest(".visual-poi-focus-btn");
          if (visualPoiFocusBtn) {
            handleVisualJourneyPoiFocus(visualPoiFocusBtn);
            return;
          }

          const journeyEditBtn = event.target.closest("[data-journey-edit-action]");
          if (journeyEditBtn) {
            handleJourneyEditAction(journeyEditBtn);
            return;
          }

          const stageStopBtn = event.target.closest(
            ".journey-map-stage-stop, .journey-live-marker[data-map-day-stop], .journey-live-marker [data-map-day-stop]"
          );
          if (stageStopBtn) {
            handleJourneyMapStageStop(stageStopBtn);
            return;
          }

          const poiSheetCloseBtn = event.target.closest("[data-poi-sheet-close='true']");
          if (poiSheetCloseBtn) {
            hideJourneyPoiSheet(poiSheetCloseBtn.closest(".journey-live-map-shell"));
            return;
          }

          const poiSheetActionBtn = event.target.closest("[data-poi-sheet-action]");
          if (poiSheetActionBtn) {
            handleJourneyPoiSheetAction(poiSheetActionBtn);
            return;
          }

          if (
            event.target.id === "journeyMapModal" ||
            event.target.closest("[data-map-modal-close='true']")
          ) {
            closeJourneyMapModal();
          }
        });
        document.addEventListener("keydown", (event) => {
          if (event.key === "Escape") {
            closeJourneyMapModal();
          }
        });
        document.addEventListener("visibilitychange", () => {
          if (
            document.visibilityState === "visible" &&
            Date.now() - state.lastHealthCheckAt > 60000
          ) {
            checkServiceHealth({ silent: true, reason: "tab-visible" });
          }
        });
        syncUiAvailability();
        updateEndpointUI();
        renderReadinessPanel();
        renderApprovalList();
        renderApprovalEvents();
        renderToolAuditList();
        renderTurnObservability();
        applyPlannerPanelState();
        await checkServiceHealth({ silent: false, reason: "startup" });
        if (state.token && state.user) {
          hideIntroOverlay();
          hideAuthOverlay();
          updateUserInfo();
          setRuntimeStatus("正在同步会话", "loading");
          await loadConversations();
          await loadApprovals({ silent: true });
        } else {
          showIntroOverlay();
          hideAuthOverlay();
          if (isServiceUsable()) {
            setRuntimeStatus("等待登录", "idle");
          }
          setMobileChatFocus(false);
          updateSessionOverview();
          setAuthFeedback(
            "如果你是第一次来，可以先注册；如果之前用过，直接登录即可继续会话，最后我会帮你整理成旅游规划报告。",
            "info"
          );
        }
        autoResizeTextarea();
        restoreDrafts();
        updatePlannerAssistStrip();
        ["username", "email", "password"].forEach((field) => {
          const input = document.getElementById(field);
          input?.addEventListener("input", () => {
            setFieldError(field, "");
            if (document.getElementById("authFeedback")?.classList.contains("error")) {
              setAuthFeedback("", "info");
            }
          });
        });
        document
          .getElementById("chatInput")
          ?.addEventListener("input", persistComposerDraft);
        document
          .getElementById("chatTitle")
          ?.addEventListener("dblclick", () => renameCurrentConversation());
        [
          "plannerOrigin",
          "plannerDestination",
          "plannerDate",
          "plannerDays",
          "plannerTravelers",
          "plannerBudget",
          "plannerTransport",
          "plannerStay",
          "plannerStyle",
        ].forEach((field) => {
          document
            .getElementById(field)
            ?.addEventListener("input", persistPlannerDraft);
        });
      });

      function switchAuthTab(tab) {
        const tabs = document.querySelectorAll(".auth-tab");
        const emailField = document.getElementById("emailField");
        const emailInput = document.getElementById("email");
        const authBtn = document.getElementById("authBtn");
        const authFormMeta = document.getElementById("authFormMeta");

        tabs.forEach((t) => t.classList.remove("active"));
        document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
        clearAuthErrors();

        if (tab === "register") {
          emailField.classList.add("show");
          emailInput.required = true;
          authBtn.textContent = "注册通行证";
          if (authFormMeta) {
            authFormMeta.textContent =
              "注册后会自动登录，并立即为你同步空白会话列表。";
          }
          setAuthFeedback(
            "建议使用常用邮箱注册，后续排查问题和找回账号会更方便。",
            "info"
          );
        } else {
          emailField.classList.remove("show");
          emailInput.required = false;
          authBtn.textContent = "开启旅程";
          if (authFormMeta) {
            authFormMeta.textContent =
              "登录后可以继续之前的行程记录，也可以新建一段旅程。";
          }
          setAuthFeedback(
            "如果你之前已经创建过账号，直接输入用户名和密码即可继续会话。",
            "info"
          );
        }
      }

      async function handleAuth(e) {
        e.preventDefault();
        const isRegister =
          document.querySelector(".auth-tab.active").dataset.tab === "register";
        const formData = validateAuthForm(isRegister);
        if (!formData) return;
        if (!(await ensureServiceReady("登录或注册"))) return;
        const { username, email, password } = formData;
        const btn = document.getElementById("authBtn");

        state.isAuthLoading = true;
        syncUiAvailability();
        setAuthFeedback(
          isRegister ? "正在创建账号并同步会话…" : "正在验证身份并拉取会话…",
          "info"
        );
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 验证中...';

        try {
          let response;
          const endpoint = isRegister
            ? "/api/v1/users/register"
            : "/api/v1/users/login";
          const body = isRegister
            ? { username, email, password }
            : { username, password };

          response = await fetch(`${getApiBase()}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });

          const data = await response.json();

          if (response.ok) {
            state.token = data.access_token;
            state.user = data.user;
            localStorage.setItem("token", state.token);
            localStorage.setItem("user", JSON.stringify(state.user));
            setAuthFeedback(
              isRegister
                ? "账号创建成功，正在进入你的旅行工作台。"
                : "登录成功，正在恢复你的会话列表。",
              "success"
            );
            showToast(isRegister ? "欢迎加入知行！" : "欢迎回来！");
            hideIntroOverlay();
            hideAuthOverlay();
            updateUserInfo();
            state.currentConversationId = null;
            state.conversations = [];
            resetConversationDrafts({ silent: true });
            renderConversationsList();
            setRuntimeStatus("正在同步会话", "loading");
            await loadConversations();
            await loadApprovals({ silent: true });
          } else {
            setRuntimeStatus("登录失败", "error");
            setAuthFeedback(data.detail || "认证失败，请检查用户名和密码。", "error");
            showToast(data.detail || "操作失败", true);
          }
        } catch (error) {
          setRuntimeStatus("连接异常", "error");
          setAuthFeedback("网络连接出现波动，请稍后重试。", "error");
          showToast("网络连接异常", true);
        } finally {
          state.isAuthLoading = false;
          btn.innerHTML = isRegister ? "注册通行证" : "开启旅程";
          syncUiAvailability();
        }
      }

      function hideAuthOverlay() {
        document.getElementById("authOverlay").classList.add("hidden");
      }
      function showAuthOverlay() {
        document.getElementById("authOverlay").classList.remove("hidden");
      }

      function updateUserInfo() {
        if (state.user) {
          document.getElementById("userName").textContent =
            state.user.username || "旅行者";
          // 提取首字母
          const name = state.user.username || state.user.email || "U";
          document.getElementById("userAvatar").textContent =
            name[0].toUpperCase();
        }
      }

      function logout() {
        resetConversationDrafts({ silent: true });
        state.token = "";
        state.user = null;
        state.currentConversationId = null;
        state.conversations = [];
        state.governance.approvals = [];
        state.governance.approvalEvents = [];
        state.governance.selectedApprovalId = null;
        state.governance.toolAuditEvents = [];
        state.governance.turnObservability = null;
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        resetPlannerDraft({ silent: true });
        showIntroOverlay();
        hideAuthOverlay();
        clearChatMessages();
        document.getElementById("conversationsList").innerHTML = "";
        document.getElementById("chatTitle").textContent = "行程助手";
        setMobileChatFocus(false);
        setRuntimeStatus("等待登录", "idle");
        updateSessionOverview();
        renderApprovalList();
        renderApprovalEvents();
        renderToolAuditList();
        renderTurnObservability();
        showToast("已登出账号");
      }

      async function loadConversations(options = {}) {
        if (!(await ensureServiceReady("加载会话"))) return;
        const preserveCurrentConversationId = Boolean(
          options?.preserveCurrentConversationId
        );
        try {
          const response = await fetch(`${getApiBase()}/api/v1/conversations`, {
            headers: { Authorization: `Bearer ${state.token}` },
          });
          if (response.ok) {
            const data = await response.json();
            state.conversations = Array.isArray(data)
              ? data
              : data.conversations || [];
            if (
              state.currentConversationId &&
              !state.conversations.some(
                (conv) => conv.id === state.currentConversationId
              )
            ) {
              if (!preserveCurrentConversationId) {
                state.currentConversationId = null;
                restoreChatTitleLabel();
                clearChatMessages();
                setMobileChatFocus(false);
              }
            }
            renderConversationsList();
            setRuntimeStatus("已连接", "online");
          } else if (response.status === 401) logout();
        } catch (error) {
          console.error(error);
          renderConversationsList();
          setRuntimeStatus("会话同步失败", "error");
        }
      }

      function renderConversationsList() {
        const container = document.getElementById("conversationsList");
        updateSessionOverview();
        if (state.conversations.length === 0) {
          container.innerHTML = `
            <div class="empty-conversations">
              <i class="fa-regular fa-map" style="display:block; font-size:18px; margin-bottom:8px; color:var(--accent);"></i>
              <span class="empty-conversations-title">还没有保存的行程</span>
              <p class="empty-conversations-text">先创建一段新会话，后面每次回来都能从这里继续追问、补充交通和住宿细节。</p>
              <button class="empty-conversations-btn" type="button" onclick="createNewConversation()">
                <i class="fa-solid fa-compass"></i>
                立即创建第一段行程
              </button>
            </div>`;
          return;
        }
        container.innerHTML = state.conversations
          .map(
            (conv) => `
                <div class="conversation-item ${
                  conv.id === state.currentConversationId ? "active" : ""
                } ${conv.id === state.editingConversationId ? "editing" : ""}"
                     onclick="switchConversation('${conv.id}')">
                    <div class="conversation-top">
                      ${
                        conv.id === state.editingConversationId
                          ? `
                              <form
                                class="conversation-title conversation-title-edit-form"
                                onsubmit="submitConversationRename(event, '${conv.id}')"
                                onclick="event.stopPropagation()"
                              >
                                <i class="fa-solid fa-map-pin" style="font-size:10px; color:var(--accent)"></i>
                                <input
                                  id="conversationRenameInput-${conv.id}"
                                  class="conversation-title-input"
                                  type="text"
                                  value="${escapeHtml(conv.title || DEFAULT_CONVERSATION_TITLE)}"
                                  maxlength="40"
                                  aria-label="编辑行程名称"
                                  onkeydown="handleConversationRenameKeydown(event, '${conv.id}')"
                                />
                              </form>
                            `
                          : `
                              <div class="conversation-title" ondblclick="beginConversationRename(event, '${conv.id}')">
                                <i class="fa-solid fa-map-pin" style="font-size:10px; color:var(--accent)"></i>
                                <span class="conversation-title-text">${escapeHtml(
                                  conv.title || "未知行程"
                                )}</span>
                              </div>
                            `
                      }
                      <div class="conversation-actions">
                        ${
                          conv.id === state.currentConversationId
                            ? '<span class="conversation-badge">当前</span>'
                            : ""
                        }
                        ${
                          conv.id === state.editingConversationId
                            ? `
                                <button
                                  class="conversation-save-btn"
                                  type="button"
                                  aria-label="保存行程名称"
                                  onclick="submitConversationRename(event, '${conv.id}')"
                                >
                                  <i class="fa-solid fa-check"></i>
                                </button>
                                <button
                                  class="conversation-cancel-btn"
                                  type="button"
                                  aria-label="取消编辑"
                                  onclick="cancelConversationRename(event)"
                                >
                                  <i class="fa-solid fa-xmark"></i>
                                </button>
                              `
                            : `
                                <button
                                  class="conversation-edit-btn"
                                  type="button"
                                  aria-label="编辑这段行程名称"
                                  onclick="renameConversation(event, '${conv.id}')"
                                >
                                  <i class="fa-regular fa-pen-to-square"></i>
                                </button>
                                <button
                                  class="conversation-delete-btn"
                                  type="button"
                                  aria-label="删除这段行程"
                                  onclick="deleteConversation(event, '${conv.id}')"
                                >
                                  <i class="fa-regular fa-trash-can"></i>
                                </button>
                              `
                        }
                      </div>
                    </div>
                    <div class="conversation-time">
                        <i class="fa-regular fa-clock" style="font-size:10px;"></i> ${formatConversationStamp(
                          conv.updated_at || conv.created_at
                        )}
                    </div>
                    <div class="conversation-subline">
                        <div class="conversation-detail">
                          ${
                            conv.id === state.currentConversationId
                              ? "当前正在查看这段行程，可继续追问细节。"
                              : `最近活跃：${formatRelativeTime(
                                  conv.updated_at || conv.created_at
                                )}`
                          }
                        </div>
                        <span class="conversation-status ${
                          conv.id === state.currentConversationId ? "active" : ""
                        }">${
                          conv.id === state.currentConversationId
                            ? "进行中"
                            : "待继续"
                        }</span>
                    </div>
                </div>
            `
          )
          .join("");
      }

      async function deleteConversation(event, id) {
        event?.stopPropagation();
        const conv = state.conversations.find((item) => item.id === id);
        const label = conv?.title || "这段行程";
        if (!window.confirm(`确定删除“${label}”吗？删除后会从当前账号的列表中移除。`)) {
          return;
        }
        if (!(await ensureServiceReady("删除行程"))) return;

        try {
          const response = await fetch(`${getApiBase()}/api/v1/conversations/${id}`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${state.token}` },
          });
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }

          const wasCurrent = state.currentConversationId === id;
          state.conversations = state.conversations.filter((item) => item.id !== id);
          if (wasCurrent) {
            state.currentConversationId = null;
            document.getElementById("chatTitle").textContent = "行程助手";
            clearChatMessages();
            resetConversationDrafts({ silent: true });
            renderConversationsList();
            setMobileChatFocus(false);
          }
          renderConversationsList();

          if (wasCurrent && state.conversations.length) {
            await switchConversation(state.conversations[0].id);
          } else if (!state.conversations.length) {
            setRuntimeStatus("可以开始新的行程", "online");
          }

          showToast("行程已删除");
        } catch (error) {
          console.error(error);
          setRuntimeStatus("删除失败", "error");
          showToast("删除失败，请稍后重试。", true);
        }
      }

      function focusConversationRenameInput(id, preferHeader = false) {
        requestAnimationFrame(() => {
          const input =
            (preferHeader && document.getElementById("chatTitleRenameInput")) ||
            document.getElementById(`conversationRenameInput-${id}`) ||
            document.getElementById("chatTitleRenameInput");
          if (!input) return;
          input.focus();
          input.select();
        });
      }

      function renderChatTitleRenameInput(id) {
        const chatTitle = document.getElementById("chatTitle");
        const conv = state.conversations.find((item) => item.id === id);
        if (!chatTitle || !conv) return;
        chatTitle.classList.add("editing");
        chatTitle.innerHTML = `
          <input
            id="chatTitleRenameInput"
            class="chat-title-input"
            type="text"
            value="${escapeHtml(conv.title || DEFAULT_CONVERSATION_TITLE)}"
            maxlength="40"
            aria-label="编辑当前行程名称"
            onkeydown="handleConversationRenameKeydown(event, '${id}')"
          />
        `;
      }

      function restoreChatTitleLabel() {
        const chatTitle = document.getElementById("chatTitle");
        if (!chatTitle) return;
        chatTitle.classList.remove("editing");
        chatTitle.textContent =
          getCurrentConversation()?.title || "行程助手";
      }

      function beginConversationRename(event, id, options = {}) {
        event?.stopPropagation();
        const conv = state.conversations.find((item) => item.id === id);
        if (!conv) return;
        state.editingConversationId = id;
        renderConversationsList();
        if (options.focusHeader || state.currentConversationId === id) {
          renderChatTitleRenameInput(id);
        }
        focusConversationRenameInput(id, Boolean(options.focusHeader));
      }

      function cancelConversationRename(event) {
        event?.preventDefault();
        event?.stopPropagation();
        state.editingConversationId = null;
        renderConversationsList();
        restoreChatTitleLabel();
        updateSessionOverview();
      }

      function handleConversationRenameKeydown(event, id) {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          submitConversationRename(event, id);
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelConversationRename(event);
        }
      }

      async function submitConversationRename(event, id) {
        event?.preventDefault();
        event?.stopPropagation();
        if (state.renamingConversationId) return;
        const conv = state.conversations.find((item) => item.id === id);
        const currentTitle = conv?.title || DEFAULT_CONVERSATION_TITLE;
        const input =
          (event?.target?.matches?.(".conversation-title-input, .chat-title-input")
            ? event.target
            : null) ||
          event?.target?.closest?.(".conversation-title-edit-form")?.querySelector?.(
            ".conversation-title-input"
          ) ||
          document.getElementById(`conversationRenameInput-${id}`) ||
          document.getElementById("chatTitleRenameInput");
        const trimmed = input?.value?.trim() || "";
        if (!trimmed || trimmed === currentTitle) {
          cancelConversationRename(event);
          return;
        }
        if (!(await ensureServiceReady("修改行程名称"))) return;
        state.renamingConversationId = id;
        document
          .querySelectorAll(".conversation-save-btn, .conversation-cancel-btn, .conversation-title-input, .chat-title-input")
          .forEach((el) => {
            el.disabled = true;
          });
        try {
          await updateConversationTitle(id, trimmed);
          state.editingConversationId = null;
        } catch (error) {
          console.error(error);
          showToast("修改名称失败，请稍后重试。", true);
          focusConversationRenameInput(id);
        } finally {
          document
            .querySelectorAll(".conversation-save-btn, .conversation-cancel-btn, .conversation-title-input, .chat-title-input")
            .forEach((el) => {
              el.disabled = false;
            });
          state.renamingConversationId = null;
        }
      }

      async function renameConversation(event, id) {
        beginConversationRename(event, id);
      }

      async function renameCurrentConversation() {
        if (!state.currentConversationId) return;
        beginConversationRename(null, state.currentConversationId, {
          focusHeader: true,
        });
      }

      async function createNewConversation() {
        if (!(await ensureServiceReady("创建新行程"))) return;
        try {
          const response = await fetch(`${getApiBase()}/api/v1/conversations`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${state.token}`,
            },
            body: JSON.stringify({ title: "新行程" }),
          });
          if (response.ok) {
            const data = await response.json();
            state.currentConversationId = data.id;
            if (!state.conversations.some((item) => item.id === data.id)) {
              state.conversations = [data, ...state.conversations];
            }
            setMobileChatFocus(true);
            clearChatMessages();
            resetConversationDrafts({ silent: true });
            document.getElementById("chatTitle").textContent = "新行程";
            setMobileChatFocus(true);
            document.getElementById("chatTitle").textContent =
              data.title || DEFAULT_CONVERSATION_TITLE;
            renderConversationsList();
            await loadConversations({ preserveCurrentConversationId: true });
            await loadApprovals({ silent: true });
            updateSessionOverview();
            setRuntimeStatus("新会话已创建", "online");
            showToast("新行程已创建");
          }
        } catch (error) {
          setRuntimeStatus("创建会话失败", "error");
          showToast("创建失败", true);
        }
      }

      async function switchConversation(id) {
        if (!(await ensureServiceReady("切换会话"))) return;
        state.currentConversationId = id;
        setMobileChatFocus(true);
        renderConversationsList();
        setRuntimeStatus("正在加载会话", "loading");

        // 获取标题
        try {
          const res = await fetch(
            `${getApiBase()}/api/v1/conversations/${id}`,
            {
              headers: { Authorization: `Bearer ${state.token}` },
            }
          );
          if (res.ok) {
            const data = await res.json();
            document.getElementById("chatTitle").textContent = data.title;
            const current = state.conversations.find((conv) => conv.id === id);
            if (current) current.title = data.title;
            updateSessionOverview();
          }
        } catch (e) {}

        // 获取历史
        try {
          const res = await fetch(`${getApiBase()}/api/v1/chat/history/${id}`, {
            headers: { Authorization: `Bearer ${state.token}` },
          });
          if (res.ok) {
            const data = await res.json();
            const msgs = Array.isArray(data) ? data : data.messages || [];
            renderMessages(msgs);
            setRuntimeStatus("历史会话已就绪", "online");
          } else clearChatMessages();
        } catch (e) {
          clearChatMessages();
          setRuntimeStatus("加载失败", "error");
        }
        await loadApprovals({ silent: true });
      }

      function hydrateGovernanceFromMessages(messages = []) {
        state.governance.toolAuditEvents = [];
        state.governance.turnObservability = null;
        (Array.isArray(messages) ? messages : []).forEach((msg) => {
          if (msg.role !== "assistant") return;
          const extra = msg.extra_info || msg.extraInfo || {};
          const auditEvents = Array.isArray(extra.tool_audit_events)
            ? extra.tool_audit_events
            : [];
          auditEvents.forEach((event) => {
            const normalized = normalizeToolAuditEvent(event);
            state.governance.toolAuditEvents.unshift(normalized);
          });
          const observation = extra.observability?.metrics || extra.observability;
          if (observation) {
            state.governance.turnObservability = null;
            rememberTurnObservability(observation);
          }
        });
        state.governance.toolAuditEvents = state.governance.toolAuditEvents.slice(0, 20);
        renderToolAuditList();
        renderTurnObservability();
      }

      function renderMessages(messages) {
        const container = document.getElementById("chatMessages");
        hydrateGovernanceFromMessages(messages);
        if (messages.length === 0) {
          clearChatMessages();
          return;
        }
        const lastAssistantIndex = messages
          .map((msg, index) => (msg.role === "assistant" ? index : -1))
          .filter((index) => index >= 0)
          .pop();
        container.innerHTML = messages
          .map(
            (msg, index) => `
                <div class="message ${
                  msg.role
                }" id="msg-${Date.now()}-${Math.random()}">
                    ${buildMessageMarkup(
                      msg.role,
                      msg.content,
                      msg.created_at || msg.updated_at || new Date(),
                      {
                        extraInfo: msg.extra_info || msg.extraInfo || {},
                        suppressJourneyPreview:
                          msg.role === "assistant" && index !== lastAssistantIndex,
                      }
                    )}
                </div>
            `
          )
          .join("");
        scheduleJourneyMapHydration(container);
        container.scrollTop = container.scrollHeight;
      }

      function clearChatMessages() {
        document.getElementById("chatMessages").innerHTML = getWelcomeMarkup();
      }

      function extractStreamContent(rawData) {
        if (!rawData || rawData === "[DONE]") return "";
        try {
          const parsed = JSON.parse(rawData);
          if (typeof parsed.content === "string") return parsed.content;
          if (typeof parsed.delta === "string") return parsed.delta;
          if (typeof parsed.message === "string") return parsed.message;
          return "";
        } catch (error) {
          return rawData;
        }
      }

      function processSseBuffer(buffer, onContent, onEvent = null) {
        const events = buffer.split("\n\n");
        const remainder = events.pop() || "";
        events.forEach((eventBlock) => {
          const dataLines = eventBlock
            .split("\n")
            .filter((line) => line.startsWith("data: "));
          dataLines.forEach((line) => {
            const rawData = line.slice(6).trim();
            if (onEvent) {
              try {
                onEvent(JSON.parse(rawData));
              } catch (error) {
                // 非 JSON SSE 片段仍按纯文本增量处理。
              }
            }
            const content = extractStreamContent(rawData);
            if (content) {
              onContent(content);
            }
          });
        });
        return remainder;
      }

      function buildStreamingFallbackMessage({
        elapsedMs = 0,
        hasPartialContent = false,
        reachedVerySlowStage = false,
      } = {}) {
        if (hasPartialContent) {
          return "\n\n补充说明：这轮回复在中途断开了。你可以直接继续追问，我会尽量接着当前上下文往下补全。";
        }
        if (reachedVerySlowStage || elapsedMs >= 45000) {
          return "这轮等待时间比较久，可能是规划链路较慢，或者交通、住宿这类外部查询还没来得及返回。你可以稍后再试一次，或直接继续追问，我会尽量接着当前上下文继续。";
        }
        return "这轮连接没有顺利完成。你可以稍后重试一次，或换个问法继续，我会接着当前会话往下帮你规划。";
      }

      async function sendMessage() {
        if (!(await ensureServiceReady("发送消息"))) return;
        const input = document.getElementById("chatInput");
        const content = input.value.trim();
        if (!content || state.isLoading) return;

        if (!state.currentConversationId) {
          await createNewConversation();
          if (!state.currentConversationId) return;
        }

        await maybeAutoNameCurrentConversation(content);

        state.isLoading = true;
        setSendButtonLoading(true);
        setRuntimeStatus("正在规划行程", "loading");

        // 移除欢迎页
        const welcome = document.querySelector(".welcome-screen");
        if (welcome) welcome.remove();

        // 用户消息
        addMessage("user", content);
        input.value = "";
        input.style.height = "auto";
        persistComposerDraft();

        // 助手Loading
        const loadingId = addLoading();
        const requestStartedAt = Date.now();
        let reachedSlowStage = false;
        let reachedVerySlowStage = false;
        let streamingMessageId = "";
        let streamingFullText = "";
        let streamingReportData = null;
        let streamingJourneyData = null;
        let streamingPlanningTrace = [];
        const streamingThinkingFilter = createAssistantThinkingFilter();
        const slowHintTimer = setTimeout(() => {
          reachedSlowStage = true;
          updateLoadingCopy(
            loadingId,
            "正在继续整理这次行程建议。如果这轮涉及交通、住宿、地图或外部服务，等待时间会比普通回答更长一些。"
          );
          setRuntimeStatus("外部信息查询中", "loading");
        }, 18000);
        const verySlowHintTimer = setTimeout(() => {
          reachedVerySlowStage = true;
          updateLoadingCopy(
            loadingId,
            "这轮等待时间比平时更久，可能正在查询外部信息，或整理较长的分日建议。页面可以继续保持打开，我会在结果返回后直接补上。"
          );
          setRuntimeStatus("仍在处理中", "loading");
        }, 45000);

        try {
          const res = await fetch(
            `${getApiBase()}/api/v1/chat/stream/${state.currentConversationId}`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${state.token}`,
              },
              body: JSON.stringify({ content }),
            }
          );

          if (
            res.ok &&
            res.headers.get("content-type")?.includes("event-stream")
          ) {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            const appendVisibleChunk = (chunk) => {
              if (!chunk) return;
              if (!streamingMessageId) {
                streamingFullText = chunk;
                streamingMessageId = convertLoadingToAssistant(
                  loadingId,
                  streamingFullText,
                  {
                    suppressJourneyPreview: true,
                    pinToTop: true,
                    reportData: streamingReportData,
                    journeyData: streamingJourneyData,
                    planningTrace: streamingPlanningTrace,
                  }
                );
                return;
              }
              streamingFullText += chunk;
              updateMessage(streamingMessageId, streamingFullText, {
                suppressJourneyPreview: true,
                pinToTop: true,
                reportData: streamingReportData,
                journeyData: streamingJourneyData,
                planningTrace: streamingPlanningTrace,
              });
            };
            const applyChunk = (chunk) => {
              const visibleChunk = streamingThinkingFilter.feed(chunk);
              if (visibleChunk) {
                appendVisibleChunk(visibleChunk);
              }
            };
            const applyStreamEvent = (event) => {
              if (event?.type === "report_data" && event.report_data) {
                streamingReportData = event.report_data;
              }
              if (event?.type === "planning_trace") {
                streamingPlanningTrace = [
                  ...streamingPlanningTrace,
                  {
                    phase: event.phase,
                    status: event.status,
                    title: event.title,
                    detail: event.detail,
                    count: event.count,
                    city: event.city,
                    date_range: event.date_range,
                    evidence_type: event.evidence_type,
                  },
                ].filter((item) => item.title || item.detail);
              }
              if (event?.type === "journey_data" && event.journey_data) {
                streamingJourneyData = event.journey_data;
                if (Array.isArray(event.planning_trace)) {
                  streamingPlanningTrace = event.planning_trace;
                }
              }
              if (event?.type === "tool_audit") {
                rememberToolAuditEvent(event);
              }
              if (event?.type === "turn_observability") {
                rememberTurnObservability(event);
              }
            };

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              buffer = processSseBuffer(buffer, applyChunk, applyStreamEvent);
            }

            const tail = decoder.decode();
            if (tail) {
              buffer += tail;
            }
            if (buffer.trim()) {
              processSseBuffer(`${buffer}\n\n`, applyChunk, applyStreamEvent);
            }
            const visibleTail = streamingThinkingFilter.finish();
            if (visibleTail) {
              appendVisibleChunk(visibleTail);
            }

            if (!streamingMessageId) {
              streamingMessageId = convertLoadingToAssistant(
                loadingId,
                streamingReportData
                  ? "结构化旅游规划报告已整理完成。"
                  : streamingJourneyData
                  ? "可视化旅程草案已整理完成。"
                  : "这次没有拿到可展示的内容，你可以再试一次，或者换个问法继续。",
                {
                  suppressJourneyPreview: false,
                  pinToTop: true,
                  reportData: streamingReportData,
                  journeyData: streamingJourneyData,
                  planningTrace: streamingPlanningTrace,
                }
              );
            } else {
              updateMessage(streamingMessageId, streamingFullText, {
                suppressJourneyPreview: false,
                pinToTop: true,
                reportData: streamingReportData,
                journeyData: streamingJourneyData,
                planningTrace: streamingPlanningTrace,
              });
            }
            setRuntimeStatus("行程建议已整理", "online");
          } else {
            clearTimeout(slowHintTimer);
            removeMessage(loadingId);
            const data = await res.json();
            addMessage(
              "assistant",
              data.content || data.message || JSON.stringify(data)
            );
            if (!res.ok) {
              setRuntimeStatus("请求失败", "error");
            } else {
              setRuntimeStatus("已连接", "online");
            }
          }
        } catch (e) {
          const elapsedMs = Date.now() - requestStartedAt;
          clearTimeout(slowHintTimer);
          clearTimeout(verySlowHintTimer);
          if (streamingMessageId && streamingFullText.trim()) {
            updateMessage(
              streamingMessageId,
              `${streamingFullText}${buildStreamingFallbackMessage({
                elapsedMs,
                hasPartialContent: true,
                reachedVerySlowStage,
              })}`,
              {
                suppressJourneyPreview: true,
                pinToTop: true,
                reportData: streamingReportData,
                journeyData: streamingJourneyData,
                planningTrace: streamingPlanningTrace,
              }
            );
          } else {
            removeMessage(loadingId);
            addMessage(
              "assistant",
              buildStreamingFallbackMessage({
                elapsedMs,
                hasPartialContent: false,
                reachedVerySlowStage,
              })
            );
          }
          setRuntimeStatus("连接异常", "error");
        } finally {
          clearTimeout(slowHintTimer);
          clearTimeout(verySlowHintTimer);
        }

        state.isLoading = false;
        setSendButtonLoading(false);
      }

      function addMessage(role, text, options = {}) {
        const container = document.getElementById("chatMessages");
        const id = "msg-" + Date.now();
        const div = document.createElement("div");
        div.className = `message ${role}`;
        div.id = id;
        div.innerHTML = buildMessageMarkup(role, text, new Date(), options);
        container.appendChild(div);
        scheduleJourneyMapHydration(div);
        container.scrollTop = container.scrollHeight;
        return id;
      }

      function scrollChatMessageToTop(id, behavior = "smooth") {
        const container = document.getElementById("chatMessages");
        const el = document.getElementById(id);
        if (!container || !el) return;

        const targetTop = Math.max(
          el.offsetTop - container.offsetTop - 16,
          0
        );
        container.scrollTo({ top: targetTop, behavior });
      }

      function pinChatMessageToTop(id) {
        if (streamingScrollFrame) {
          cancelAnimationFrame(streamingScrollFrame);
        }
        streamingScrollFrame = requestAnimationFrame(() => {
          scrollChatMessageToTop(id, "auto");
          streamingScrollFrame = null;
        });
      }

      function updateMessage(id, text, options = {}) {
        const el = document.getElementById(id);
        if (el) {
          el.querySelector(".message-text").innerHTML = renderMessageText(
            "assistant",
            text,
            options
          );
          if (!options?.suppressJourneyPreview) {
            scheduleJourneyMapHydration(el);
          }
          if (options?.pinToTop) {
            pinChatMessageToTop(id);
          }
        }
      }

      function convertLoadingToAssistant(id, text, options = {}) {
        const el = document.getElementById(id);
        if (!el) {
          return addMessage("assistant", text, options);
        }
        const messageId = "msg-" + Date.now();
        el.id = messageId;
        el.className = "message assistant";
        el.innerHTML = buildMessageMarkup("assistant", text, new Date(), options);
        if (!options?.suppressJourneyPreview) {
          scheduleJourneyMapHydration(el);
        }
        scrollChatMessageToTop(messageId, options?.pinToTop ? "auto" : "smooth");
        return messageId;
      }

      function addLoading() {
        const container = document.getElementById("chatMessages");
        const id = "loading-" + Date.now();
        const div = document.createElement("div");
        div.className = "message assistant";
        div.id = id;
        div.innerHTML = `
                <div class="message-avatar"><i class="fa-solid fa-compass"></i></div>
                <div class="message-content thinking-card">
                    <div class="thinking-header">
                        <div class="thinking-title">
                            <i class="fa-solid fa-route"></i>
                            正在整理行程建议
                        </div>
                        <span class="thinking-badge">处理中</span>
                    </div>
                    <div class="thinking-copy">正在结合你的需求和已经聊到的信息，整理下一步更完整的建议。</div>
                    <div class="thinking-progress"></div>
                    <div class="typing-dots" style="margin-top: 12px;"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
                </div>
            `;
        container.appendChild(div);
        scrollChatMessageToTop(id);
        return id;
      }

      function updateLoadingCopy(id, text) {
        const el = document.getElementById(id);
        const copy = el?.querySelector(".thinking-copy");
        if (copy) {
          copy.textContent = text;
        }
      }

      function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
      }

      function handleInputKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      }

      function autoResizeTextarea() {
        const el = document.getElementById("chatInput");
        el.addEventListener("input", function () {
          this.style.height = "auto";
          this.style.height = Math.min(this.scrollHeight, 120) + "px";
        });
      }

      function showToast(msg, isError = false) {
        const t = document.getElementById("toast");
        document.getElementById("toastMsg").textContent = msg;
        t.className = `toast show ${isError ? "error" : ""}`;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(() => t.classList.remove("show"), 3000);
      }

      function formatTime(str) {
        if (!str) return "";
        const d = new Date(str);
        return `${d.getMonth() + 1}月${d.getDate()}日`;
      }

      function formatConversationStamp(str) {
        if (!str) return "";
        const d = new Date(str);
        const now = new Date();
        const sameYear = d.getFullYear() === now.getFullYear();
        const day = `${d.getMonth() + 1}月${d.getDate()}日`;
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        return sameYear ? `${day} ${hh}:${mm}` : `${d.getFullYear()}年${day} ${hh}:${mm}`;
      }

      function formatRelativeTime(str) {
        if (!str) return "";
        const d = new Date(str);
        const diff = Date.now() - d.getTime();
        const minute = 60 * 1000;
        const hour = 60 * minute;
        const day = 24 * hour;

        if (diff < minute) return "刚刚更新";
        if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} 分钟前更新`;
        if (diff < day) return `${Math.floor(diff / hour)} 小时前更新`;
        if (diff < day * 2) return "昨天更新";
        if (diff < day * 7) return `${Math.floor(diff / day)} 天前更新`;
        return `更新于 ${formatTime(str)}`;
      }

      function escapeHtml(text) {
        if (!text) return "";
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, "<br>");
      }
