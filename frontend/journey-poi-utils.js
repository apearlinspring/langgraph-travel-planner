(function (global) {
  function createJourneyPoiUtils() {
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

    return {
      getPoiVerificationText,
      getPoiVerificationTone,
      normalizeJourneyPoiAsStop,
      getVisualPoiInitial,
      getVisualPoiVerificationBadge,
    };
  }

  global.ZhiXingJourneyPoiUtils = {
    createJourneyPoiUtils,
  };
})(window);
