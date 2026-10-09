(function (global) {
  function createJourneyMapData(options = {}) {
    const parseJourneyDayNumber =
      typeof options.parseJourneyDayNumber === "function"
        ? options.parseJourneyDayNumber
        : () => 0;
    const cleanJourneyLocationValue =
      typeof options.cleanJourneyLocationValue === "function"
        ? options.cleanJourneyLocationValue
        : (value = "") => String(value || "").replace(/\s+/g, " ").trim();

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

    function getJourneyPlanDayNumber(day = {}, fallback = 0) {
      const explicit = Number(day.dayNumber || day.day_number || day.day || 0);
      if (explicit > 0) return explicit;
      const parsed = parseJourneyDayNumber(
        [day.key, day.label, day.title, day.date].filter(Boolean).join(" ")
      );
      return parsed || fallback || 0;
    }

    function normalizeJourneyModalDayPlan(day = {}, fallback = 0) {
      if (!day || typeof day !== "object") return null;
      const dayNumber = getJourneyPlanDayNumber(day, fallback);
      if (!dayNumber) return null;
      const stops = Array.isArray(day.stops) ? day.stops : [];
      const stopNames = stops
        .map((stop) => cleanJourneyLocationValue(stop?.name || ""))
        .filter(Boolean);
      const waypoints = [
        ...(Array.isArray(day.waypoints) ? day.waypoints : []),
        ...(Array.isArray(day.points) ? day.points.map((point) => point?.name || point?.label || "") : []),
        ...stopNames,
      ]
        .map((item) => cleanJourneyLocationValue(item || ""))
        .filter(Boolean)
        .filter((item, index, list) => list.indexOf(item) === index);
      return {
        ...day,
        key: day.key || `report-day-${dayNumber}`,
        dayNumber,
        label: day.label || `Day ${dayNumber}`,
        title: day.title || day.summary || `Day ${dayNumber}`,
        note: day.note || day.route_note || day.summary || "",
        waypoints,
        stops,
        segments: Array.isArray(day.segments) ? day.segments : [],
      };
    }

    function collectJourneyDayPlanCandidates(source) {
      if (!source) return [];
      const parsed = typeof source === "string" ? parseMapPayload(source) : source;
      if (!parsed) return [];
      if (Array.isArray(parsed)) return parsed;
      if (Array.isArray(parsed.days)) return parsed.days;
      return typeof parsed === "object" ? [parsed] : [];
    }

    function mergeJourneyDayPlanSources(...sources) {
      const byDay = new Map();
      let maxDay = 0;
      sources
        .flatMap((source) => collectJourneyDayPlanCandidates(source))
        .forEach((day, index) => {
          const normalized = normalizeJourneyModalDayPlan(day, index + 1);
          if (!normalized) return;
          maxDay = Math.max(maxDay, normalized.dayNumber);
          const existing = byDay.get(normalized.dayNumber) || {};
          const waypoints = [
            ...(existing.waypoints || []),
            ...(normalized.waypoints || []),
          ].filter((item, itemIndex, list) => item && list.indexOf(item) === itemIndex);
          const stops = [
            ...(Array.isArray(existing.stops) ? existing.stops : []),
            ...(Array.isArray(normalized.stops) ? normalized.stops : []),
          ].filter((stop, stopIndex, list) => {
            const name = cleanJourneyLocationValue(stop?.name || "");
            return name && list.findIndex((item) => cleanJourneyLocationValue(item?.name || "") === name) === stopIndex;
          });
          byDay.set(normalized.dayNumber, {
            ...existing,
            ...normalized,
            key: existing.key || normalized.key,
            label: existing.label || normalized.label,
            title: existing.title || normalized.title,
            note: existing.note || normalized.note,
            waypoints,
            stops,
            segments: (existing.segments || []).length
              ? existing.segments
              : normalized.segments || [],
          });
        });
      const result = [];
      for (let dayNumber = 1; dayNumber <= maxDay; dayNumber += 1) {
        result.push(
          byDay.get(dayNumber) || {
            key: `report-day-${dayNumber}`,
            dayNumber,
            label: `Day ${dayNumber}`,
            title: `Day ${dayNumber}`,
            waypoints: [],
            stops: [],
            segments: [],
            note: "当天路线待核验。",
          }
        );
      }
      return result;
    }

    function mergeMapPayloadWithDayPlans(rawPayload, dayPlans = []) {
      const parsed = typeof rawPayload === "string" ? parseMapPayload(rawPayload) : rawPayload;
      const payload = parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? { ...parsed }
        : {};
      const originalDays = Array.isArray(payload.days) ? payload.days : [];
      const mergedDayPlans = mergeJourneyDayPlanSources(dayPlans, originalDays);
      payload.days = mergedDayPlans.map((day) => {
        const matchingOriginal = originalDays.find(
          (item, index) =>
            getJourneyPlanDayNumber(item, index + 1) === day.dayNumber ||
            (item.key && item.key === day.key)
        ) || {};
        return {
          ...matchingOriginal,
          key: day.key,
          label: day.label,
          waypoints: day.waypoints || [],
          stops: day.stops || [],
          segments: day.segments || matchingOriginal.segments || [],
        };
      });
      return payload;
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

    return {
      serializeMapPayload,
      parseMapPayload,
      getJourneyPlanDayNumber,
      normalizeJourneyModalDayPlan,
      mergeJourneyDayPlanSources,
      mergeMapPayloadWithDayPlans,
      parseJourneyStopMeta,
      cloneJourneyDayPlans,
      normalizeJourneyDayPlanStops,
    };
  }

  global.ZhiXingJourneyMapData = {
    createJourneyMapData,
  };
})(window);
