(function (global) {
  function createJourneyMapView(options = {}) {
    const escapeHtml =
      typeof options.escapeHtml === "function"
        ? options.escapeHtml
        : (value = "") =>
            String(value || "")
              .replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");

    const JOURNEY_DAY_COLORS = [
      "#0f766e",
      "#2563eb",
      "#b45309",
      "#be123c",
      "#4d7c0f",
      "#7c3aed",
    ];

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

    function getJourneySegmentLabelViewOpacity({
      isOverview = true,
      isSelected = false,
      activeMode = "fade",
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
        segment.verification_status,
        segment.verification_label,
        segment.verification_note,
        segment.distance_text,
        segment.duration_text,
      ]
        .filter(Boolean)
        .join(" ");
      if (/amap_driving|verified|已核验|高德/i.test(statusText) && !/待/.test(statusText)) {
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

    function getJourneyPointTooltip(point = {}, fallback = "地点") {
      return [point.name, point.address, point.label, fallback]
        .map((item) => String(item || "").trim())
        .find(Boolean) || "地点";
    }

    function normalizeJourneyRoutePathPoint(point = {}) {
      const lng = Number(point?.lng);
      const lat = Number(point?.lat);
      if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
      return { lng, lat };
    }

    function isSameJourneyRoutePoint(left, right) {
      return (
        left &&
        right &&
        Math.abs(Number(left.lng) - Number(right.lng)) < 0.000001 &&
        Math.abs(Number(left.lat) - Number(right.lat)) < 0.000001
      );
    }

    function getJourneySegmentRoutePoints(dayPoints = [], segments = []) {
      const routePoints = [];
      const normalizedDayPoints = dayPoints
        .map((point) => normalizeJourneyRoutePathPoint(point))
        .filter(Boolean);
      if (!Array.isArray(segments) || !segments.length) {
        return normalizedDayPoints;
      }

      segments.forEach((segment, segmentIndex) => {
        const segmentPath = Array.isArray(segment?.path)
          ? segment.path.map((point) => normalizeJourneyRoutePathPoint(point)).filter(Boolean)
          : [];
        const fallbackPath = [dayPoints[segmentIndex], dayPoints[segmentIndex + 1]]
          .map((point) => normalizeJourneyRoutePathPoint(point))
          .filter(Boolean);
        const chosenPath = segmentPath.length >= 2 ? segmentPath : fallbackPath;
        chosenPath.forEach((point, pointIndex) => {
          if (
            routePoints.length &&
            pointIndex === 0 &&
            isSameJourneyRoutePoint(routePoints[routePoints.length - 1], point)
          ) {
            return;
          }
          routePoints.push(point);
        });
      });

      return routePoints.length >= 2 ? routePoints : normalizedDayPoints;
    }

    function getJourneyDayBadgeLabel(day = {}, index = 0) {
      const label = String(day.label || "").trim();
      if (label && !/^day\s*\d+$/i.test(label)) return label;
      return `Day ${index + 1}`;
    }

    return {
      buildJourneyMapIcon,
      buildJourneyDayMapIcon,
      getJourneyDayColor,
      isJourneyRecommendationPoint,
      getJourneyRecommendationMarkers,
      getJourneySegmentLabelViewOpacity,
      getJourneySegmentLabel,
      getJourneyShortDayLabel,
      getJourneySegmentLabelParts,
      getJourneySegmentLabelTone,
      getJourneySegmentLabelOffset,
      getJourneyMidpoint,
      getJourneyPointTooltip,
      normalizeJourneyRoutePathPoint,
      isSameJourneyRoutePoint,
      getJourneySegmentRoutePoints,
      getJourneyDayBadgeLabel,
    };
  }

  global.ZhiXingJourneyMapView = {
    createJourneyMapView,
  };
})(window);
