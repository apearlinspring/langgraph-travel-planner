(function (global) {
  function createJourneyEditor(deps = {}) {
    const {
      parseJourneyStopMeta,
      getJourneyMapShellFromControl,
      cloneJourneyDayPlans,
      normalizeJourneyDayPlanStops,
      updateVisualJourneyPoiCards,
      refreshJourneyMapAfterEdit,
      saveEditedJourneyDraft,
      showToast,
      getVisualJourneyMapEntry,
      setJourneyMapDaySelection,
      focusJourneyDayStop,
      getJourneyReplacementCandidates,
      getJourneyPendingPoiCandidates,
      normalizeJourneyPoiAsStop,
    } = deps;

    function commitJourneyPlanEdit(button, shell, dayPlans, message) {
      const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
      const workbench = button.closest(".visual-journey-workbench");
      updateVisualJourneyPoiCards?.(workbench, normalizedDayPlans);
      refreshJourneyMapAfterEdit?.(shell, normalizedDayPlans);
      saveEditedJourneyDraft?.(workbench, normalizedDayPlans);
      if (message) showToast?.(message);
      return true;
    }

    function getStopCoordinate(stop = {}) {
      const lat = Number(stop.lat);
      const lng = Number(stop.lng);
      return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null;
    }

    function getCoordinateDistance(left = {}, right = {}) {
      const leftPoint = getStopCoordinate(left);
      const rightPoint = getStopCoordinate(right);
      if (!leftPoint || !rightPoint) return Number.POSITIVE_INFINITY;
      const latDiff = leftPoint.lat - rightPoint.lat;
      const lngDiff = leftPoint.lng - rightPoint.lng;
      return latDiff * latDiff + lngDiff * lngDiff;
    }

    function canOptimizeStop(stop = {}) {
      return !stop.locked && Boolean(getStopCoordinate(stop));
    }

    function sortOptimizableRun(stops = [], anchor = null) {
      if (stops.length < 2) return stops.slice();
      const remaining = stops.slice();
      const ordered = [];
      let cursor = anchor && getStopCoordinate(anchor) ? anchor : remaining.shift();
      if (!anchor) ordered.push(cursor);
      while (remaining.length) {
        let bestIndex = 0;
        let bestDistance = getCoordinateDistance(cursor, remaining[0]);
        for (let index = 1; index < remaining.length; index += 1) {
          const distance = getCoordinateDistance(cursor, remaining[index]);
          if (distance < bestDistance) {
            bestDistance = distance;
            bestIndex = index;
          }
        }
        const [nextStop] = remaining.splice(bestIndex, 1);
        ordered.push(nextStop);
        cursor = nextStop;
      }
      return ordered;
    }

    function optimizeJourneyDayStops(stops = []) {
      const nextStops = stops.slice();
      let optimizedCount = 0;
      let index = 0;
      while (index < nextStops.length) {
        if (!canOptimizeStop(nextStops[index])) {
          index += 1;
          continue;
        }
        const start = index;
        while (index < nextStops.length && canOptimizeStop(nextStops[index])) {
          index += 1;
        }
        const run = nextStops.slice(start, index);
        if (run.length < 2) continue;
        const anchor = start > 0 ? nextStops[start - 1] : null;
        const sortedRun = sortOptimizableRun(run, anchor);
        sortedRun.forEach((stop, offset) => {
          nextStops[start + offset] = stop;
        });
        optimizedCount += run.length;
      }
      const changed = nextStops.some((stop, index) => stop !== stops[index]);
      return { stops: nextStops, changed, optimizedCount };
    }

    function hasDuplicateStop(dayPlans, candidate = {}) {
      const candidateId = candidate.id || "";
      const candidateName = String(candidate.name || "").trim().toLowerCase();
      return (dayPlans || []).some((day) =>
        (day.stops || []).some((stop) => {
          if (candidateId && stop.id === candidateId) return true;
          return (
            candidateName &&
            String(stop.name || "").trim().toLowerCase() === candidateName
          );
        })
      );
    }

    function normalizeEditedTimeText(value = "") {
      return String(value || "")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 40);
    }

    function parseEditedDurationMinutes(value = "") {
      const text = String(value || "").trim();
      if (!text) return "";
      const minutes = Math.round(Number(text));
      return Number.isFinite(minutes) && minutes > 0 ? Math.min(minutes, 1440) : null;
    }

    function parseJourneySegmentMeta(value = "") {
      if (!String(value || "").includes(":")) return null;
      const [dayKey, segmentIndexText] = String(value).split(":");
      const segmentIndex = Number(segmentIndexText);
      if (!dayKey || Number.isNaN(segmentIndex)) return null;
      return { dayKey, segmentIndex };
    }

    function normalizeSegmentMode(value = "") {
      const raw = String(value || "").toLowerCase();
      if (/walk|walking|步行/.test(raw)) return "walking";
      if (/bus|公交|metro|subway|地铁|transit/.test(raw)) return "transit";
      if (/taxi|ride|打车|网约车/.test(raw)) return "taxi";
      if (/drive|driving|car|驾车|自驾/.test(raw)) return "taxi";
      return raw || "taxi";
    }

    function getSegmentModeLabel(mode = "") {
      const normalized = normalizeSegmentMode(mode);
      if (normalized === "walking") return "步行";
      if (normalized === "transit") return "公交/地铁";
      if (normalized === "taxi") return "打车";
      return "交通";
    }

    function handleJourneyEditAction(button) {
      if (button.disabled) return false;
      const action = button.dataset.journeyEditAction || "";
      const shell = getJourneyMapShellFromControl?.(button);
      if (!action || !shell) return false;
      const workbench = button.closest(".visual-journey-workbench");
      const dayPlans = cloneJourneyDayPlans?.(shell)?.map(normalizeJourneyDayPlanStops) || [];

      if (action === "add-pending") {
        const dayKey = button.dataset.journeyDayKey || "";
        const pendingPoiId = button.dataset.pendingPoiId || "";
        const pendingPoiName = String(button.dataset.pendingPoiName || "").trim().toLowerCase();
        const day = dayPlans.find((item) => item.key === dayKey);
        if (!day || !Array.isArray(day.stops)) return false;
        const candidates = getJourneyPendingPoiCandidates?.(workbench, dayPlans) || [];
        const candidate = candidates.find((poi) => {
          if (pendingPoiId && poi.id === pendingPoiId) return true;
          return (
            pendingPoiName &&
            String(poi.name || "").trim().toLowerCase() === pendingPoiName
          );
        });
        if (!candidate) {
          showToast?.("这个地点已经在路线中", true);
          return true;
        }
        const normalizedCandidate =
          normalizeJourneyPoiAsStop?.(candidate, { city: day.city || "" }) || candidate;
        if (hasDuplicateStop(dayPlans, normalizedCandidate)) {
          showToast?.(`${normalizedCandidate.name || "这个地点"} 已在路线中`, true);
          return true;
        }
        day.stops.push(normalizedCandidate);
        return commitJourneyPlanEdit(
          button,
          shell,
          dayPlans,
          `已加入 ${normalizedCandidate.name || "待规划地点"}`
        );
      }

      if (action === "optimize-day") {
        const dayKey = button.dataset.journeyDayKey || "";
        const day = dayPlans.find((item) => item.key === dayKey);
        if (!day || !Array.isArray(day.stops)) return false;
        const result = optimizeJourneyDayStops(day.stops);
        if (!result.optimizedCount) {
          showToast?.("可优化地点不足，先补充地图坐标", true);
          return true;
        }
        if (!result.changed) {
          showToast?.("当前顺序已经很顺，锁定点保持不动");
          return true;
        }
        day.stops = result.stops;
        return commitJourneyPlanEdit(
          button,
          shell,
          dayPlans,
          `已优化 ${day.label || "当天"} 顺序，锁定点未移动`
        );
      }

      if (action === "select-segment-mode" || action === "toggle-segment-lock") {
        const segmentMeta = parseJourneySegmentMeta(button.dataset.mapDaySegment || "");
        if (!segmentMeta) return false;
        const day = dayPlans.find((item) => item.key === segmentMeta.dayKey);
        if (!day || !Array.isArray(day.segments)) return false;
        const segment = day.segments[segmentMeta.segmentIndex];
        if (!segment) return false;
        if (action === "select-segment-mode") {
          const selectedMode = normalizeSegmentMode(button.dataset.segmentMode || "");
          const currentMode = normalizeSegmentMode(
            segment.selected_mode || segment.mode || segment.transport_mode || ""
          );
          const modeChanged = selectedMode !== currentMode;
          day.segments[segmentMeta.segmentIndex] = {
            ...segment,
            mode: selectedMode,
            selected_mode: selectedMode,
            ...(modeChanged
              ? {
                  distance_text: "待高德路线核验",
                  duration_text: "待高德路线核验",
                  confidence: "needs_live_route",
                  source: "user_segment_mode_preference",
                  verification_note: "用户已切换交通方式，真实路线和用时待核验。",
                }
              : {}),
          };
          return commitJourneyPlanEdit(
            button,
            shell,
            dayPlans,
            `已选用${getSegmentModeLabel(selectedMode)}，真实路线待核验`
          );
        }
        const currentMode = normalizeSegmentMode(
          segment.selected_mode || segment.mode || segment.transport_mode || ""
        );
        day.segments[segmentMeta.segmentIndex] = {
          ...segment,
          mode: currentMode,
          selected_mode: currentMode,
          locked_by_user: !segment.locked_by_user,
        };
        return commitJourneyPlanEdit(
          button,
          shell,
          dayPlans,
          segment.locked_by_user
            ? "已解除这段交通锁定"
            : `已锁定这段为${getSegmentModeLabel(currentMode)}`
        );
      }

      const meta = parseJourneyStopMeta?.(button.dataset.mapDayStop || "");
      if (!meta) return false;
      const day = dayPlans.find((item) => item.key === meta.dayKey);
      if (!day || !Array.isArray(day.stops)) return false;
      const index = meta.stopIndex;
      if (index < 0 || index >= day.stops.length) return false;
      const currentStop = day.stops[index] || {};

      if (action === "toggle-lock") {
        day.stops[index] = { ...currentStop, locked: !currentStop.locked };
      } else if (action === "save-time") {
        const timeEditor = button.closest("[data-route-time-editor='true']");
        const timeValue = normalizeEditedTimeText(
          timeEditor?.querySelector("input[name='time_range']")?.value || ""
        );
        const durationValue = parseEditedDurationMinutes(
          timeEditor?.querySelector("input[name='duration_minutes']")?.value || ""
        );
        if (durationValue === null) {
          showToast?.("停留时长请输入有效分钟数", true);
          return true;
        }
        if (!timeValue && !durationValue) {
          showToast?.("至少填写时间段或停留分钟", true);
          return true;
        }
        day.stops[index] = {
          ...currentStop,
          time_range: timeValue,
          suggested_time: timeValue,
          duration_minutes: durationValue || "",
        };
        return commitJourneyPlanEdit(
          button,
          shell,
          dayPlans,
          `已更新 ${currentStop.name || "这个地点"} 的时间`
        );
      } else if (action === "delete") {
        if (day.stops.length <= 1) {
          showToast?.("当天至少保留一个地点", true);
          return true;
        }
        day.stops.splice(index, 1);
      } else if (action === "up" && index > 0) {
        [day.stops[index - 1], day.stops[index]] = [day.stops[index], day.stops[index - 1]];
      } else if (action === "down" && index < day.stops.length - 1) {
        [day.stops[index], day.stops[index + 1]] = [day.stops[index + 1], day.stops[index]];
      } else if (action === "prev-day" || action === "next-day") {
        if (day.stops.length <= 1) {
          showToast?.("当天至少保留一个地点", true);
          return true;
        }
        const dayIndex = dayPlans.findIndex((item) => item.key === day.key);
        const targetDay = dayPlans[action === "prev-day" ? dayIndex - 1 : dayIndex + 1];
        if (!targetDay || !Array.isArray(targetDay.stops)) return false;
        const [movedStop] = day.stops.splice(index, 1);
        targetDay.stops.push(movedStop);
      } else if (action === "replace") {
        const candidates = getJourneyReplacementCandidates?.(workbench, dayPlans, day.key, index) || [];
        const replacement = candidates[0];
        if (!replacement) {
          showToast?.("暂时没有可替换的候选地点", true);
          return true;
        }
        day.stops[index] = normalizeJourneyPoiAsStop?.(replacement, currentStop) || replacement;
      } else {
        return false;
      }

      const actionLabels = {
        delete: `已移除 ${currentStop.name || "这个地点"}`,
        up: "已上移地点",
        down: "已下移地点",
        "prev-day": `已移到上一天：${currentStop.name || "这个地点"}`,
        "next-day": `已移到下一天：${currentStop.name || "这个地点"}`,
        replace: `已替换 ${currentStop.name || "这个地点"}`,
        "toggle-lock": currentStop.locked
          ? `已解锁 ${currentStop.name || "这个地点"}`
          : `已锁定 ${currentStop.name || "这个地点"}`,
      };
      return commitJourneyPlanEdit(
        button,
        shell,
        dayPlans,
        actionLabels[action] || "已更新路线"
      );
    }

    function handleVisualJourneyDayFocus(button) {
      const dayKey = button.dataset.mapDayFocus || "all";
      const entry = getVisualJourneyMapEntry?.(button);
      if (!entry) return false;
      setJourneyMapDaySelection?.(entry, dayKey);
      button
        .closest(".visual-journey-workbench")
        ?.querySelector(".journey-live-map-shell")
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      return true;
    }

    function handleVisualJourneyPoiFocus(button) {
      const stopMeta = button.dataset.mapDayStop || "";
      const entry = getVisualJourneyMapEntry?.(button);
      if (!entry) return false;
      if (stopMeta.includes(":")) {
        const [dayKey, stopIndexText] = stopMeta.split(":");
        const stopIndex = Number(stopIndexText);
        focusJourneyDayStop?.(entry, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
      }
      button
        .closest(".visual-journey-workbench")
        ?.querySelector(".journey-live-map-shell")
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      return true;
    }

    function handleWorkbenchClick(event) {
      const visualDayFocusBtn = event.target.closest(".visual-day-focus-btn");
      if (visualDayFocusBtn) {
        return handleVisualJourneyDayFocus(visualDayFocusBtn);
      }

      const visualPoiFocusBtn = event.target.closest(".visual-poi-focus-btn");
      if (visualPoiFocusBtn) {
        return handleVisualJourneyPoiFocus(visualPoiFocusBtn);
      }

      const journeyEditBtn = event.target.closest("[data-journey-edit-action]");
      if (journeyEditBtn) {
        return handleJourneyEditAction(journeyEditBtn);
      }

      return false;
    }

    return {
      handleJourneyEditAction,
      handleVisualJourneyDayFocus,
      handleVisualJourneyPoiFocus,
      handleWorkbenchClick,
    };
  }

  global.ZhiXingJourneyEditor = {
    createJourneyEditor,
  };
})(window);
