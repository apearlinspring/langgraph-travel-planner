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

    function handleJourneyEditAction(button) {
      if (button.disabled) return false;
      const action = button.dataset.journeyEditAction || "";
      const meta = parseJourneyStopMeta?.(button.dataset.mapDayStop || "");
      const shell = getJourneyMapShellFromControl?.(button);
      if (!action || !meta || !shell) return false;
      const dayPlans = cloneJourneyDayPlans?.(shell)?.map(normalizeJourneyDayPlanStops) || [];
      const day = dayPlans.find((item) => item.key === meta.dayKey);
      if (!day || !Array.isArray(day.stops)) return false;
      const index = meta.stopIndex;
      if (index < 0 || index >= day.stops.length) return false;
      const currentStop = day.stops[index] || {};

      if (action === "delete") {
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
        const workbench = button.closest(".visual-journey-workbench");
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
