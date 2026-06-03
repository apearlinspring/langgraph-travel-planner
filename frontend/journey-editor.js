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
    } = deps;

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
      } else {
        return false;
      }

      const normalizedDayPlans = dayPlans.map(normalizeJourneyDayPlanStops);
      const workbench = button.closest(".visual-journey-workbench");
      updateVisualJourneyPoiCards?.(workbench, normalizedDayPlans);
      refreshJourneyMapAfterEdit?.(shell, normalizedDayPlans);
      saveEditedJourneyDraft?.(workbench, normalizedDayPlans);
      showToast?.("已更新当天路线顺序");
      return true;
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
