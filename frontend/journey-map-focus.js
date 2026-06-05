(function (global) {
  function createJourneyMapFocus(options = {}) {
    const setJourneyMapDaySelection =
      typeof options.setJourneyMapDaySelection === "function"
        ? options.setJourneyMapDaySelection
        : () => {};
    const hideJourneyPoiSheet =
      typeof options.hideJourneyPoiSheet === "function"
        ? options.hideJourneyPoiSheet
        : () => {};

    function buildBoundsFromPoints(L, points = []) {
      if (!points.length) return null;
      return L.latLngBounds(points.map((point) => [point.lat, point.lng]));
    }

    function moveJourneyMapToBounds(map, bounds, options = {}) {
      if (!map || !bounds?.isValid?.()) return false;
      const { padding = [26, 26], animate = false } = options;
      if (bounds.engine === "amap_points") {
        const points = Array.isArray(bounds.points) ? bounds.points : [];
        if (!points.length || typeof map.setZoomAndCenter !== "function") return false;
        const lngValues = points.map((point) => Number(point.lng));
        const latValues = points.map((point) => Number(point.lat));
        const minLng = Math.min(...lngValues);
        const maxLng = Math.max(...lngValues);
        const minLat = Math.min(...latValues);
        const maxLat = Math.max(...latValues);
        const span = Math.max(maxLng - minLng, maxLat - minLat);
        const zoom =
          points.length === 1
            ? 13
            : span < 0.018
              ? 15
              : span < 0.045
                ? 14
                : span < 0.12
                  ? 13
                  : span < 0.35
                    ? 12
                    : 11;
        map.resize?.();
        map.setZoomAndCenter(zoom, [(minLng + maxLng) / 2, (minLat + maxLat) / 2], true);
        map.resize?.();
        return true;
      }
      if (bounds.engine === "amap") {
        const overlays = (bounds.overlays || [])
          .map((item) => item?.overlay || item)
          .filter(Boolean);
        if (!overlays.length || typeof map.setFitView !== "function") return false;
        map.resize?.();
        map.setFitView(overlays, false, [
          padding[1] || 26,
          padding[0] || 26,
          padding[1] || 26,
          padding[0] || 26,
        ]);
        map.resize?.();
        return true;
      }
      if (animate && typeof map.flyToBounds === "function") {
        map.flyToBounds(bounds, { padding, duration: 0.65, easeLinearity: 0.25 });
      } else {
        map.fitBounds(bounds, { padding });
      }
      return true;
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

    function buildAmapBoundsFromPoints(points = []) {
      const normalizedPoints = (Array.isArray(points) ? points : [])
        .map((point) => ({
          lng: Number(point?.lng),
          lat: Number(point?.lat),
        }))
        .filter((point) => Number.isFinite(point.lng) && Number.isFinite(point.lat));
      return {
        engine: "amap_points",
        points: normalizedPoints,
        isValid() {
          return normalizedPoints.length > 0;
        },
      };
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

    function activateJourneyBottomStop(shell, dayKey = "", stopIndex = 0, options = {}) {
      if (!shell || !dayKey) return null;
      const normalizedIndex = Number.isFinite(Number(stopIndex)) ? Number(stopIndex) : 0;
      const targetMeta = `${dayKey}:${normalizedIndex}`;
      shell
        .querySelectorAll(".journey-map-stage-stop.active")
        .forEach((item) => item.classList.remove("active"));
      shell
        .querySelectorAll("[data-journey-day-card].active")
        .forEach((item) => item.classList.remove("active"));

      const stopButton = [...shell.querySelectorAll(".journey-map-stage-stop[data-map-day-stop]")]
        .find((button) => button.dataset.mapDayStop === targetMeta);
      if (!stopButton) return null;
      stopButton.classList.add("active");
      const dayCard = stopButton.closest("[data-journey-day-card]");
      dayCard?.classList.add("active");
      if (options.scroll !== false) {
        stopButton.scrollIntoView({
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
      hideJourneyPoiSheet(entry.shell);
    }

    return {
      buildBoundsFromPoints,
      moveJourneyMapToBounds,
      buildAmapBoundsFromLayers,
      buildAmapBoundsFromPoints,
      fitJourneyMapState,
      focusJourneyMapTarget,
      activateJourneyHighlightCard,
      activateJourneyBottomStop,
      focusJourneyDayStop,
    };
  }

  global.ZhiXingJourneyMapFocus = {
    createJourneyMapFocus,
  };
})(window);
