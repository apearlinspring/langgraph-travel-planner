(function (global) {
  function createMapControls(deps = {}) {
    const {
      getJourneyMapEntry,
      syncJourneyMapToggleLabels,
      fitJourneyMapState,
      toggleJourneyRecommendations,
      applyJourneyDayView,
      setJourneyMapStyle,
      focusJourneyMapTarget,
      setJourneyMapDaySelection,
      setJourneyMapDayMode,
      activateJourneyBottomStop,
      focusJourneyDayStop,
      openJourneyMapModalFromButton,
    } = deps;

    function handleJourneyMapAction(button) {
      if (button.disabled) return false;
      const action = button.dataset.mapAction || "";
      const shell = button.closest(".journey-live-map-shell");
      if (action === "toggle-tools") {
        shell?.classList.toggle("journey-map-tools-collapsed");
        syncJourneyMapToggleLabels?.(shell);
        return true;
      }
      if (action === "toggle-sidebar") {
        shell?.classList.toggle("journey-map-sidebar-collapsed");
        syncJourneyMapToggleLabels?.(shell);
        const mapNode = shell?.querySelector(".journey-live-map[data-map-payload]");
        const entry = mapNode ? getJourneyMapEntry?.(mapNode) : null;
        setTimeout(() => entry?.map?.invalidateSize?.(), 80);
        return true;
      }
      if (action === "toggle-day-routes") {
        const routesCard = button.closest(".journey-map-sidebar-routes");
        routesCard?.classList.toggle("is-collapsed");
        syncJourneyMapToggleLabels?.(shell);
        return true;
      }
      if (action === "expand") {
        openJourneyMapModalFromButton?.(button);
        return true;
      }

      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      if (action === "recommendations") {
        toggleJourneyRecommendations?.(entry);
        return true;
      }
      if (action === "highlights") {
        entry.recommendationsVisible = true;
        applyJourneyDayView?.(entry);
      }
      fitJourneyMapState?.(entry, action === "highlights" ? "highlights" : "route");

      shell?.querySelectorAll(".journey-map-action-btn").forEach((btn) => {
        const shouldActivate =
          btn.dataset.mapAction === action &&
          (action === "route" || action === "highlights");
        btn.classList.toggle("active", shouldActivate);
        if (btn.dataset.mapAction === "route" || btn.dataset.mapAction === "highlights") {
          btn.setAttribute("aria-pressed", String(shouldActivate));
        }
      });
      return true;
    }

    function handleJourneyMapStyle(button) {
      if (button.disabled) return false;
      const style = button.dataset.mapStyle || "standard";
      const shell = button.closest(".journey-live-map-shell");
      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      setJourneyMapStyle?.(entry, style);

      shell?.querySelectorAll(".journey-map-style-btn").forEach((btn) => {
        const isActive = btn === button;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", String(isActive));
      });
      return true;
    }

    function handleJourneyMapFocus(button) {
      if (button.disabled) return false;
      const focus = button.dataset.mapFocus || "destination";
      const shell = button.closest(".journey-live-map-shell");
      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      focusJourneyMapTarget?.(entry, focus);

      shell?.querySelectorAll(".journey-map-focus-btn").forEach((btn) => {
        btn.classList.toggle("active", btn === button);
      });
      return true;
    }

    function handleJourneyMapDay(button) {
      if (button.disabled) return false;
      const dayKey = button.dataset.mapDay || "all";
      const shell = button.closest(".journey-live-map-shell");
      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      setJourneyMapDaySelection?.(entry, dayKey);
      return true;
    }

    function handleJourneyMapDayMode(button) {
      if (button.disabled) return false;
      const mode = button.dataset.mapDayMode || "solo";
      const shell = button.closest(".journey-live-map-shell");
      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      setJourneyMapDayMode?.(entry, mode);
      return true;
    }

    function handleJourneyMapStageStop(button) {
      const stopMeta = button.dataset.mapDayStop || "";
      const shell = button.closest(".journey-live-map-shell");
      const node = shell?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);

      if (stopMeta.includes(":")) {
        const [dayKey, stopIndexText] = stopMeta.split(":");
        const stopIndex = Number(stopIndexText);
        activateJourneyBottomStop?.(shell, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
        focusJourneyDayStop?.(entry, dayKey, Number.isNaN(stopIndex) ? 0 : stopIndex);
        return true;
      }

      const focusTarget = button.dataset.mapFocus || "";
      if (focusTarget) {
        focusJourneyMapTarget?.(entry, focusTarget);
        return true;
      }
      return false;
    }

    function handleMapClick(event) {
      const actionBtn = event.target.closest(".journey-map-action-btn");
      if (actionBtn) return handleJourneyMapAction(actionBtn);

      const styleBtn = event.target.closest(".journey-map-style-btn");
      if (styleBtn) return handleJourneyMapStyle(styleBtn);

      const focusBtn = event.target.closest(".journey-map-focus-btn");
      if (focusBtn) return handleJourneyMapFocus(focusBtn);

      const dayBtn = event.target.closest(".journey-map-day-btn");
      if (dayBtn) return handleJourneyMapDay(dayBtn);

      const dayModeBtn = event.target.closest(".journey-map-day-mode-btn");
      if (dayModeBtn) return handleJourneyMapDayMode(dayModeBtn);

      const stageStopBtn = event.target.closest(
        ".journey-map-stage-stop, .journey-live-marker[data-map-day-stop], .journey-live-marker [data-map-day-stop]"
      );
      if (stageStopBtn) return handleJourneyMapStageStop(stageStopBtn);

      return false;
    }

    return {
      handleJourneyMapAction,
      handleJourneyMapStyle,
      handleJourneyMapFocus,
      handleJourneyMapDay,
      handleJourneyMapDayMode,
      handleJourneyMapStageStop,
      handleMapClick,
    };
  }

  global.ZhiXingMapControls = {
    createMapControls,
  };
})(window);
