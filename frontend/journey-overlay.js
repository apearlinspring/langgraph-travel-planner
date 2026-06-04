(function (global) {
  function createJourneyOverlayActions(deps = {}) {
    const {
      parseMapPayload,
      mergeJourneyDayPlanSources,
      mergeMapPayloadWithDayPlans,
      serializeMapPayload,
      hydrateJourneyMap,
      getJourneyMapEntry,
      escapeHtml,
      cloneJourneyDayPlans,
      normalizeJourneyDayPlanStops,
      getJourneyReplacementCandidates,
      normalizeJourneyPoiAsStop,
      updateVisualJourneyPoiCards,
      refreshJourneyMapAfterEdit,
      saveEditedJourneyDraft,
      showToast,
      focusJourneyDayStop,
      parseJourneyStopMeta,
      appendToComposer,
      setRuntimeStatus,
    } = deps;

    function hideJourneyPoiSheetFromButton(button) {
      const sheet = button?.closest(".journey-poi-bottom-sheet");
      if (!sheet) return false;
      sheet.hidden = true;
      sheet.classList.remove("show");
      return true;
    }

    function closeJourneyMapModal() {
      const modal = document.getElementById("journeyMapModal");
      if (!modal) return false;
      modal.classList.remove("show");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("journey-map-modal-open");
      return true;
    }

    function openJourneyMapModalFromButton(button) {
      const shell = button.closest(".journey-live-map-shell");
      const sourceMap = shell?.querySelector(".journey-live-map[data-map-payload]");
      const modal = document.getElementById("journeyMapModal");
      const modalShell = document.getElementById("journeyMapModalShell");
      const modalDays = document.getElementById("journeyMapModalDays");
      if (!shell || !sourceMap || !modal) return false;
      const sourcePayload = parseMapPayload?.(sourceMap.dataset.mapPayload || "") || {};
      const sourceEntry = getJourneyMapEntry?.(sourceMap);
      const title = shell.dataset.mapTitle || "路线地图";
      const dayPlans = mergeJourneyDayPlanSources?.(
        shell.dataset.dayPlans || "",
        sourceEntry?.dayPlans || [],
        sourcePayload?.days || []
      );
      const modalPayload = mergeMapPayloadWithDayPlans?.(sourcePayload, dayPlans);
      const modalTitle = modal.querySelector(".journey-map-modal-title");
      const modalMap = modal.querySelector(".journey-live-map-modal-canvas");
      if (!modalTitle || !modalMap) return false;
      modalTitle.textContent = title;
      if (modalShell) {
        modalShell.dataset.mapTitle = title;
        modalShell.dataset.dayPlans = serializeMapPayload?.(dayPlans);
        modalShell.dataset.routeStops = shell.dataset.routeStops || "[]";
        modalShell.dataset.activeDay = "all";
        modalShell.dataset.dayMode = "solo";
      }
      if (modalDays) {
        modalDays.innerHTML = `
            <button class="journey-map-day-btn active" type="button" data-map-day="all" aria-pressed="true" title="查看全程总览">
              <span>总览</span><small>全程</small>
            </button>
            ${(dayPlans || [])
              .map(
                (day, index) => `
                  <button class="journey-map-day-btn" type="button" data-map-day="${escapeHtml?.(
                    day.key || `day-${index + 1}`
                  )}" aria-pressed="false" title="${escapeHtml?.(
                    day.label || `Day ${index + 1}`
                  )}">
                    <span>${escapeHtml?.(day.label || `Day ${index + 1}`)}</span>
                    <small>单日</small>
                  </button>
                `
              )
              .join("")}
          `;
      }
      modalMap.dataset.mapPayload = serializeMapPayload?.(modalPayload);
      modalMap.dataset.dayPlans = serializeMapPayload?.(dayPlans);
      modalMap.dataset.routeStops = shell.dataset.routeStops || "[]";
      modalMap.dataset.mapReady = "";
      modalMap.innerHTML =
        '<div class="journey-live-map-state loading">正在准备大图地图…</div>';
      modal.classList.add("show");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("journey-map-modal-open");
      hydrateJourneyMap?.(modalMap);
      return true;
    }

    function replaceJourneyPoiFromSheet(sheet, button) {
      const shell = sheet?.closest(".journey-live-map-shell");
      const workbench = sheet?.closest(".visual-journey-workbench");
      const dayKey = sheet?.dataset?.poiDayKey || "";
      const stopIndex = Number(sheet?.dataset?.poiStopIndex || "-1");
      if (!shell || !workbench || !dayKey || !Number.isInteger(stopIndex)) return false;
      const dayPlans =
        cloneJourneyDayPlans?.(shell)?.map((item) => normalizeJourneyDayPlanStops?.(item)) || [];
      const day = dayPlans.find((item) => item.key === dayKey);
      if (!day || !Array.isArray(day.stops) || !day.stops[stopIndex]) return false;
      const candidates = getJourneyReplacementCandidates?.(workbench, dayPlans, dayKey, stopIndex);
      const candidateId = button?.dataset?.replacementPoiId || "";
      const candidate =
        candidates?.find((poi) => poi.id && poi.id === candidateId) || candidates?.[0];
      if (!candidate) return false;
      const previousName = day.stops[stopIndex].name || "当前地点";
      day.stops[stopIndex] = normalizeJourneyPoiAsStop?.(candidate, day.stops[stopIndex]);
      const normalizedDayPlans = dayPlans.map((item) => normalizeJourneyDayPlanStops?.(item));
      updateVisualJourneyPoiCards?.(workbench, normalizedDayPlans);
      refreshJourneyMapAfterEdit?.(shell, normalizedDayPlans);
      saveEditedJourneyDraft?.(workbench, normalizedDayPlans);
      showToast?.(`已将 ${previousName} 替换为 ${candidate.name}`);
      return true;
    }

    function applyJourneyRecommendationFromSheet(sheet, options = {}) {
      const shell = sheet?.closest(".journey-live-map-shell");
      const workbench = sheet?.closest(".visual-journey-workbench");
      const dayKey = sheet?.dataset?.recommendationDayKey || "";
      const candidate = parseMapPayload?.(sheet?.dataset?.recommendationPoi || "");
      if (!shell || !workbench || !dayKey || !candidate?.name) return false;

      const dayPlans =
        cloneJourneyDayPlans?.(shell)?.map((item) => normalizeJourneyDayPlanStops?.(item)) || [];
      const day = dayPlans.find((item) => item.key === dayKey);
      if (!day || !Array.isArray(day.stops)) return false;

      const normalizedCandidate = normalizeJourneyPoiAsStop?.(candidate, {
        city: day.city || "",
      });
      const duplicateIndex = day.stops.findIndex(
        (stop) =>
          (normalizedCandidate.id && stop.id === normalizedCandidate.id) ||
          String(stop.name || "").trim().toLowerCase() ===
            String(normalizedCandidate.name || "").trim().toLowerCase()
      );
      if (duplicateIndex >= 0) {
        focusJourneyDayStop?.(
          getJourneyMapEntry?.(shell.querySelector(".journey-live-map[data-map-payload]")),
          dayKey,
          duplicateIndex
        );
        showToast?.(`${normalizedCandidate.name} 已在当天路线中`);
        return true;
      }

      const activeMeta = parseJourneyStopMeta?.(
        shell.querySelector(".journey-map-stage-stop.active[data-map-day-stop]")?.dataset
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
        showToast?.(`已将 ${previousName} 替换为 ${normalizedCandidate.name}`);
      } else {
        const insertIndex = activeIndex >= 0 ? activeIndex + 1 : day.stops.length;
        day.stops.splice(insertIndex, 0, normalizedCandidate);
        showToast?.(`已把 ${normalizedCandidate.name} 加入 ${day.label || "当天"}`);
      }

      const normalizedDayPlans = dayPlans.map((item) => normalizeJourneyDayPlanStops?.(item));
      updateVisualJourneyPoiCards?.(workbench, normalizedDayPlans);
      refreshJourneyMapAfterEdit?.(shell, normalizedDayPlans);
      saveEditedJourneyDraft?.(workbench, normalizedDayPlans);
      return true;
    }

    function handleJourneyPoiSheetAction(button) {
      const action = button?.dataset?.poiSheetAction || "";
      const sheet = button?.closest(".journey-poi-bottom-sheet");
      const title = sheet?.dataset?.poiTitle || "这个地点";
      const dayLabel = sheet?.dataset?.poiDayLabel || "当天";
      if (action === "replace" && replaceJourneyPoiFromSheet(sheet, button)) {
        return true;
      }
      if (
        action === "add-recommendation" &&
        applyJourneyRecommendationFromSheet(sheet, { replace: false })
      ) {
        return true;
      }
      if (
        action === "replace-recommendation" &&
        applyJourneyRecommendationFromSheet(sheet, { replace: true })
      ) {
        return true;
      }
      const prompts = {
        replace: `把${dayLabel}的「${title}」替换成同片区、更适合当前节奏的备选地点，并同步刷新地图路线。`,
        "add-recommendation": `把推荐点「${title}」加入${dayLabel}，并同步刷新地图路线。`,
        "replace-recommendation": `用推荐点「${title}」替换${dayLabel}当前不合适的地点，并同步刷新地图路线。`,
        verify: `继续核验「${title}」的开放时间、门票/预约，以及它和前后地点之间的交通距离与时长。`,
        keep: `我想保留「${title}」，请基于当前可视化旅程继续补交通、酒店、预算和最终报告所需信息。`,
      };
      const prompt = prompts[action];
      if (!prompt) return false;
      appendToComposer?.(prompt, "replace");
      setRuntimeStatus?.("已把地点调整请求填入输入框", "online");
      return true;
    }

    function handleOverlayClick(event) {
      const poiSheetCloseBtn = event.target.closest("[data-poi-sheet-close='true']");
      if (poiSheetCloseBtn) {
        return hideJourneyPoiSheetFromButton(poiSheetCloseBtn);
      }

      const poiSheetActionBtn = event.target.closest("[data-poi-sheet-action]");
      if (poiSheetActionBtn) {
        return handleJourneyPoiSheetAction(poiSheetActionBtn);
      }

      if (
        event.target.id === "journeyMapModal" ||
        event.target.closest("[data-map-modal-close='true']")
      ) {
        return closeJourneyMapModal();
      }

      return false;
    }

    return {
      closeJourneyMapModal,
      openJourneyMapModalFromButton,
      handleJourneyPoiSheetAction,
      handleOverlayClick,
    };
  }

  global.ZhiXingJourneyOverlay = {
    createJourneyOverlayActions,
  };
})(window);
