(function (global) {
  function createJourneyPoiUtils(options = {}) {
    const parseMapPayload =
      typeof options.parseMapPayload === "function" ? options.parseMapPayload : () => null;
    const normalizeJourneyMatchText =
      typeof options.normalizeJourneyMatchText === "function"
        ? options.normalizeJourneyMatchText
        : (value = "") =>
            String(value || "")
              .toLowerCase()
              .replace(/[^\p{L}\p{N}]+/gu, "")
              .trim();

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
        locked: Boolean(poi.locked || fallback.locked),
      };
    }

    function getVisualPoiInitial(name = "") {
      const normalized = String(name || "").trim();
      return normalized ? normalized.slice(0, 1) : "点";
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

    function getJourneyPoiPool(workbench) {
      const original = parseMapPayload(workbench?.dataset.journeyData || "") || {};
      return [
        ...(Array.isArray(original.alternative_pois) ? original.alternative_pois : []),
        ...(Array.isArray(original.pois) ? original.pois : []),
      ].filter((poi) => poi && typeof poi === "object");
    }

    function getJourneyReplacementCandidates(workbench, dayPlans, dayKey, stopIndex) {
      const allPois = getJourneyPoiPool(workbench);
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

    function getJourneyPendingPoiCandidates(workbench, dayPlans) {
      const allPois = getJourneyPoiPool(workbench);
      if (!allPois.length) return [];
      const activeIds = new Set(
        (dayPlans || []).flatMap((item) =>
          (item.stops || []).map((stop) => stop.id).filter(Boolean)
        )
      );
      const activeNames = new Set(
        (dayPlans || []).flatMap((item) =>
          (item.stops || [])
            .map((stop) => normalizeJourneyMatchText(stop.name || ""))
            .filter(Boolean)
        )
      );
      const seen = new Set();
      return allPois
        .filter((poi) => {
          const name = normalizeJourneyMatchText(poi.name || "");
          const key = poi.id || name;
          if (!name || seen.has(key)) return false;
          seen.add(key);
          if (poi.id && activeIds.has(poi.id)) return false;
          if (activeNames.has(name)) return false;
          return true;
        })
        .sort((left, right) => {
          const leftScore =
            (left.map_verified ? 3 : 0) +
            (typeof left.lng === "number" && typeof left.lat === "number" ? 2 : 0) +
            (left.coordinate_estimated ? 1 : 0);
          const rightScore =
            (right.map_verified ? 3 : 0) +
            (typeof right.lng === "number" && typeof right.lat === "number" ? 2 : 0) +
            (right.coordinate_estimated ? 1 : 0);
          return rightScore - leftScore;
        });
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

    return {
      getPoiVerificationText,
      getPoiVerificationTone,
      normalizeJourneyPoiAsStop,
      getVisualPoiInitial,
      getVisualPoiVerificationBadge,
      getJourneyPoiPool,
      getJourneyReplacementCandidates,
      getJourneyPendingPoiCandidates,
      resolveJourneyRecommendationPoi,
      getJourneyRecommendationTargetDay,
    };
  }

  global.ZhiXingJourneyPoiUtils = {
    createJourneyPoiUtils,
  };
})(window);
