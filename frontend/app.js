// === 逻辑代码保持不变，仅适配样式类名 ===

      let state = {
        token: "",
        user: null,
        currentConversationId: null,
        conversations: [],
        isLoading: false,
        isAuthLoading: false,
        serviceStatus: "checking",
        lastHealthCheckAt: 0,
        readiness: {
          status: "checking",
          payload: null,
          checkedAt: 0,
        },
        governance: {
          approvalFilter: "all",
          approvals: [],
          approvalEvents: [],
          selectedApprovalId: null,
          isApprovalLoading: false,
          toolAuditEvents: [],
          turnObservability: null,
          progressSnapshot: null,
        },
        plannerCollapsed: localStorage.getItem("zhixing-planner-collapsed") === "1",
        mobileChatFocus: false,
        editingConversationId: null,
        renamingConversationId: null,
      };
      const sessionApi = window.ZhiXingSessionApi;
      const conversationApi = window.ZhiXingConversationApi;
      const guideImportApi = window.ZhiXingGuideImportApi;
      const governanceApi = window.ZhiXingGovernanceApi;
      const journeyApi = window.ZhiXingJourneyApi;
      const journeyEditorFactory = window.ZhiXingJourneyEditor;
      const guideImportFactory = window.ZhiXingGuideImport;
      const journeyOverlayFactory = window.ZhiXingJourneyOverlay;
      const mapControlsFactory = window.ZhiXingMapControls;
      const reportBudgetFactory = window.ZhiXingReportBudget;
      const reportExportFactory = window.ZhiXingReportExport;
      const reportRendererFactory = window.ZhiXingReportRenderer;
      const reportActionsFactory = window.ZhiXingReportActions;
      const draftStorageFactory = window.ZhiXingDraftStorage;
      const runtimeStatusFactory = window.ZhiXingRuntimeStatus;
      const chatStreamFactory = window.ZhiXingChatStream;
      if (!guideImportApi) {
        throw new Error("ZhiXingGuideImportApi is not loaded.");
      }
      let toastTimer = null;
      let streamingScrollFrame = null;
      const composerDraftKey = "zhixing-composer-draft";
      const plannerDraftKey = "zhixing-planner-draft";
      const plannerCollapseKey = "zhixing-planner-collapsed";
      const draftStorage = draftStorageFactory?.createDraftStorage?.({
        getScope: () => state.user?.id || state.user?.username || "guest",
      });
      if (!draftStorage) {
        throw new Error("ZhiXingDraftStorage is not loaded.");
      }
      const {
        readDraftStorage,
        writeDraftStorage,
        clearDraftStorage,
        flushAllDraftStorageWrites,
      } = draftStorage;
      const runtimeStatus = runtimeStatusFactory?.createRuntimeStatus?.({
        document,
      });
      if (!runtimeStatus) {
        throw new Error("ZhiXingRuntimeStatus is not loaded.");
      }
      const {
        setRuntimeStatus,
        updateEndpointTone,
        setServiceBanner,
        setAuthServiceHint,
        setAuthFeedback,
        setFieldError,
        clearAuthErrors,
      } = runtimeStatus;
      const chatStream = chatStreamFactory?.createChatStream?.();
      if (!chatStream) {
        throw new Error("ZhiXingChatStream is not loaded.");
      }
      const {
        createAssistantThinkingFilter,
        processSseBuffer,
        buildStreamingFallbackMessage,
      } = chatStream;

      const getDefaultApiBase = () =>
        window.location.protocol === "file:"
          ? "http://localhost:8000"
          : ["localhost", "127.0.0.1"].includes(window.location.hostname) &&
              window.location.port !== "8000"
            ? "http://127.0.0.1:8000"
          : window.location.origin;

      const getApiBase = () =>
        document.getElementById("apiBase").value || getDefaultApiBase();
      const buildApiRequestOptions = (options = {}) =>
        sessionApi.buildApiRequestOptions(state.token, options);

      async function restoreSessionFromCookie() {
        const result = await sessionApi.restoreSessionFromCookie({
          apiBase: getApiBase(),
          stateToken: state.token,
        });
        if (result.ok) {
          state.user = result.user;
          return true;
        }
        if (result.error) {
          console.warn("Session restore failed", result.error);
        }
        state.token = "";
        state.user = null;
        return false;
      }

      const shouldShowApiConfig = () =>
        window.location.protocol === "file:" ||
        ["localhost", "127.0.0.1"].includes(window.location.hostname);

      const getCurrentConversation = () =>
        state.conversations.find((conv) => conv.id === state.currentConversationId);

      const isMobileViewport = () => window.innerWidth <= 900;
      const journeyMapInstances = new WeakMap();
      const scheduledJourneyMapHydrationRoots = new WeakSet();
      const JOURNEY_MAP_DEGRADE_AFTER_MS = 180000;
      const DEFAULT_CONVERSATION_TITLE = "新行程";
      const journeyTextUtils = window.ZhiXingJourneyTextUtils?.createJourneyTextUtils?.({
        sanitizeConversationTitleSegment,
        isDefaultConversationTitle,
      });
      if (!journeyTextUtils) {
        throw new Error("ZhiXingJourneyTextUtils is not loaded.");
      }
      const {
        extractJourneyCityPairFromConversationTitle,
        parseJourneyChineseDayNumber,
        normalizeJourneyDayHeading,
        parseJourneyDayNumber,
        extractJourneyCityPair,
        extractJourneyPrimaryOrigin,
        extractJourneyPrimaryDestination,
      } = journeyTextUtils;
      const journeyMapData = window.ZhiXingJourneyMapData?.createJourneyMapData?.({
        parseJourneyDayNumber,
        cleanJourneyLocationValue,
      });
      if (!journeyMapData) {
        throw new Error("ZhiXingJourneyMapData is not loaded.");
      }
      const {
        serializeMapPayload,
        parseMapPayload,
        getJourneyPlanDayNumber,
        mergeJourneyDayPlanSources,
        mergeMapPayloadWithDayPlans,
        parseJourneyStopMeta,
        cloneJourneyDayPlans,
        normalizeJourneyDayPlanStops,
      } = journeyMapData;
      const journeyMapView = window.ZhiXingJourneyMapView?.createJourneyMapView?.({
        escapeHtml,
      });
      if (!journeyMapView) {
        throw new Error("ZhiXingJourneyMapView is not loaded.");
      }
      const {
        buildJourneyMapIcon,
        buildJourneyDayMapIcon,
        getJourneyDayColor,
        isJourneyRecommendationPoint,
        getJourneyRecommendationMarkers,
        getJourneySegmentLabelViewOpacity,
        getJourneySegmentLabelParts,
        getJourneySegmentLabelTone,
        getJourneySegmentLabelOffset,
        getJourneyMidpoint,
        getJourneyPointTooltip,
        getJourneySegmentRoutePoints,
        getJourneyDayBadgeLabel,
      } = journeyMapView;
      const journeyMapFocus = window.ZhiXingJourneyMapFocus?.createJourneyMapFocus?.({
        setJourneyMapDaySelection: (...args) => setJourneyMapDaySelection(...args),
        hideJourneyPoiSheet: (...args) => hideJourneyPoiSheet(...args),
      });
      if (!journeyMapFocus) {
        throw new Error("ZhiXingJourneyMapFocus is not loaded.");
      }
      const {
        buildBoundsFromPoints,
        moveJourneyMapToBounds,
        buildAmapBoundsFromLayers,
        fitJourneyMapState,
        focusJourneyMapTarget,
        activateJourneyHighlightCard,
        activateJourneyBottomStop,
        focusJourneyDayStop,
      } = journeyMapFocus;
      const journeyMapShell = window.ZhiXingJourneyMapShell?.createJourneyMapShell?.({
        getJourneyMapEntry: (node) => journeyMapInstances.get(node) || null,
      });
      if (!journeyMapShell) {
        throw new Error("ZhiXingJourneyMapShell is not loaded.");
      }
      const {
        syncJourneyMapToggleLabels,
        getVisualJourneyMapEntry,
        getJourneyMapShellFromControl,
      } = journeyMapShell;
      const journeyPoiUtils = window.ZhiXingJourneyPoiUtils?.createJourneyPoiUtils?.({
        parseMapPayload,
        normalizeJourneyMatchText,
      });
      if (!journeyPoiUtils) {
        throw new Error("ZhiXingJourneyPoiUtils is not loaded.");
      }
      const {
        getPoiVerificationText,
        getPoiVerificationTone,
        normalizeJourneyPoiAsStop,
        getVisualPoiInitial,
        getVisualPoiVerificationBadge,
        getJourneyReplacementCandidates,
        getJourneyPendingPoiCandidates,
        resolveJourneyRecommendationPoi,
        getJourneyRecommendationTargetDay,
      } = journeyPoiUtils;
      const journeyPoiRenderer = window.ZhiXingJourneyPoiRenderer?.createJourneyPoiRenderer?.({
        escapeHtml,
        getVisualPoiInitial,
        getVisualPoiVerificationBadge,
      });
      if (!journeyPoiRenderer) {
        throw new Error("ZhiXingJourneyPoiRenderer is not loaded.");
      }
      const {
        renderVisualPoiMedia,
        renderVisualPoiDetails,
      } = journeyPoiRenderer;
      const journeyEditor = journeyEditorFactory?.createJourneyEditor?.({
        parseJourneyStopMeta: (...args) => parseJourneyStopMeta(...args),
        getJourneyMapShellFromControl: (...args) => getJourneyMapShellFromControl(...args),
        cloneJourneyDayPlans: (...args) => cloneJourneyDayPlans(...args),
        normalizeJourneyDayPlanStops: (...args) => normalizeJourneyDayPlanStops(...args),
        updateVisualJourneyPoiCards: (...args) => updateVisualJourneyPoiCards(...args),
        refreshJourneyMapAfterEdit: (...args) => refreshJourneyMapAfterEdit(...args),
        saveEditedJourneyDraft: (...args) => saveEditedJourneyDraft(...args),
        showToast: (...args) => showToast(...args),
        getVisualJourneyMapEntry: (...args) => getVisualJourneyMapEntry(...args),
        setJourneyMapDaySelection: (...args) => setJourneyMapDaySelection(...args),
        focusJourneyDayStop: (...args) => focusJourneyDayStop(...args),
        getJourneyReplacementCandidates: (...args) => getJourneyReplacementCandidates(...args),
        getJourneyPendingPoiCandidates: (...args) => getJourneyPendingPoiCandidates(...args),
        normalizeJourneyPoiAsStop: (...args) => normalizeJourneyPoiAsStop(...args),
      });
      const guideImport = guideImportFactory?.createGuideImport?.({
        getPlannerFields: () => readPlannerFields(),
        appendToComposer: (...args) => appendToComposer(...args),
        updatePlannerSummary: (...args) => updatePlannerSummary(...args),
        setRuntimeStatus: (...args) => setRuntimeStatus(...args),
        showToast: (...args) => showToast(...args),
        fetchGuideUrl: (url) =>
          guideImportApi.fetchGuideUrl({
            apiBase: getApiBase(),
            stateToken: state.token,
            url,
          }),
        sendMessage: (...args) => sendMessage(...args),
      });
      const reportExport = reportExportFactory?.createReportExport?.({
        getCurrentConversationTitle: () => getCurrentConversation()?.title || "",
        escapeHtml: (...args) => escapeHtml(...args),
      });
      const reportActions = reportActionsFactory?.createReportActions?.({
        appendToComposer: (...args) => appendToComposer(...args),
        setRuntimeStatus: (...args) => setRuntimeStatus(...args),
        showToast: (...args) => showToast(...args),
        exportTravelReport: (...args) => reportExport?.exportTravelReport?.(...args),
        focusJourneyMapTarget: (...args) => focusJourneyMapTarget(...args),
        getJourneyMapEntry: (node) => journeyMapInstances.get(node) || null,
        setJourneyMapDaySelection: (...args) => setJourneyMapDaySelection(...args),
      });
      const reportBudget = reportBudgetFactory?.createReportBudget?.({
        normalizeSectionTitle: (...args) => normalizeSectionTitle(...args),
        getMarkdownTableSpan: (...args) => getMarkdownTableSpan(...args),
        splitTableCells: (...args) => splitTableCells(...args),
        isMeaningfulBudgetAmount: (...args) => isMeaningfulBudgetAmount(...args),
        renderAssistantLines: (...args) => renderAssistantLines(...args),
        formatInlineText: (...args) => formatInlineText(...args),
        escapeHtml: (...args) => escapeHtml(...args),
      });
      const reportRenderer = reportRendererFactory?.createReportRenderer?.({
        escapeHtml: (...args) => escapeHtml(...args),
        normalizeReportDataList: (...args) => normalizeReportDataList(...args),
        renderTravelReportNextAction: (...args) => renderTravelReportNextAction(...args),
        isStructuredTravelReportData: (...args) => isStructuredTravelReportData(...args),
        buildReportDataViewModel: (...args) => buildReportDataViewModel(...args),
        parseReportDataExpectedDays: (...args) => parseReportDataExpectedDays(...args),
        formatReportDataMoney: (...args) => formatReportDataMoney(...args),
        buildReportDataJourneyPreviewState: (...args) =>
          buildReportDataJourneyPreviewState(...args),
        renderJourneyPreview: (...args) => renderJourneyPreview(...args),
        renderReportDataList: (...args) => renderReportDataList(...args),
        renderReportDataDailyItinerary: (...args) => renderReportDataDailyItinerary(...args),
        renderReportDataBudgetItems: (...args) => renderReportDataBudgetItems(...args),
        renderReportDataBudgetConfidence: (...args) =>
          renderReportDataBudgetConfidence(...args),
        renderReportDataHandoffPanel: (...args) => renderReportDataHandoffPanel(...args),
        renderReportDataGovernancePanel: (...args) =>
          renderReportDataGovernancePanel(...args),
        extractReportDayGroups: (...args) => extractReportDayGroups(...args),
        parseJourneyDayNumber: (...args) => parseJourneyDayNumber(...args),
        renderReportDailyNotReadyState: (...args) => renderReportDailyNotReadyState(...args),
        renderAssistantLines: (...args) => renderAssistantLines(...args),
        formatInlineText: (...args) => formatInlineText(...args),
        renderReportBudgetBreakdown: (...args) => renderReportBudgetBreakdown(...args),
        expandStructuredTravelBlocks: (...args) => expandStructuredTravelBlocks(...args),
        hasTravelReportSignal: (...args) => hasTravelReportSignal(...args),
        extractTravelReportSections: (...args) => extractTravelReportSections(...args),
        extractJourneyCityPair: (...args) => extractJourneyCityPair(...args),
        extractJourneyCityPairFromConversationTitle: (...args) =>
          extractJourneyCityPairFromConversationTitle(...args),
        getCurrentConversationTitle: () => getCurrentConversation()?.title || "",
        extractReportExpectedDayCount: (...args) => extractReportExpectedDayCount(...args),
        filterReportSummaryLines: (...args) => filterReportSummaryLines(...args),
        buildJourneyPreviewState: (...args) => buildJourneyPreviewState(...args),
        dedupeTravelReportSections: (...args) => dedupeTravelReportSections(...args),
        mergeTravelReportDailySections: (...args) => mergeTravelReportDailySections(...args),
        shouldRenderJourneyPreviewBlock: (...args) => shouldRenderJourneyPreviewBlock(...args),
        inferTextTravelReportMode: (...args) => inferTextTravelReportMode(...args),
        getReportPlanningModeMeta: (...args) => getReportPlanningModeMeta(...args),
        reportBudget,
      });
      const journeyOverlayActions = journeyOverlayFactory?.createJourneyOverlayActions?.({
        parseMapPayload: (...args) => parseMapPayload(...args),
        mergeJourneyDayPlanSources: (...args) => mergeJourneyDayPlanSources(...args),
        mergeMapPayloadWithDayPlans: (...args) => mergeMapPayloadWithDayPlans(...args),
        serializeMapPayload: (...args) => serializeMapPayload(...args),
        hydrateJourneyMap: (...args) => hydrateJourneyMap(...args),
        getJourneyMapEntry: (node) => journeyMapInstances.get(node) || null,
        escapeHtml: (...args) => escapeHtml(...args),
        cloneJourneyDayPlans: (...args) => cloneJourneyDayPlans(...args),
        normalizeJourneyDayPlanStops: (...args) => normalizeJourneyDayPlanStops(...args),
        getJourneyReplacementCandidates: (...args) =>
          getJourneyReplacementCandidates(...args),
        normalizeJourneyPoiAsStop: (...args) => normalizeJourneyPoiAsStop(...args),
        updateVisualJourneyPoiCards: (...args) => updateVisualJourneyPoiCards(...args),
        refreshJourneyMapAfterEdit: (...args) => refreshJourneyMapAfterEdit(...args),
        saveEditedJourneyDraft: (...args) => saveEditedJourneyDraft(...args),
        showToast: (...args) => showToast(...args),
        focusJourneyDayStop: (...args) => focusJourneyDayStop(...args),
        parseJourneyStopMeta: (...args) => parseJourneyStopMeta(...args),
        appendToComposer: (...args) => appendToComposer(...args),
        setRuntimeStatus: (...args) => setRuntimeStatus(...args),
      });
      const mapControls = mapControlsFactory?.createMapControls?.({
        getJourneyMapEntry: (node) => journeyMapInstances.get(node) || null,
        syncJourneyMapToggleLabels: (...args) => syncJourneyMapToggleLabels(...args),
        fitJourneyMapState: (...args) => fitJourneyMapState(...args),
        toggleJourneyRecommendations: (...args) => toggleJourneyRecommendations(...args),
        applyJourneyDayView: (...args) => applyJourneyDayView(...args),
        setJourneyMapStyle: (...args) => setJourneyMapStyle(...args),
        focusJourneyMapTarget: (...args) => focusJourneyMapTarget(...args),
        setJourneyMapDaySelection: (...args) => setJourneyMapDaySelection(...args),
        setJourneyMapDayMode: (...args) => setJourneyMapDayMode(...args),
        activateJourneyBottomStop: (...args) => activateJourneyBottomStop(...args),
        focusJourneyDayStop: (...args) => focusJourneyDayStop(...args),
        openJourneyMapModalFromButton: (...args) =>
          journeyOverlayActions?.openJourneyMapModalFromButton?.(...args),
      });

      function getAmapPosition(point) {
        return [Number(point.lng), Number(point.lat)];
      }

      function shouldUseAmapJourneyMap(preview, mapConfig) {
        const webKey = String(mapConfig?.amap_web_js_key || "").trim();
        if (!webKey) return false;
        return (
          preview?.provider === "amap-js" ||
          mapConfig?.preferred_provider === "amap-js"
        );
      }

      function normalizeJourneyMatchText(text = "") {
        return String(text || "")
          .toLowerCase()
          .replace(/[^\p{L}\p{N}]+/gu, "")
          .trim();
      }

      function resolveJourneyPlanHighlightIndexes(plan, highlightPoints = []) {
        if (!plan || !Array.isArray(highlightPoints) || !highlightPoints.length) return [];
        const tokens = [...(plan.highlights || []), ...(plan.waypoints || [])]
          .map((item) => normalizeJourneyMatchText(item))
          .filter(Boolean);
        if (!tokens.length) return [];

        const matched = [];
        highlightPoints.forEach((point, index) => {
          const haystacks = [point?.name, point?.address, point?.label]
            .map((item) => normalizeJourneyMatchText(item))
            .filter(Boolean);
          const hit = tokens.some((token) =>
            haystacks.some(
              (field) => field === token || field.includes(token) || token.includes(field)
            )
          );
          if (hit) matched.push(index);
        });
        return [...new Set(matched)];
      }

      function hideJourneyPoiSheet(shell) {
        const sheet = shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        sheet.hidden = true;
        sheet.classList.remove("show");
      }

      function resetJourneyPoiSheetActions(sheet) {
        const replaceButton = sheet?.querySelector("[data-poi-sheet-action='replace'], [data-poi-sheet-action='add-recommendation']");
        const verifyButton = sheet?.querySelector("[data-poi-sheet-action='verify']");
        const keepButton = sheet?.querySelector("[data-poi-sheet-action='keep'], [data-poi-sheet-action='replace-recommendation']");
        if (replaceButton) {
          replaceButton.dataset.poiSheetAction = "replace";
          replaceButton.dataset.replacementPoiId = "";
          replaceButton.textContent = "替换这个点";
        }
        if (verifyButton) {
          verifyButton.dataset.poiSheetAction = "verify";
          verifyButton.textContent = "核验门票交通";
        }
        if (keepButton) {
          keepButton.dataset.poiSheetAction = "keep";
          keepButton.textContent = "保留继续规划";
        }
      }

      function showJourneyPoiSheet(entry, dayKey = "all", stopIndex = 0) {
        const sheet = entry?.shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        resetJourneyPoiSheetActions(sheet);
        sheet.dataset.poiMode = "stop";
        delete sheet.dataset.recommendationPoi;
        delete sheet.dataset.recommendationDayKey;
        const dayPlan = entry.dayPlans?.find((day) => day.key === dayKey);
        const stop = dayPlan?.stops?.[stopIndex];
        const point = entry.dayLayers?.find((layer) => layer.key === dayKey)?.points?.[stopIndex];
        if (!stop && !point) return;

        const title = stop?.name || point?.name || "地点详情";
        const meta = [
          dayPlan?.label,
          stop?.type_label || stop?.type,
          stop?.time_range,
        ].filter(Boolean);
        const durationText = stop?.duration_minutes
          ? `建议停留 ${stop.duration_minutes} 分钟`
          : "停留时间待核验";
        const addressText = stop?.address || point?.address || stop?.map_query || "";
        const verificationText = getPoiVerificationText(stop, point);
        const typeText = stop?.amap_type || stop?.type_label || stop?.type || "";
        const proofItems = [
          { label: verificationText, tone: getPoiVerificationTone(verificationText) },
          { label: addressText, tone: "" },
          { label: typeText, tone: "" },
          ...(Array.isArray(stop?.tags)
            ? stop.tags.slice(0, 2).map((tag) => ({ label: tag, tone: "" }))
            : []),
        ].filter(Boolean);
        sheet.dataset.poiTitle = title;
        sheet.dataset.poiDayLabel = dayPlan?.label || "";
        sheet.dataset.poiDayKey = dayKey;
        sheet.dataset.poiStopIndex = String(stopIndex);
        const workbench = sheet.closest(".visual-journey-workbench");
        const replacement = getJourneyReplacementCandidates(
          workbench,
          entry.dayPlans || [],
          dayKey,
          stopIndex
        )[0];
        const replaceButton = sheet.querySelector("[data-poi-sheet-action='replace']");
        if (replaceButton) {
          replaceButton.dataset.replacementPoiId = replacement?.id || "";
          replaceButton.textContent = replacement?.name
            ? `替换为${replacement.name}`
            : "寻找替换点";
        }
        const media = sheet.querySelector(".journey-poi-bottom-media");
        const imageUrl = String(stop?.image_url || "").trim();
        if (media) {
          media.classList.toggle("has-image", /^https?:\/\//i.test(imageUrl));
          media.style.backgroundImage = /^https?:\/\//i.test(imageUrl)
            ? `url("${imageUrl.replace(/"/g, "%22")}")`
            : "";
          media.querySelector("span")?.replaceChildren(
            document.createTextNode(getVisualPoiInitial(title))
          );
        }
        sheet.querySelector("[data-poi-sheet-title]")?.replaceChildren(
          document.createTextNode(title)
        );
        sheet.querySelector("[data-poi-sheet-meta]")?.replaceChildren(
          document.createTextNode(meta.join(" · ") || "地点信息待核验")
        );
        sheet.querySelector("[data-poi-sheet-desc]")?.replaceChildren(
          document.createTextNode(stop?.description || point?.address || "地点介绍待补充。")
        );
        sheet.querySelector("[data-poi-sheet-duration]")?.replaceChildren(
          document.createTextNode(durationText)
        );
        sheet.querySelector("[data-poi-sheet-cost]")?.replaceChildren(
          document.createTextNode(stop?.estimated_cost || "费用待核验")
        );
        sheet.querySelector("[data-poi-sheet-note]")?.replaceChildren(
          document.createTextNode(
            stop?.verification_note ||
              stop?.reservation_note ||
              "开放、预约、票价和道路情况出发前二次核验。"
          )
        );
        const proof = sheet.querySelector("[data-poi-sheet-proof]");
        if (proof) {
          proof.innerHTML = proofItems
            .slice(0, 5)
            .filter((item) => item.label)
            .map(
              (item) =>
                `<span class="${escapeHtml(item.tone || "")}">${escapeHtml(
                  item.label
                )}</span>`
            )
            .join("");
        }
        sheet.hidden = false;
        requestAnimationFrame(() => sheet.classList.add("show"));
      }

      function showJourneyRecommendationSheet(entry, point = {}) {
        const sheet = entry?.shell?.querySelector(".journey-poi-bottom-sheet");
        if (!sheet) return;
        resetJourneyPoiSheetActions(sheet);
        const workbench = sheet.closest(".visual-journey-workbench");
        const candidate = resolveJourneyRecommendationPoi(workbench, point);
        const targetDay = getJourneyRecommendationTargetDay(entry);
        if (!candidate || !targetDay) return;

        const title = candidate.name || point.name || "推荐点";
        const targetLabel = targetDay.label || targetDay.title || "当天";
        const addressText = candidate.address || point.address || candidate.map_query || "";
        const verificationText = getPoiVerificationText(candidate, point);
        const proofItems = [
          { label: "地图推荐点", tone: "ready" },
          { label: verificationText, tone: getPoiVerificationTone(verificationText) },
          { label: addressText, tone: "" },
          { label: candidate.type_label || candidate.type || "", tone: "" },
          ...(Array.isArray(candidate.tags)
            ? candidate.tags.slice(0, 2).map((tag) => ({ label: tag, tone: "" }))
            : []),
        ].filter(Boolean);

        sheet.dataset.poiMode = "recommendation";
        sheet.dataset.poiTitle = title;
        sheet.dataset.poiDayLabel = targetLabel;
        sheet.dataset.poiDayKey = "";
        sheet.dataset.poiStopIndex = "-1";
        sheet.dataset.recommendationDayKey = targetDay.key || "";
        sheet.dataset.recommendationPoi = serializeMapPayload(candidate);

        const addButton = sheet.querySelector("[data-poi-sheet-action='replace']");
        if (addButton) {
          addButton.dataset.poiSheetAction = "add-recommendation";
          addButton.textContent = `加入${targetLabel}`;
        }
        const replaceButton = sheet.querySelector("[data-poi-sheet-action='keep']");
        if (replaceButton) {
          replaceButton.dataset.poiSheetAction = "replace-recommendation";
          replaceButton.textContent = "替换当天首点";
        }

        const media = sheet.querySelector(".journey-poi-bottom-media");
        const imageUrl = String(candidate.image_url || "").trim();
        if (media) {
          media.classList.toggle("has-image", /^https?:\/\//i.test(imageUrl));
          media.style.backgroundImage = /^https?:\/\//i.test(imageUrl)
            ? `url("${imageUrl.replace(/"/g, "%22")}")`
            : "";
          media.querySelector("span")?.replaceChildren(
            document.createTextNode(getVisualPoiInitial(title))
          );
        }
        sheet.querySelector("[data-poi-sheet-title]")?.replaceChildren(
          document.createTextNode(title)
        );
        sheet.querySelector("[data-poi-sheet-meta]")?.replaceChildren(
          document.createTextNode([targetLabel, candidate.type_label || candidate.type, candidate.time_range].filter(Boolean).join(" · ") || "推荐点待核验")
        );
        sheet.querySelector("[data-poi-sheet-desc]")?.replaceChildren(
          document.createTextNode(candidate.description || point.address || "推荐点详情待补充。")
        );
        sheet.querySelector("[data-poi-sheet-duration]")?.replaceChildren(
          document.createTextNode(
            candidate.duration_minutes
              ? `建议停留 ${candidate.duration_minutes} 分钟`
              : "停留时间待核验"
          )
        );
        sheet.querySelector("[data-poi-sheet-cost]")?.replaceChildren(
          document.createTextNode(candidate.estimated_cost || "费用待核验")
        );
        sheet.querySelector("[data-poi-sheet-note]")?.replaceChildren(
          document.createTextNode(
            candidate.verification_note ||
              candidate.reservation_note ||
              "开放、预约、票价和道路情况出发前二次核验。"
          )
        );
        const proof = sheet.querySelector("[data-poi-sheet-proof]");
        if (proof) {
          proof.innerHTML = proofItems
            .slice(0, 5)
            .filter((item) => item.label)
            .map(
              (item) =>
                `<span class="${escapeHtml(item.tone || "")}">${escapeHtml(item.label)}</span>`
            )
            .join("");
        }
        sheet.hidden = false;
        requestAnimationFrame(() => sheet.classList.add("show"));
      }

      function renderJourneyDayInsight(entry) {
        if (!entry?.shell) return;
        const activeDayKey = entry.activeDayKey || "all";
        const activeMode = entry.dayDisplayMode || "solo";
        const insightTitle = entry.shell.querySelector(".journey-map-day-insight-title");
        const insightCopy = entry.shell.querySelector(".journey-map-day-insight-copy");
        const insightList = entry.shell.querySelector(".journey-map-day-insight-points");
        if (!insightTitle || !insightCopy || !insightList) return;

        if (activeDayKey === "all") {
          const overviewRoute = entry.routeStops
            .map((item) => item.value)
            .filter((item) => item && !/待/.test(item))
            .join(" → ");
          insightTitle.textContent = "当前查看总览路线";
          insightCopy.textContent =
            overviewRoute ||
            "补齐具体地点后会显示更完整的分日路线。";
          insightList.innerHTML = entry.routeStops
            .map(
              (stop) => `
                <li>
                  <span>${escapeHtml(stop.label)}</span>
                  <strong>${escapeHtml(stop.value)}</strong>
                </li>
              `
            )
            .join("");
          return;
        }

        const selectedLayer = entry.dayLayers.find((layer) => layer.key === activeDayKey);
        const selectedPlan =
          entry.dayPlans.find((day) => day.key === activeDayKey) ||
          entry.dayPlans.find((day) => day.label === selectedLayer?.label);
        const selectedLabel = selectedLayer?.label || selectedPlan?.label || "当日";
        const waypoints = selectedPlan?.waypoints?.length
          ? selectedPlan.waypoints
          : selectedLayer?.points?.map((point) => point.name || point.address || point.label) || [];
        const highlights = selectedPlan?.highlights?.length ? selectedPlan.highlights : [];
        const matchedHighlightIndexes = resolveJourneyPlanHighlightIndexes(
          selectedPlan,
          entry.highlightPoints
        );

        insightTitle.textContent = `${selectedLabel} · ${
          activeMode === "solo" ? "单独显示" : "突出显示"
        }`;
        insightCopy.textContent =
          selectedPlan?.note ||
          `${selectedLabel}的路线节点已经高亮出来了，你可以继续看当天怎么走、住哪里、看什么。`;
        insightList.innerHTML = [
          ...waypoints.slice(0, 5).map(
            (point, index) => `
              <li>
                <button
                  class="journey-map-stage-stop journey-map-stage-stop--inline"
                  type="button"
                  data-map-day-stop="${escapeHtml(activeDayKey)}:${index}"
                >
                  <span>${index + 1 < 10 ? `0${index + 1}` : index + 1}</span>
                  <strong>${escapeHtml(point)}</strong>
                  <small>${escapeHtml(selectedLabel)}</small>
                </button>
              </li>
            `
          ),
          ...highlights.slice(0, 2).map(
            (item, index) => `
              <li class="highlight">
                <span>景</span>
                <strong>${escapeHtml(item)}</strong>
              </li>
            `
          ),
        ].join("");
        insightList.querySelectorAll("li.highlight").forEach((item, index) => {
          const highlightText = item.querySelector("strong")?.textContent?.trim();
          if (!highlightText) return;
          item.innerHTML = `
            <button
              class="journey-map-stage-stop journey-map-stage-stop--inline"
              type="button"
              data-map-focus="highlight:${matchedHighlightIndexes[index] ?? 0}"
            >
              <span>景</span>
              <strong>${escapeHtml(highlightText)}</strong>
              <small>${escapeHtml(selectedLayer?.label || "沿途看点")}</small>
            </button>
          `;
        });
      }

      function setJourneyMapStyle(entry, style = "standard") {
        if (!entry?.map) return;
        if (entry.engine === "amap") {
          const amapStyles = {
            standard: "amap://styles/normal",
            terrain: "amap://styles/fresh",
            calm: "amap://styles/whitesmoke",
          };
          entry.map.setMapStyle?.(amapStyles[style] || amapStyles.standard);
          entry.activeLayerKey = style;
          return;
        }
        if (!entry.baseLayers) return;
        const nextLayer = entry.baseLayers[style] || entry.baseLayers.standard;
        if (!nextLayer || entry.activeLayerKey === style) return;
        Object.values(entry.baseLayers).forEach((layer) => {
          if (entry.map.hasLayer(layer)) {
            entry.map.removeLayer(layer);
          }
        });
        nextLayer.addTo(entry.map);
        entry.activeLayerKey = style;
      }

      function setJourneyLayerOpacity(layer, opacity) {
        if (!layer) return;
        if (typeof layer.setOpacity === "function") {
          layer.setOpacity(opacity);
          return;
        }
        if (typeof layer.setOptions === "function") {
          layer.setOptions({
            opacity,
            strokeOpacity: opacity,
            fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
          });
          return;
        }
        if (typeof layer.setStyle === "function") {
          layer.setStyle({
            opacity,
            fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
          });
        }
      }

      function updateJourneyDayButtons(shell, activeDay = "all", activeMode = "fade") {
        shell?.querySelectorAll(".journey-map-day-btn").forEach((btn) => {
          const isActive = (btn.dataset.mapDay || "all") === activeDay;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", String(isActive));
        });
        shell?.querySelectorAll(".journey-map-day-mode-btn").forEach((btn) => {
          const isActive = (btn.dataset.mapDayMode || "solo") === activeMode;
          btn.classList.toggle("active", isActive);
          btn.setAttribute("aria-pressed", String(isActive));
        });
      }

      function applyJourneyDayView(entry) {
        if (!entry) return;
        const activeDayKey = entry.activeDayKey || "all";
        const activeMode = entry.dayDisplayMode || "solo";
        const isOverview = activeDayKey === "all";
        const dayLayers = Array.isArray(entry.dayLayers) ? entry.dayLayers : [];
        const selectedPlan = entry.dayPlans?.find((day) => day.key === activeDayKey);
        const selectedHighlightIndexes = new Set(
          resolveJourneyPlanHighlightIndexes(selectedPlan, entry.highlightPoints)
        );

        dayLayers.forEach((layer) => {
          const isSelected = layer.key === activeDayKey;
          const opacity = isOverview
            ? 0.92
            : activeMode === "solo"
              ? (isSelected ? 0.96 : 0)
              : (isSelected ? 0.98 : 0.18);
          layer.markers.forEach((marker) => setJourneyLayerOpacity(marker, opacity));
          (layer.segmentLabels || []).forEach((label, labelIndex) => {
            const labelOpacity = getJourneySegmentLabelViewOpacity({
              isOverview,
              isSelected,
              activeMode,
              labelIndex,
            });
            setJourneyLayerOpacity(label, labelOpacity);
          });
          setJourneyLayerOpacity(layer.dayBadge, opacity);
          setJourneyLayerOpacity(layer.polyline, opacity);
          if (typeof layer.polyline?.setStyle === "function") {
            layer.polyline.setStyle({
              weight: isOverview ? 6 : isSelected ? 8 : 4,
            });
          }
        });

        const baseOpacity = isOverview ? 1 : activeMode === "solo" ? 0 : 0.32;
        entry.markers.forEach((marker) => setJourneyLayerOpacity(marker, baseOpacity));
        if (entry.routeLine?.setStyle) {
          entry.routeLine.setStyle({
            opacity: baseOpacity,
            weight: isOverview ? 6 : 4,
          });
        }
        getJourneyRecommendationMarkers(entry).forEach((marker, index) => {
          const opacity = isOverview
            ? 0.95
            : selectedHighlightIndexes.size
              ? selectedHighlightIndexes.has(index)
                ? 0.98
                : activeMode === "solo"
                  ? 0.08
                  : 0.22
              : activeMode === "solo"
                ? 0.18
                : 0.38;
          setJourneyLayerOpacity(marker, opacity);
        });
        if (entry.recommendationsVisible === false) {
          getJourneyRecommendationMarkers(entry).forEach((marker) =>
            setJourneyLayerOpacity(marker, 0)
          );
        }

        const selectedLayer = dayLayers.find((layer) => layer.key === activeDayKey);
        if (entry.shell) {
          entry.shell.dataset.activeDay = activeDayKey;
          entry.shell.dataset.dayMode = activeMode;
        }
        const metaValue = entry.shell?.querySelector(".journey-live-map-meta-value");
        if (metaValue) {
          metaValue.textContent = isOverview
            ? `已定位 ${entry.points.length} 个路线地点`
            : selectedLayer
              ? `${selectedLayer.label || selectedPlan?.label || "当日"}已切换为${
                  activeMode === "solo" ? "单日路线" : "重点路线"
                }`
              : `${selectedPlan?.label || "当日"}路线待核验`;
        }
        renderJourneyDayInsight(entry);
        updateJourneyDayButtons(entry.shell, activeDayKey, activeMode);
        syncJourneyRecommendationButtons(entry);
      }

      function syncJourneyRecommendationButtons(entry) {
        const visible = entry?.recommendationsVisible !== false;
        const count = getJourneyRecommendationMarkers(entry).length;
        entry?.shell
          ?.querySelectorAll('[data-map-action="recommendations"]')
          .forEach((button) => {
            button.classList.toggle("active", visible);
            button.setAttribute("aria-pressed", String(visible));
            button.textContent = visible ? "隐藏推荐点" : count ? `推荐点 ${count}` : "推荐点";
          });
      }

      function setJourneyMapDaySelection(entry, dayKey = "all") {
        if (!entry) return;
        const hasLayer = entry.dayLayers?.some((layer) => layer.key === dayKey);
        const hasPlan = entry.dayPlans?.some((day) => day.key === dayKey);
        if (dayKey !== "all" && !hasLayer && !hasPlan) {
          return;
        }
        entry.activeDayKey = dayKey || "all";
        applyJourneyDayView(entry);
        if (dayKey === "all") {
          entry.shell
            ?.querySelectorAll(".journey-map-stage-stop.active, [data-journey-day-card].active")
            .forEach((item) => item.classList.remove("active"));
          fitJourneyMapState(entry, "all");
          return;
        }
        const selectedLayer = entry.dayLayers?.find((layer) => layer.key === dayKey);
        activateJourneyBottomStop(entry.shell, dayKey, 0, {
          expandDrawer: false,
          scroll: false,
        });
        if (selectedLayer?.bounds?.isValid()) {
          moveJourneyMapToBounds(entry.map, selectedLayer.bounds, {
            padding: [30, 30],
            animate: true,
          });
          selectedLayer.markers?.[0]?.openPopup?.();
        }
      }

      function setJourneyMapDayMode(entry, mode = "fade") {
        if (!entry) return;
          entry.dayDisplayMode = mode === "fade" ? "fade" : "solo";
        applyJourneyDayView(entry);
      }

      function toggleJourneyRecommendations(entry) {
        if (!entry) return;
        entry.recommendationsVisible = entry.recommendationsVisible === false;
        applyJourneyDayView(entry);
      }

      function registerJourneyMapEntry(node, entry) {
        const shell = entry.shell;
        const availableDayKeys = new Set(
          [
            ...(entry.dayLayers || []).map((layer) => layer.key),
            ...(entry.dayPlans || []).map((day) => day.key),
          ].filter(Boolean)
        );
        shell?.querySelectorAll(".journey-map-day-btn").forEach((button) => {
          const key = button.dataset.mapDay || "all";
          const enabled = key === "all" || availableDayKeys.has(key);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = false;
        });
        const dayModes = shell?.querySelector(".journey-map-floating-modes");
        if (dayModes) {
          dayModes.hidden = availableDayKeys.size <= 1;
        }
        const enabledFocusTargets = new Set([
          ...Object.keys(entry.pointsByKind || {}),
          ...(entry.recommendationPoints?.length ? ["highlights"] : []),
          ...(entry.routePoints?.length >= 2 ? ["route"] : []),
        ]);
        shell?.querySelectorAll(".journey-map-focus-btn").forEach((button) => {
          const focusTarget = button.dataset.mapFocus || "";
          const enabled =
            !focusTarget ||
            enabledFocusTargets.has(focusTarget) ||
            /^highlight:\d+$/.test(focusTarget);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = !enabled;
        });
        shell?.querySelectorAll(".journey-map-action-btn").forEach((button) => {
          const action = button.dataset.mapAction || "";
          const enabled =
            action === "expand" ||
            action === "toggle-tools" ||
            action === "toggle-sidebar" ||
            action === "toggle-day-routes" ||
            (action === "recommendations" && entry.recommendationPoints?.length > 0) ||
            (action === "route" && entry.routePoints?.length >= 2) ||
            (action === "highlights" && entry.recommendationPoints?.length > 0);
          button.disabled = !enabled;
          button.classList.toggle("disabled", !enabled);
          button.hidden = !enabled;
        });
        syncJourneyMapToggleLabels(shell);
        journeyMapInstances.set(node, entry);
        node
          .closest(".journey-live-map-shell")
          ?.querySelector(".journey-live-map-meta-value")
          ?.replaceChildren(
            document.createTextNode(
              entry.engine === "amap"
                ? `高德地图已定位 ${entry.points.length} 个地点`
                : `已定位 ${entry.points.length} 个路线地点`
            )
          );
        applyJourneyDayView(entry);
        node.dataset.mapReady = "1";
        node.dataset.mapProvider = entry.engine || "leaflet";
        setTimeout(() => {
          if (typeof entry.map?.invalidateSize === "function") {
            entry.map.invalidateSize();
          } else {
            entry.map?.resize?.();
          }
        }, 80);
      }

      function buildAmapMarkerContent(kind = "highlight", text = "●", color = "") {
        const node = document.createElement("div");
        node.className = `journey-live-marker amap-journey-marker kind-${kind}`;
        node.innerHTML = `<span>${escapeHtml(text)}</span>`;
        if (color) {
          node.style.borderColor = color;
          node.style.color = color;
        }
        return node;
      }

      function wrapAmapLayer(overlay, options = {}) {
        const { contentNode = null, infoWindow = null, map = null, point = null } = options;
        return {
          __journeyMapEngine: "amap",
          overlay,
          setOpacity(opacity) {
            if (typeof overlay?.setOpacity === "function") {
              overlay.setOpacity(opacity);
            }
            if (contentNode?.style) {
              contentNode.style.opacity = String(opacity);
            }
            if (typeof overlay?.setOptions === "function") {
              overlay.setOptions({
                strokeOpacity: opacity,
                fillOpacity: Math.max(Math.min(opacity, 1), 0) * 0.45,
              });
            }
          },
          setStyle(style = {}) {
            if (typeof overlay?.setOptions !== "function") return;
            overlay.setOptions({
              strokeOpacity: style.opacity,
              fillOpacity:
                typeof style.fillOpacity === "number" ? style.fillOpacity : undefined,
              strokeWeight: style.weight,
              strokeColor: style.color,
            });
          },
          openPopup() {
            if (infoWindow && map && point) {
              infoWindow.open(map, getAmapPosition(point));
            }
          },
        };
      }

      function createAmapJourneyMarker(AMap, map, point, options = {}) {
        const kind = options.kind || point.kind || "highlight";
        const tooltipText = getJourneyPointTooltip(point, options.label || point.label);
        const contentNode = buildAmapMarkerContent(
          kind,
          options.text || (kind === "highlight" ? "★" : "●"),
          options.color || ""
        );
        contentNode.title = tooltipText;
        if (options.dayKey) {
          contentNode.dataset.mapDayStop = `${options.dayKey}:${options.stopIndex || 0}`;
        }
        const marker = new AMap.Marker({
          position: getAmapPosition(point),
          content: contentNode,
          offset: new AMap.Pixel(-11, -11),
          zIndex: options.zIndex || 100,
          title: tooltipText,
        });
        marker.setTitle?.(tooltipText);
        marker.setMap(map);
        const infoWindow = new AMap.InfoWindow({
          offset: new AMap.Pixel(0, -18),
          content: `
            <div class="amap-journey-popup">
              <strong>${escapeHtml(point.name || point.label || options.label || "地点")}</strong>
              <span>${escapeHtml(point.address || point.label || "")}</span>
            </div>
          `,
        });
        marker.on?.("click", () => {
          infoWindow.open(map, marker.getPosition());
          options.onClick?.();
        });
        return wrapAmapLayer(marker, { contentNode, infoWindow, map, point });
      }

      function createAmapJourneyPolyline(AMap, map, points, options = {}) {
        const path = (points || [])
          .map((point) => getAmapPosition(point))
          .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
        if (path.length < 2) return null;
        const polyline = new AMap.Polyline({
          path,
          strokeColor: options.color || "#0f766e",
          strokeWeight: options.weight || 7,
          strokeOpacity: options.opacity ?? 0.98,
          strokeStyle: options.dashed ? "dashed" : "solid",
          lineJoin: "round",
          lineCap: "round",
          zIndex: options.zIndex || 80,
        });
        polyline.setMap(map);
        return wrapAmapLayer(polyline);
      }

      function createAmapJourneySegmentLabel(
        AMap,
        map,
        left,
        right,
        segment,
        color,
        segmentIndex = 0,
        day = {},
        dayIndex = 0
      ) {
        const labelParts = getJourneySegmentLabelParts(segment, day, dayIndex);
        const midpoint = getJourneyMidpoint(left, right);
        if (!labelParts || !midpoint) return null;
        const tone = getJourneySegmentLabelTone(segment);
        const offset = getJourneySegmentLabelOffset(segmentIndex, dayIndex);
        const contentNode = document.createElement("div");
        contentNode.className = `amap-journey-segment-label ${tone}`;
        contentNode.innerHTML = `<strong>${escapeHtml(labelParts.day)}</strong><span>${escapeHtml(labelParts.metric)}</span>`;
        contentNode.title =
          segment?.verification_note ||
          (tone === "verified" ? "高德路线已核验" : "距离/时长待二次核验");
        contentNode.style.borderColor = color;
        const marker = new AMap.Marker({
          position: [midpoint.lng, midpoint.lat],
          content: contentNode,
          offset: new AMap.Pixel(-58 + offset.x, offset.y),
          zIndex: 160,
        });
        marker.setMap(map);
        return wrapAmapLayer(marker, { contentNode });
      }

      function createAmapJourneyDayBadge(AMap, map, point, day, color, index = 0) {
        if (!point) return null;
        const contentNode = document.createElement("div");
        contentNode.className = "amap-journey-day-badge";
        contentNode.style.borderColor = color;
        contentNode.innerHTML = `
          <strong>${escapeHtml(getJourneyDayBadgeLabel(day, index))}</strong>
          <span>${escapeHtml((day.points || []).length ? `${(day.points || []).length}站` : "路线")}</span>
        `;
        const badgeOffsets = [
          [-18, -58],
          [16, -70],
          [-66, -42],
          [24, -34],
          [-54, -72],
        ];
        const [offsetX, offsetY] = badgeOffsets[Math.abs(Number(index) || 0) % badgeOffsets.length];
        const marker = new AMap.Marker({
          position: getAmapPosition(point),
          content: contentNode,
          offset: new AMap.Pixel(offsetX, offsetY),
          zIndex: 170,
        });
        marker.setMap(map);
        return wrapAmapLayer(marker, { contentNode });
      }

      async function renderAmapJourneyMap(node, payload, preview, mapConfig) {
        const AMap = await journeyApi.loadAmapJourneyMapAssets(
          mapConfig?.amap_web_js_key
        );
        if (!AMap) throw new Error("amap-sdk-unavailable");
        const points = Array.isArray(preview?.points) ? preview.points : [];
        if (!points.length) throw new Error("map-preview-empty");

        node.innerHTML = "";
        node.classList.add("journey-live-map--amap");
        const map = new AMap.Map(node, {
          zoom: 8,
          viewMode: "2D",
          resizeEnable: true,
          mapStyle: "amap://styles/normal",
        });
        map.invalidateSize = () => map.resize?.();
        map.flyTo = ([lat, lng], zoom = 11) => {
          map.setZoomAndCenter(zoom, [lng, lat]);
          return map;
        };
        if (AMap.Scale) map.addControl(new AMap.Scale());
        if (AMap.ToolBar) {
          map.addControl(
            new AMap.ToolBar({
              position: { right: "12px", top: "12px" },
            })
          );
        }

        const orderedKinds = ["origin", "destination", "stay"];
        const routePoints = points
          .filter((point) => orderedKinds.includes(point.kind))
          .sort((a, b) => orderedKinds.indexOf(a.kind) - orderedKinds.indexOf(b.kind));
        const highlightPoints = points.filter((point) => point.kind === "highlight");
        const recommendationPoints = points.filter(isJourneyRecommendationPoint);
        const pointsByKind = Object.fromEntries(
          routePoints.map((point) => [point.kind, point])
        );
        const markersByKind = {};
        const shell = node.closest(".journey-live-map-shell");
        let entry = null;

        const markers = points.map((point) => {
          const highlightIndex =
            point.kind === "highlight" ? markersByKind.highlight?.length || 0 : 0;
          const marker = createAmapJourneyMarker(AMap, map, point, {
            kind: point.kind,
            text: point.kind === "highlight" ? "★" : point.kind === "recommendation" ? "+" : "●",
            onClick:
              point.kind === "recommendation"
                ? () => hideJourneyPoiSheet(shell)
                : point.kind === "highlight"
                ? () => {
                    activateJourneyHighlightCard(shell, highlightIndex);
                  }
                : null,
          });
          if (!markersByKind[point.kind]) markersByKind[point.kind] = [];
          markersByKind[point.kind].push(marker);
          return marker;
        });

        const routeLine =
          routePoints.length >= 2
            ? createAmapJourneyPolyline(AMap, map, routePoints, {
                color: "#a16207",
                weight: 7,
                dashed: true,
                zIndex: 70,
              })
            : null;

        const dayLayers = (Array.isArray(preview?.days) ? preview.days : [])
          .map((day, index) => {
            const dayPoints = Array.isArray(day?.points) ? day.points : [];
            if (!dayPoints.length) return null;
            const color = getJourneyDayColor(index);
            const dayMarkers = dayPoints.map((point, pointIndex) =>
              createAmapJourneyMarker(AMap, map, point, {
                kind: "day",
                text: String(pointIndex + 1),
                color,
                zIndex: 130 + index,
                label: day.label || `Day ${index + 1}`,
                dayKey: day.key || `day-${index + 1}`,
                stopIndex: pointIndex,
                onClick: () => {
                  if (entry) {
                    focusJourneyDayStop(entry, day.key || `day-${index + 1}`, pointIndex);
                  }
                },
              })
            );
            const dayRoutePoints = getJourneySegmentRoutePoints(dayPoints, day.segments);
            const polyline = createAmapJourneyPolyline(AMap, map, dayRoutePoints, {
              color,
              weight: 8,
              zIndex: 90 + index,
            });
            const dayBadge = createAmapJourneyDayBadge(
              AMap,
              map,
              dayPoints[0],
              day,
              color,
              index
            );
            const segmentLabels = (Array.isArray(day?.segments) ? day.segments : [])
              .map((segment, segmentIndex) =>
                createAmapJourneySegmentLabel(
                  AMap,
                  map,
                  dayPoints[segmentIndex],
                  dayPoints[segmentIndex + 1],
                  segment,
                  color,
                  segmentIndex,
                  day,
                  index
                )
              )
              .filter(Boolean);
            return {
              key: day.key || `day-${index + 1}`,
              label: day.label || `Day ${index + 1}`,
              points: dayPoints,
              markers: dayMarkers,
              dayBadge,
              segmentLabels,
              polyline,
              bounds: buildAmapBoundsFromLayers([...dayMarkers, dayBadge, polyline, ...segmentLabels].filter(Boolean)),
            };
          })
          .filter(Boolean);

        const allBounds = buildAmapBoundsFromLayers([
          ...markers,
          routeLine,
          ...dayLayers.flatMap((layer) => [...layer.markers, layer.dayBadge, layer.polyline, ...(layer.segmentLabels || [])]),
        ].filter(Boolean));
        const dayBounds = buildAmapBoundsFromLayers(
          dayLayers.flatMap((layer) => [...layer.markers, layer.dayBadge, layer.polyline, ...(layer.segmentLabels || [])]).filter(Boolean)
        );
        const routeBounds = buildAmapBoundsFromLayers([
          ...orderedKinds.flatMap((kind) => markersByKind[kind] || []),
          routeLine,
        ].filter(Boolean));
        const highlightBounds = buildAmapBoundsFromLayers([
          ...(markersByKind.highlight || []),
          ...(markersByKind.recommendation || []),
        ]);
        if (points.length === 1) {
          map.setZoomAndCenter(11, getAmapPosition(points[0]));
        } else {
          fitJourneyMapState(
            {
              map,
              allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
              routeBounds,
              highlightBounds,
            },
            "all"
          );
        }

        entry = {
          engine: "amap",
          map,
          baseLayers: null,
          activeLayerKey: "standard",
          shell,
          points,
          pointsByKind,
          markersByKind,
          routePoints,
          highlightPoints,
          recommendationPoints,
          markers,
          routeLine,
          dayLayers,
          dayPlans: parseMapPayload(shell?.dataset.dayPlans || "") || [],
          routeStops: parseMapPayload(shell?.dataset.routeStops || "") || [],
          activeDayKey: "all",
          dayDisplayMode: "solo",
          recommendationsVisible: false,
          allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
          routeBounds,
          highlightBounds,
        };
        registerJourneyMapEntry(node, entry);
      }

      async function hydrateJourneyMap(node) {
        if (!node || node.dataset.mapReady === "1" || node.dataset.mapReady === "loading") {
          return;
        }
        const payload = parseMapPayload(node.dataset.mapPayload || "");
        if (!payload) {
          node.dataset.mapReady = "error";
          node.innerHTML = '<div class="journey-live-map-state error">路线地图载入失败</div>';
          return;
        }

        node.dataset.mapReady = "loading";
        node.innerHTML = '<div class="journey-live-map-state loading">正在定位行程路线的关键地点…</div>';
        const longMapTimer = setTimeout(() => {
          if (node.dataset.mapReady === "loading") {
            console.warn("Map preview still loading after 180s", {
              hasPayload: Boolean(node.dataset.mapPayload),
              payloadSize: (node.dataset.mapPayload || "").length,
              routeTitle: node.closest(".journey-live-map-shell")?.dataset?.mapTitle || "",
            });
            node.dataset.mapReady = "error";
            node.dataset.mapDegraded = "timeout";
            node.innerHTML =
              '<div class="journey-live-map-state error">路线地图定位超过 180 秒，已先保留文字路线。</div>';
          }
        }, JOURNEY_MAP_DEGRADE_AFTER_MS);

        try {
          const preview = await journeyApi.fetchJourneyMapPreview({
            apiBase: getApiBase(),
            stateToken: state.token,
            payload,
          });
          if (node.dataset.mapDegraded === "timeout") {
            return;
          }
          const points = Array.isArray(preview?.points) ? preview.points : [];
          if (!points.length) {
            throw new Error(preview?.message || "map-preview-empty");
          }

          const mapConfig =
            preview?.provider === "amap-js"
              ? await journeyApi.fetchJourneyMapConfig({
                  apiBase: getApiBase(),
                  stateToken: state.token,
                })
              : journeyApi.getFallbackJourneyMapConfig();
          if (shouldUseAmapJourneyMap(preview, mapConfig)) {
            try {
              await renderAmapJourneyMap(node, payload, preview, mapConfig);
              return;
            } catch (amapError) {
              node.classList.remove("journey-live-map--amap");
              console.warn("AMap journey map failed, falling back to Leaflet", amapError);
            }
          }

          const L = await journeyApi.loadJourneyMapAssets();
          node.innerHTML = "";
          node.classList.remove("journey-live-map--amap");
          const map = L.map(node, {
            zoomControl: true,
            scrollWheelZoom: false,
            attributionControl: true,
          });
          const baseLayers = {
            standard: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
              maxZoom: 18,
              attribution: "&copy; OpenStreetMap contributors",
            }),
            terrain: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
              maxZoom: 17,
              attribution: "Map data: &copy; OpenTopoMap contributors",
            }),
            calm: L.tileLayer(
              "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
              {
                maxZoom: 19,
                attribution: "&copy; CARTO & OpenStreetMap contributors",
              }
            ),
          };
          baseLayers.standard.addTo(map);

          const orderedKinds = ["origin", "destination", "stay"];
          const routePoints = points
            .filter((point) => orderedKinds.includes(point.kind))
            .sort((a, b) => orderedKinds.indexOf(a.kind) - orderedKinds.indexOf(b.kind));
          const highlightPoints = points.filter((point) => point.kind === "highlight");
          const recommendationPoints = points.filter(isJourneyRecommendationPoint);
          const pointsByKind = Object.fromEntries(
            routePoints.map((point) => [point.kind, point])
          );
          const markersByKind = {};
          const shell = node.closest(".journey-live-map-shell");
          let entry = null;

          const latLngs = [];
          const markers = [];
          points.forEach((point) => {
            const marker = L.marker([point.lat, point.lng], {
              icon: buildJourneyMapIcon(L, point.kind),
            }).addTo(map);
            marker.bindPopup(
              `<strong>${escapeHtml(point.name || point.label)}</strong><br>${escapeHtml(
                point.address || point.label || ""
              )}`
            );
            marker.bindTooltip(escapeHtml(getJourneyPointTooltip(point, point.label)), {
              direction: "top",
              sticky: true,
              opacity: 0.96,
            });
            if (point.kind === "highlight") {
              const highlightIndex = markersByKind.highlight?.length || 0;
              marker.on("click", () => {
                activateJourneyHighlightCard(shell, highlightIndex);
              });
            } else if (point.kind === "recommendation") {
              marker.on("click", () => hideJourneyPoiSheet(shell));
            }
            latLngs.push([point.lat, point.lng]);
            markers.push(marker);
            if (!markersByKind[point.kind]) markersByKind[point.kind] = [];
            markersByKind[point.kind].push(marker);
          });

          let routeLine = null;
          if (routePoints.length >= 2) {
            const routeLatLngs = routePoints.map((point) => [point.lat, point.lng]);
            routeLine = L.polyline(routeLatLngs, {
              color: "#a16207",
              weight: 6,
              opacity: 0.95,
              dashArray: "10 8",
            }).addTo(map);
          }

          const dayLayers = (Array.isArray(preview?.days) ? preview.days : [])
            .map((day, index) => {
              const dayPoints = Array.isArray(day?.points) ? day.points : [];
              if (!dayPoints.length) return null;
              const color = getJourneyDayColor(index);
              const markers = dayPoints.map((point, pointIndex) => {
                const dayKey = day.key || `day-${index + 1}`;
                const marker = L.marker([point.lat, point.lng], {
                  icon: buildJourneyDayMapIcon(
                    L,
                    String(pointIndex + 1),
                    color,
                    dayKey,
                    pointIndex
                  ),
                }).addTo(map);
                const markerElement = marker.getElement?.() || marker._icon || marker._element;
                if (markerElement?.dataset) {
                  markerElement.dataset.mapDayStop = `${dayKey}:${pointIndex}`;
                }
                marker.bindPopup(
                  `<strong>${escapeHtml(day.label || `Day ${index + 1}`)}</strong><br>${escapeHtml(
                    point.address || point.name
                  )}`
                );
                marker.bindTooltip(escapeHtml(getJourneyPointTooltip(point, day.label || `Day ${index + 1}`)), {
                  direction: "top",
                  sticky: true,
                  opacity: 0.96,
                });
                marker.on("click", () => {
                  if (entry) {
                    focusJourneyDayStop(entry, dayKey, pointIndex);
                  }
                });
                return marker;
              });
              const dayLatLngs = getJourneySegmentRoutePoints(dayPoints, day.segments).map((point) => [
                point.lat,
                point.lng,
              ]);
              const polyline =
                dayLatLngs.length >= 2
                  ? L.polyline(dayLatLngs, {
                      color,
                      weight: 7,
                      opacity: 1,
                    }).addTo(map)
                  : null;
              const firstPoint = dayPoints[0];
              const dayBadge = firstPoint
                ? L.marker([firstPoint.lat, firstPoint.lng], {
                    icon: L.divIcon({
                      className: "leaflet-journey-day-badge",
                      html: `<span style="border-color:${escapeHtml(color)}"><strong>${escapeHtml(
                        getJourneyDayBadgeLabel(day, index)
                      )}</strong><small>${escapeHtml(dayPoints.length ? `${dayPoints.length}站` : "路线")}</small></span>`,
                      iconSize: [118, 42],
                      iconAnchor: [
                        [18, -18, 66, -24, 54][Math.abs(index) % 5],
                        [52, 64, 42, 34, 70][Math.abs(index) % 5],
                      ],
                    }),
                    interactive: false,
                  }).addTo(map)
                : null;
              const segmentLabels = (Array.isArray(day?.segments) ? day.segments : [])
                .map((segment, segmentIndex) => {
                  const midpoint = getJourneyMidpoint(
                    dayPoints[segmentIndex],
                    dayPoints[segmentIndex + 1]
                  );
                  const labelParts = getJourneySegmentLabelParts(segment, day, index);
                  if (!midpoint || !labelParts) return null;
                  const tone = getJourneySegmentLabelTone(segment);
                  const offset = getJourneySegmentLabelOffset(segmentIndex, index);
                  return L.marker([midpoint.lat, midpoint.lng], {
                    icon: L.divIcon({
                      className: "leaflet-journey-segment-label",
                      html: `<span class="${escapeHtml(tone)}" style="border-color:${escapeHtml(color)}" title="${escapeHtml(
                        segment?.verification_note ||
                          (tone === "verified" ? "高德路线已核验" : "距离/时长待二次核验")
                      )}"><strong>${escapeHtml(labelParts.day)}</strong><small>${escapeHtml(
                        labelParts.metric
                      )}</small></span>`,
                      iconSize: [160, 40],
                      iconAnchor: [80 - offset.x, 20 - offset.y],
                    }),
                    interactive: false,
                  }).addTo(map);
                })
                .filter(Boolean);
              return {
                key: day.key || `day-${index + 1}`,
                label: day.label || `Day ${index + 1}`,
                points: dayPoints,
                markers,
                dayBadge,
                segmentLabels,
                polyline,
                bounds: buildBoundsFromPoints(L, dayPoints),
              };
            })
            .filter(Boolean);

          const allBounds = buildBoundsFromPoints(L, points);
          const routeBounds = buildBoundsFromPoints(L, routePoints);
          const highlightBounds = buildBoundsFromPoints(L, recommendationPoints);
          const dayBounds = buildBoundsFromPoints(
            L,
            dayLayers.flatMap((layer) => layer.points || [])
          );
          if (latLngs.length === 1) {
            map.setView(latLngs[0], 11);
          } else {
            fitJourneyMapState(
              {
                map,
                allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
                routeBounds,
                highlightBounds,
              },
              "all"
            );
          }

          entry = {
            map,
            baseLayers,
            activeLayerKey: "standard",
            shell,
            points,
            pointsByKind,
            markersByKind,
            routePoints,
            highlightPoints,
            recommendationPoints,
            markers,
            routeLine,
            dayLayers,
            dayPlans: parseMapPayload(shell?.dataset.dayPlans || "") || [],
            routeStops: parseMapPayload(shell?.dataset.routeStops || "") || [],
            activeDayKey: "all",
            dayDisplayMode: "solo",
            recommendationsVisible: false,
            allBounds: dayBounds?.isValid() ? dayBounds : allBounds,
            routeBounds,
            highlightBounds,
          };
          registerJourneyMapEntry(node, entry);
        } catch (error) {
          node.dataset.mapReady = "error";
          node.innerHTML =
            `<div class="journey-live-map-state error">${escapeHtml(
              error?.name === "AbortError"
                ? "地图定位超过 12 秒，已先保留文字路线。"
                : error?.message && !/^map-preview/.test(error.message)
                  ? error.message
                  : "暂时没能定位到路线地图，请先查看文字方案。"
            )}</div>`;
        } finally {
          clearTimeout(longMapTimer);
        }
      }

      function getHydratableJourneyMapNodes(root = document) {
        if (!root) return [];
        const nodes = [];
        if (root.matches?.(".journey-live-map[data-map-payload]")) {
          nodes.push(root);
        }
        root
          .querySelectorAll?.(".journey-live-map[data-map-payload]")
          .forEach((node) => {
            if (node !== root) nodes.push(node);
          });
        return nodes;
      }

      function hydrateJourneyMaps(root = document) {
        getHydratableJourneyMapNodes(root).forEach((node) => hydrateJourneyMap(node));
      }

      function scheduleJourneyMapHydration(root = document) {
        if (
          !getHydratableJourneyMapNodes(root).length ||
          scheduledJourneyMapHydrationRoots.has(root)
        ) {
          return;
        }
        scheduledJourneyMapHydrationRoots.add(root);
        requestAnimationFrame(() => {
          scheduledJourneyMapHydrationRoots.delete(root);
          hydrateJourneyMaps(root);
        });
      }

      function getJourneyDayRouteStatus(day = {}) {
        const segments = Array.isArray(day.segments) ? day.segments : [];
        if (!segments.length) {
          return {
            tone: "pending",
            label: "路线参考",
            detail: "路程时间行前确认",
          };
        }
        const metricReadyCount = segments.filter((segment) => {
          const metricText = [segment.distance_text, segment.duration_text]
            .filter(Boolean)
            .join(" ");
          return metricText && !/待|needs|unknown/i.test(metricText);
        }).length;
        const verifiedCount = segments.filter(
          (segment) => String(segment.confidence || "") === "amap_driving"
        ).length;
        const estimatedCount = segments.filter((segment) =>
          /estimated|估算/i.test(
            [segment.confidence, segment.source, segment.verification_note]
              .filter(Boolean)
              .join(" ")
          )
        ).length;
        const missingCount = Math.max(segments.length - metricReadyCount, 0);
        if (verifiedCount === segments.length) {
          return {
            tone: "ready",
            label: "路线已核验",
            detail: `${segments.length} 段路程已返回高德距离/时长`,
          };
        }
        if (verifiedCount || estimatedCount || metricReadyCount) {
          return {
            tone: "pending",
            label: verifiedCount ? "部分路线已回填" : "路线已估算",
            detail: `${verifiedCount} 段已核验，${estimatedCount} 段参考估算，${missingCount} 段行前确认`,
          };
        }
        return {
          tone: "pending",
          label: "路线参考",
          detail: `${segments.length} 段路程时间行前确认`,
        };
      }

      function getJourneyDayWeatherStatus(day = {}) {
        const weather = day.weather && typeof day.weather === "object" ? day.weather : {};
        const summary = String(weather.summary || "").trim();
        const city = String(weather.city || day.city || "").trim();
        if (!summary) {
          return {
            tone: "pending",
            label: city ? `${city}天气提示` : "天气提示",
            detail: "出发前确认",
          };
        }
        return {
          tone: /待|needs/i.test(String(weather.confidence || summary))
            ? "pending"
            : "ready",
          label: city ? `${city}天气` : "天气",
          detail: summary,
        };
      }

      function renderJourneyDayStatusChips(day = {}) {
        const routeStatus = getJourneyDayRouteStatus(day);
        const weatherStatus = getJourneyDayWeatherStatus(day);
        const poiCount = Array.isArray(day.pois)
          ? day.pois.length
          : Array.isArray(day.stops)
          ? day.stops.length
          : Array.isArray(day.waypoints)
          ? day.waypoints.length
          : 0;
        return `
          <span class="journey-day-status-chips">
            <span class="journey-status-chip ready">
              <i class="fa-solid fa-location-dot"></i> ${poiCount || 0} 个地点
            </span>
            <span class="journey-status-chip ${escapeHtml(routeStatus.tone)}">
              <i class="fa-solid fa-route"></i> ${escapeHtml(routeStatus.label)}
            </span>
            <span class="journey-status-chip ${escapeHtml(weatherStatus.tone)}" title="${escapeHtml(
              weatherStatus.detail
            )}">
              <i class="fa-solid fa-cloud-sun"></i> ${escapeHtml(weatherStatus.label)}
            </span>
          </span>
        `;
      }

      function buildVisualJourneyStats(journeyData = {}) {
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const pois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const segments = Array.isArray(journeyData.segments) ? journeyData.segments : [];
        const pendingChecks = Array.isArray(journeyData.pending_checks)
          ? journeyData.pending_checks
          : [];
        const routeNeedsCheck =
          !segments.length ||
          segments.some((segment) =>
            /待|needs|fallback|unknown|estimated|估算/i.test(
              [segment.confidence, segment.distance_text, segment.duration_text]
                .filter(Boolean)
                .join(" ")
            )
          );
        const verifiedRouteCount = segments.filter(
          (segment) => String(segment.confidence || "") === "amap_driving"
        ).length;
        const estimatedRouteCount = segments.filter((segment) =>
          /estimated|估算/i.test(
            [segment.confidence, segment.source, segment.verification_note]
              .filter(Boolean)
              .join(" ")
          )
        ).length;
        const cityCount = new Set(
          pois.map((poi) => String(poi.city || "").trim()).filter(Boolean)
        ).size;
        return [
          {
            icon: "fa-calendar-days",
            label: "天数",
            value: `${days.length || journeyData.overview?.duration_days || 0} 天`,
            tone: "ready",
          },
          {
            icon: "fa-map-pin",
            label: "地点",
            value: `${pois.length} 个${cityCount ? ` · ${cityCount} 城` : ""}`,
            tone: "ready",
          },
          {
            icon: "fa-route",
            label: "路线",
            value:
              routeNeedsCheck && (verifiedRouteCount || estimatedRouteCount)
                ? `${verifiedRouteCount} 段核验 · ${estimatedRouteCount} 段估算`
                : routeNeedsCheck
                ? "路程时间行前确认"
                : "已返回路段",
            tone: routeNeedsCheck ? "pending" : "ready",
          },
          {
            icon: "fa-clipboard-check",
            label: "待核验",
            value: `${pendingChecks.length || 0} 项`,
            tone: pendingChecks.length ? "pending" : "ready",
          },
        ];
      }

      function renderVisualJourneyStats(journeyData = {}) {
        return `
          <div class="visual-journey-stats">
            ${buildVisualJourneyStats(journeyData)
              .map(
                (item) => `
                  <div class="visual-journey-stat ${escapeHtml(item.tone)}">
                    <span><i class="fa-solid ${escapeHtml(item.icon)}"></i> ${escapeHtml(
                  item.label
                )}</span>
                    <strong>${escapeHtml(item.value)}</strong>
                  </div>
                `
              )
              .join("")}
          </div>
        `;
      }

      function getVisualRoutePlanningPool(dayPlans = [], planningPool = []) {
        const activeIds = new Set(
          dayPlans.flatMap((day) => (day.stops || []).map((stop) => stop.id).filter(Boolean))
        );
        const activeNames = new Set(
          dayPlans.flatMap((day) =>
            (day.stops || [])
              .map((stop) => cleanJourneyLocationValue(stop.name || "").toLowerCase())
              .filter(Boolean)
          )
        );
        const seen = new Set();
        return planningPool
          .map((poi) => normalizeJourneyPoiAsStop(poi))
          .filter((poi) => {
            const name = cleanJourneyLocationValue(poi.name || "");
            const key = poi.id || name.toLowerCase();
            if (!name || seen.has(key)) return false;
            seen.add(key);
            if (poi.id && activeIds.has(poi.id)) return false;
            if (activeNames.has(name.toLowerCase())) return false;
            return true;
          })
          .slice(0, 8);
      }

      function renderVisualRoutePlanningPool(dayPlans = [], planningPool = []) {
        const candidates = getVisualRoutePlanningPool(dayPlans, planningPool);
        return `
          <div class="visual-route-planning-pool" data-route-planning-pool="true">
            <div class="visual-route-planning-head">
              <div>
                <span>待规划地点</span>
                <strong>先放进地点池，再安排到某一天</strong>
              </div>
              <small>${escapeHtml(String(candidates.length))} 个可加入</small>
            </div>
            ${
              candidates.length
                ? `<div class="visual-route-planning-list">
                    ${candidates
                      .map((poi) => {
                        const poiName = cleanJourneyLocationValue(poi.name || "待规划地点");
                        const poiMeta = [
                          poi.type_label || poi.type,
                          poi.time_range || poi.suggested_time,
                          poi.estimated_cost,
                        ]
                          .filter(Boolean)
                          .join(" · ");
                        return `
                          <article class="visual-route-planning-card" data-pending-poi-id="${escapeHtml(
                            poi.id || ""
                          )}">
                            <div>
                              <strong>${escapeHtml(poiName)}</strong>
                              <span>${escapeHtml(poiMeta || "地点信息待核验")}</span>
                            </div>
                            <div class="visual-route-planning-add">
                              ${dayPlans
                                .map(
                                  (day, index) => `
                                    <button
                                      type="button"
                                      data-journey-edit-action="add-pending"
                                      data-pending-poi-id="${escapeHtml(poi.id || "")}"
                                      data-pending-poi-name="${escapeHtml(poiName)}"
                                      data-journey-day-key="${escapeHtml(day.key || "")}"
                                      title="${escapeHtml(`加入${day.label || `Day ${index + 1}`}`)}"
                                    >
                                      D${index + 1}
                                    </button>
                                  `
                                )
                                .join("")}
                            </div>
                          </article>
                        `;
                      })
                      .join("")}
                  </div>`
                : `<p class="visual-route-planning-empty">待规划地点已全部排入行程；可以继续导入攻略或让助手补充候选点。</p>`
            }
          </div>
        `;
      }

      function getVisualRouteSegmentView(segment = {}) {
        const rawMode = String(segment.mode || segment.transport_mode || segment.source || "").toLowerCase();
        const modeText = /walk|步行/.test(rawMode)
          ? "步行"
          : /bus|公交|metro|subway|地铁/.test(rawMode)
          ? "公交/地铁"
          : /train|rail|火车|高铁/.test(rawMode)
          ? "铁路"
          : /flight|air|航班|飞机/.test(rawMode)
          ? "航班"
          : /drive|driving|car|驾车|自驾/.test(rawMode)
          ? "驾车"
          : "交通";
        const metricText = [segment.distance_text, segment.duration_text]
          .filter(Boolean)
          .join(" · ");
        const confidenceText = [
          segment.confidence,
          segment.source,
          segment.verification_note,
        ]
          .filter(Boolean)
          .join(" ");
        const isVerified = /amap|高德|已核验/i.test(confidenceText);
        const isEstimated = /estimated|估算/i.test(confidenceText);
        const isPending =
          !metricText || /待|needs|unknown/i.test([metricText, confidenceText].join(" "));
        const displayMetricText = isPending
          ? "待高德路线核验"
          : metricText || "距离/用时待核验";
        return {
          modeText,
          metricText: displayMetricText,
          tone: isVerified ? "ready" : isEstimated ? "estimated" : isPending ? "pending" : "",
          statusText: isVerified ? "已核验" : isEstimated ? "估算" : "待核验",
        };
      }

      function renderVisualRouteSegment(segment = {}, fromStop = {}, toStop = {}) {
        const view = getVisualRouteSegmentView(segment);
        const fromName = cleanJourneyLocationValue(fromStop.name || segment.from_name || "上一站");
        const toName = cleanJourneyLocationValue(toStop.name || segment.to_name || "下一站");
        return `
          <div class="visual-route-segment ${escapeHtml(view.tone)}" data-route-segment="true">
            <span class="visual-route-segment-line" aria-hidden="true"></span>
            <div>
              <strong>${escapeHtml(view.modeText)}</strong>
              <small>${escapeHtml(`${fromName} → ${toName}`)}</small>
            </div>
            <em>${escapeHtml(view.metricText)}</em>
            <span class="visual-route-segment-status">${escapeHtml(view.statusText)}</span>
          </div>
        `;
      }

      function formatVisualStopDuration(minutes) {
        const value = Number(minutes);
        if (!Number.isFinite(value) || value <= 0) return "停留待定";
        const rounded = Math.round(value);
        if (rounded < 60) return `停留 ${rounded}分钟`;
        const hours = Math.floor(rounded / 60);
        const remainingMinutes = rounded % 60;
        return remainingMinutes
          ? `停留 ${hours}小时${remainingMinutes}分钟`
          : `停留 ${hours}小时`;
      }

      function getVisualStopTicketStatus(stop = {}) {
        const costText = String(stop.estimated_cost || "").trim();
        const reservationText = String(stop.reservation_note || "").trim();
        const descriptionText = String(stop.description || "").trim();
        const combined = [costText, reservationText, descriptionText]
          .filter(Boolean)
          .join(" ");
        if (/预约|限流|名额|博物馆|展馆/u.test(combined)) {
          return { tone: "pending", label: "预约核验" };
        }
        if (/门票|票价|香花券|购票/u.test(combined)) {
          return { tone: "pending", label: "票务核验" };
        }
        if (/游船|体验|演出|项目/u.test(combined)) {
          return { tone: "pending", label: "活动核验" };
        }
        if (/餐饮|茶饮|购物|消费自理|自理/u.test(combined)) {
          return { tone: "neutral", label: "消费自理" };
        }
        if (/免费|无需门票|免票/u.test(combined)) {
          return { tone: "ready", label: "无需门票" };
        }
        if (/待核验|待确认|待定|参考/u.test(combined)) {
          return { tone: "pending", label: "待核验" };
        }
        return { tone: "pending", label: "行前确认" };
      }

      function renderVisualRouteStopDetails(stop = {}) {
        const ticketStatus = getVisualStopTicketStatus(stop);
        const timeText = stop.time_range || stop.suggested_time || "时间待定";
        const durationText = formatVisualStopDuration(stop.duration_minutes);
        return `
          <div class="visual-route-stop-details">
            <span class="visual-route-stop-pill time">${escapeHtml(timeText)}</span>
            <span class="visual-route-stop-pill duration">${escapeHtml(durationText)}</span>
            <span class="visual-route-stop-pill ticket ${escapeHtml(
              ticketStatus.tone
            )}" data-ticket-status="${escapeHtml(ticketStatus.label)}">${escapeHtml(
          ticketStatus.label
        )}</span>
          </div>
        `;
      }

      function renderVisualJourneyDayEditor(dayPlans = [], planningPool = []) {
        if (!Array.isArray(dayPlans) || !dayPlans.length) return "";
        const totalStops = dayPlans.reduce(
          (count, day) => count + (Array.isArray(day.stops) ? day.stops.length : 0),
          0
        );
        return `
          <section class="visual-route-editor" data-visual-route-editor="true">
            <div class="visual-route-editor-head">
              <div>
                <span>路线编辑</span>
                <strong>分日地点顺序</strong>
              </div>
              <small>${escapeHtml(String(totalStops))} 个地点</small>
            </div>
            ${renderVisualRoutePlanningPool(dayPlans, planningPool)}
            <div class="visual-route-day-list">
              ${dayPlans
                .map((day, dayIndex) => {
                  const dayKey = day.key || `visual-day-${dayIndex + 1}`;
                  const stops = Array.isArray(day.stops) ? day.stops : [];
                  const segments = Array.isArray(day.segments) ? day.segments : [];
                  return `
                    <article class="visual-route-day-card" data-journey-day-card="${escapeHtml(dayKey)}">
                      <header>
                        <button
                          class="visual-route-day-focus visual-day-focus-btn"
                          type="button"
                          data-map-day-focus="${escapeHtml(dayKey)}"
                        >
                          <span>${escapeHtml(day.label || `Day ${dayIndex + 1}`)}</span>
                          <strong>${escapeHtml(day.title || day.note || "当天路线")}</strong>
                        </button>
                        <div class="visual-route-day-tools">
                          <small>${escapeHtml(String(stops.length))} 点</small>
                          <button
                            type="button"
                            data-journey-edit-action="optimize-day"
                            data-journey-day-key="${escapeHtml(dayKey)}"
                            title="按坐标优化当天地点顺序，锁定点保持不动"
                          >
                            优化
                          </button>
                        </div>
                      </header>
                      ${
                        stops.length
                          ? `<div class="visual-route-stop-list">
                              ${stops
                                .map((stop, stopIndex) => {
                                  const stopMeta = `${dayKey}:${stopIndex}`;
                                  const stopLabel = cleanJourneyLocationValue(stop.name || "地点待确认");
                                  return `
                                    <div class="visual-route-stop-entry">
                                      <div class="visual-route-stop-row${
                                      stop.locked ? " is-locked" : ""
                                    }" data-map-day-stop="${escapeHtml(
                                      stopMeta
                                    )}" data-journey-stop-locked="${stop.locked ? "true" : "false"}">
                                      <button
                                        class="visual-route-stop-main visual-poi-focus-btn"
                                        type="button"
                                        data-map-day-stop="${escapeHtml(stopMeta)}"
                                        aria-label="${escapeHtml(`定位${stopLabel}`)}"
                                      >
                                        <span>${stopIndex + 1}</span>
                                        <div>
                                          <strong>${escapeHtml(stopLabel)}</strong>
                                          ${renderVisualRouteStopDetails(stop)}
                                          ${
                                            stop.locked
                                              ? `<small class="visual-route-stop-lock-note">已锁定，优化时不移动</small>`
                                              : ""
                                          }
                                        </div>
                                      </button>
                                      <div class="visual-route-stop-actions">
                                        <button
                                          class="visual-route-action-primary"
                                          type="button"
                                          data-journey-edit-action="up"
                                          data-map-day-stop="${escapeHtml(stopMeta)}"
                                          aria-label="${escapeHtml(`上移${stopLabel}`)}"
                                          title="上移"
                                          ${stopIndex === 0 ? "disabled" : ""}
                                        ><span aria-hidden="true">↑</span></button>
                                        <button
                                          class="visual-route-action-primary"
                                          type="button"
                                          data-journey-edit-action="down"
                                          data-map-day-stop="${escapeHtml(stopMeta)}"
                                          aria-label="${escapeHtml(`下移${stopLabel}`)}"
                                          title="下移"
                                          ${stopIndex === stops.length - 1 ? "disabled" : ""}
                                        ><span aria-hidden="true">↓</span></button>
                                        <details class="visual-route-more-actions">
                                          <summary
                                            aria-label="${escapeHtml(`更多操作：${stopLabel}`)}"
                                            title="更多操作"
                                          >
                                            <span aria-hidden="true">⋯</span>
                                          </summary>
                                          <div class="visual-route-more-menu">
                                            <button
                                              type="button"
                                              data-journey-edit-action="toggle-lock"
                                              data-map-day-stop="${escapeHtml(stopMeta)}"
                                              aria-label="${escapeHtml(
                                                stop.locked ? `解锁${stopLabel}` : `锁定${stopLabel}`
                                              )}"
                                              title="${stop.locked ? "解锁" : "锁定"}"
                                            ><span>${stop.locked ? "解锁" : "锁定"}</span></button>
                                            <button
                                              type="button"
                                              data-journey-edit-action="prev-day"
                                              data-map-day-stop="${escapeHtml(stopMeta)}"
                                              aria-label="${escapeHtml(`移到上一天：${stopLabel}`)}"
                                              title="移到上一天"
                                              ${dayIndex === 0 ? "disabled" : ""}
                                            ><span aria-hidden="true">←</span><span>上一天</span></button>
                                            <button
                                              type="button"
                                              data-journey-edit-action="next-day"
                                              data-map-day-stop="${escapeHtml(stopMeta)}"
                                              aria-label="${escapeHtml(`移到下一天：${stopLabel}`)}"
                                              title="移到下一天"
                                              ${dayIndex === dayPlans.length - 1 ? "disabled" : ""}
                                            ><span aria-hidden="true">→</span><span>下一天</span></button>
                                            <button
                                              type="button"
                                              data-journey-edit-action="replace"
                                              data-map-day-stop="${escapeHtml(stopMeta)}"
                                              aria-label="${escapeHtml(`替换${stopLabel}`)}"
                                              title="替换"
                                            ><span aria-hidden="true">↻</span><span>替换</span></button>
                                            <button
                                              type="button"
                                              data-journey-edit-action="delete"
                                              data-map-day-stop="${escapeHtml(stopMeta)}"
                                              aria-label="${escapeHtml(`删除${stopLabel}`)}"
                                              title="删除"
                                            ><span aria-hidden="true">×</span><span>删除</span></button>
                                          </div>
                                        </details>
                                      </div>
                                      </div>
                                      ${
                                        stopIndex < stops.length - 1
                                          ? renderVisualRouteSegment(
                                              segments[stopIndex] || {},
                                              stop,
                                              stops[stopIndex + 1]
                                            )
                                          : ""
                                      }
                                    </div>
                                  `;
                                })
                                .join("")}
                            </div>`
                          : `<p class="visual-route-empty">当天地点待补齐。</p>`
                      }
                    </article>
                  `;
                })
                .join("")}
            </div>
          </section>
        `;
      }

      function refreshVisualJourneyDayEditor(workbench, dayPlans = []) {
        const panel = workbench?.querySelector("[data-visual-route-editor='true']");
        if (!panel) return;
        const planningPool = getJourneyPendingPoiCandidates?.(workbench, dayPlans) || [];
        const wrapper = document.createElement("div");
        wrapper.innerHTML = renderVisualJourneyDayEditor(dayPlans, planningPool);
        const nextPanel = wrapper.firstElementChild;
        if (nextPanel) panel.replaceWith(nextPanel);
      }

      function destroyJourneyMapEntry(node) {
        const entry = node ? journeyMapInstances.get(node) : null;
        try {
          entry?.map?.destroy?.();
          entry?.map?.remove?.();
        } catch (error) {
          // 地图实例销毁失败时继续重建，避免一次异常卡住编辑体验。
        }
        if (node) journeyMapInstances.delete(node);
      }

      function renderJourneySidebarDayRoutes(dayPlans = []) {
        if (!Array.isArray(dayPlans) || !dayPlans.length) return "";
        return `
          <div class="journey-map-sidebar-card journey-map-sidebar-routes is-collapsed">
            <div class="journey-map-sidebar-head">
              <span>分日路线</span>
              <button
                class="journey-map-day-list-toggle journey-map-action-btn secondary"
                type="button"
                data-map-action="toggle-day-routes"
                aria-expanded="false"
                title="展开分日路线"
              >
                展开分日路线
              </button>
            </div>
            <div class="journey-map-sidebar-day-list">
              <article class="journey-map-sidebar-day-card overview">
                <div class="journey-map-sidebar-day-head">
                  <button
                    class="journey-map-day-btn active"
                    type="button"
                    data-map-day="all"
                    aria-pressed="true"
                    title="查看全程路线总览"
                  >
                    <span>总览</span>
                    <small>全程叠加路线</small>
                  </button>
                  <button
                    class="journey-map-route-reference-btn journey-map-day-btn active"
                    type="button"
                    data-map-day="all"
                    aria-pressed="true"
                  >
                    路线参考
                  </button>
                </div>
              </article>
              ${dayPlans
                .map((day, dayIndex) => {
                  const dayKey = day.key || `day-${dayIndex + 1}`;
                  const places = [...(day.waypoints || []), ...(day.highlights || [])]
                    .map((item) => cleanJourneyLocationValue(item))
                    .filter(Boolean)
                    .slice(0, 4);
                  return `
                    <article class="journey-map-sidebar-day-card" data-journey-day-card="${escapeHtml(dayKey)}">
                      <div class="journey-map-sidebar-day-head">
                        <button
                          class="journey-map-day-btn"
                          type="button"
                          data-map-day="${escapeHtml(dayKey)}"
                          aria-pressed="false"
                          title="${escapeHtml(`${day.label || `Day ${dayIndex + 1}`}路线参考`)}"
                        >
                          <span>${escapeHtml(day.label || `Day ${dayIndex + 1}`)}</span>
                          <small>${escapeHtml(day.title || day.note || "当天路线")}</small>
                        </button>
                        <button
                          class="journey-map-route-reference-btn journey-map-day-btn"
                          type="button"
                          data-map-day="${escapeHtml(dayKey)}"
                          aria-pressed="false"
                        >
                          路线参考
                        </button>
                      </div>
                      ${
                        places.length
                          ? `<div class="journey-map-sidebar-place-chips">
                              ${places
                                .map(
                                  (place, placeIndex) => `
                                    <button
                                      class="journey-map-sidebar-place-chip journey-map-stage-stop journey-map-stage-stop--inline"
                                      type="button"
                                      data-map-day-stop="${escapeHtml(dayKey)}:${placeIndex}"
                                    >
                                      <span>${placeIndex + 1}</span>
                                      <strong>${escapeHtml(place)}</strong>
                                    </button>
                                  `
                                )
                                .join("")}
                            </div>`
                          : `<p class="journey-map-sidebar-muted">当天路线待补充具体地点。</p>`
                      }
                    </article>
                  `;
                })
                .join("")}
            </div>
          </div>
        `;
      }

      function refreshJourneyMapAfterEdit(shell, dayPlans) {
        const mapNode = shell?.querySelector(".journey-live-map[data-map-payload]");
        if (!shell || !mapNode) return;
        const normalizedDayPlans = dayPlans.map((day) => {
          const normalizedDay = normalizeJourneyDayPlanStops(day);
          return {
            ...normalizedDay,
            segments: buildEditedJourneySegments(
              normalizedDay.dayNumber || 1,
              normalizedDay.stops || []
            ),
          };
        });
        const payload = parseMapPayload(mapNode.dataset.mapPayload || "") || {};
        payload.days = normalizedDayPlans.map((day) => ({
          key: day.key,
          label: day.label,
          waypoints: day.waypoints,
          stops: day.stops || [],
          segments: buildEditedJourneySegments(day.dayNumber || 1, day.stops || []),
        }));
        shell.dataset.dayPlans = serializeMapPayload(normalizedDayPlans);
        mapNode.dataset.mapPayload = serializeMapPayload(payload);
        const sidebarDays = shell.querySelector(".journey-map-sidebar-day-list");
        if (sidebarDays) {
          const wrapper = document.createElement("div");
          wrapper.innerHTML = renderJourneySidebarDayRoutes(normalizedDayPlans);
          sidebarDays.innerHTML =
            wrapper.querySelector(".journey-map-sidebar-day-list")?.innerHTML || "";
        }
        destroyJourneyMapEntry(mapNode);
        mapNode.dataset.mapReady = "";
        mapNode.innerHTML =
          '<div class="journey-live-map-state loading">正在按新顺序刷新路线…</div>';
        hideJourneyPoiSheet(shell);
        hydrateJourneyMap(mapNode);
      }

      function updateVisualJourneyPoiCards(workbench, dayPlans) {
        if (!workbench) return;
        refreshVisualJourneyDayEditor(workbench, dayPlans);
        const activeIds = new Set(
          dayPlans.flatMap((day) => (day.stops || []).map((stop) => stop.id).filter(Boolean))
        );
        if (!activeIds.size) return;
        workbench.querySelectorAll(".visual-poi-card[data-poi-id]").forEach((card) => {
          const poiId = card.dataset.poiId || "";
          const visible = !poiId || activeIds.has(poiId);
          card.hidden = !visible;
          const stopRef = dayPlans
            .flatMap((day) =>
              (day.stops || []).map((stop, index) => ({
                dayKey: day.key,
                index,
                id: stop.id,
              }))
            )
            .find((item) => item.id === poiId);
          if (stopRef) {
            card
              .querySelectorAll("[data-map-day-stop]")
              .forEach((button) => {
                button.dataset.mapDayStop = `${stopRef.dayKey}:${stopRef.index}`;
              });
          }
        });
      }

      function buildEditedJourneySegments(dayNumber, pois = []) {
        const segments = [];
        for (let index = 0; index < Math.max(pois.length - 1, 0); index += 1) {
          const left = pois[index];
          const right = pois[index + 1];
          segments.push({
            id: `d${dayNumber}-s${index + 1}`,
            day_number: dayNumber,
            from_poi_id: left.id || "",
            to_poi_id: right.id || "",
            from_name: left.name || "",
            to_name: right.name || "",
            mode: "driving",
            distance_text: "待高德路线核验",
            duration_text: "待高德路线核验",
            confidence: "needs_live_route",
          });
        }
        return segments;
      }

      function buildJourneyDataFromEditedPlans(workbench, dayPlans) {
        const original = parseMapPayload(workbench?.dataset.journeyData || "") || {};
        if (original.version !== "journey_plan.v1") return null;
        const normalizedPlans = dayPlans.map((day) => {
          const normalizedDay = normalizeJourneyDayPlanStops(day);
          return {
            ...normalizedDay,
            segments: buildEditedJourneySegments(
              normalizedDay.dayNumber || 1,
              normalizedDay.stops || []
            ),
          };
        });
        const days = (Array.isArray(original.days) ? original.days : []).map((day) => {
          const planKey = `visual-day-${day.day_number || 1}`;
          const plan = normalizedPlans.find((item) => item.key === planKey);
          if (!plan) return day;
          const pois = (plan.stops || []).map((stop, index) => ({
            ...normalizeJourneyPoiAsStop(stop, { city: day.city || "" }),
            id: stop.id || `d${day.day_number || 1}-p${index + 1}`,
            day_number: day.day_number || plan.dayNumber || 1,
            order: index + 1,
            suggested_time: stop.time_range || stop.suggested_time || "",
            locked: Boolean(stop.locked),
          }));
          return {
            ...day,
            summary: pois.map((poi) => poi.name).filter(Boolean).join(" · "),
            pois,
            segments: buildEditedJourneySegments(day.day_number || plan.dayNumber || 1, pois),
          };
        });
        const activePois = days.flatMap((day) => day.pois || []);
        const activeIds = new Set(activePois.map((poi) => poi.id).filter(Boolean));
        const originalPois = Array.isArray(original.pois) ? original.pois : [];
        const originalAlternativePois = Array.isArray(original.alternative_pois)
          ? original.alternative_pois
          : [];
        const inactiveOriginalPois = originalPois.filter(
          (poi) => !poi.id || !activeIds.has(poi.id)
        );
        const inactiveAlternativePois = originalAlternativePois.filter(
          (poi) => !poi.id || !activeIds.has(poi.id)
        );
        const pois = [...activePois, ...inactiveOriginalPois];
        const segments = days.flatMap((day) => day.segments || []);
        return {
          ...original,
          days,
          pois,
          alternative_pois: inactiveAlternativePois,
          segments,
          source_summary: {
            ...(original.source_summary || {}),
            edited_by_user: true,
          },
        };
      }

      async function saveEditedJourneyDraft(workbench, dayPlans) {
        if (!state.user || !state.currentConversationId || !workbench) return;
        const journeyData = buildJourneyDataFromEditedPlans(workbench, dayPlans);
        if (!journeyData) return;
        workbench.dataset.journeyData = serializeMapPayload(journeyData);
        try {
          const { response } = await journeyApi.saveJourneyDraft({
            apiBase: getApiBase(),
            stateToken: state.token,
            conversationId: state.currentConversationId,
            journeyData,
          });
          if (!response.ok) throw new Error(`journey-save-${response.status}`);
          showToast("路线草案已保存");
        } catch (error) {
          console.error(error);
          showToast("路线已本地更新，保存到会话失败", true);
        }
      }

      function runWhenBrowserIdle(callback, timeout = 1200) {
        if (typeof window.requestIdleCallback === "function") {
          window.requestIdleCallback(callback, { timeout });
          return;
        }
        window.setTimeout(callback, timeout);
      }

      function enableIntroSecondaryImages() {
        document.body.classList.add("intro-secondary-images-ready");
      }

      function scheduleIntroSecondaryImages() {
        const loadSecondaryImages = () =>
          runWhenBrowserIdle(enableIntroSecondaryImages, 1600);
        if (document.readyState === "complete") {
          loadSecondaryImages();
          return;
        }
        window.addEventListener("load", loadSecondaryImages, { once: true });
      }

      function enableAuthHeroImages() {
        document.body.classList.add("auth-hero-images-ready");
      }

      function showIntroOverlay() {
        const intro = document.getElementById("introOverlay");
        if (!intro) return;
        intro.classList.remove("hidden");
        document.body.classList.add("intro-active");
      }

      function hideIntroOverlay() {
        const intro = document.getElementById("introOverlay");
        if (!intro) return;
        intro.classList.add("hidden");
        document.body.classList.remove("intro-active");
      }

      function enterAuthPortal() {
        hideIntroOverlay();
        showAuthOverlay();
        requestAnimationFrame(() => {
          document.getElementById("username")?.focus();
        });
      }

      function handleIntroKeydown(event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          enterAuthPortal();
        }
      }

      function persistComposerDraft(options = {}) {
        const input = document.getElementById("chatInput");
        if (!input) return;
        writeDraftStorage(composerDraftKey, input.value || "", options);
      }

      function persistPlannerDraft() {
        const payload = {
          origin: document.getElementById("plannerOrigin")?.value || "",
          destination:
            document.getElementById("plannerDestination")?.value || "",
          date: document.getElementById("plannerDate")?.value || "",
          days: document.getElementById("plannerDays")?.value || "",
          travelers: document.getElementById("plannerTravelers")?.value || "",
          budget: document.getElementById("plannerBudget")?.value || "",
          transport: document.getElementById("plannerTransport")?.value || "",
          stay: document.getElementById("plannerStay")?.value || "",
          style: document.getElementById("plannerStyle")?.value || "",
        };
        writeDraftStorage(plannerDraftKey, JSON.stringify(payload));
        updatePlannerAssistStrip();
      }

      function restoreDrafts() {
        const composerDraft = readDraftStorage(composerDraftKey);
        if (composerDraft) {
          const input = document.getElementById("chatInput");
          if (input && !input.value) {
            input.value = composerDraft;
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 120) + "px";
          }
        }

        const plannerDraft = readDraftStorage(plannerDraftKey);
        if (plannerDraft) {
          try {
            const parsed = JSON.parse(plannerDraft);
            document.getElementById("plannerOrigin").value = parsed.origin || "";
            document.getElementById("plannerDestination").value =
              parsed.destination || "";
            document.getElementById("plannerDate").value = parsed.date || "";
            document.getElementById("plannerDays").value = parsed.days || "";
            document.getElementById("plannerTravelers").value =
              parsed.travelers || "";
            document.getElementById("plannerBudget").value = parsed.budget || "";
            document.getElementById("plannerTransport").value =
              parsed.transport || "";
            document.getElementById("plannerStay").value = parsed.stay || "";
            document.getElementById("plannerStyle").value = parsed.style || "";
          } catch (error) {}
        }
      }

      function resetComposerDraft(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        const input = document.getElementById("chatInput");
        if (input) {
          input.value = "";
          input.style.height = "auto";
        }
        clearDraftStorage(composerDraftKey);
        if (!silent) {
          setRuntimeStatus("输入草稿已重置", "online");
        }
      }

      function applyPlannerPanelState() {
        const panel = document.querySelector(".planner-panel");
        const toggleBtn = document.getElementById("plannerToggleBtn");
        const panelBody = document.getElementById("plannerPanelBody");
        if (!panel || !toggleBtn || !panelBody) return;
        panel.classList.toggle("collapsed", state.plannerCollapsed);
        panelBody.hidden = state.plannerCollapsed;
        toggleBtn.setAttribute("aria-expanded", String(!state.plannerCollapsed));
        toggleBtn.innerHTML = state.plannerCollapsed
          ? '<i class="fa-solid fa-angle-down"></i> 展开辅助栏'
          : '<i class="fa-solid fa-angle-up"></i> 收起辅助栏';
      }

      function togglePlannerPanel(forceCollapsed) {
        state.plannerCollapsed =
          typeof forceCollapsed === "boolean"
            ? forceCollapsed
            : !state.plannerCollapsed;
        localStorage.setItem(plannerCollapseKey, state.plannerCollapsed ? "1" : "0");
        applyPlannerPanelState();
      }

      function setMobileChatFocus(enabled) {
        const shouldFocus = Boolean(enabled && isMobileViewport() && state.user);
        state.mobileChatFocus = shouldFocus;
        document.body.classList.toggle("mobile-chat-focus", shouldFocus);
      }

      function exitMobileChatFocus() {
        setMobileChatFocus(false);
      }

      function validateAuthForm(isRegister) {
        clearAuthErrors();
        const username = document.getElementById("username").value.trim();
        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;
        let firstInvalidField = null;

        if (username.length < 2) {
          setFieldError("username", "用户名至少需要 2 个字符。");
          firstInvalidField ||= "username";
        }

        if (password.length < 6) {
          setFieldError("password", "密码至少需要 6 位。");
          firstInvalidField ||= "password";
        }

        if (isRegister) {
          if (!email) {
            setFieldError("email", "注册时需要填写邮箱。");
            firstInvalidField ||= "email";
          } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            setFieldError("email", "邮箱格式看起来不正确，请再检查一下。");
            firstInvalidField ||= "email";
          }
        }

        if (firstInvalidField) {
          document.getElementById(firstInvalidField)?.focus();
          setAuthFeedback("请先补全表单信息，再继续操作。", "error");
          return null;
        }

        return {
          username,
          email,
          password,
        };
      }

      function isServiceUsable() {
        return state.serviceStatus === "ready" || state.serviceStatus === "degraded";
      }

      function getStatusLabel(status = "") {
        const labels = {
          ready: "就绪",
          degraded: "降级可用",
          not_ready: "未就绪",
          checking: "检查中",
          error: "连接失败",
          idle: "待开始",
          ok: "正常",
          pending: "待确认",
          approved: "已批准",
          rejected: "已拒绝",
          expired: "已过期",
          failed: "失败",
          none: "记录",
          completed: "已完成",
          running: "运行中",
          success: "成功",
          needs_verification: "需核验",
          not_found: "未查到",
          insufficient_parameters: "参数不足",
          service_exception: "服务异常",
          skipped: "已跳过",
          pending_confirmation: "待确认",
          requirement_collection: "需求收集",
          destination_recommendation: "目的地推荐",
          transport_planning: "交通规划",
          accommodation_planning: "住宿规划",
          food_planning: "餐饮规划",
          itinerary_generation: "行程生成",
          budget_summarization: "预算汇总",
          order_generation: "报告生成",
          intent_split: "意图分流",
          agency_requirement: "基础需求",
          agency_product_match: "匹配方案",
          agency_plan_draft: "方案草案",
          agency_feedback: "方案确认",
          agency_report: "报告生成",
          free_planning: "个性化旅游规划",
          agency_plan: "省心方案",
          unknown: "待确认",
        };
        return labels[status] || status || "待确认";
      }

      const governanceTools = window.ZhiXingGovernanceTools?.createGovernanceTools?.({
        getStatusLabel,
      });
      if (!governanceTools) {
        throw new Error("ZhiXingGovernanceTools is not loaded.");
      }
      const {
        redactClientText,
        normalizeToolAuditEvent,
      } = governanceTools;
      const governanceProgress = window.ZhiXingGovernanceProgress?.createGovernanceProgress?.({
        parseJourneyChineseDayNumber,
        extractJourneyCityPair,
        getStatusLabel,
        redactClientText,
      });
      if (!governanceProgress) {
        throw new Error("ZhiXingGovernanceProgress is not loaded.");
      }
      const {
        mergeGovernanceProgressSnapshots,
        parseOptimisticTripFactsFromText,
        progressSnapshotFromFastSplit,
        progressSnapshotFromReportData,
        progressSnapshotFromObservability,
        normalizeTurnObservability,
      } = governanceProgress;
      const governanceRenderer = window.ZhiXingGovernanceRenderer?.createGovernanceRenderer?.({
        escapeHtml,
        redactClientText,
        getStatusLabel,
        formatEpochSeconds,
      });
      if (!governanceRenderer) {
        throw new Error("ZhiXingGovernanceRenderer is not loaded.");
      }
      const {
        renderReadinessServiceGrid,
        renderToolAuditListHtml,
        renderTurnObservabilityGridHtml,
        renderApprovalListHtml,
        renderApprovalEventList,
      } = governanceRenderer;

      function getReadinessStatusCopy(status = "") {
        if (status === "ready") return "对话、报告和行程进度都可演示。";
        if (status === "degraded") return "核心规划可继续，部分外部查询可能需要稍后复查。";
        if (status === "not_ready") return "关键能力尚未就绪，暂不开放登录、聊天或确认动作。";
        if (status === "error") return "暂时无法连接服务，需要稍后重试。";
        return "正在确认当前可用能力。";
      }

      function formatEpochSeconds(value) {
        if (value === null || value === undefined || value === "") return "未设置";
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return String(value);
        return formatClock(new Date(numeric * 1000));
      }

      function setPillStatus(el, status, fallbackText = "") {
        if (!el) return;
        el.textContent = fallbackText || getStatusLabel(status);
        el.className = `governance-status-pill ${status || "idle"}`.trim();
      }

      const READINESS_ITEM_LABELS = {
        checkpointer: "会话进度",
        store: "长期偏好",
        mcp: "外部查询",
        session_lock: "会话保护",
        approval_governance: "下单保护",
        postgres: "业务数据",
        redis: "会话保护",
      };

      function normalizeReadinessStatus(service = {}) {
        const rawStatus = String(service.status || (service.ready ? "ready" : "checking"));
        if (rawStatus === "healthy" || rawStatus === "ok") return "ready";
        if (rawStatus === "unavailable" || rawStatus === "missing") return "not_ready";
        if (rawStatus === "error") return "not_ready";
        return rawStatus || "checking";
      }

      function combineReadinessStatuses(statuses = []) {
        if (statuses.some((status) => status === "not_ready")) return "not_ready";
        if (statuses.some((status) => status === "degraded")) return "degraded";
        if (statuses.length && statuses.every((status) => status === "ready")) return "ready";
        return "checking";
      }

      function formatReadinessName(name = "") {
        return READINESS_ITEM_LABELS[name] || String(name || "待确认能力");
      }

      function summarizeReadinessServices(services = {}) {
        const checkpointerStatus = normalizeReadinessStatus(services.checkpointer);
        const storeStatus = normalizeReadinessStatus(services.store);
        const mcpStatus = normalizeReadinessStatus(services.mcp);
        const sessionLockStatus = normalizeReadinessStatus(services.session_lock);
        const approvalStatus = normalizeReadinessStatus(services.approval_governance);
        const coreStatus = combineReadinessStatuses([checkpointerStatus, storeStatus]);
        const protectionStatus = combineReadinessStatuses([sessionLockStatus, approvalStatus]);
        return [
          {
            key: "core",
            label: "对话与报告",
            status: coreStatus,
            description: "对话续接、阶段进度、报告生成",
          },
          {
            key: "memory",
            label: "长期偏好",
            status: storeStatus,
            description: "用户偏好可用于后续建议",
          },
          {
            key: "external",
            label: "外部服务",
            status: mcpStatus,
            description: "天气、地图、交通、酒店等查询能力",
          },
          {
            key: "human_boundary",
            label: "下单保护",
            status: protectionStatus,
            description: "当前只记录边界，不会真实支付或下单",
          },
        ];
      }

      function readinessSummaryLines(data = {}, status = "") {
        const services = data.services || {};
        const items = summarizeReadinessServices(services);
        const available = items
          .filter((item) => item.status === "ready" || item.status === "degraded")
          .map((item) => item.label);
        const mcpStatus = normalizeReadinessStatus(services.mcp);
        const approval = services.approval_governance || {};
        const approvalReady = normalizeReadinessStatus(approval) === "ready";
        const missing = Array.isArray(data.missing_required)
          ? data.missing_required.map(formatReadinessName)
          : [];
        const degraded = Array.isArray(data.degraded_optional)
          ? data.degraded_optional.map(formatReadinessName)
          : [];
        const attention = [
          ...missing.map((item) => `${item}未就绪`),
          ...degraded.map((item) => `${item}需复查`),
          ...(data.startup_complete === false ? ["服务仍在启动中"] : []),
        ];
        const turn = state.governance?.turnObservability || {};
        const progress = getGovernanceProgressSnapshot();
        const planningModeValue =
          progress.planning_mode ||
          turn.planningMode ||
          turn.planning_mode ||
          "pending_confirmation";
        const planningMode = getStatusLabel(planningModeValue);
        const factItems = Array.isArray(progress.confirmed_facts)
          ? progress.confirmed_facts
              .map((item) => {
                const label = item?.label || item?.key || "";
                const value = item?.value;
                if (!label || value === undefined || value === null || value === "") return "";
                return `${label}：${value}`;
              })
              .filter(Boolean)
          : [];
        const preferenceItems = Array.isArray(progress.long_term_preferences)
          ? progress.long_term_preferences
              .map((item) => (typeof item === "string" ? item : item?.label || item?.value || ""))
              .filter(Boolean)
          : [];
        const currentPreferenceItems = Array.isArray(progress.current_trip_preferences)
          ? progress.current_trip_preferences
              .map((item) => (typeof item === "string" ? item : item?.label || item?.value || ""))
              .filter(Boolean)
          : [];
        const preferenceCopy = preferenceItems.length
          ? `长期：${preferenceItems.slice(0, 4).join("、")}`
          : currentPreferenceItems.length
            ? `本次：${currentPreferenceItems.slice(0, 5).join("、")}`
            : available.includes("长期偏好")
              ? "本次偏好待继续沉淀"
              : "登录后逐步沉淀";
        return [
          `<span>方案类型：${escapeHtml(planningMode)}</span>`,
          `<span>已确认信息：${escapeHtml(
            factItems.length
              ? factItems.slice(0, 6).join("；")
              : "待你补充出发地、时间、人数和预算"
          )}</span>`,
          `<span>偏好记录：${escapeHtml(preferenceCopy)}</span>`,
          `<span>外部服务：${escapeHtml(
            mcpStatus === "ready"
              ? "天气、地图、交通、酒店等查询可用"
              : mcpStatus === "degraded"
                ? "部分查询能力不稳定，结果会提示核验"
                : mcpStatus === "not_ready"
                  ? "暂不可用，可先生成草案"
                  : "正在检测"
          )}</span>`,
          `<span>重要提醒：${escapeHtml(
            approvalReady
              ? approval.persistent
                ? "当前不会自动支付、发短信或下单"
                : "当前不会自动支付、发短信或下单"
              : "当前不会自动支付、发短信或下单"
          )}</span>`,
          `<span>待关注：${escapeHtml(attention.length ? attention.join("、") : "无")}</span>`,
        ];
      }

      function readinessCurrentStageLabel() {
        const turn = state.governance?.turnObservability || {};
        const progress = getGovernanceProgressSnapshot();
        const planningMode =
          progress.planning_mode ||
          turn.planningMode ||
          turn.planning_mode ||
          "pending_confirmation";
        const agencyStep = progress.agency_step || turn.agency_step || "";
        const step = turn.step || "requirement_collection";
        if (planningMode === "pending_confirmation") {
          return getStatusLabel("intent_split");
        }
        if (planningMode === "agency_plan") {
          return getStatusLabel(agencyStep || step || "agency_requirement");
        }
        return (
          state.governance?.turnObservability?.stepLabel ||
          getStatusLabel(step)
        );
      }

      function renderReadinessPanel(payload = null) {
        const data = payload || state.readiness.payload || {};
        const status = data.status || state.readiness.status || "checking";
        const statusPill = document.getElementById("readinessStatusPill");
        const title = document.getElementById("readinessTitle");
        const summary = document.getElementById("readinessSummary");
        const grid = document.getElementById("readinessServiceGrid");

        setPillStatus(statusPill, status, getStatusLabel(status));

        if (title) {
          title.textContent = `当前阶段：${readinessCurrentStageLabel()}`;
        }

        if (summary) {
          summary.innerHTML = readinessSummaryLines(data, status).join("");
        }

        if (grid) {
          grid.innerHTML = renderReadinessServiceGrid(
            summarizeReadinessServices(data.services || {})
          );
        }
        syncGovernanceDebugVisibility();
      }

      function getCurrentUserRole() {
        return (
          state.user?.role ||
          state.user?.preferences?.role ||
          state.user?.profile?.role ||
          "user"
        );
      }

      function canShowAdvisorDebug() {
        return ["advisor", "approver", "admin", "debug"].includes(getCurrentUserRole());
      }

      function syncGovernanceDebugVisibility() {
        const details = document.getElementById("governanceDetails");
        if (!details) return;
        const visible = canShowAdvisorDebug();
        details.hidden = !visible;
        if (!visible) {
          details.open = false;
        }
      }

      function canRequestAllApprovals() {
        return ["approver", "admin"].includes(getCurrentUserRole());
      }

      function syncAdminPortalVisibility() {
        const link = document.getElementById("adminPortalLink");
        if (!link) return;
        link.hidden = !canRequestAllApprovals();
      }

      function rememberToolAuditEvent(event = {}) {
        const normalized = normalizeToolAuditEvent(event);
        const key = [
          normalized.tool,
          normalized.status,
          normalized.evidenceType,
          normalized.errorType,
        ].join("|");
        const existingIndex = state.governance.toolAuditEvents.findIndex(
          (item) => [item.tool, item.status, item.evidenceType, item.errorType].join("|") === key
        );
        if (existingIndex >= 0) {
          state.governance.toolAuditEvents[existingIndex] = normalized;
        } else {
          state.governance.toolAuditEvents.unshift(normalized);
        }
        state.governance.toolAuditEvents = state.governance.toolAuditEvents.slice(0, 20);
        renderToolAuditList();
      }

      function getGovernanceProgressSnapshot() {
        return (
          state.governance?.progressSnapshot ||
          state.governance?.turnObservability?.progressSnapshot ||
          state.governance?.turnObservability?.progress_snapshot ||
          {}
        );
      }

      function rememberProgressSnapshot(snapshot = {}) {
        if (!snapshot || typeof snapshot !== "object" || !Object.keys(snapshot).length) return;
        state.governance.progressSnapshot = mergeGovernanceProgressSnapshots(
          state.governance.progressSnapshot || {},
          snapshot
        );
      }

      function rememberTurnObservability(event = {}) {
        if (!event || typeof event !== "object") return;
        rememberProgressSnapshot(progressSnapshotFromObservability(event));
        const mergedProgress = getGovernanceProgressSnapshot();
        const normalized = normalizeTurnObservability(event, mergedProgress);
        if (!normalized) return;
        state.governance.turnObservability = normalized;
        renderReadinessPanel();
        renderTurnObservability();
      }

      function renderToolAuditList() {
        const count = document.getElementById("toolAuditCount");
        const list = document.getElementById("toolAuditList");
        const events = state.governance.toolAuditEvents;
        if (count) count.textContent = String(events.length);
        if (!list) return;
        list.innerHTML = renderToolAuditListHtml(events);
      }

      function renderTurnObservability() {
        const grid = document.getElementById("turnObservabilityGrid");
        const pill = document.getElementById("turnStatusPill");
        const item = state.governance.turnObservability;
        if (!grid) return;
        if (!item) {
          setPillStatus(pill, "idle", "待开始");
          grid.innerHTML = renderTurnObservabilityGridHtml(null);
          return;
        }
        setPillStatus(pill, item.degradationStatus, item.degradationLabel);
        grid.innerHTML = renderTurnObservabilityGridHtml(item);
      }

      function renderApprovalList() {
        const list = document.getElementById("approvalList");
        if (!list) return;
        const filter = state.governance.approvalFilter;
        const approvals = state.governance.approvals.filter((approval) =>
          filter === "pending" ? approval.status === "pending" : true
        );
        document.querySelectorAll(".approval-filter-btn").forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.approvalFilter === filter);
        });

        list.innerHTML = renderApprovalListHtml({
          approvals,
          filter,
          selectedApprovalId: state.governance.selectedApprovalId,
          userPresent: Boolean(state.user),
          loading: state.governance.isApprovalLoading,
        });
      }

      function renderApprovalEvents() {
        const list = document.getElementById("approvalEventsList");
        if (!list) return;
        const events = state.governance.approvalEvents || [];
        const rendered = renderApprovalEventList({
          selectedApprovalId: state.governance.selectedApprovalId,
          events,
        });
        list.className = rendered.className;
        list.innerHTML = rendered.html;
      }

      async function loadApprovalEvents(approvalId) {
        if (!approvalId || !state.user || !isServiceUsable()) {
          state.governance.approvalEvents = [];
          renderApprovalEvents();
          return;
        }
        try {
          const { response, data } = await governanceApi.fetchApprovalEvents({
            apiBase: getApiBase(),
            stateToken: state.token,
            approvalId,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          state.governance.approvalEvents = Array.isArray(data.events)
            ? data.events
            : [];
        } catch (error) {
          state.governance.approvalEvents = [];
          showToast("人工确认事件同步失败", true);
        }
        renderApprovalEvents();
      }

      async function loadApprovals({ silent = true } = {}) {
        if (!state.user || !isServiceUsable()) {
          state.governance.approvals = [];
          state.governance.approvalEvents = [];
          renderApprovalList();
          renderApprovalEvents();
          return;
        }
        state.governance.isApprovalLoading = true;
        syncUiAvailability();
        renderApprovalList();
        const params = new URLSearchParams();
        try {
          const { response, data } = await governanceApi.fetchApprovals({
            apiBase: getApiBase(),
            stateToken: state.token,
            filter: state.governance.approvalFilter,
            canRequestAll: canRequestAllApprovals(),
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          state.governance.approvals = Array.isArray(data.approvals)
            ? data.approvals
            : [];
          if (
            state.governance.selectedApprovalId &&
            !state.governance.approvals.some(
              (approval) => approval.approval_id === state.governance.selectedApprovalId
            )
          ) {
            state.governance.selectedApprovalId = null;
          }
          state.governance.selectedApprovalId ||=
            state.governance.approvals[0]?.approval_id || null;
          if (!silent) showToast("进度台已刷新");
        } catch (error) {
          state.governance.approvals = [];
          state.governance.selectedApprovalId = null;
          if (!silent) showToast("人工确认记录同步失败", true);
        } finally {
          state.governance.isApprovalLoading = false;
          syncUiAvailability();
          renderApprovalList();
          await loadApprovalEvents(state.governance.selectedApprovalId);
        }
      }

      async function refreshGovernanceConsole(options = {}) {
        const silent = Boolean(options?.silent);
        await checkServiceHealth({ silent, reason: "governance-refresh" });
        renderToolAuditList();
        renderTurnObservability();
        await loadApprovals({ silent });
      }

      async function setApprovalFilter(filter = "all") {
        state.governance.approvalFilter = filter === "pending" ? "pending" : "all";
        await loadApprovals({ silent: true });
      }

      async function selectApprovalRecord(approvalId) {
        state.governance.selectedApprovalId = approvalId;
        renderApprovalList();
        await loadApprovalEvents(approvalId);
      }

      async function createDemoApproval() {
        if (!(await ensureServiceReady("创建人工确认记录"))) return;
        if (!state.user) {
          showToast("请先登录后再创建人工确认记录。", true);
          return;
        }
        state.governance.isApprovalLoading = true;
        syncUiAvailability();
        try {
          const { response, data } = await governanceApi.createDemoApproval({
            apiBase: getApiBase(),
            stateToken: state.token,
            conversationId: state.currentConversationId,
          });
          if (!response.ok) {
            throw new Error(data?.detail?.message || `HTTP ${response.status}`);
          }
          state.governance.selectedApprovalId = data.approval_id;
          showToast("人工确认演示记录已创建，不会触发真实支付或下单。");
          await loadApprovals({ silent: true });
        } catch (error) {
          showToast("演示记录创建失败，请确认人工确认记录服务可用。", true);
        } finally {
          state.governance.isApprovalLoading = false;
          syncUiAvailability();
        }
      }

      async function decideApproval(approvalId, decision, event) {
        event?.stopPropagation();
        if (!(await ensureServiceReady("处理人工确认"))) return;
        if (!approvalId || !["approve", "reject", "expire"].includes(decision)) return;
        const decisionPath =
          decision === "approve" ? "approve" : decision === "reject" ? "reject" : "expire";
        const decisionCopy = {
          approve: "人工批准：确认当前仍不触发真实支付或预订。",
          reject: "人工拒绝：真实供应链未接入。",
          expire: "",
        };
        try {
          const { response, data } = await governanceApi.submitApprovalDecision({
            apiBase: getApiBase(),
            stateToken: state.token,
            approvalId,
            decisionPath,
            reason: decision === "expire" ? "" : decisionCopy[decision],
          });
          if (!response.ok) {
            const message =
              data?.detail?.message ||
              data?.detail ||
              "当前账号没有处理权限，或人工确认记录状态已变化。";
            throw new Error(redactClientText(message));
          }
          state.governance.selectedApprovalId = data.approval_id || approvalId;
          showToast(`人工确认记录已${decision === "approve" ? "批准" : decision === "reject" ? "拒绝" : "过期"}`);
          await loadApprovals({ silent: true });
        } catch (error) {
          showToast(error.message || "人工确认处理失败", true);
        }
      }

      function syncUiAvailability() {
        const healthy = isServiceUsable();
        const input = document.getElementById("chatInput");
        const sendBtn = document.getElementById("sendBtn");
        const authBtn = document.getElementById("authBtn");
        const newChatBtn = document.getElementById("newChatBtn");
        const retryBtn = document.getElementById("retryHealthBtn");
        const governanceRefreshBtn = document.getElementById("governanceRefreshBtn");
        const createDemoApprovalBtn = document.getElementById("createDemoApprovalBtn");
        const inputWrapper = document.querySelector(".chat-input-wrapper");

        if (input) {
          input.disabled = !healthy || state.isLoading;
        }
        if (inputWrapper) {
          inputWrapper.classList.toggle(
            "disabled",
            !healthy || state.isLoading
          );
        }
        if (sendBtn) {
          sendBtn.disabled = !healthy || state.isLoading;
        }
        if (newChatBtn) {
          newChatBtn.disabled = !healthy;
        }
        if (authBtn) {
          authBtn.disabled = state.isAuthLoading || !healthy;
        }
        if (retryBtn) {
          retryBtn.disabled = state.serviceStatus === "checking";
        }
        if (governanceRefreshBtn) {
          governanceRefreshBtn.disabled = state.serviceStatus === "checking";
        }
        if (createDemoApprovalBtn) {
          createDemoApprovalBtn.disabled =
            !healthy || !state.user || state.governance.isApprovalLoading;
        }
        document.querySelectorAll("[data-planner-control='true']").forEach((el) => {
          el.disabled = !healthy;
        });
        syncAdminPortalVisibility();
        updateEndpointUI();
      }

      async function checkServiceHealth({
        silent = false,
        reason = "startup",
      } = {}) {
        if (state.serviceStatus === "checking") {
          syncUiAvailability();
        }

        if (!silent) {
          setRuntimeStatus("正在连接服务", "loading");
          updateEndpointTone("warning");
          setAuthServiceHint("正在检查服务状态，确认就绪后即可登录或注册。", "loading");
          setServiceBanner({
            visible: true,
            tone: "loading",
            title: "正在检查服务状态",
            text:
              reason === "startup"
                ? "页面正在确认后端和工具链是否就绪，请稍候。"
                : "正在重新连接服务，请稍候。",
            meta: "正在检测中",
          });
        }

        state.serviceStatus = "checking";
        syncUiAvailability();

        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 8000);
          const { response, data } = await governanceApi.fetchReadiness({
            apiBase: getApiBase(),
            signal: controller.signal,
          });
          clearTimeout(timeoutId);
          if (!data?.status) {
            throw new Error(`HTTP ${response.status}`);
          }

          state.readiness = {
            status: data.status,
            payload: data,
            checkedAt: Date.now(),
          };
          renderReadinessPanel(data);

          if (data.status === "ready" && data.startup_complete) {
            state.serviceStatus = "ready";
            state.lastHealthCheckAt = Date.now();
          setRuntimeStatus(state.user ? "已连接" : "服务就绪", "online");
            updateEndpointTone("idle");
            setAuthServiceHint(
              "服务已就绪，可以登录、创建会话并开始规划行程。",
              "online"
            );
            setServiceBanner({
              visible: false,
              tone: "success",
              title: "",
              text: "",
              meta: "",
            });
            syncUiAvailability();
            return true;
          }

          if (data.status === "degraded" && data.startup_complete) {
            state.serviceStatus = "degraded";
            state.lastHealthCheckAt = Date.now();
          setRuntimeStatus(state.user ? "已连接 · 降级" : "服务降级可用", "online");
            updateEndpointTone("warning");
            setAuthServiceHint(
              "核心服务可用，但部分外部能力降级；聊天、人工确认和报告边界仍可继续查看。",
              "online"
            );
            setServiceBanner({
              visible: true,
              tone: "loading",
              title: "服务降级可用",
              text: getReadinessStatusCopy("degraded"),
              meta: `检查时间：${formatClock(new Date())}`,
            });
            syncUiAvailability();
            return true;
          }

          state.serviceStatus = "not_ready";
          state.lastHealthCheckAt = Date.now();
          setRuntimeStatus("服务未就绪", "error");
          updateEndpointTone("error");
          setAuthServiceHint(
            "后端关键能力尚未就绪，暂时不能登录、聊天或处理人工确认。",
            "error"
          );
          setServiceBanner({
            visible: true,
            tone: "error",
            title: "服务尚未就绪",
            text: getReadinessStatusCopy("not_ready"),
            meta: `检查时间：${formatClock(new Date())}`,
          });
          syncUiAvailability();
          return false;
        } catch (error) {
          state.serviceStatus = "error";
          state.readiness = {
            status: "error",
            payload: null,
            checkedAt: Date.now(),
          };
          renderReadinessPanel({ status: "error", services: {} });
          setRuntimeStatus("服务暂不可用", "error");
          updateEndpointTone("error");
          setAuthServiceHint(
            "当前无法连接后端服务，请稍后重试或点击“重新检查”。",
            "error"
          );
          setServiceBanner({
            visible: true,
            tone: "error",
            title: "服务连接出现波动",
            text:
              "当前无法确认后端是否就绪。你可以稍后重试，或点击右侧按钮重新检查。",
            meta:
              state.lastHealthCheckAt > 0
                ? `上次成功检查：${formatClock(
                    new Date(state.lastHealthCheckAt)
                  )}`
                : "尚未完成首次健康检查",
          });
          syncUiAvailability();
          if (!silent) {
            showToast("服务暂时不可用，请稍后重试。", true);
          }
          return false;
        }
      }

      async function ensureServiceReady(actionLabel = "继续操作") {
        if (isServiceUsable()) return true;
        const ok = await checkServiceHealth({ silent: false, reason: actionLabel });
        if (!ok) {
          showToast(`服务尚未就绪，暂时无法${actionLabel}。`, true);
        }
        return ok;
      }

      async function retryHealthCheck() {
        await checkServiceHealth({ silent: false, reason: "manual-retry" });
      }

      function updateSessionOverview() {
        const current = getCurrentConversation();
        const conversationCountChip = document.getElementById(
          "conversationCountChip"
        );
        const activeConversationChip = document.getElementById(
          "activeConversationChip"
        );
        const chatTitle = document.getElementById("chatTitle");
        const chatSubtitle = document.getElementById("chatSubtitle");
        const tripOverview = document.getElementById("tripOverview");
        const total = state.conversations.length;

        if (conversationCountChip) {
          conversationCountChip.innerHTML = `<i class="fa-regular fa-folder-open"></i> ${total} 个行程`;
        }

        if (activeConversationChip) {
          activeConversationChip.innerHTML = current
            ? `<i class="fa-solid fa-location-arrow"></i> ${escapeHtml(
                current.title || "当前会话"
              )}`
            : '<i class="fa-regular fa-compass"></i> 未选择行程';
        }

        if (chatTitle) {
          chatTitle.classList.toggle("renameable", Boolean(current));
          chatTitle.title = current ? "双击可修改行程名称" : "行程助手";
        }

        if (chatSubtitle) {
          chatSubtitle.textContent = current
            ? `当前会话最近更新于 ${formatConversationStamp(
                current.updated_at || current.created_at
              )}`
            : "把出发地、时间、人数和预算告诉我，我会按步骤整理成一份旅游规划报告。";
        }

        if (tripOverview) {
          tripOverview.innerHTML = current
            ? `
                <span class="overview-chip primary">
                  <i class="fa-solid fa-route"></i> ${escapeHtml(
                    current.title || "新行程"
                  )}
                </span>
                <span class="overview-chip">
                  <i class="fa-regular fa-clock"></i> ${formatRelativeTime(
                    current.updated_at || current.created_at
                  )}
                </span>
              `
            : `
                <span class="overview-chip primary">
                  <i class="fa-solid fa-route"></i> 未选择行程
                </span>
                <span class="overview-chip">
                  <i class="fa-regular fa-pen-to-square"></i> 随时可以开始
                </span>
              `;
        }
      }

      function updateEndpointUI() {
        const endpoint = getApiBase();
        const endpointHint = document.getElementById("endpointHint");
        const composerHint = document.getElementById("composerHint");
        const apiConfig = document.querySelector(".api-config");

        if (apiConfig) {
          apiConfig.classList.toggle("hidden", !shouldShowApiConfig());
        }

        if (endpointHint) {
          const hostLabel =
            window.location.protocol === "file:"
              ? "本地调试模式"
              : "当前站点";
          endpointHint.innerHTML = `<i class="fa-solid fa-globe"></i> ${hostLabel}: ${escapeHtml(
            endpoint
          )}`;
        }

        if (composerHint) {
          if (state.serviceStatus === "error") {
            composerHint.textContent =
              "服务暂不可用，建议先点击“重新检查”确认后再继续操作";
          } else if (state.serviceStatus === "not_ready") {
            composerHint.textContent =
              "服务尚未就绪，请等待后端核心依赖完成初始化";
          } else if (state.serviceStatus === "degraded") {
            composerHint.textContent =
              "部分能力降级，可继续使用核心规划并留意右侧进度提示";
          } else if (state.serviceStatus === "checking") {
            composerHint.textContent =
              "正在检测服务状态，确认就绪后会自动开放发送和新建会话";
          } else {
            composerHint.textContent = shouldShowApiConfig()
              ? `当前接口地址：${endpoint}`
              : "部署环境已自动使用当前域名，无需手动配置接口地址";
          }
        }
      }

      function setSendButtonLoading(isLoading) {
        const sendBtn = document.getElementById("sendBtn");
        if (!sendBtn) return;
        sendBtn.classList.toggle("loading", isLoading);
        sendBtn.innerHTML = isLoading
          ? '<i class="fa-solid fa-spinner"></i>'
          : '<i class="fa-regular fa-paper-plane"></i>';
        syncUiAvailability();
      }

      function getWelcomeMarkup() {
        return `
                <div class="welcome-screen">
              <div class="welcome-logo"><i class="fa-solid fa-paper-plane"></i></div>
              <h3 class="welcome-title">欢迎使用 知行</h3>
              <p class="welcome-text">直接告诉我这次想去哪、几天、几个人、预算和偏好，我会按步骤整理目的地、交通、住宿，并在最后形成一份旅游规划报告。</p>
                    <div class="welcome-suggestions">
                        ${renderSuggestionButton(
                          "周末城市小旅行",
                          "我想从北京出发，端午去成都玩 4 天，2 个人，预算 5000 元，喜欢美食和慢节奏。"
                        )}
                        ${renderSuggestionButton(
                          "亲子长线行程",
                          "帮我规划一次去云南的 7 天亲子旅行，暑假出发，预算 12000 元。"
                        )}
                        ${renderSuggestionButton(
                          "先做目的地推荐",
                          "我想先看看 3 个适合海边度假的目的地，预算 8000 元以内。"
                        )}
                    </div>
                </div>
            `;
      }

      function renderSuggestionButton(label, text) {
        return `
          <button
            class="suggestion-btn"
            type="button"
            data-suggestion-text="${escapeAttribute(text)}"
          >${escapeHtml(label)}</button>
        `;
      }

      function updatePlannerSummary(message) {
        const el = document.getElementById("plannerSummary");
        if (el) {
          el.textContent = message;
        }
      }

      function updatePlannerAssistStrip() {
        const strip = document.getElementById("plannerAssistStrip");
        const panel = document.querySelector(".planner-panel");
        if (!strip) return;
        const fields = readPlannerFields();
        const checks = [
          { key: "origin", label: "出发地", required: true },
          { key: "destination", label: "目的地", required: true },
          { key: "days", label: "天数", required: true },
          { key: "budget", label: "预算", required: false },
          { key: "travelers", label: "人数", required: false },
          { key: "style", label: "偏好", required: false },
        ];
        const requiredFilled = checks.filter(
          (item) => item.required && fields[item.key]
        ).length;
        const ready = requiredFilled >= checks.filter((item) => item.required).length;
        panel?.classList.toggle("planner-panel-ready", ready);
        strip.innerHTML = checks
          .map((item) => {
            const filled = Boolean(fields[item.key]);
            const tone = filled ? "filled" : item.required ? "missing" : "optional";
            const icon = filled ? "fa-circle-check" : "fa-circle";
            return `
              <span class="planner-assist-chip ${tone}">
                <i class="fa-regular ${icon}"></i>
                ${escapeHtml(item.label)}${!item.required && !filled ? "可选" : ""}
              </span>
            `;
          })
          .join("");
        [
          ["plannerOrigin", fields.origin],
          ["plannerDestination", fields.destination],
          ["plannerDate", fields.date],
          ["plannerDays", fields.days],
          ["plannerTravelers", fields.travelers],
          ["plannerBudget", fields.budget],
          ["plannerTransport", fields.transport],
          ["plannerStay", fields.stay],
          ["plannerStyle", fields.style],
        ].forEach(([id, value]) => {
          document
            .getElementById(id)
            ?.closest(".planner-field")
            ?.classList.toggle("filled", Boolean(value));
        });
      }

      function appendToComposer(text, mode = "replace") {
        const input = document.getElementById("chatInput");
        const current = input.value.trim();
        input.value =
          mode === "append" && current ? `${current}\n${text}` : text;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
        input.focus();
        persistComposerDraft({ immediate: true });
      }

      function applySuggestion(text) {
        appendToComposer(text, "replace");
        updatePlannerSummary("这组需求已经填入输入框，可以直接发送；我会先确认你想要省心方案还是个性化旅游规划。");
        setRuntimeStatus("需求已填入，可以直接发送", "online");
      }

      function appendPlannerStyle(value) {
        const input = document.getElementById("plannerStyle");
        const current = input.value
          .split(/[，,\s]+/)
          .map((item) => item.trim())
          .filter(Boolean);
        if (!current.includes(value)) {
          current.push(value);
        }
        input.value = current.join("、");
        persistPlannerDraft();
        updatePlannerSummary(`已加入偏好关键词：${current.join("、")}`);
      }

      function fillPlannerTemplate(kind) {
        const templates = {
          weekend: {
            origin: "北京",
            destination: "成都",
            date: "本周末",
            days: "3天2晚",
            travelers: "2人",
            budget: "5000元以内",
            transport: "高铁或飞机都可以，少折腾优先",
            stay: "市中心，吃饭方便",
            style: "美食慢游、轻松、不赶行程",
          },
          family: {
            origin: "上海",
            destination: "云南",
            date: "暑假",
            days: "5天4晚",
            travelers: "2大1小",
            budget: "12000元左右",
            transport: "飞行时间别太折腾，市内交通轻松",
            stay: "亲子友好，卫生安静",
            style: "亲子出游、轻松、自然体验",
          },
        };
        const picked = templates[kind];
        if (!picked) return;
        document.getElementById("plannerOrigin").value = picked.origin;
        document.getElementById("plannerDestination").value = picked.destination;
        document.getElementById("plannerDate").value = picked.date;
        document.getElementById("plannerDays").value = picked.days;
        document.getElementById("plannerTravelers").value = picked.travelers;
        document.getElementById("plannerBudget").value = picked.budget;
        document.getElementById("plannerTransport").value = picked.transport;
        document.getElementById("plannerStay").value = picked.stay;
        document.getElementById("plannerStyle").value = picked.style;
        persistPlannerDraft();
        updatePlannerSummary("模板已填入，可以选择省心方案，也可以选择个性化旅游规划。");
      }

      function readPlannerFields() {
        return {
          origin: document.getElementById("plannerOrigin").value.trim(),
          destination: document
            .getElementById("plannerDestination")
            .value.trim(),
          date: document.getElementById("plannerDate").value.trim(),
          days: document.getElementById("plannerDays").value.trim(),
          travelers: document
            .getElementById("plannerTravelers")
            .value.trim(),
          budget: document.getElementById("plannerBudget").value.trim(),
          transport: document.getElementById("plannerTransport").value.trim(),
          stay: document.getElementById("plannerStay").value.trim(),
          style: document.getElementById("plannerStyle").value.trim(),
        };
      }

      function buildPlannerOpening({ origin, destination }) {
        if (origin && destination) return `我想从${origin}出发去${destination}`;
        if (destination) return `我想去${destination}旅行`;
        if (origin) return `我想从${origin}出发规划一次旅行`;
        return "我想规划一次旅行";
      }

      function composePlannerDraft(mode = "personalized") {
        const {
          origin,
          destination,
          date,
          days,
          travelers,
          budget,
          transport,
          stay,
          style,
        } = readPlannerFields();

        const parts = [
          buildPlannerOpening({ origin, destination }),
          date ? `，出发时间大概是${date}` : "",
          days ? `，行程预计${days}` : "",
          travelers ? `，同行人数是${travelers}` : "",
          budget ? `，预算希望控制在${budget}` : "",
          transport ? `，交通偏好是${transport}` : "",
          stay ? `，住宿偏好是${stay}` : "",
          style ? `，偏好是${style}` : "",
        ];

        const modeInstruction =
          mode === "agency"
            ? "。请按“现成省心方案”来做：优先匹配成熟路线样板，直接给交通、住宿商圈与示例酒店、门票参考、餐饮、费用说明和涵盖服务；价格只按参考价和待核验口径说明，不承诺实时锁价。"
            : "。请按“个性化旅游规划”来做：先判断需求是否完整；如果已经足够，请继续完成目的地、交通、住宿、预算、每日路线，并在最后整理成专属于我的个性化旅游规划报告。交通和住宿可以结合可用工具做真实查询与对比。";
        parts.push(modeInstruction);

        const draft = parts.join("");
        appendToComposer(draft, "replace");
        updatePlannerSummary(
          mode === "agency"
            ? "省心方案草稿已放进输入框：会优先匹配成熟路线，并说明价格待核验边界。"
            : "个性化旅游规划草稿已放进输入框：会继续补齐交通、住宿、预算和最终报告。"
        );
        setRuntimeStatus(
          mode === "agency" ? "省心方案草稿已整理" : "个性化规划草稿已整理",
          "online"
        );
      }

      function resetPlannerDraft(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        [
          "plannerOrigin",
          "plannerDestination",
          "plannerDate",
          "plannerDays",
          "plannerTravelers",
          "plannerBudget",
          "plannerTransport",
          "plannerStay",
          "plannerStyle",
        ].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.value = "";
        });
        clearDraftStorage(plannerDraftKey);
        updatePlannerAssistStrip();
        updatePlannerSummary(
          silent
            ? "可以先选一种规划方式；如果你只写旅行需求，我会先帮你确认要省心方案还是个性化旅游规划。"
            : "行程摘要已清空。你可以重新填写，也可以直接在下面描述需求。"
        );
      }

      function resetConversationDrafts(options = {}) {
        const silent =
          typeof options === "boolean"
            ? options
            : Boolean(options?.silent);
        resetComposerDraft({ silent: true });
        resetPlannerDraft({ silent });
      }

      function isDefaultConversationTitle(title = "") {
        const normalized = (title || "").trim();
        return !normalized || normalized === DEFAULT_CONVERSATION_TITLE;
      }

      async function updateConversationTitle(id, title, options = {}) {
        const nextTitle = (title || "").trim();
        if (!id || !nextTitle) return false;
        const { response, data } = await conversationApi.updateConversation({
          apiBase: getApiBase(),
          stateToken: state.token,
          id,
          payload: { title: nextTitle },
        });
        if (!response.ok) {
          throw new Error(`conversation-title-${response.status}`);
        }
        const current = state.conversations.find((conv) => conv.id === id);
        if (current) current.title = data.title || nextTitle;
        if (state.editingConversationId === id) {
          state.editingConversationId = null;
        }
        if (state.currentConversationId === id) {
          const chatTitle = document.getElementById("chatTitle");
          if (chatTitle) {
            chatTitle.classList.remove("editing");
            chatTitle.textContent = data.title || nextTitle;
          }
        }
        renderConversationsList();
        updateSessionOverview();
        if (!options?.silent) {
          showToast("行程名称已更新");
        }
        return true;
      }

      function sanitizeConversationTitleSegment(value = "") {
        return String(value || "")
          .replace(
            /^(?:\u4ece|\u53bb|\u5230|\u5f80|\u60f3\u53bb|\u51c6\u5907\u53bb|\u8ba1\u5212\u53bb)\s*/u,
            ""
          )
          .replace(
            /\s*(?:\u51fa\u53d1|\u6e38\u73a9|\u65c5\u884c|\u65c5\u6e38|\u770b\u770b|\u901b\u901b|\u4f4f\u51e0\u665a|\u73a9\u51e0\u5929|\u73a9\u51e0\u591c)\s*$/u,
            ""
          )
          .replace(/[\uFF0C\u3002\uFF1B\u3001,.!?]+/gu, " ")
          .replace(/\s+/g, " ")
          .trim();
      }

      function extractTitleDays(text = "") {
        const normalized = String(text || "").replace(/\s+/g, "");
        const match = normalized.match(
          /(\d+\u5929\d+[\u665a\u591c]|\u4e00\u5929\u4e00\u591c|\u4e24\u5929\u4e00\u591c|\u4e09\u5929\u4e24\u591c|\u56db\u5929\u4e09\u591c|\u4e94\u5929\u56db\u591c|\u516d\u5929\u4e94\u591c|\u4e03\u5929\u516d\u591c)/u
        );
        return match ? match[1] : "";
      }

      function generateConversationTitle(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return DEFAULT_CONVERSATION_TITLE;

        const routeMatch = normalized.match(
          /\u4ece\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})\s*(?:\u51fa\u53d1)?\s*(?:\u53bb|\u5230)\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})/u
        );
        const destinationMatch = normalized.match(
          /(?:\u53bb|\u5230)\s*([^\s\uFF0C\u3002\uFF1B\u3001,]{1,12})(?:\u65c5\u6e38|\u65c5\u884c|\u6e38\u73a9|\u73a9|\u901b|\u770b\u770b)?/u
        );
        const dayText = extractTitleDays(normalized);
        const styleTag = /\u60c5\u4fa3/u.test(normalized)
          ? "\u60c5\u4fa3"
          : /\u4eb2\u5b50/u.test(normalized)
          ? "\u4eb2\u5b50"
          : /\u7f8e\u98df/u.test(normalized)
          ? "\u7f8e\u98df"
          : /\u4eba\u6587/u.test(normalized)
          ? "\u4eba\u6587"
          : "";

        if (routeMatch?.[1] && routeMatch?.[2]) {
          const origin = sanitizeConversationTitleSegment(routeMatch[1]);
          const destination = sanitizeConversationTitleSegment(routeMatch[2]);
          return [`${origin} → ${destination}`, dayText, styleTag]
            .filter(Boolean)
            .join(" · ")
            .slice(0, 24);
        }

        if (destinationMatch?.[1]) {
          const destination = sanitizeConversationTitleSegment(destinationMatch[1]);
          return [destination, dayText, styleTag]
            .filter(Boolean)
            .join(" · ")
            .slice(0, 24);
        }

        const summary = normalized
          .replace(
            /^(?:\u6211\u60f3|\u5e2e\u6211|\u8bf7\u5e2e\u6211|\u9ebb\u70e6\u5e2e\u6211|\u60f3\u8981|\u8ba1\u5212|\u51c6\u5907)\s*/u,
            ""
          )
          .split(/[\u3002\uFF01\uFF1F.!?]/u)[0]
          .trim()
          .slice(0, 24);
        return summary || DEFAULT_CONVERSATION_TITLE;
      }

      async function maybeAutoNameCurrentConversation(text = "") {
        const conversationId = state.currentConversationId;
        if (!conversationId) return;
        const current = getCurrentConversation();
        if (current && !isDefaultConversationTitle(current.title)) return;
        const nextTitle = generateConversationTitle(text);
        if (!nextTitle || isDefaultConversationTitle(nextTitle)) return;
        try {
          await updateConversationTitle(conversationId, nextTitle, { silent: true });
        } catch (error) {
          console.error(error);
        }
      }

      function formatClock(value = new Date()) {
        const date = value instanceof Date ? value : new Date(value);
        const hh = String(date.getHours()).padStart(2, "0");
        const mm = String(date.getMinutes()).padStart(2, "0");
        return `${hh}:${mm}`;
      }

      function formatInlineText(text) {
        return escapeHtml(text)
          .replace(/`([^`]+)`/g, '<span class="inline-code">$1</span>')
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      }

      function sanitizeAssistantOutputText(text = "") {
        const visibleText = stripAssistantThinkingBlocks(text);
        const hiddenLinePatterns = [
          /^(requirement_collection|destination_selection|transport_planning|accommodation_planning|order_generation|report_generation)$/i,
          /^(收集需求|需求收集|当前阶段|当前步骤|阶段切换|状态更新|流程推进)$/u,
          /^(进入|切换到).{0,18}阶段$/u,
          /^(tool_call|工具调用|调用工具)[:：]?\s*/i,
          /^(理解|收到|明白|好的)$/u,
        ];
        return visibleText
          .split("\n")
          .filter((line) => {
            const trimmed = line.trim();
            if (!trimmed) return true;
            if (/^-{1,3}$/.test(trimmed) || /^---+$/.test(trimmed)) return false;
            return !hiddenLinePatterns.some((pattern) => pattern.test(trimmed));
          })
          .join("\n")
          .replace(/\n{3,}/g, "\n\n")
          .trim();
      }

      function stripAssistantThinkingBlocks(text = "") {
        const thinkingFilter = createAssistantThinkingFilter();
        return thinkingFilter.feed(text) + thinkingFilter.finish();
      }

      function normalizeCollapsedMarkdownTables(text = "") {
        return String(text || "")
          .replace(
            /(\|[^\n|]+(?:\|[^\n|]+)+\|)\s+(\|:?-{3,}:?(?:\|:?-{3,}:?)+\|)/g,
            "$1\n$2"
          )
          .replace(/\s+(\|\s*(?:D\d+|Day\s*\d+|\d+)\s*\|)/gu, "\n$1");
      }

      function splitAssistantBlocks(text) {
        return normalizeCollapsedMarkdownTables(sanitizeAssistantOutputText(text))
          .replace(/\r\n/g, "\n")
          .split(/\n{2,}/)
          .map((block) => block.trim())
          .filter(Boolean);
      }

      function normalizeSectionTitle(title = "") {
        return title
          .replace(/^#{1,3}\s+/, "")
          .replace(/^\*\*(.+?)\*\*$/, "$1")
          .replace(/^【(.+?)】$/, "$1")
          .replace(/^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]+\s*/u, "")
          .replace(/[：:]\s*$/, "")
          .trim();
      }

      function isReportSummaryMarkerOnly(line = "") {
        const normalized = normalizeSectionTitle(line)
          .replace(/^[-*•]\s*/, "")
          .trim();
        return /^(?:每日安排|每日行程|分日安排|分日行程)$/u.test(normalized);
      }

      function filterReportSummaryLines(lines = []) {
        return lines.filter((line) => !isReportSummaryMarkerOnly(line));
      }

      function isEmbeddedSectionHeading(line = "") {
        const normalized = normalizeSectionTitle(
          line
            .replace(/^[-*•]\s*/, "")
            .replace(/（.*$/, "")
            .replace(/\(.*$/, "")
            .trim()
        );
        if (!normalized || normalized.length > 26) return false;
        return /^(预算|交通|住宿|住宿推荐|住哪里|玩法建议|玩法|行程安排|每日安排|目的地|提醒|下一步)/.test(
          normalized
        );
      }

      function looksLikeDecisionPrompt(text = "") {
        return /想跟你确认|确认一下|请确认|你觉得|要不要|是否|还是你想|可以直接告诉我|你更想|更合适吗|看看其他备选|哪个方向/u.test(
          text
        );
      }

      function inferSectionMetaFromBody(lines = []) {
        const bodyText = lines.join(" ");
        if (looksLikeDecisionPrompt(bodyText)) {
          return { tone: "next", icon: "fa-circle-question" };
        }
        if (/高铁|火车|自驾|大巴|公交|航班|车程|打车|高速|车站|出发|到达/.test(bodyText)) {
          return { tone: "transport", icon: "fa-train-subway" };
        }
        if (/住宿|酒店|民宿|温泉|私汤|住在|客栈|房型|每晚/.test(bodyText)) {
          return { tone: "stay", icon: "fa-bed" };
        }
        if (/预算|费用|花费|价格|每人|总共/.test(bodyText)) {
          return { tone: "budget", icon: "fa-wallet" };
        }
        if (/玩法|景点|适合|行程|打卡|游览|放松|亲水|徒步|温泉|眉县|太白山/.test(bodyText)) {
          return { tone: "overview", icon: "fa-map-location-dot" };
        }
        return null;
      }

      function expandStructuredTravelBlocks(blocks = []) {
        const expanded = [];
        blocks.forEach((block) => {
          const normalizedBlock = block
            .replace(
              /([^\n])\s+((?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?\s*)?\*\*[^*\n]{2,18}\*\*[：:])/gu,
              "$1\n$2"
            )
            .replace(
              /([^\n])\s+((?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?\s*)?(交通建议|住宿选址|行程基调|住宿推荐|交通方案|玩法建议|行程安排|预算建议)[：:])/gu,
              "$1\n$2"
            );
          const lines = normalizedBlock
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          let current = [];
          lines.forEach((line, index) => {
            const shouldStartNew =
              index > 0 &&
              isEmbeddedSectionHeading(line) &&
              current.length > 0;
            if (shouldStartNew) {
              expanded.push(current.join("\n"));
              current = [line];
              return;
            }
            current.push(line);
          });
          if (current.length) {
            expanded.push(current.join("\n"));
          }
        });
        return expanded;
      }

      function getTravelSectionMeta(title) {
        const normalized = normalizeSectionTitle(title).toLowerCase();
        const contains = (...keywords) =>
          keywords.some((keyword) => normalized.includes(keyword));

        if (looksLikeDecisionPrompt(normalized)) {
          return { tone: "next", icon: "fa-circle-question" };
        }
        if (contains("下一步", "接下来", "行动", "后续", "请评价")) {
          return { tone: "next", icon: "fa-arrow-right" };
        }
        if (contains("费用说明", "费用边界", "预算", "费用", "花费", "价格", "成本")) {
          return { tone: "budget", icon: "fa-wallet" };
        }
        if (contains("涵盖服务", "服务边界", "接送", "预约", "应急", "人工确认")) {
          return { tone: "service", icon: "fa-handshake-angle" };
        }
        if (
          contains(
            "概览",
            "总览",
            "方案",
            "推荐理由",
            "行程安排",
            "每日安排",
            "一句话定位",
            "为什么适合你",
            "适合你"
          )
        ) {
          return { tone: "overview", icon: "fa-map-location-dot" };
        }
        if (contains("目的地", "城市", "景点", "路线")) {
          return { tone: "overview", icon: "fa-location-dot" };
        }
        if (contains("交通", "航班", "火车", "高铁", "大交通", "出发")) {
          return { tone: "transport", icon: "fa-train-subway" };
        }
        if (contains("住宿", "酒店", "民宿", "住哪里")) {
          return { tone: "stay", icon: "fa-bed" };
        }
        if (contains("美食", "餐饮", "吃")) {
          return { tone: "food", icon: "fa-utensils" };
        }
        if (contains("提醒", "注意", "避坑", "贴士", "须知")) {
          return { tone: "warning", icon: "fa-triangle-exclamation" };
        }
        return null;
      }

      function cleanJourneyLocationValue(value = "") {
        return value
          .replace(/^[-*#\s]+/, "")
          .replace(/[📍✅⚠️✨🌤️]/g, "")
          .replace(/^(?:上午|中午|午餐|下午|傍晚|晚上|晚餐|早餐|早上|全天)[：:\s-]*/u, "")
          .replace(/^(需求很完整|信息基本齐了|现在先把|我已经按你的要求查到|我先帮你梳理确认一下)[！!：:\s]*/g, "")
          .replace(/\s*[·•｜|].*$/, "")
          .replace(/(一句话定位|为什么适合你|适合你|两个小提醒|小提醒|提醒|建议)$/g, "")
          .replace(/\s+/g, " ")
          .trim();
      }

      function isJourneyNoiseLocation(value = "") {
        const normalized = cleanJourneyLocationValue(value);
        if (!normalized) return true;
        if (normalized.length > 28) return true;
        return /^(?:路线参考|当前查看|总览|默认|若满意|如果满意|请评价|请评估|下一步|需要你确认|值停留|地图定位|住宿周边|关键节点|自然醒|自由返程|从容返程|返回|返程|专车接站|办理入住|稍作休整|待核验|费用待核验|停留时间待核验|杭州玩\d+天|西安到杭州玩\d+天)$/u.test(
          normalized
        );
      }

      function splitTableCells(line) {
        return line
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((cell) => cell.trim());
      }

      function isMarkdownTable(lines) {
        if (lines.length < 2) return false;
        if (!lines[0].includes("|") || !lines[1].includes("|")) return false;
        const dividerCells = splitTableCells(lines[1]);
        return (
          dividerCells.length > 0 &&
          dividerCells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, "")))
        );
      }

      function getMarkdownTableSpan(lines, startIndex = 0) {
        const rest = lines.slice(startIndex);
        if (!isMarkdownTable(rest)) return 0;
        let endIndex = startIndex + 2;
        while (endIndex < lines.length && lines[endIndex].includes("|")) {
          endIndex += 1;
        }
        return endIndex - startIndex;
      }

      function renderMarkdownTable(lines) {
        const headers = splitTableCells(lines[0]);
        const rows = lines
          .slice(2)
          .map(splitTableCells)
          .filter((cells) => cells.some(Boolean));

        if (!headers.length || !rows.length) {
          return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
        }

        if (isTransportTable(headers)) {
          return renderTransportTable(headers, rows);
        }

        return `
          <div class="message-table-wrap">
            <table class="message-table">
              <thead>
                <tr>${headers
                  .map((header) => `<th>${formatInlineText(header)}</th>`)
                  .join("")}</tr>
              </thead>
              <tbody>
                ${rows
                  .map(
                    (cells) => `<tr>${headers
                      .map(
                        (_, index) =>
                          `<td>${formatInlineText(cells[index] || "")}</td>`
                      )
                      .join("")}</tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
      }

      function normalizeTransportHeader(header = "") {
        const normalized = header.replace(/\s+/g, "").toLowerCase();
        if (
          normalized.includes("车次") ||
          normalized.includes("车次/航班") ||
          normalized.includes("航班") ||
          normalized.includes("班次") ||
          normalized.includes("方案")
        ) {
          return "code";
        }
        if (
          normalized.includes("出发时间") ||
          normalized.includes("到达时间") ||
          normalized.includes("出发→到达") ||
          normalized.includes("出发->到达") ||
          normalized.includes("时间")
        ) {
          return "schedule";
        }
        if (normalized.includes("耗时") || normalized.includes("历时")) {
          return "duration";
        }
        if (
          normalized.includes("票价") ||
          normalized.includes("价格") ||
          normalized.includes("费用") ||
          normalized.includes("二等座") ||
          normalized.includes("一等座") ||
          normalized.includes("商务座")
        ) {
          return "price";
        }
        if (
          normalized.includes("推荐理由") ||
          normalized.includes("备注") ||
          normalized.includes("说明") ||
          normalized.includes("建议")
        ) {
          return "reason";
        }
        if (normalized.includes("余票") || normalized.includes("舱位")) {
          return "inventory";
        }
        return "extra";
      }

      function isTransportTable(headers = []) {
        const mapped = headers.map(normalizeTransportHeader);
        const hasCode = mapped.includes("code");
        const hasCoreInfo =
          mapped.includes("schedule") ||
          mapped.includes("duration") ||
          mapped.includes("price");
        return hasCode && hasCoreInfo;
      }

      function detectTransportCardKind(code = "", reason = "") {
        const source = `${code} ${reason}`.toUpperCase();
        if (
          /^(G|D|C|K|T|Z)\d+/.test(code.toUpperCase()) ||
          source.includes("高铁") ||
          source.includes("火车")
        ) {
          return { label: "铁路方案", icon: "fa-train-subway" };
        }
        if (
          /^[A-Z]{2}\d+/.test(code.toUpperCase()) ||
          source.includes("航班") ||
          source.includes("飞机")
        ) {
          return { label: "航班方案", icon: "fa-plane-departure" };
        }
        if (source.includes("自驾") || source.includes("驾车")) {
          return { label: "自驾方案", icon: "fa-car-side" };
        }
        return { label: "交通方案", icon: "fa-route" };
      }

      function splitScheduleText(text = "") {
        const compact = text.replace(/\s+/g, " ").trim();
        const parts = compact.split(/\s*(?:→|->|➜|至)\s*/);
        if (parts.length >= 2) {
          return {
            departure: parts[0].trim(),
            arrival: parts.slice(1).join(" → ").trim(),
          };
        }
        return { departure: compact, arrival: "" };
      }

      function renderTransportTable(headers, rows) {
        const keyOrder = headers.map(normalizeTransportHeader);
        const cards = rows.map((cells) => {
          const entry = {};
          headers.forEach((header, index) => {
            const key = keyOrder[index];
            const value = cells[index] || "";
            if (key === "extra") {
              if (!entry.extra) entry.extra = [];
              if (value) {
                entry.extra.push({ label: header, value });
              }
              return;
            }
            if (entry[key]) {
              entry[key] = `${entry[key]} ${value}`.trim();
            } else {
              entry[key] = value;
            }
          });

          const kind = detectTransportCardKind(entry.code || "", entry.reason || "");
          const schedule = splitScheduleText(entry.schedule || "");
          const recommendationTone =
            /(推荐|首选|优先)/.test(entry.reason || "") ? "recommended" : "";

          return `
            <article class="transport-option-card ${recommendationTone}">
              <div class="transport-option-head">
                <div class="transport-option-kind">
                  <i class="fa-solid ${kind.icon}"></i>
                  <span>${kind.label}</span>
                </div>
                <div class="transport-option-code">${formatInlineText(entry.code || "待确认")}</div>
              </div>
              <div class="transport-option-times">
                <div class="transport-stop">
                  <span class="transport-stop-label">出发</span>
                  <strong>${formatInlineText(schedule.departure || "待确认")}</strong>
                </div>
                <div class="transport-stop-arrow">
                  <i class="fa-solid fa-arrow-right-long"></i>
                </div>
                <div class="transport-stop">
                  <span class="transport-stop-label">到达</span>
                  <strong>${formatInlineText(schedule.arrival || "待确认")}</strong>
                </div>
              </div>
              <div class="transport-option-meta">
                ${
                  entry.duration
                    ? `<span class="transport-meta-pill"><i class="fa-regular fa-clock"></i> ${formatInlineText(
                        entry.duration
                      )}</span>`
                    : ""
                }
                ${
                  entry.price
                    ? `<span class="transport-meta-pill price"><i class="fa-solid fa-yen-sign"></i> ${formatInlineText(
                        entry.price
                      )}</span>`
                    : ""
                }
                ${
                  entry.inventory
                    ? `<span class="transport-meta-pill"><i class="fa-solid fa-ticket"></i> ${formatInlineText(
                        entry.inventory
                      )}</span>`
                    : ""
                }
              </div>
              ${
                entry.reason
                  ? `<div class="transport-option-reason">${formatInlineText(entry.reason)}</div>`
                  : ""
              }
              ${
                entry.extra?.length
                  ? `<dl class="transport-extra-list">${entry.extra
                      .map(
                        (item) => `
                          <div class="transport-extra-item">
                            <dt>${formatInlineText(item.label)}</dt>
                            <dd>${formatInlineText(item.value)}</dd>
                          </div>
                        `
                      )
                      .join("")}</dl>`
                  : ""
              }
            </article>
          `;
        });

        return `<div class="transport-options-board">${cards.join("")}</div>`;
      }

      function renderAssistantLineGroup(lines) {
        if (!lines.length) return "";

        if (isMarkdownTable(lines)) {
          return renderMarkdownTable(lines);
        }

        if (lines.every((line) => /^[-*•]\s+/.test(line))) {
          return `<ul>${lines
            .map(
              (line) =>
                `<li>${formatInlineText(line.replace(/^[-*•]\s+/, ""))}</li>`
            )
            .join("")}</ul>`;
        }

        if (lines.every((line) => /^\d+\.\s+/.test(line))) {
          return `<ol>${lines
            .map(
              (line) =>
                `<li>${formatInlineText(line.replace(/^\d+\.\s+/, ""))}</li>`
            )
            .join("")}</ol>`;
        }

        if (/^#{1,3}\s+/.test(lines[0])) {
          const title = lines[0].replace(/^#{1,3}\s+/, "");
          const bodyLines = lines.slice(1);
          return `${title ? `<h4>${formatInlineText(title)}</h4>` : ""}${
            bodyLines.length
              ? `<p>${bodyLines.map((line) => formatInlineText(line)).join("<br>")}</p>`
              : ""
          }`;
        }

        return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
      }

      function renderAssistantLines(lines) {
        if (!lines.length) return "";

        const chunks = [];
        let current = [];
        const flushCurrent = () => {
          if (!current.length) return;
          chunks.push(renderAssistantLineGroup(current));
          current = [];
        };

        for (let index = 0; index < lines.length; index += 1) {
          const tableSpan = getMarkdownTableSpan(lines, index);
          if (tableSpan) {
            flushCurrent();
            chunks.push(renderMarkdownTable(lines.slice(index, index + tableSpan)));
            index += tableSpan - 1;
            continue;
          }
          current.push(lines[index]);
        }

        flushCurrent();
        return chunks.join("");
      }

      function dedupeAssistantFallbackBlocks(blocks = []) {
        const seen = new Set();
        return (Array.isArray(blocks) ? blocks : []).filter((block) => {
          const lines = String(block || "")
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return false;
          const title = lines[0].replace(/^#{1,4}\s+/, "").trim();
          const normalizedTitle = title.replace(/[【】\[\]\s*_#|:-]+/g, "");
          const normalizedBody = lines
            .join(" ")
            .replace(/[【】\[\]\s*_#|:-]+/g, "")
            .replace(/\s+/g, "")
            .toLowerCase();
          const isBudget = /预算|费用|价格|花费/u.test(normalizedTitle);
          const key = isBudget
            ? `budget:${normalizedTitle || "section"}`
            : `${normalizedTitle}:${normalizedBody}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      }

      function renderAssistantFallback(blocks) {
        const uniqueBlocks = dedupeAssistantFallbackBlocks(blocks);
        return `<div class="travel-fallback">${uniqueBlocks
          .map((block) => {
            const lines = block
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean);
            return renderAssistantLines(lines);
          })
          .join("")}</div>`;
      }

      function truncateJourneyNote(text = "", fallback = "等待你继续补充细节") {
        const normalized = text.replace(/\s+/g, " ").trim();
        if (!normalized) return fallback;
        return normalized.length > 42 ? `${normalized.slice(0, 42)}…` : normalized;
      }

      function splitJourneyFragments(text = "") {
        return text
          .replace(/\s+/g, " ")
          .split(/[。！？；\n]/)
          .map((part) => part.trim())
          .filter((part) => part.length >= 4 && part.length <= 36);
      }

      function extractJourneyHighlights(sections) {
        const highlightKeywords = [
          "山",
          "海",
          "湖",
          "江",
          "河",
          "岛",
          "古镇",
          "老街",
          "夜市",
          "温泉",
          "寺",
          "博物馆",
          "公园",
          "书店",
          "营地",
          "民宿",
          "美食",
          "小吃",
          "日落",
          "咖啡",
          "亲水",
          "徒步",
          "骑行",
          "露营",
        ];
        const pool = sections
          .filter((section) => ["overview", "stay", "next"].includes(section.tone))
          .flatMap((section) => splitJourneyFragments(section.rawLines.join(" ")));

        const scored = pool
          .map((fragment) => ({
            fragment,
            score: highlightKeywords.reduce(
              (count, keyword) => count + (fragment.includes(keyword) ? 1 : 0),
              0
            ),
          }))
          .sort((a, b) => b.score - a.score || a.fragment.length - b.fragment.length);

        const picked = [];
        scored.forEach(({ fragment }) => {
          const normalized = fragment.replace(/[：:]/g, " ").trim();
          if (
            !normalized ||
            isJourneyNoiseLocation(normalized) ||
            picked.some((item) => item.includes(normalized) || normalized.includes(item))
          ) {
            return;
          }
          picked.push(normalized);
        });

        return picked.slice(0, 4);
      }

      function inferHighlightTheme(text = "") {
        if (/温泉|亲水|湖|江|河|海/.test(text)) return "亲水放松";
        if (/古镇|老街|博物馆|寺|书店/.test(text)) return "人文慢游";
        if (/山|徒步|骑行|营地|露营/.test(text)) return "户外探索";
        if (/美食|小吃|夜市|咖啡/.test(text)) return "在地风味";
        return "值得停留";
      }

      function buildJourneyHighlightCards(highlights = []) {
        return highlights.map((text, index) => {
          const normalized = text.replace(/\s+/g, " ").trim();
          const title = normalized.length > 14 ? `${normalized.slice(0, 14)}…` : normalized;
          const note =
            normalized.length > 36
              ? `${normalized.slice(0, 36)}…`
              : normalized || "适合继续展开玩法、停留时长和拍照点。";
          return {
            index,
            title,
            note,
            theme: inferHighlightTheme(normalized),
          };
        });
      }

      function getKnownCityNearbyPlaces(destination = "") {
        const city = cleanJourneyLocationValue(destination);
        const presets = [
          {
            test: /南京|金陵/u,
            places: [
              ["主要景点", "夫子庙秦淮风光带", "fa-landmark"],
              ["热闹商业街", "新街口商圈", "fa-store"],
              ["美食小吃", "老门东美食街", "fa-bowl-food"],
            ],
          },
          {
            test: /成都|蓉城/u,
            places: [
              ["主要景点", "武侯祠", "fa-landmark"],
              ["热闹商业街", "春熙路", "fa-store"],
              ["美食小吃", "宽窄巷子", "fa-bowl-food"],
            ],
          },
          {
            test: /西安|长安/u,
            places: [
              ["主要景点", "西安城墙", "fa-landmark"],
              ["热闹商业街", "钟楼商圈", "fa-store"],
              ["美食小吃", "回民街", "fa-bowl-food"],
            ],
          },
          {
            test: /北京/u,
            places: [
              ["主要景点", "故宫博物院", "fa-landmark"],
              ["热闹商业街", "王府井", "fa-store"],
              ["美食小吃", "簋街", "fa-bowl-food"],
            ],
          },
          {
            test: /上海/u,
            places: [
              ["主要景点", "外滩", "fa-landmark"],
              ["热闹商业街", "南京东路步行街", "fa-store"],
              ["美食小吃", "云南南路美食街", "fa-bowl-food"],
            ],
          },
          {
            test: /杭州/u,
            places: [
              ["主要景点", "西湖", "fa-landmark"],
              ["热闹商业街", "湖滨银泰", "fa-store"],
              ["美食小吃", "河坊街", "fa-bowl-food"],
            ],
          },
          {
            test: /长沙/u,
            places: [
              ["主要景点", "橘子洲", "fa-landmark"],
              ["热闹商业街", "五一广场", "fa-store"],
              ["美食小吃", "坡子街", "fa-bowl-food"],
            ],
          },
        ];
        return presets.find((preset) => preset.test.test(city))?.places || [];
      }

      function buildStayNearbyHighlights(previewState = {}) {
        const destination = cleanJourneyLocationValue(
          previewState.cityPair?.destination || previewState.destinationSection?.title || ""
        );
        const presetPlaces = getKnownCityNearbyPlaces(destination);
        if (presetPlaces.length) {
          return presetPlaces.map(([label, name, icon]) => ({
            label,
            name,
            icon,
            query: destination && !name.includes(destination) ? `${destination} ${name}` : name,
          }));
        }
        const picked = [];
        const push = (label, pattern, icon, fallback) => {
          const hit = (previewState.highlights || []).find((item) => pattern.test(item));
          const name = cleanJourneyLocationValue(hit || fallback || "");
          if (!name) return;
          picked.push({
            label,
            name,
            icon,
            query: destination && !name.includes(destination) ? `${destination} ${name}` : name,
          });
        };
        push("主要景点", /景区|景点|公园|博物馆|寺|山|湖|江|河|古镇/u, "fa-landmark", `${destination} 主要景点`);
        push("热闹商业街", /商圈|步行街|夜市|老街|街区|广场/u, "fa-store", `${destination} 商业街`);
        push("美食小吃", /美食|小吃|餐|夜市|咖啡|甜品/u, "fa-bowl-food", `${destination} 小吃街`);
        return picked.filter((item) => item.name && !/待确认|待补充/.test(item.name));
      }

      function extractJourneyRhythm(summaryBlocks, sections) {
        const rhythmLines = [];
        const directRhythmLines = [...summaryBlocks.flat(), ...sections.flatMap((section) => section.rawLines)]
          .map((line) => line.trim())
          .filter(Boolean)
          .filter((line) =>
            /day\s*\d+|第.天|上午|中午|下午|傍晚|晚上|早上|行程|安排/i.test(line)
          );

        directRhythmLines.forEach((line) => {
          const normalized = line.replace(/^[-*•]\s*/, "").trim();
          if (
            normalized &&
            !rhythmLines.some((item) => item.includes(normalized) || normalized.includes(item))
          ) {
            rhythmLines.push(normalized);
          }
        });

        if (rhythmLines.length >= 3) {
          return rhythmLines.slice(0, 3);
        }

        const overviewSection =
          sections.find((section) => section.title.includes("行程") || section.title.includes("安排")) ||
          sections.find((section) => section.tone === "overview");
        const fallbackFragments = splitJourneyFragments(
          overviewSection?.rawLines?.join(" ") || summaryBlocks.flat().join(" ")
        );

        fallbackFragments.forEach((fragment) => {
          if (
            fragment &&
            !rhythmLines.some((item) => item.includes(fragment) || fragment.includes(item))
          ) {
            rhythmLines.push(fragment);
          }
        });

        return rhythmLines.slice(0, 3);
      }

      function hasJourneyClarificationSignal(text = "") {
        return /确认一下|想跟你确认|哪个更合适|还是.*预算|想先了解|更精准|会影响|待补充|待确认|请先帮我判断|请先确认|方便|是否完整|告诉我|大概想什么时候|从哪个城市出发|继续补充/.test(
          text
        );
      }

      function hasJourneyPlanSignal(text = "", sections = [], highlights = [], rhythm = []) {
        if (sections.some((section) => ["stay", "warning", "next", "food"].includes(section.tone))) {
          return true;
        }
        if (highlights.length >= 2 || rhythm.length >= 2) {
          return true;
        }
        return /推荐|路线|行程|安排|玩法|景点|入住|住宿|酒店|民宿|车次|航班|美食|看点|打卡|游览/.test(
          text
        );
      }

      function splitJourneyWaypoints(text = "") {
        const cleaned = (text || "")
          .replace(/^#{1,3}\s+/, "")
          .replace(/^.*?[|｜]/, "")
          .replace(/^\s*(?:day)\s*\d+\s*/i, "")
          .replace(/^\s*第\s*[一二三四五六七八九十\d]+\s*天\s*/, "")
          .replace(/（[^）]*）|\([^)]*\)/g, " ")
          .replace(/\s+/g, " ")
          .trim();

        return cleaned
          .split(/(?:→|->|—|–|·|\/|、|,|，|\s{2,})+/)
          .map((item) => item.trim())
          .map((item) => item.replace(/^[|｜:：-]+|[|｜:：-]+$/g, "").trim())
          .filter(Boolean)
          .filter((item) => !isJourneyNoiseLocation(item))
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
      }

      function extractJourneyDayWaypointsFromLines(lines = []) {
        const candidates = [];
        const pushCandidate = (value = "") => {
          const cleaned = cleanJourneyLocationValue(value)
            .replace(/（[^）]*）|\([^)]*\)/g, " ")
            .replace(/^(?:推荐|建议|可选|可去|前往|游览|参观|观看)\s*/u, "")
            .replace(/\s+/g, " ")
            .trim();
          if (!cleaned || isJourneyNoiseLocation(cleaned)) return;
          if (/^(?:上午|中午|下午|晚上|午餐|晚餐|早餐|全天)$/u.test(cleaned)) return;
          if (!candidates.includes(cleaned)) candidates.push(cleaned);
        };

        lines.slice(1).forEach((rawLine) => {
          const normalized = normalizeJourneyDayHeading(rawLine)
            .replace(/^[-*•]\s*/, "")
            .trim();
          if (!normalized || /(?:请评价|若满意|如果满意|下一步|生成报告|调整方向)/u.test(normalized)) {
            return;
          }
          const afterTime = normalized.replace(
            /^(?:上午|中午|午餐|下午|傍晚|晚上|晚餐|早餐|早上|全天)[：:\s-]*/u,
            ""
          );
          const mainText = afterTime.split(/[。；;，,]/u)[0] || afterTime;
          mainText
            .split(/(?:→|->|\+|＋|、|\/|及|和|至|到)+/u)
            .map((item) => item.trim())
            .forEach(pushCandidate);
        });

        return candidates.slice(0, 6);
      }

      function extractJourneyDayPlansFromLines(lines = []) {
        const plans = [];
        let current = null;
        const flush = () => {
          if (!current?.dayNumber) return;
          const routeSeed =
            current.rawLines.find((line) => /(?:→|->|—|－|至|到)/.test(line)) || current.title;
          const bodyWaypoints = extractJourneyDayWaypointsFromLines(current.rawLines);
          const titleWaypoints = splitJourneyWaypoints(routeSeed);
          const waypoints = bodyWaypoints.length >= 2 ? bodyWaypoints : titleWaypoints;
          const note = truncateJourneyNote(
            current.rawLines.slice(1).join(" "),
            "这一天的节奏会在后续继续细化。"
          );
          plans.push({
            key: `day-${current.dayNumber}`,
            dayNumber: current.dayNumber,
            label: `Day ${current.dayNumber}`,
            title: current.title,
            waypoints,
            highlights: extractJourneyHighlights([
              {
                title: current.title,
                rawLines: current.rawLines,
              },
            ]).slice(0, 3),
            note,
          });
          current = null;
        };

        lines.forEach((rawLine) => {
          const line = (rawLine || "").trim();
          if (!line || /^[-*]{3,}$/.test(line)) return;
          const dayNumber = parseJourneyDayNumber(line);
          if (dayNumber) {
            flush();
            current = {
              dayNumber,
              title: line,
              rawLines: [line],
            };
            return;
          }
          if (current) {
            current.rawLines.push(line);
          }
        });

        flush();
        return plans;
      }

      function extractJourneyDayPlans(sections = [], summaryBlocks = []) {
        const sectionPlans = sections
          .map((section) => {
            const dayNumber = parseJourneyDayNumber(
              section.title || section.rawLines?.[0] || ""
            );
            if (!dayNumber) return null;
            const routeTitle = section.title || section.rawLines?.[0] || "";
            const bodyWaypoints = extractJourneyDayWaypointsFromLines([
              routeTitle,
              ...(section.rawLines || []),
            ]);
            const waypoints =
              bodyWaypoints.length >= 2 ? bodyWaypoints : splitJourneyWaypoints(routeTitle);
            return {
              key: `day-${dayNumber}`,
              dayNumber,
              label: `Day ${dayNumber}`,
              title: routeTitle,
              waypoints,
              highlights: extractJourneyHighlights([section]).slice(0, 3),
              note: truncateJourneyNote(
                (section.rawLines || []).slice(1).join(" "),
                "\u8fd9\u4e00\u5929\u7684\u8282\u594f\u4f1a\u5728\u540e\u7eed\u7ee7\u7eed\u7ec6\u5316\u3002"
              ),
            };
          })
          .filter(Boolean)
          .sort((left, right) => left.dayNumber - right.dayNumber);
        const lineFallbackPlans = extractJourneyDayPlansFromLines([
          ...summaryBlocks.flat(),
          ...sections.flatMap((section) => [section.title, ...(section.rawLines || [])]),
        ]);
        const mergedPlans = new Map();
        [...lineFallbackPlans, ...sectionPlans].forEach((plan) => {
          const existing = mergedPlans.get(plan.dayNumber);
          if (!existing) {
            mergedPlans.set(plan.dayNumber, plan);
            return;
          }
          mergedPlans.set(plan.dayNumber, {
            ...existing,
            ...plan,
            waypoints:
              plan.waypoints?.length && !plan.waypoints.every((item) => /^\*{0,2}day/i.test(item))
                ? plan.waypoints
                : existing.waypoints,
            highlights: plan.highlights?.length ? plan.highlights : existing.highlights,
            note: plan.note?.length ? plan.note : existing.note,
          });
        });
        return Array.from(mergedPlans.values())
          .sort((left, right) => left.dayNumber - right.dayNumber)
          .slice(0, 7);
      }

      function resolveTravelCardMapFocus(section, previewState) {
        if (!previewState?.shouldRender) {
          return "";
        }
        if (parseJourneyDayNumber(section.title || "")) {
          return "";
        }
        if (section.tone === "stay" && !/待补充|待确认/.test(section.title)) {
          return "stay";
        }
        if (section.tone === "food") {
          return previewState.highlightCards.length ? "highlights" : "";
        }
        if (section.tone === "overview") {
          return "destination";
        }
        return "";
      }

      function isJourneyPlaceholderValue(value = "") {
        const normalized = (value || "").trim();
        return (
          !normalized ||
          /待确认|待继续|待补充|待比较|待定|后面继续补/.test(normalized) ||
          isJourneyNoiseLocation(normalized)
        );
      }

      function isLowValueJourneyMetric(value = "") {
        const normalized = String(value || "").trim();
        return (
          !normalized ||
          /待继续|待补充|待比较|待定|后面会继续|后面继续|待核验/.test(
            normalized
          )
        );
      }

      function getJourneySectionText(section = {}) {
        return [
          section?.title || "",
          ...(Array.isArray(section?.rawLines) ? section.rawLines : []),
        ]
          .filter(Boolean)
          .join(" ")
          .replace(/\s+/g, " ")
          .trim();
      }

      function summarizeJourneyTransportMetric(section = {}, cityPair = {}) {
        const title = cleanJourneyLocationValue(section?.title || "");
        if (title && !/服务边界|涵盖服务|交通住宿|待/.test(title)) {
          return truncateJourneyNote(title, "交通待核验", 30);
        }
        const text = getJourneySectionText(section);
        const match = text.match(
          /(?:大交通|交通|高铁|航班|接送|专车|网约车|地铁)[：:\s-]*([^。；\n]{4,60})/u
        );
        if (match?.[1]) {
          return truncateJourneyNote(match[1], "交通待核验", 34);
        }
        if (cityPair?.origin && cityPair?.destination) {
          return "";
        }
        return "";
      }

      function extractJourneyExampleHotel(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ");
        const explicitMatch = normalized.match(
          /(?:示例酒店|酒店示例|住宿示例|候选酒店)[：:\s-]*([^。；，,\n]{4,36}(?:酒店|饭店|宾馆|度假村))/u
        );
        if (explicitMatch?.[1]) return explicitMatch[1].trim();
        const hotelMatch = normalized.match(
          /([\u4e00-\u9fa5A-Za-z0-9·\- ]{2,32}(?:酒店|饭店|宾馆|度假村))/u
        );
        return hotelMatch?.[1]?.trim() || "";
      }

      function summarizeJourneyStayMetric(section = {}, combinedText = "") {
        const sectionText = getJourneySectionText(section);
        const hotelName = extractJourneyExampleHotel(`${sectionText} ${combinedText}`);
        if (hotelName) {
          return truncateJourneyNote(hotelName, "住宿示例待核验", 30);
        }
        const title = cleanJourneyLocationValue(section?.title || "");
        if (title && !/住宿口径|交通住宿|服务边界|待/.test(title)) {
          return truncateJourneyNote(title, "住宿待核验", 30);
        }
        const areaMatch = sectionText.match(
          /(?:住宿|酒店|商圈|区域|落脚)[：:\s-]*([^。；\n]{4,60})/u
        );
        if (areaMatch?.[1]) {
          return truncateJourneyNote(areaMatch[1], "住宿区域待核验", 34);
        }
        return "";
      }

      function formatJourneyDayNightLabel(dayCount = 0, text = "") {
        const normalized = String(text || "");
        const dayNightMatch = normalized.match(
          /(\d+\s*天\s*\d+\s*[晚夜]|[一二三四五六七八九十]\s*天\s*[一二三四五六七八九十]\s*[晚夜])/u
        );
        if (dayNightMatch?.[1]) {
          return dayNightMatch[1].replace(/\s+/g, "");
        }
        if (dayCount > 1) return `${dayCount}天${Math.max(dayCount - 1, 1)}晚`;
        if (dayCount === 1) return "1天";
        return "先显示总览";
      }

      function buildJourneyAtlasTitle(previewState, previewStops = []) {
        const origin = cleanJourneyLocationValue(
          previewState?.cityPair?.origin || previewStops[0]?.value || ""
        );
        const destination = cleanJourneyLocationValue(
          previewState?.cityPair?.destination || previewStops[1]?.value || ""
        );
        if (!isJourneyPlaceholderValue(origin) && !isJourneyPlaceholderValue(destination)) {
          return `${origin} → ${destination}`;
        }
        if (!isJourneyPlaceholderValue(destination)) {
          return destination;
        }
        return "行程路线";
      }

      function renderJourneyAtlas(previewState, previewStops, previewMetrics) {
        const { cityPair, highlights, highlightCards, dayPlans } = previewState;
        const stayNearbyHighlights = buildStayNearbyHighlights(previewState);
        const mapHighlightQueries = [
          ...stayNearbyHighlights.map((item) => item.query),
          ...highlights,
        ]
          .map((item) => cleanJourneyLocationValue(item || ""))
          .filter(Boolean)
          .filter((item) => !isJourneyNoiseLocation(item))
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
        const routeStops = [
          { ...previewStops[0], target: "origin" },
          { ...previewStops[1], target: "destination" },
          { ...previewStops[2], target: "route" },
          { ...previewStops[3], target: "stay" },
        ].map((item) => ({
          ...item,
          value: cleanJourneyLocationValue(item.value || ""),
          disabled: isJourneyPlaceholderValue(cleanJourneyLocationValue(item.value || "")),
        }));
        const validRouteStops = routeStops.filter((item) => !item.disabled);
        const atlasTitle = buildJourneyAtlasTitle(previewState, previewStops);
        const hasDayView = dayPlans.length >= 1;
        const hasLiveMapPayload =
          hasDayView ||
          mapHighlightQueries.length >= 2 ||
          (previewState.recommendations || []).some(
            (item) => item && Number.isFinite(Number(item.lng)) && Number.isFinite(Number(item.lat))
          );
        const mapPayload = serializeMapPayload({
          origin: cityPair?.origin || routeStops[0]?.value || "",
          destination: cityPair?.destination || routeStops[1]?.value || "",
          stay: routeStops[3]?.disabled ? "" : routeStops[3]?.value || "",
          highlights: mapHighlightQueries,
          recommendations: previewState.recommendations || [],
          days: dayPlans.map((day) => ({
            key: day.key,
            label: day.label,
            day_number: day.dayNumber,
            title: day.title,
            route_note: day.note,
            waypoints: day.waypoints,
            stops: day.stops || [],
            segments: day.segments || [],
          })),
        });
        const isImmersive = previewState.mapExperience === "immersive";
        return `
          <section class="journey-map-studio${
            isImmersive ? " journey-map-studio--immersive" : ""
          }">
            <div
              class="journey-live-map-shell journey-live-map-shell--studio${
                isImmersive ? " journey-live-map-shell--immersive" : ""
              } journey-map-tools-collapsed journey-map-sidebar-collapsed${
                hasDayView ? "" : " journey-live-map-shell--overview-only"
              }"
              data-map-title="${escapeHtml(atlasTitle)}"
              data-day-plans="${serializeMapPayload(dayPlans)}"
              data-route-stops="${serializeMapPayload(validRouteStops)}"
            >
              <div class="journey-live-map-head">
                <div class="journey-live-map-head-copy">
                  <span class="journey-map-shell-kicker">
                    <i class="fa-solid fa-route"></i> 路线地图
                  </span>
                  <strong>${escapeHtml(atlasTitle)}</strong>
                  <span>${
                    hasDayView
                      ? "地图默认显示全程叠加总览；展开路线说明后，可切换查看某一天的路线参考。"
                      : "当前显示路线总览。"
                  }</span>
                </div>
              </div>
              <div class="journey-live-map-shell-body journey-live-map-shell-body--studio">
                <div class="journey-map-stage">
                  <div class="journey-map-title-pill">
                    <strong>${escapeHtml(atlasTitle)}</strong>
                    <span>${escapeHtml(
                      hasDayView ? `${dayPlans.length} 天路线` : "路线总览"
                    )}</span>
                  </div>
                  <div class="journey-map-floating-panel">
                    <div class="journey-map-floating-actions journey-map-floating-summary">
                      <button class="journey-map-action-btn secondary" type="button" data-map-action="toggle-tools" aria-expanded="false" title="展开地图工具">地图工具</button>
                      <button class="journey-map-action-btn secondary" type="button" data-map-action="expand" title="全屏查看地图">全屏</button>
                    </div>
                    ${
                      hasDayView
                        ? ""
                        : ""
                    }
                    <div class="journey-map-floating-actions">
                      <button class="journey-map-action-btn active" type="button" data-map-action="route" aria-pressed="true" title="聚焦路线主线">路线</button>
                      <button class="journey-map-action-btn" type="button" data-map-action="highlights" aria-pressed="false" title="聚焦沿途景点">景点</button>
                      <button class="journey-map-action-btn" type="button" data-map-action="recommendations" aria-pressed="false" title="显示或隐藏地图推荐点">推荐点</button>
                    </div>
                    <div class="journey-map-floating-actions journey-live-map-styles">
                      <button class="journey-map-style-btn active" type="button" data-map-style="standard" aria-pressed="true" title="标准底图">标准</button>
                      <button class="journey-map-style-btn" type="button" data-map-style="terrain" aria-pressed="false" title="更强调地形层次">地形</button>
                      <button class="journey-map-style-btn" type="button" data-map-style="calm" aria-pressed="false" title="更轻的清爽底图">清爽</button>
                    </div>
                  </div>
                  ${
                    hasLiveMapPayload
                      ? `
                  <div class="journey-live-map" data-map-payload="${mapPayload}">
                    <div class="journey-live-map-state loading">正在准备地图…</div>
                  </div>`
                      : `
                  <div class="journey-live-map journey-live-map--static">
                    <div class="journey-live-map-state">行程路线会在每日安排明确后显示地图。</div>
                  </div>`
                  }
                  <div class="journey-live-map-footer">
                    <div class="journey-live-map-meta">
                      <span class="journey-live-map-meta-label">路线状态</span>
                      <span class="journey-live-map-meta-value">${
                        hasLiveMapPayload ? "定位路线中" : "待补充具体点位"
                      }</span>
                    </div>
                    <div class="journey-map-focus-rail">
                      ${validRouteStops
                        .map(
                          (stop) => `
                            <button class="journey-map-focus-btn" type="button" data-map-focus="${escapeHtml(
                              stop.target
                            )}">
                              ${escapeHtml(stop.label)}
                            </button>
                          `
                        )
                        .join("")}
                      ${
                        highlightCards.length
                          ? '<button class="journey-map-focus-btn" type="button" data-map-focus="highlights">聚焦看点</button>'
                          : ""
                      }
                    </div>
                  </div>
                  <div class="journey-poi-bottom-sheet" hidden>
                    <span class="journey-poi-bottom-handle"></span>
                    <button
                      class="journey-poi-bottom-close"
                      type="button"
                      data-poi-sheet-close="true"
                      title="收起地点详情"
                    >
                      ×
                    </button>
                    <figure class="journey-poi-bottom-media">
                      <span>点</span>
                    </figure>
                    <div class="journey-poi-bottom-content">
                      <small data-poi-sheet-meta>地点信息待核验</small>
                      <strong data-poi-sheet-title>地点详情</strong>
                      <p data-poi-sheet-desc>地点介绍待补充。</p>
                      <div class="journey-poi-bottom-meta">
                        <span data-poi-sheet-duration>停留时间待核验</span>
                        <span data-poi-sheet-cost>费用待核验</span>
                      </div>
                      <div class="journey-poi-bottom-proof" data-poi-sheet-proof></div>
                      <em data-poi-sheet-note>开放、预约、票价和道路情况出发前二次核验。</em>
                      <div class="journey-poi-bottom-actions">
                        <button type="button" data-poi-sheet-action="replace">替换这个点</button>
                        <button type="button" data-poi-sheet-action="verify">核验门票交通</button>
                        <button type="button" data-poi-sheet-action="keep">保留继续规划</button>
                      </div>
                    </div>
                  </div>
                  <button class="journey-map-sidebar-open journey-map-action-btn secondary" type="button" data-map-action="toggle-sidebar" aria-expanded="false" title="展开路线说明">展开路线说明</button>
                </div>
                <aside class="journey-map-sidebar">
                  <div class="journey-map-sidebar-toolbar">
                    <span>路线说明</span>
                    <button class="journey-map-sidebar-toggle journey-map-action-btn secondary" type="button" data-map-action="toggle-sidebar" aria-expanded="true" title="收起路线说明">收起路线说明</button>
                  </div>
                  ${
                    hasDayView
                      ? renderJourneySidebarDayRoutes(dayPlans)
                      : `
                          <div class="journey-map-sidebar-card compact">
                            <div class="journey-map-sidebar-head">
                              <span>路线说明</span>
                              <strong>暂无分日路线</strong>
                            </div>
                            <p class="journey-map-day-insight-copy">
                              具体地点补齐后会显示分日路线。
                            </p>
                          </div>
                        `
                  }
                </aside>
              </div>
            </div>
          </section>
        `;
      }

      function renderJourneyPreview(previewState) {
        if (!previewState?.shouldRender) {
          return "";
        }
        const {
          cityPair,
          destinationSection,
          transportSection,
          staySection,
          budgetSection,
        } = previewState;
        const previewMetrics = [
          {
            icon: "fa-route",
            label: "主路线",
            value:
              cityPair?.origin && cityPair?.destination
                ? `${cityPair.origin} → ${cityPair.destination}`
                : cityPair?.destination || "待继续确认路线",
          },
          {
            icon: "fa-train-subway",
            label: "交通",
            value: summarizeJourneyTransportMetric(transportSection, cityPair),
          },
          {
            icon: "fa-bed",
            label: "住宿",
            value: summarizeJourneyStayMetric(staySection, previewState.combinedText),
          },
        ].filter((item) => !isLowValueJourneyMetric(item.value));

        const previewStops = [
          {
            label: "出发",
            icon: "fa-location-crosshairs",
            value: cleanJourneyLocationValue(cityPair?.origin || "待确认出发地"),
            note: cityPair?.origin
              ? "从这里出发，后面我会继续补齐更细的时间和方式。"
              : "告诉我从哪里走，我会把整段路线串得更完整。",
          },
          {
            label: "目的地",
            icon: "fa-map-pin",
            value: cleanJourneyLocationValue(
              cityPair?.destination || destinationSection?.title || "待确认目的地"
            ),
            note: truncateJourneyNote(
              destinationSection?.rawLines?.join(" "),
              "这里会放最值得去的点、适合你的玩法和整体氛围。"
            ),
          },
          {
            label: "交通",
            icon: "fa-train-subway",
            value: cleanJourneyLocationValue(transportSection?.title || "交通待定"),
            note: truncateJourneyNote(
              transportSection?.rawLines?.join(" "),
              "我会继续比较高铁、自驾、航班或其他更合适的方式。"
            ),
          },
          {
            label: "落脚点",
            icon: "fa-bed",
            value: cleanJourneyLocationValue(staySection?.title || "住宿待补充"),
            note: truncateJourneyNote(
              staySection?.rawLines?.join(" "),
              "后面我会把住哪里更省心、更顺路也一起整理进去。"
            ),
          },
        ];
        const atlasHtml = renderJourneyAtlas(
          previewState,
          previewStops,
          previewMetrics
        );

        const isImmersive = previewState.mapExperience === "immersive";
        return `
          <section class="journey-preview-board${
            isImmersive ? " journey-preview-board--immersive" : ""
          }">
            <div class="journey-preview-head">
              <div class="journey-preview-title">
                <strong>路线预览</strong>
                <span>先看整段路线，也可以切换到具体某一天，沿途景点会同步高亮。</span>
              </div>
              <div class="journey-preview-badge">
                <i class="fa-solid fa-map-location-dot"></i> ${
                  isImmersive ? "沉浸地图" : "轻量地图预览"
                }
              </div>
            </div>
            ${atlasHtml}
          </section>
        `;
      }

      function buildJourneyPreviewState(summaryBlocks, sections) {
        const summaryText = summaryBlocks.flat().join(" ").replace(/\s+/g, " ").trim();
        const sectionText = sections
          .flatMap((section) => [section.title, ...section.rawLines])
          .join(" ")
          .replace(/\s+/g, " ")
          .trim();
        const combinedText = [summaryText, sectionText].filter(Boolean).join(" ").trim();
        const overviewSection = sections.find((section) => section.tone === "overview");
        const overviewText = overviewSection
          ? [overviewSection.title, ...overviewSection.rawLines].join(" ").replace(/\s+/g, " ").trim()
          : "";
        const conversationTitlePair = extractJourneyCityPairFromConversationTitle(
          getCurrentConversation()?.title || ""
        );
        const cityPair =
          conversationTitlePair ||
          extractJourneyCityPair(summaryText) ||
          extractJourneyCityPair(overviewText) ||
          extractJourneyCityPair(combinedText) ||
          (() => {
            const origin =
              extractJourneyPrimaryOrigin(summaryText) ||
              extractJourneyPrimaryOrigin(overviewText) ||
              extractJourneyPrimaryOrigin(combinedText);
            const destination =
              extractJourneyPrimaryDestination(summaryText) ||
              extractJourneyPrimaryDestination(overviewText) ||
              extractJourneyPrimaryDestination(combinedText);
            return origin || destination ? { origin, destination } : null;
          })();

        const destinationSection =
          overviewSection || {
            tone: "overview",
            title: cityPair?.destination || "待确认目的地",
            rawLines: splitJourneyFragments(summaryText || combinedText).slice(0, 3),
          };
        const transportSection = sections.find((section) => section.tone === "transport");
        const staySection = sections.find((section) => section.tone === "stay");
        const budgetSection = sections.find((section) => section.tone === "budget");
        const highlights = extractJourneyHighlights(sections);
        const highlightCards = buildJourneyHighlightCards(highlights);
        const rhythm = extractJourneyRhythm(summaryBlocks, sections);
        const dayPlans = extractJourneyDayPlans(sections, summaryBlocks);
        const hasClarificationSignal = hasJourneyClarificationSignal(combinedText);
        const hasPlanSignal = hasJourneyPlanSignal(
          combinedText,
          sections,
          highlights,
          rhythm
        );
        const hasConcreteRoutePayload =
          (
            sections.some((section) => section.tone === "transport") ||
            /高铁|火车|自驾|大巴|公交|航班|车程|打车/u.test(combinedText)
          ) &&
          (
            sections.some((section) => ["overview", "stay"].includes(section.tone)) ||
            /住宿|酒店|民宿|景点|玩法|美食/u.test(combinedText)
          );
        const shouldRender =
          (sections.length >= 2 || dayPlans.length >= 1 || hasConcreteRoutePayload) &&
          hasPlanSignal &&
          (!hasClarificationSignal || hasConcreteRoutePayload);

        return {
          combinedText,
          cityPair,
          destinationSection,
          transportSection,
          staySection,
          budgetSection,
          highlights,
          highlightCards,
          rhythm,
          dayPlans,
          shouldRender,
        };
      }

      function shouldRenderJourneyPreviewBlock(previewState = {}, sections = []) {
        if (!previewState?.shouldRender) return false;

        const combinedText = previewState.combinedText || "";
        const tones = new Set(sections.map((section) => section.tone).filter(Boolean));
        const dayCount = previewState.dayPlans?.length || 0;
        const hasDayPlanSignal =
          dayCount >= 2 ||
          /(?:Day\s*\d+|\u7b2c\s*[一二三四五六七八九十\d]+\s*\u5929)/iu.test(
            combinedText
          );
        const hasReportSignal =
          /(?:\u6700\u7ec8|\u5b8c\u6574|\u62a5\u544a|\u6210\u7a3f|\u9884\u7b97\u660e\u7ec6|\u6bcf\u65e5\u884c\u7a0b|\u8def\u7ebf\u56fe|\u5730\u56fe\u8def\u7ebf|\u89c4\u5212\u5b8c\u6210)/u.test(
            combinedText
          );
        const hasStrongClarification =
          hasJourneyClarificationSignal(combinedText) &&
          /[？?]|(?:\u786e\u8ba4|\u8fd8\u662f|\u54ea\u4e2a|\u662f\u5426|\u8981\u4e0d\u8981|\u60f3\u8ddf\u4f60\u786e\u8ba4|\u8865\u5145)/u.test(
            combinedText
          );

        const hasCoreRouteCards =
          tones.has("overview") &&
          tones.has("transport") &&
          (tones.has("stay") || tones.has("schedule") || tones.has("scenic"));
        const hasConcreteRouteCopy =
          /(?:\u4ea4\u901a|\u9ad8\u94c1|\u706b\u8f66|\u822a\u73ed|\u81ea\u9a7e|\u8def\u7ebf)/u.test(
            combinedText
          ) &&
          /(?:\u4f4f\u5bbf|\u9152\u5e97|\u6c11\u5bbf|\u666f\u70b9|\u884c\u7a0b|\u7f8e\u98df)/u.test(
            combinedText
          );

        if (hasStrongClarification && !hasReportSignal) return false;
        if (!hasReportSignal && !hasDayPlanSignal) return false;
        if (hasDayPlanSignal) {
          return dayCount >= 2 || hasReportSignal || hasConcreteRouteCopy;
        }

        return hasReportSignal
          ? hasCoreRouteCards || hasConcreteRouteCopy
          : hasCoreRouteCards && hasConcreteRouteCopy && !hasStrongClarification;
      }

      function hasTravelReportSignal(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        if (!normalized) return false;
        const hasFinalSignal =
          /(?:最终|完整|成品|报告|个性化旅游规划|旅行方案报告|规划完成)/u.test(
            normalized
          );
        const sectionHits = [
          /(?:行程概览|旅行计划|方案概览|总览)/u,
          /(?:预算明细|费用明细|预算匹配|总预算|人均)/u,
          /(?:每日行程|分日行程|Day\s*\d+|第\s*[一二三四五六七八九十\d]+\s*天)/iu,
          /(?:景点地图|路线地图|地图|路线预览)/u,
          /(?:天气|风险|注意事项|关键假设|贴士)/u,
        ].filter((pattern) => pattern.test(normalized)).length;
        return hasFinalSignal && sectionHits >= 2;
      }

      function inferTextTravelReportMode(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        const agencyScore = [
          /省心方案/u,
          /旅行社/u,
          /成熟路线/u,
          /产品口径/u,
          /涵盖服务/u,
          /服务边界/u,
          /费用说明/u,
          /待核验/u,
        ].filter((pattern) => pattern.test(normalized)).length;
        const freeScore = [
          /个性化旅游规划/u,
          /自由行/u,
          /自己订/u,
          /自助/u,
          /专属旅程/u,
        ].filter((pattern) => pattern.test(normalized)).length;
        return agencyScore > freeScore ? "agency_plan" : "free_planning";
      }

      function getReportSectionMeta(title = "", bodyLines = []) {
        const normalized = normalizeSectionTitle(title);
        const bodyText = bodyLines.join(" ");
        const contains = (...keywords) =>
          keywords.some(
            (keyword) => normalized.includes(keyword) || bodyText.includes(keyword)
          );

        if (looksLikeDecisionPrompt(`${normalized} ${bodyText}`)) {
          return { tone: "next", icon: "fa-circle-question", label: "需要你确认" };
        }
        if (contains("下一步", "接下来", "用户下一步", "请评价")) {
          return { tone: "next", icon: "fa-circle-question", label: "需要你确认" };
        }
        if (contains("交付", "核验清单")) {
          return { tone: "handoff", icon: "fa-list-check", label: "交付清单" };
        }
        if (
          contains("置信度", "待核验", "可追溯", "兜底估算") &&
          !contains("费用说明", "费用边界", "预算拆分", "预算明细", "人均", "总计")
        ) {
          return { tone: "budget-confidence", icon: "fa-clipboard-check", label: "预算核验" };
        }
        if (contains("预算", "费用", "花费", "明细", "人均", "总计")) {
          return { tone: "budget", icon: "fa-wallet", label: "费用说明" };
        }
        if (contains("涵盖服务", "服务边界", "接送", "预约", "应急", "人工确认")) {
          return { tone: "service", icon: "fa-handshake-angle", label: "涵盖服务" };
        }
        if (contains("概览", "总览", "旅行计划", "方案", "行程摘要")) {
          return { tone: "overview", icon: "fa-passport", label: "行程概览" };
        }
        if (contains("每日", "分日", "Day", "第", "日程")) {
          return { tone: "daily", icon: "fa-calendar-days", label: "每日行程" };
        }
        if (contains("地图", "路线", "景点")) {
          return { tone: "map", icon: "fa-map-location-dot", label: "路线地图" };
        }
        if (contains("交通", "航班", "火车", "高铁", "自驾")) {
          return { tone: "transport", icon: "fa-train-subway", label: "交通住宿" };
        }
        if (contains("住宿", "酒店", "民宿", "落脚")) {
          return { tone: "stay", icon: "fa-bed", label: "交通住宿" };
        }
        if (contains("天气", "风险", "提醒", "注意", "假设", "预约")) {
          return { tone: "warning", icon: "fa-cloud-sun", label: "天气风险" };
        }
        if (contains("美食", "餐饮", "吃")) {
          return { tone: "food", icon: "fa-utensils", label: "美食体验" };
        }
        return getTravelSectionMeta(normalized);
      }

      function normalizeReportDedupeText(value = "") {
        return String(value || "")
          .replace(/<[^>]+>/g, " ")
          .replace(/[【】\[\]\s*_#|:-]+/g, "")
          .trim()
          .toLowerCase();
      }

      function isReportNextActionLine(line = "") {
        const normalized = String(line || "")
          .replace(/^[-*•]\s*/, "")
          .trim();
        if (!normalized) return false;
        return /(?:下一步|接下来|请你?评价|请您评价|需要你确认|满意|想调整|想改哪里|如果满意|如果想调整|如果要调整)/u.test(
          normalized
        );
      }

      function splitReportSectionNextActionLines(lines = []) {
        const firstNextIndex = lines.findIndex((line) => isReportNextActionLine(line));
        if (firstNextIndex < 0) {
          return { mainLines: lines, nextLines: [] };
        }
        return {
          mainLines: lines.slice(0, firstNextIndex).filter(Boolean),
          nextLines: lines.slice(firstNextIndex).filter(Boolean),
        };
      }

      function dedupeTravelReportSections(sections = []) {
        const seen = new Set();
        const deduped = [];
        sections.forEach((section) => {
          if (!section || typeof section !== "object") return;
          const tone = section.reportTone || section.tone || "";
          const title = normalizeReportDedupeText(section.title || section.reportLabel || "");
          const body = normalizeReportDedupeText((section.rawLines || []).join(" "));
          const isBudget = tone === "budget" || /预算|费用|budget/u.test(title);
          const key =
            isBudget && /预算拆分|预算明细|费用拆分|费用明细/u.test(title)
              ? `budget:${title}`
              : isBudget
                ? `budget:${body || title}`
                : `${tone}:${title}:${body}`;
          if (key && seen.has(key)) return;
          seen.add(key);
          deduped.push(section);
        });
        return deduped;
      }

      function extractTravelReportSections(blocks = []) {
        const summaryBlocks = [];
        const sections = [];

        blocks.forEach((block) => {
          const lines = block
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          const firstLine = lines[0];
          const headingCandidate = normalizeSectionTitle(firstLine);
          const inlineMatch = headingCandidate.match(/^([^：:]{2,18})[：:]\s*(.+)$/);
          const sectionTitle = inlineMatch ? inlineMatch[1] : headingCandidate;
          const bodyLines = [
            ...(inlineMatch?.[2] ? [inlineMatch[2].trim()] : []),
            ...lines.slice(1),
          ].filter(Boolean);
          const preliminaryMeta = getReportSectionMeta(sectionTitle, bodyLines);
          const isHeading =
            /^#{1,3}\s+/.test(firstLine) ||
            /^\*\*.+\*\*$/.test(firstLine) ||
            Boolean(inlineMatch) ||
            isEmbeddedSectionHeading(firstLine) ||
            (Boolean(preliminaryMeta) &&
              (/[：:]$/.test(firstLine) || headingCandidate.length <= 18));
          const meta = isHeading ? preliminaryMeta : null;

          if (!meta || !bodyLines.length) {
            const firstDayIndex = lines.findIndex((line) => parseJourneyDayNumber(line));
            if (firstDayIndex >= 0) {
              const introLines = lines
                .slice(0, firstDayIndex)
                .filter((line) => !looksLikeDecisionPrompt(line))
                .filter((line) => !isReportNextActionLine(line))
                .filter((line) => !isReportSummaryMarkerOnly(line));
              if (introLines.length) {
                summaryBlocks.push(introLines);
              }
              const dayLines = lines
                .slice(firstDayIndex)
                .filter((line) => !isReportNextActionLine(line));
              sections.push({
                tone: "overview",
                reportTone: "daily",
                reportLabel: "每日行程",
                title: "每日安排",
                rawLines: dayLines,
                bodyHtml: reportRenderer?.renderReportSectionBody?.("daily", dayLines),
              });
              return;
            }
            const { mainLines: summaryCandidateLines, nextLines } =
              splitReportSectionNextActionLines(lines);
            if (nextLines.length) {
              sections.push({
                tone: "next",
                reportTone: "next",
                reportLabel: "需要你确认",
                title: "下一步",
                rawLines: nextLines,
                bodyHtml: reportRenderer?.renderReportSectionBody?.("next", nextLines),
              });
            }
            const cleanSummaryLines = filterReportSummaryLines(
              summaryCandidateLines.length ? summaryCandidateLines : lines
            );
            if (cleanSummaryLines.length) {
              summaryBlocks.push(cleanSummaryLines);
            }
            return;
          }

          const travelMeta =
            meta.tone === "daily" || meta.tone === "map"
              ? { tone: "overview", icon: meta.icon }
              : { tone: meta.tone, icon: meta.icon };
          const { mainLines, nextLines } =
            meta.tone === "next"
              ? { mainLines: [], nextLines: bodyLines }
              : splitReportSectionNextActionLines(bodyLines);
          if (mainLines.length) {
            sections.push({
              ...travelMeta,
              reportTone: meta.tone,
              reportLabel: meta.label || normalizeSectionTitle(sectionTitle),
              title: normalizeSectionTitle(sectionTitle),
              rawLines: mainLines,
              bodyHtml: reportRenderer?.renderReportSectionBody?.(meta.tone, mainLines),
            });
          }
          if (nextLines.length) {
            sections.push({
              tone: "next",
              reportTone: "next",
              reportLabel: "需要你确认",
              title: "下一步",
              rawLines: nextLines,
              bodyHtml: reportRenderer?.renderReportSectionBody?.("next", nextLines),
            });
          }
          if (mainLines.length || nextLines.length) {
            return;
          }
          sections.push({
            ...travelMeta,
            reportTone: meta.tone,
            reportLabel: meta.label || normalizeSectionTitle(sectionTitle),
            title: normalizeSectionTitle(sectionTitle),
            rawLines: bodyLines,
            bodyHtml: reportRenderer?.renderReportSectionBody?.(meta.tone, bodyLines),
          });
        });

        return { summaryBlocks, sections: dedupeTravelReportSections(sections) };
      }

      function mergeTravelReportDailySections(sections = []) {
        const dailySections = sections.filter((section) => section.reportTone === "daily");
        if (dailySections.length <= 1) return sections;
        const firstDaily = dailySections[0];
        const seen = new Set();
        const mergedLines = [];
        dailySections.forEach((section) => {
          (section.rawLines || []).forEach((line) => {
            const normalized = String(line || "").trim();
            if (!normalized || seen.has(normalized)) return;
            seen.add(normalized);
            mergedLines.push(normalized);
          });
        });
        const mergedDaily = {
          ...firstDaily,
          title: "每日安排",
          reportLabel: "每日行程",
          rawLines: mergedLines,
          bodyHtml: reportRenderer?.renderReportSectionBody?.("daily", mergedLines),
        };
        let inserted = false;
        return sections
          .flatMap((section) => {
            if (section.reportTone !== "daily") return [section];
            if (inserted) return [];
            inserted = true;
            return [mergedDaily];
          });
      }

      function renderTravelReportNextAction(sections = []) {
        const nextSections = sections.filter(
          (section) => (section.reportTone || section.tone) === "next"
        );
        if (!nextSections.length) return "";
        const seen = new Set();
        const lines = [];
        nextSections.forEach((section) => {
          (section.rawLines || []).forEach((line) => {
            const normalized = String(line || "")
              .trim()
              .replace(/^[-*•]\s*/, "")
              .trim();
            if (
              !normalized ||
              /^下一步[:：]?$/.test(normalized) ||
              seen.has(normalized)
            ) {
              return;
            }
            seen.add(normalized);
            lines.push(normalized);
          });
        });
        if (!lines.length) return "";
        return `
          <section class="travel-report-next-action">
            <div class="travel-report-next-action-head">
              <span><i class="fa-solid fa-circle-check"></i></span>
              <div>
                <small>需要你确认</small>
                <h4>下一步</h4>
              </div>
            </div>
            <div class="travel-report-next-action-body">
              <ul>
                ${lines
                  .map((line) => `<li>${formatInlineText(line)}</li>`)
                  .join("")}
              </ul>
            </div>
          </section>
        `;
      }

      function extractReportExpectedDayCount(text = "") {
        const normalized = String(text || "").replace(/\s+/g, " ").trim();
        const digitMatch = normalized.match(/(\d+)\s*天/u);
        if (digitMatch) return Number(digitMatch[1]);
        const chineseMatch = normalized.match(/([一二三四五六七八九十])\s*天/u);
        return chineseMatch ? parseJourneyChineseDayNumber(chineseMatch[1]) : 0;
      }

      function extractReportDayGroups(lines = []) {
        const groups = [];
        let current = null;

        lines.forEach((line) => {
          const normalized = normalizeJourneyDayHeading(line);
          const dayMatch = normalized.match(
            /^(Day\s*\d+|第\s*[一二三四五六七八九十\d]+\s*天)[：:\s-]*(.*)$/iu
          );
          if (dayMatch) {
            current = {
              label: dayMatch[1],
              title: dayMatch[2] || "当天安排",
              lines: [],
            };
            groups.push(current);
            return;
          }
          if (current) {
            current.lines.push(normalized);
          }
        });

        return groups;
      }

      function normalizeReportAmount(value = "") {
        const normalized = String(value || "").replace(/\s+/g, "");
        if (!normalized) return "";
        return normalized.startsWith("¥") ? normalized : normalized.replace(/^￥/, "¥");
      }

      function isMeaningfulBudgetAmount(value = "") {
        return /[元¥￥]/u.test(String(value || ""));
      }

      function getBudgetItemMeta(label = "") {
        if (/交通|车票|机票|高铁|火车|航班|打车/u.test(label)) {
          return {
            icon: "fa-train-subway",
            note: "往返大交通、市内换乘或临时打车，出发前还要核验实时票价与余票。",
          };
        }
        if (/住宿|酒店|民宿|客栈|房/u.test(label)) {
          return {
            icon: "fa-bed",
            note: "按晚数、房间数和住宿档位估算，最终以可订房源价格为准。",
          };
        }
        if (/餐|美食|吃|饮/u.test(label)) {
          return {
            icon: "fa-utensils",
            note: "覆盖正餐、特色小吃和咖啡甜品，保留一点弹性更舒服。",
          };
        }
        if (/景点|门票|体验|项目|游船|展馆/u.test(label)) {
          return {
            icon: "fa-ticket",
            note: "含门票、预约项目和体验活动，热门项目建议提前确认。",
          };
        }
        if (/服务|预留|机动|缓冲/u.test(label)) {
          return {
            icon: "fa-shield-heart",
            note: "覆盖市内交通、寄存、临时休息和价格波动缓冲。",
          };
        }
        if (/人均/u.test(label)) {
          return {
            icon: "fa-user-group",
            note: "按当前人数均摊后的参考值，方便判断预算压力。",
            featured: true,
          };
        }
        if (/总计|合计|总预算|总额|预算/u.test(label)) {
          return {
            icon: "fa-calculator",
            note: "当前方案的总预算估算，后续改交通或住宿会同步变化。",
            featured: true,
          };
        }
        return {
          icon: "fa-wallet",
          note: "机动费用、寄存、临时休息和其他小额弹性支出。",
        };
      }

      function extractReportBudgetItems(lines = [], combinedText = "") {
        const source = [lines.join(" "), combinedText].filter(Boolean).join(" ");
        const normalized = source.replace(/\s+/g, " ");
        const pattern =
          /(交通|大交通|市内交通|住宿|酒店|民宿|餐饮|美食|吃饭|景点体验|景点|门票|体验|服务\/预留|服务|预留|其他|机动|总计|合计|总预算|预算|人均)[：:\s|，,、]*([¥￥]?\s*\d[\d,.]*(?:\s*(?:-|~|—|–|至|到)\s*\d[\d,.]*)?\s*元?(?:\/人|每人)?)/gu;
        const picked = [];
        const seen = new Set();
        let match;
        while ((match = pattern.exec(normalized))) {
          const label = match[1].replace(/预算$/, "总计");
          if (!isMeaningfulBudgetAmount(match[2])) continue;
          const amount = normalizeReportAmount(match[2]);
          const key = `${label}-${amount}`;
          if (!amount || seen.has(key)) continue;
          seen.add(key);
          picked.push({
            label,
            amount,
            ...getBudgetItemMeta(label),
          });
        }
        return picked.slice(0, 8);
      }

      function renderReportBudgetBreakdown(lines = [], combinedText = "") {
        const items = extractReportBudgetItems(lines, combinedText);
        if (!items.length) {
          return `${renderAssistantLines(lines)}
            <div class="travel-report-budget-gap">
              预算仍缺少交通、住宿、门票、餐饮等分项拆分，生成正式报告前需要继续补齐依据。
            </div>`;
        }

        return `
          <div class="travel-report-budget-grid">
            ${items
              .map(
                (item) => `
                  <article class="travel-report-budget-item ${
                    item.featured ? "featured" : ""
                  }">
                    <div class="travel-report-budget-icon">
                      <i class="fa-solid ${item.icon}"></i>
                    </div>
                    <div>
                      <span>${escapeHtml(item.label)}</span>
                      <strong>${escapeHtml(item.amount)}</strong>
                      <p>${escapeHtml(item.note)}</p>
                    </div>
                  </article>
                `
              )
              .join("")}
          </div>
          ${
            items.length < 3
              ? `<div class="travel-report-budget-gap">当前只识别到总价或少量预算项，还需要继续补齐交通、住宿、门票、餐饮和机动费用依据。</div>`
              : ""
          }
        `;
      }

      function getReportRouteWaypoints(day = {}, fallback = {}) {
        const waypoints = Array.isArray(day.waypoints) ? day.waypoints : [];
        const cleaned = waypoints
          .map((item) => cleanJourneyLocationValue(item))
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index);
        if (cleaned.length >= 2) return cleaned.slice(0, 6);
        return [
          fallback.origin,
          ...(cleaned.length ? cleaned : []),
          fallback.destination,
        ]
          .map((item) => cleanJourneyLocationValue(item || ""))
          .filter(Boolean)
          .filter((item, index, list) => list.indexOf(item) === index)
          .slice(0, 6);
      }

      function renderReportRouteSketch(waypoints = [], label = "当天路线") {
        const points = [
          [18, 72],
          [34, 42],
          [50, 58],
          [66, 30],
          [82, 46],
          [88, 22],
        ];
        const picked = waypoints.slice(0, points.length);
        if (!picked.length) {
          return `
            <div class="travel-report-route-sketch empty">
              <div class="travel-report-route-empty">这一天的路线点还没被识别出来，后续补齐完整日程后会形成静态路线图。</div>
            </div>
          `;
        }
        const svgPoints = picked
          .map((_, index) => `${points[index][0]},${points[index][1]}`)
          .join(" ");
        return `
          <div class="travel-report-route-sketch" aria-label="${escapeHtml(label)}">
            <svg viewBox="0 0 100 82" preserveAspectRatio="none" aria-hidden="true">
              <polyline points="${svgPoints}" fill="none" stroke="#24a6a1" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            ${picked
              .map((point, index) => {
                const [x, y] = points[index];
                return `
                  <div class="travel-report-route-node" style="--x:${x}%; --y:${y}%;">
                    <span>${index + 1}</span>
                    <strong>${escapeHtml(point)}</strong>
                  </div>
                `;
              })
              .join("")}
          </div>
        `;
      }

      function getReportDataFromOptions(options = {}) {
        return (
          options.reportData ||
          options.extraInfo?.report_data ||
          options.extra_info?.report_data ||
          null
        );
      }

      function getJourneyDataFromOptions(options = {}) {
        return (
          options.journeyData ||
          options.extraInfo?.journey_data ||
          options.extra_info?.journey_data ||
          null
        );
      }

      function getPlanningTraceFromOptions(options = {}) {
        const trace =
          options.planningTrace ||
          options.extraInfo?.planning_trace ||
          options.extra_info?.planning_trace ||
          [];
        return Array.isArray(trace) ? trace : [];
      }

      function isVisualJourneyData(journeyData) {
        return (
          journeyData &&
          typeof journeyData === "object" &&
          journeyData.version === "journey_plan.v1" &&
          Array.isArray(journeyData.days)
        );
      }

      function isStructuredTravelReportData(reportData) {
        return (
          reportData &&
          typeof reportData === "object" &&
          reportData.version === "travel_report.v1" &&
          reportData.overview
        );
      }

      function formatReportDataMoney(value) {
        if (typeof value !== "number" || Number.isNaN(value)) return "";
        return `${Math.round(value).toLocaleString("zh-CN")} 元`;
      }

      function renderReportDataList(items = [], emptyText = "待补充") {
        const list = (Array.isArray(items) ? items : [])
          .map((item) => String(item || "").trim())
          .filter(Boolean);
        if (!list.length) return `<p>${escapeHtml(emptyText)}</p>`;
        return `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
      }

      function normalizeReportDataList(items = []) {
        return (Array.isArray(items) ? items : [])
          .map((item) => String(item || "").trim())
          .filter(Boolean);
      }

      const REPORT_BUDGET_GROUPS = [
        { key: "transport", label: "交通", icon: "fa-train-subway" },
        { key: "accommodation", label: "住宿", icon: "fa-bed" },
        { key: "food", label: "餐饮", icon: "fa-utensils" },
        { key: "attractions", label: "景点/体验", icon: "fa-ticket" },
        { key: "service_reserve", label: "服务/预留", icon: "fa-shield-heart" },
        { key: "other", label: "其他", icon: "fa-wallet" },
      ];

      function reportBudgetGroupKey(item = {}) {
        const source = `${item.key || item.category || ""} ${item.label || ""}`.toLowerCase();
        if (/transport|traffic|交通|高铁|航班|机票|火车/.test(source)) return "transport";
        if (/accommodation|hotel|lodging|住宿|酒店|民宿|房/.test(source)) return "accommodation";
        if (/food|dining|meal|餐|美食|小吃/.test(source)) return "food";
        if (/attraction|scenic|sight|experience|景点|门票|体验|游船/.test(source)) return "attractions";
        if (/service|reserve|contingency|buffer|misc|服务|预留|机动/.test(source)) return "service_reserve";
        return "other";
      }

      function normalizeReportBudgetItems(budget = {}) {
        const grouped = new Map(
          REPORT_BUDGET_GROUPS.map((group) => [
            group.key,
            {
              ...group,
              amount: 0,
              basis: "",
              confidence: "",
            },
          ])
        );
        (Array.isArray(budget.items) ? budget.items : []).forEach((item) => {
          if (!item || typeof item !== "object") return;
          const group = grouped.get(reportBudgetGroupKey(item)) || grouped.get("other");
          if (typeof item.amount === "number" && !Number.isNaN(item.amount)) {
            group.amount += item.amount;
          }
          if (item.basis && !group.basis) group.basis = String(item.basis);
          if (item.confidence && !group.confidence) group.confidence = String(item.confidence);
        });

        const fieldFallbacks = {
          transport: "transport",
          accommodation: "accommodation",
          food: "food",
          attractions: "attractions",
          service_reserve: budget.service_reserve !== undefined ? "service_reserve" : "misc",
          other: "other",
        };
        Object.entries(fieldFallbacks).forEach(([groupKey, budgetKey]) => {
          const group = grouped.get(groupKey);
          const value = budget[budgetKey];
          if (group && !group.amount && typeof value === "number" && !Number.isNaN(value)) {
            group.amount = value;
          }
        });

        const defaults = {
          transport: "交通票价、余票和退改签规则需在正式预订前复核。",
          accommodation: "住宿按区域、房型、晚数和取消政策估算。",
          food: "餐饮按用餐偏好、餐次和热门餐厅排队情况估算。",
          attractions: "景点/体验按门票、预约项目和临时展览收费估算。",
          service_reserve: "覆盖市内交通、寄存、临时休息和价格波动缓冲。",
          other: "个人购物、伴手礼和临时加项按实际发生处理。",
        };
        return REPORT_BUDGET_GROUPS.map((group) => {
          const item = grouped.get(group.key);
          return {
            ...item,
            basis: item.basis || defaults[group.key],
            confidence: item.confidence || "待核验",
          };
        });
      }

      function parseReportDataExpectedDays(reportData = {}) {
        const duration = String(reportData.overview?.duration || "");
        const digitMatch = duration.match(/(\d+)\s*天/u);
        const chineseMatch = duration.match(/([一二三四五六七八九十])\s*天/u);
        const parsed = digitMatch
          ? Number(digitMatch[1])
          : chineseMatch
          ? parseJourneyChineseDayNumber(chineseMatch[1])
          : 0;
        const itineraryDays = Array.isArray(reportData.itinerary)
          ? reportData.itinerary.map((day) => Number(day.day_number || day.day || 0))
          : [];
        const routeDays = Array.isArray(reportData.map_routes)
          ? reportData.map_routes.map((route) => Number(route.day_number || route.day || 0))
          : [];
        const routeMapDays = Array.isArray(reportData.route_map?.days)
          ? reportData.route_map.days.map((day) => Number(day.day_number || day.day || 0))
          : [];
        return Math.max(parsed, ...itineraryDays, ...routeDays, ...routeMapDays, 0);
      }

      function routePointName(point = "") {
        if (point && typeof point === "object") {
          return String(point.name || point.label || point.title || "").trim();
        }
        return String(point || "").trim();
      }

      function normalizeRouteMapDayPoints(routeMapDay = {}, route = {}) {
        const typedPoints = Array.isArray(routeMapDay.points) ? routeMapDay.points : [];
        if (typedPoints.length) {
          return typedPoints
            .map((point) => ({
              name: routePointName(point),
              typeLabel: point.type_label || point.type || "路线点",
              description: point.description || point.note || "",
            }))
            .filter((point) => point.name);
        }
        return normalizeReportDataList(routeMapDay.route_points || route.route_points || []).map(
          (name) => ({
            name,
            typeLabel: "路线点",
            description: "当天路线节点，后续可继续细化停留时间。",
          })
        );
      }

      function getReportDataDayNumber(day = {}, fallback = 0) {
        const explicit = Number(day?.day_number || day?.day || 0);
        if (explicit > 0) return explicit;
        const parsed = parseJourneyDayNumber(
          [day?.title, day?.summary, day?.label].filter(Boolean).join(" ")
        );
        return parsed || fallback || 0;
      }

      function normalizeReportRoutePointNames(values = []) {
        const names = [];
        const pushName = (value) => {
          if (value === null || value === undefined) return;
          if (Array.isArray(value)) {
            value.forEach(pushName);
            return;
          }
          if (typeof value === "object") {
            [
              value.name,
              value.label,
              value.title,
              value.location,
              value.place,
              value.poi,
              value.spot,
              value.scenic_spot,
              value.destination,
              value.area,
              value.address,
              value.summary,
              value.description,
              value.content,
              value.note,
              value.activity,
            ].forEach(pushName);
            if (value.route && typeof value.route === "object") pushName(value.route);
            if (Array.isArray(value.pois)) pushName(value.pois);
            if (Array.isArray(value.waypoints)) pushName(value.waypoints);
            if (Array.isArray(value.stops)) pushName(value.stops);
            if (Array.isArray(value.activities)) pushName(value.activities);
            if (Array.isArray(value.items)) pushName(value.items);
            if (Array.isArray(value.time_blocks)) pushName(value.time_blocks);
            if (Array.isArray(value.timeline)) pushName(value.timeline);
            if (Array.isArray(value.schedule)) pushName(value.schedule);
            if (Array.isArray(value.route_points)) pushName(value.route_points);
            if (Array.isArray(value.points)) pushName(value.points);
            return;
          }
          const raw = String(value || "").trim();
          if (!raw) return;
          const split = splitJourneyWaypoints(raw);
          const candidates = split.length ? split : [raw];
          candidates.forEach((candidate) => {
            const cleaned = cleanJourneyLocationValue(candidate)
              .replace(/^(?:推荐|建议|可选|可去|前往|游览|参观|观看)\s*/u, "")
              .replace(/\s+/g, " ")
              .trim();
            if (!cleaned || isJourneyNoiseLocation(cleaned)) return;
            if (!names.includes(cleaned)) names.push(cleaned);
          });
        };
        values.forEach(pushName);
        return names.slice(0, 8);
      }

      function extractReportItineraryDayRoutePoints(day = {}) {
        if (!day || typeof day !== "object") return [];
        return normalizeReportRoutePointNames([
          day.pois,
          day.waypoints,
          day.stops,
          day.route_points,
          day.points,
          day.route?.route_points,
          day.route?.points,
          day.route?.waypoints,
          day.route?.stops,
          day.route?.summary,
          day.time_blocks,
          day.timeline,
          day.schedule,
          day.activities,
          day.items,
          day.meals,
          day.accommodation,
          day.transport_note,
          day.route_note,
          day.summary,
          day.content,
          day.note,
          day.title,
        ]);
      }

      function buildReportDataJourneyDayPlans(reportData = {}) {
        const routes = Array.isArray(reportData.map_routes) ? reportData.map_routes : [];
        const routeMapDays = Array.isArray(reportData.route_map?.days)
          ? reportData.route_map.days
          : [];
        const itineraryDays = Array.isArray(reportData.itinerary)
          ? reportData.itinerary.filter((day) => !day?.missing)
          : [];
        const routeByDay = new Map(
          routes.map((route, index) => [getReportDataDayNumber(route, index + 1), route])
        );
        const routeMapByDay = new Map(
          routeMapDays.map((day, index) => [getReportDataDayNumber(day, index + 1), day])
        );
        const itineraryByDay = new Map(
          itineraryDays.map((day, index) => [getReportDataDayNumber(day, index + 1), day])
        );
        const expectedDays = parseReportDataExpectedDays(reportData);
        const maxDay = Math.max(
          expectedDays,
          ...routeByDay.keys(),
          ...routeMapByDay.keys(),
          ...itineraryByDay.keys(),
          0
        );
        if (!maxDay) return [];

        const dayPlans = [];
        for (let dayNumber = 1; dayNumber <= maxDay; dayNumber += 1) {
          const routeDay = routeMapByDay.get(dayNumber) || {};
          const matchedRoute = routeByDay.get(dayNumber) || {};
          const itineraryDay = itineraryByDay.get(dayNumber) || {};
          const routePointNames = normalizeRouteMapDayPoints(routeDay, matchedRoute)
            .map((point) => point.name)
            .filter(Boolean);
          const itineraryPointNames = extractReportItineraryDayRoutePoints(itineraryDay);
          const waypoints = normalizeReportRoutePointNames([
            routePointNames,
            itineraryPointNames,
          ]).filter((item) => !isJourneyNoiseLocation(item));
          const title =
            routeDay.title ||
            routeDay.summary ||
            matchedRoute.summary ||
            itineraryDay.title ||
            `Day ${dayNumber}`;
          const note =
            routeDay.route_note ||
            routeDay.summary ||
            matchedRoute.route_note ||
            matchedRoute.summary ||
            itineraryDay.route_note ||
            (waypoints.length ? waypoints.join(" → ") : "当天路线待补充具体地点。");
          dayPlans.push({
            key: `report-day-${dayNumber}`,
            dayNumber,
            label: `Day ${dayNumber}`,
            title,
            waypoints,
            highlights: waypoints.slice(0, 3),
            note,
          });
        }
        return dayPlans;
      }

      function buildReportDataJourneyPreviewState(reportData = {}) {
        const overview = reportData.overview || {};
        const routeLabel = overview.route_label || "路线总览";
        const dayPlans = buildReportDataJourneyDayPlans(reportData).sort(
          (left, right) => left.dayNumber - right.dayNumber
        );
        const allWaypoints = dayPlans
          .flatMap((day) => day.waypoints || [])
          .filter((item, index, list) => item && list.indexOf(item) === index);
        if (!allWaypoints.length) return { shouldRender: false };

        const cityPair =
          extractJourneyCityPair(routeLabel) ||
          (allWaypoints.length >= 2
            ? {
                origin: allWaypoints[0],
                destination: allWaypoints[allWaypoints.length - 1],
              }
            : { origin: "", destination: allWaypoints[0] || routeLabel });
        return {
          combinedText: [
            routeLabel,
            reportData.transport?.summary,
            reportData.accommodation?.summary,
            allWaypoints.join(" "),
          ]
            .filter(Boolean)
            .join(" "),
          cityPair,
          destinationSection: {
            tone: "overview",
            title: routeLabel,
            rawLines: [
              overview.duration ? `行程天数：${overview.duration}` : "",
              overview.people ? `出行人数：${overview.people}` : "",
              ...(overview.travel_styles || []),
            ].filter(Boolean),
          },
          transportSection: {
            tone: "transport",
            title: reportData.transport?.summary || "交通待核验",
            rawLines: [reportData.transport?.summary || ""].filter(Boolean),
          },
          staySection: {
            tone: "stay",
            title: reportData.accommodation?.summary || "住宿待核验",
            rawLines: [reportData.accommodation?.summary || ""].filter(Boolean),
          },
          budgetSection: {
            tone: "budget",
            title: formatReportDataMoney(reportData.budget?.total) || "预算待核验",
            rawLines: [],
          },
          highlights: allWaypoints.slice(1, 5),
          highlightCards: buildJourneyHighlightCards(allWaypoints.slice(1, 5)),
          rhythm: dayPlans.map((day) => day.note).slice(0, 3),
          dayPlans,
          shouldRender: true,
        };
      }

      function renderReportRoutePointChips(points = []) {
        if (!points.length) return "";
        return `
          <div class="travel-report-route-point-chips">
            ${points
              .slice(0, 6)
              .map(
                (point) => `
                  <span class="travel-report-route-point-chip">
                    <strong>${escapeHtml(point.typeLabel || "路线点")}</strong>
                    ${escapeHtml(point.name)}
                  </span>
                `
              )
              .join("")}
          </div>
        `;
      }

      function getReportPlanningModeMeta(reportData = {}) {
        const mode = reportData.agency_context?.mode || "";
        if (mode === "agency_plan") {
          return {
            mode,
            label: "省心方案",
            shortLabel: "省心方案",
            icon: "fa-user-tie",
            tone: "agency",
            copy:
              "按成熟路线、服务节点、费用依据和出发前核验项组织。",
          };
        }
        if (mode === "free_planning") {
          return {
            mode,
            label: "个性化旅游规划",
            shortLabel: "个性化规划",
            icon: "fa-route",
            tone: "free",
            copy:
              "按你的偏好呈现路线、预算依据和风险提醒。",
          };
        }
        return {
          mode: "unknown",
          label: "规划方案",
          shortLabel: "规划方案",
          icon: "fa-compass",
          tone: "neutral",
          copy: "已按当前结构化信息整理路线、预算和后续核验项。",
        };
      }

      function getBudgetConfidenceTone(level = "") {
        const normalized = String(level || "").trim();
        if (/高|中高/.test(normalized)) return "strong";
        if (/中/.test(normalized)) return "medium";
        if (/低|待/.test(normalized)) return "caution";
        return "neutral";
      }

      function buildReportDataViewModel(reportData = {}) {
        const budgetConfidence = reportData.budget_confidence || {};
        const toolAudit = reportData.tool_audit_summary || {};
        const agencyContext = reportData.agency_context || {};
        const approval =
          toolAudit.approval ||
          reportData.evidence_bundle?.approval_governance ||
          {};
        const pendingChecks = normalizeReportDataList([
          ...normalizeReportDataList(budgetConfidence.verification_items),
          ...normalizeReportDataList(toolAudit.pending_checks),
        ]).filter((item, index, list) => list.indexOf(item) === index);

        return {
          mode: getReportPlanningModeMeta(reportData),
          budgetConfidence: {
            level: budgetConfidence.level || "待评估",
            tone: getBudgetConfidenceTone(budgetConfidence.level),
            confirmedItems: normalizeReportDataList(budgetConfidence.confirmed_items),
            estimatedItems: normalizeReportDataList(budgetConfidence.estimated_items),
            verificationItems: normalizeReportDataList(
              budgetConfidence.verification_items
            ),
          },
          handoff: {
            readiness: toolAudit.readiness || "可交付，预订前需核验",
            usedSources: normalizeReportDataList(toolAudit.used_sources),
            pendingChecks,
            unsupportedActions: normalizeReportDataList(toolAudit.unsupported_actions),
            toolEvents: Array.isArray(toolAudit.events) ? toolAudit.events : [],
          },
          approval: {
            approvalId: String(approval.approval_id || "").trim(),
            action: String(approval.action || "generate_order_id").trim(),
            status: String(approval.status || "none").trim(),
            pending: Boolean(approval.pending),
            requiresApproval: Boolean(approval.requires_approval),
            isBlocking: Boolean(approval.is_blocking),
            recordOnly: approval.record_only !== false,
            expiresAt: approval.expires_at || null,
            reason: String(approval.reason || "").trim(),
            boundary:
              String(approval.boundary || "").trim() ||
              "当前报告不代表真实支付、真实预订、真实锁价或履约成功。",
            unsupportedWithoutIntegration: normalizeReportDataList(
              approval.unsupported_without_integration
            ),
          },
          agency: {
            summary: String(agencyContext.summary || "").trim(),
            highlights: normalizeReportDataList(agencyContext.highlights),
            modeReason: String(agencyContext.mode_reason || "").trim(),
          },
        };
      }

      function renderReportDataInsightGroup({
        title = "",
        items = [],
        emptyText = "待补充",
        icon = "fa-circle-check",
        tone = "",
      } = {}) {
        const list = normalizeReportDataList(items);
        return `
          <div class="travel-report-insight-group ${tone}">
            <div class="travel-report-insight-group-head">
              <i class="fa-solid ${escapeHtml(icon)}"></i>
              <span>${escapeHtml(title)}</span>
            </div>
            ${
              list.length
                ? `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
                : `<p>${escapeHtml(emptyText)}</p>`
            }
          </div>
        `;
      }

      function renderReportDataBudgetConfidence(viewModel) {
        const confidence = viewModel.budgetConfidence;
        return `
          <div class="travel-report-confidence travel-report-confidence--${escapeHtml(
            confidence.tone
          )}">
            <div class="travel-report-confidence-head">
              <span>预算置信度</span>
              <strong>${escapeHtml(confidence.level)}</strong>
              <p>把已确认价格、规则估算和出发前需要复核的项目分开看，避免把估算误当成锁价。</p>
            </div>
            <div class="travel-report-insight-grid">
              ${renderReportDataInsightGroup({
                title: "已确认 / 可追溯",
                items: confidence.confirmedItems,
                emptyText: "暂无已确认价格，正式预订前都需要二次核验。",
                icon: "fa-circle-check",
                tone: "confirmed",
              })}
              ${renderReportDataInsightGroup({
                title: "规则估算",
                items: confidence.estimatedItems,
                emptyText: "暂无估算项。",
                icon: "fa-calculator",
                tone: "estimated",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验",
                items: confidence.verificationItems,
                emptyText: "正式预订或出发前复核票价、酒店、景点开放和天气。",
                icon: "fa-clipboard-check",
                tone: "verification",
              })}
            </div>
          </div>
        `;
      }

      function renderReportDataHandoffPanel(viewModel) {
        return `
          <div class="travel-report-handoff">
            <div class="travel-report-handoff-status">
              <span>交付状态</span>
              <strong>${escapeHtml(viewModel.handoff.readiness)}</strong>
            </div>
            <div class="travel-report-insight-grid compact">
              ${renderReportDataInsightGroup({
                title: "已用依据",
                items: viewModel.handoff.usedSources,
                emptyText: "来源摘要待补充。",
                icon: "fa-file-shield",
                tone: "sources",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验清单",
                items: viewModel.handoff.pendingChecks,
                emptyText: "暂无额外待核验项。",
                icon: "fa-list-check",
                tone: "verification",
              })}
              ${renderReportDataInsightGroup({
                title: "不支持承诺",
                items: viewModel.handoff.unsupportedActions,
                emptyText: "暂无额外限制说明。",
                icon: "fa-ban",
                tone: "unsupported",
              })}
            </div>
          </div>
        `;
      }

      function renderReportDataGovernancePanel(viewModel) {
        const approval = viewModel.approval || {};
        const unsupported = [
          "不接真实支付，不生成支付链接。",
          "不接真实预订、短信、客服或供应链下单。",
          "不承诺真实库存、真实锁价或履约成功。",
          ...normalizeReportDataList(approval.unsupportedWithoutIntegration),
        ].filter((item, index, list) => list.indexOf(item) === index);
        const statusText = approval.requiresApproval
          ? approval.pending
            ? "等待人工确认"
            : getStatusLabel(approval.status)
          : "边界记录";
        return `
          <div class="travel-report-governance">
            <div class="travel-report-governance-status">
              <div>
                <span>确认状态</span>
                <strong>${escapeHtml(statusText)}</strong>
              </div>
              <div>
                <span>动作</span>
                <strong>${escapeHtml(approval.action || "需确认动作")}</strong>
              </div>
              <div>
                <span>阻塞</span>
                <strong>${approval.isBlocking ? "阻塞真实动作" : "当前不阻塞报告交付"}</strong>
              </div>
            </div>
            <div class="travel-report-governance-boundary">
              <strong>确认边界</strong>
              <p>${escapeHtml(approval.boundary)}</p>
              ${renderReportDataList(unsupported, "暂无额外不可承诺项。")}
            </div>
          </div>
        `;
      }

      function renderReportDataBudgetItems(budget = {}) {
        const items = normalizeReportBudgetItems(budget);
        const total = formatReportDataMoney(budget.total);

        return `
          <div class="travel-report-budget-table-wrap">
            <table class="travel-report-budget-table">
              <thead>
                <tr>
                  <th>类别</th>
                  <th>金额</th>
                  <th>依据</th>
                </tr>
              </thead>
              <tbody>
                ${items
                  .map(
                    (item) => `
                      <tr>
                        <th scope="row">
                          <i class="fa-solid ${escapeHtml(item.icon || "fa-wallet")}"></i>
                          ${escapeHtml(item.label || "预算项")}
                        </th>
                        <td>${escapeHtml(formatReportDataMoney(item.amount) || "待核验")}</td>
                        <td>${escapeHtml(item.basis || "出发前需要二次核验")}</td>
                      </tr>
                    `
                  )
                  .join("")}
              </tbody>
            </table>
            <div class="travel-report-budget-total-line">
              <span>当前估算合计</span>
              <strong>${escapeHtml(total || "待核验")}</strong>
            </div>
            ${budget.fit ? `<p class="travel-report-budget-fit">${escapeHtml(budget.fit)}</p>` : ""}
          </div>
        `;
      }

      function isPlaceholderReportDay(day = {}) {
        const text = [
          day.title,
          day.theme,
          day.route_summary,
          ...(Array.isArray(day.time_blocks) ? day.time_blocks : []),
          ...(Array.isArray(day.risk_notes) ? day.risk_notes : []),
        ]
          .filter(Boolean)
          .join(" ");
        return (
          day.missing ||
          /待补齐当天安排|这一天还没有|待补齐路线|路线补齐\s*Day|行程明细待补充|地图路线补齐/u.test(
            text
          )
        );
      }

      function renderReportDailyNotReadyState() {
        return `
          <div class="travel-report-empty-state">
            <strong>正式每日行程尚未生成</strong>
            <p>请先确认出发城市和出发日期，再生成可交付报告；我会把每天玩法、餐饮、住宿和动线补齐后再展示这里。</p>
          </div>
        `;
      }

      function renderReportDataDailyItinerary(
        days = [],
        mapRoutes = [],
        routeMap = {},
        expectedDayCount = 0
      ) {
        const safeDays = (Array.isArray(days) ? days : []).filter(
          (day) => !isPlaceholderReportDay(day)
        );
        const safeRoutes = Array.isArray(mapRoutes) ? mapRoutes : [];
        const routeMapDays = Array.isArray(routeMap?.days) ? routeMap.days : [];
        if (!safeDays.length) return renderReportDailyNotReadyState();
        const routeByDay = new Map(
          safeRoutes.map((route) => [
            Number(route.day_number || route.day || 0),
            route,
          ])
        );
        const routeMapByDay = new Map(
          routeMapDays.map((day) => [Number(day.day_number || day.day || 0), day])
        );
        const dayByNumber = new Map(
          safeDays.map((day, index) => [
            Number(day.day_number || day.day || index + 1),
            day,
          ])
        );
        const entries = safeDays
          .map((day, index) => ({
            ...day,
            day_number: Number(day.day_number || day.day || index + 1),
            missing: false,
          }))
          .sort((left, right) => Number(left.day_number || 0) - Number(right.day_number || 0));

        return `
          <div class="travel-report-days">
            ${entries
              .map((day) => {
                const route = routeByDay.get(Number(day.day_number || 0)) || day.route || {};
                const routeMapDay = routeMapByDay.get(Number(day.day_number || 0)) || {};
                const routeSummary =
                  routeMapDay.summary ||
                  route.summary ||
                  day.route?.summary ||
                  day.route_summary ||
                  "";
                const routePoints = normalizeRouteMapDayPoints(routeMapDay, route);
                const timeBlocks = Array.isArray(day.time_blocks)
                  ? day.time_blocks
                  : [];
                const meals = Array.isArray(day.meals) ? day.meals : [];
                const riskNotes = Array.isArray(day.risk_notes)
                  ? day.risk_notes
                  : [];
                return `
                  <article class="travel-report-day ${day.missing ? "missing" : ""}">
                    <div class="travel-report-day-badge">Day ${escapeHtml(
                      day.day_number || ""
                    )}</div>
                    <div class="travel-report-day-main">
                      <h5>${escapeHtml(day.title || "当天安排")}</h5>
                      ${
                        routeSummary
                          ? `<p class="travel-report-route-line">${escapeHtml(
                              routeSummary
                            )}</p>`
                          : ""
                      }
                      ${renderReportRoutePointChips(routePoints)}
                      ${renderReportDataList(timeBlocks.slice(0, 4), "当天时段待补充")}
                      ${
                        meals.length
                          ? `<p><strong>餐饮：</strong>${escapeHtml(
                              meals.slice(0, 3).join("；")
                            )}</p>`
                          : ""
                      }
                      ${
                        day.plan_b
                          ? `<p><strong>Plan B：</strong>${escapeHtml(day.plan_b)}</p>`
                          : ""
                      }
                      ${
                        riskNotes.length
                          ? `<p><strong>当天提醒：</strong>${escapeHtml(
                              riskNotes.slice(0, 2).join("；")
                            )}</p>`
                          : ""
                      }
                    </div>
                  </article>
                `;
              })
              .join("")}
          </div>
        `;
      }

      function buildReportDefaultWarningSection(combinedText = "") {
        const hasWeatherHint = /雨|雪|热|冷|高温|台风|天气|温差|端午|暑期|节假日/u.test(
          combinedText
        );
        const lines = [
          hasWeatherHint
            ? "出发前 24-48 小时重新核验天气、景点开放状态和预约名额，遇到高温、降雨或节假日客流时优先执行室内/低强度备选。"
            : "出发前 24-48 小时重新核验天气、交通票价、酒店入住政策和景点预约名额。",
          "每天保留 1-2 小时机动时间，热门餐厅、博物馆、夜游和演出类项目尽量提前预约。",
          "预算里的交通、住宿和门票价格会随日期波动，正式下单前需要再做一次实时确认。",
        ];
        return {
          tone: "warning",
          reportTone: "warning",
          icon: "fa-cloud-sun",
          reportLabel: "天气风险",
          title: "天气与风险提醒",
          rawLines: lines,
        };
      }

      function renderStructuredTravelPlan(blocks, options = {}) {
        const expandedBlocks = expandStructuredTravelBlocks(blocks);
        const summaryBlocks = [];
        const sections = [];

        expandedBlocks.forEach((block) => {
          const lines = block
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          if (!lines.length) return;

          const isHeadingBlock = /^#{1,3}\s+/.test(lines[0]);
          const isBoldHeadingBlock = /^\*\*.+\*\*$/.test(lines[0]);
          const headingCandidate = lines[0].replace(/^#{1,3}\s+/, "").trim();
          const looksLikeSectionHeading = isEmbeddedSectionHeading(lines[0]);
          const inlineMatch = headingCandidate.match(/^([^：:]{2,16})[：:]\s*(.+)$/);
          const shouldTreatAsSection =
            Boolean(inlineMatch) ||
            isHeadingBlock ||
            isBoldHeadingBlock ||
            looksLikeSectionHeading ||
            headingCandidate.length <= 18;
          if (!shouldTreatAsSection) {
            summaryBlocks.push(lines);
            return;
          }
          const sectionTitle = inlineMatch ? inlineMatch[1] : headingCandidate;
          const bodyLines = [
            ...(inlineMatch && inlineMatch[2] ? [inlineMatch[2].trim()] : []),
            ...lines.slice(1),
          ].filter(Boolean);
          const meta =
            getTravelSectionMeta(sectionTitle) ||
            inferSectionMetaFromBody(bodyLines);

          if (!meta) {
            summaryBlocks.push(lines);
            return;
          }

          if (!bodyLines.length) {
            return;
          }

          sections.push({
            ...meta,
            title: normalizeSectionTitle(sectionTitle),
            bodyHtml: renderAssistantLines(bodyLines),
            rawLines: bodyLines,
          });
        });

        const dedupedSections = dedupeTravelReportSections(sections);
        const journeyPreviewState = buildJourneyPreviewState(summaryBlocks, dedupedSections);
        const visibleSections = dedupedSections.filter(
          (section) => !reportBudget?.isPrematureTravelBudgetSection?.(section)
        );
        const shouldRenderTravelCards = visibleSections.length >= 2;
        const shouldRenderJourneyPreview =
          !options?.suppressJourneyPreview &&
          shouldRenderJourneyPreviewBlock(journeyPreviewState, visibleSections);
        if (!shouldRenderTravelCards && !shouldRenderJourneyPreview) {
          return null;
        }
        const summaryLines = filterReportSummaryLines(summaryBlocks.flat());
        const summaryHtml = summaryLines.length
          ? renderAssistantLines(summaryLines)
          : "";
        const journeyPreviewHtml = shouldRenderJourneyPreview
          ? renderJourneyPreview(journeyPreviewState)
          : "";
        const budgetReminderLines = visibleSections
          .filter((section) => section.tone === "warning")
          .flatMap((section) => section.rawLines || []);
        const hasBudgetCard = visibleSections.some((section) => section.tone === "budget");
        const displaySections =
          hasBudgetCard && budgetReminderLines.length
            ? visibleSections.filter((section) => section.tone !== "warning")
            : visibleSections;

        return `
          <div class="travel-plan">
            ${
              shouldRenderTravelCards
                ? `
                    <div class="travel-grid">
                      ${displaySections
                        .map((section) => {
                          const sectionMapFocus = resolveTravelCardMapFocus(
                            section,
                            journeyPreviewState
                          );
                          const isBudgetSection = section.tone === "budget";
                          const sectionTitle = isBudgetSection
                            ? reportBudget?.normalizeTravelBudgetTitle?.(section.title)
                            : section.title;
                          const sectionBodyHtml = isBudgetSection
                            ? reportBudget?.renderTravelBudgetCardBody?.(
                                section.rawLines,
                                budgetReminderLines
                              )
                            : section.bodyHtml;
                          const mapButtonLabel =
                            sectionMapFocus === "stay" ? "看周边" : "看地图";
                          return `
                            <section class="travel-card ${section.tone}${
                              isBudgetSection && budgetReminderLines.length ? " with-reminders" : ""
                            }"${
                              sectionMapFocus ? ` data-map-focus="${sectionMapFocus}"` : ""
                            }>
                              <div class="travel-card-head">
                                <div class="travel-card-head-main">
                                  <div class="travel-card-icon">
                                    <i class="fa-solid ${section.icon}"></i>
                                  </div>
                                  <div class="travel-card-title">${escapeHtml(sectionTitle)}</div>
                                </div>
                                ${
                                  sectionMapFocus
                                    ? `
                                        <button
                                          class="travel-card-link-btn"
                                          type="button"
                                          data-map-focus="${sectionMapFocus}"
                                        >
                                          ${escapeHtml(mapButtonLabel)}
                                        </button>
                                      `
                                    : ""
                                }
                              </div>
                              <div class="travel-card-body">${sectionBodyHtml}</div>
                            </section>
                          `;
                        })
                        .join("")}
                    </div>
                  `
                : ""
            }
            ${journeyPreviewHtml}
            ${
              summaryHtml
                ? `<div class="travel-summary">
                    <div class="travel-summary-label">
                      <i class="fa-solid fa-compass-drafting"></i> 行程摘要
                    </div>
                    <div class="travel-summary-copy">${summaryHtml}</div>
                  </div>`
                : ""
            }
          </div>
        `;
      }

      function buildVisualJourneyPreviewState(journeyData = {}) {
        if (!isVisualJourneyData(journeyData)) return { shouldRender: false };
        const overview = journeyData.overview || {};
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const allPois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const alternativePois = Array.isArray(journeyData.alternative_pois)
          ? journeyData.alternative_pois
          : [];
        const dayPlans = days
          .map((day, index) => {
            const pois = Array.isArray(day.pois) ? day.pois : [];
            const waypoints = pois
              .map((poi) => cleanJourneyLocationValue(poi.name || ""))
              .filter(Boolean);
            if (!waypoints.length) return null;
            return {
              key: `visual-day-${day.day_number || index + 1}`,
              dayNumber: day.day_number || index + 1,
              label: day.date
                ? `${String(day.date).slice(5)} ${day.weekday || ""}`.trim()
                : `Day ${day.day_number || index + 1}`,
              title: day.title || `Day ${day.day_number || index + 1}`,
              waypoints,
              stops: pois.map((poi) => ({
                id: poi.id || "",
                name: poi.name || "",
                city: poi.city || "",
                type: poi.type || "attraction",
                type_label: poi.type_label || poi.type || "地点",
                time_range: poi.suggested_time || "",
                description: poi.description || "",
                duration_minutes: poi.duration_minutes || "",
                estimated_cost: poi.estimated_cost || "",
                reservation_note: poi.reservation_note || "",
                verification_status: poi.verification_status || "",
                verification_note: poi.verification_note || "",
                locked: Boolean(poi.locked),
                map_verified: Boolean(poi.map_verified),
                coordinate_estimated: Boolean(poi.coordinate_estimated),
                address: poi.address || "",
                amap_type: poi.amap_type || "",
                amap_source_name: poi.amap_source_name || "",
                tags: Array.isArray(poi.tags) ? poi.tags : [],
                image_url: poi.image_url || "",
                map_query: poi.map_query || "",
                lng: typeof poi.lng === "number" ? poi.lng : null,
                lat: typeof poi.lat === "number" ? poi.lat : null,
              })),
              highlights: waypoints.slice(0, 3),
              note: day.summary || waypoints.join(" → "),
              city: day.city || "",
              weather: day.weather || null,
              segments: Array.isArray(day.segments) ? day.segments : [],
              routeStatus: getJourneyDayRouteStatus(day),
              weatherStatus: getJourneyDayWeatherStatus(day),
            };
          })
          .filter(Boolean);
        if (!dayPlans.length) return { shouldRender: false };
        const destination = overview.destination || dayPlans[0]?.waypoints?.[0] || "";
        const recommendations = alternativePois
          .map((poi) => normalizeJourneyPoiAsStop(poi, { city: destination }))
          .filter((poi) => cleanJourneyLocationValue(poi.name || ""))
          .slice(0, 8);
        const origin = overview.route_label?.includes("进")
          ? overview.route_label.split("进")[0]
          : "";
        return {
          combinedText: [
            overview.title,
            overview.summary,
            allPois.map((poi) => poi.name).join(" "),
            recommendations.map((poi) => poi.name).join(" "),
          ]
            .filter(Boolean)
            .join(" "),
          cityPair: {
            origin: origin || dayPlans[0]?.waypoints?.[0] || "",
            destination,
          },
          destinationSection: {
            tone: "overview",
            title: overview.title || `${destination}旅程草案`,
            rawLines: [
              overview.summary,
              overview.date_range ? `日期：${overview.date_range}` : "",
              overview.route_label ? `路线：${overview.route_label}` : "",
            ].filter(Boolean),
          },
          transportSection: {
            tone: "transport",
            title: "交通待后续核验",
            rawLines: ["大交通、城际交通和实时路况会在后续继续核验。"],
          },
          staySection: {
            tone: "stay",
            title: "住宿待后续核验",
            rawLines: ["住宿区域和真实酒店候选会在旅程草案确认后继续补齐。"],
          },
          budgetSection: {
            tone: "budget",
            title: "预算待核验",
            rawLines: [],
          },
          highlights: allPois.map((poi) => poi.name).filter(Boolean).slice(0, 6),
          highlightCards: buildJourneyHighlightCards(
            allPois.map((poi) => poi.name).filter(Boolean).slice(0, 6)
          ),
          recommendations,
          rhythm: days.map((day) => day.summary || day.title || "").filter(Boolean).slice(0, 3),
          dayPlans,
          mapExperience: "immersive",
          shouldRender: true,
        };
      }

      function renderPlanningTrace(trace = []) {
        const items = (Array.isArray(trace) ? trace : []).filter(Boolean);
        if (!items.length || !canShowAdvisorDebug()) return "";
        return `
          <details class="planning-trace-panel" open>
            <summary>
              <span>规划过程</span>
              <strong>${items.length} 步完成</strong>
            </summary>
            <div class="planning-trace-list">
              ${items
                .map((item) => {
                  const status = item.status || "completed";
                  return `
                    <div class="planning-trace-item ${escapeHtml(status)}">
                      <span class="planning-trace-icon">${
                        status === "completed" ? "✓" : "·"
                      }</span>
                      <div>
                        <strong>${escapeHtml(item.title || item.phase || "规划步骤")}</strong>
                        <p>${escapeHtml(item.detail || "")}</p>
                        <small>${[
                          item.city,
                          item.date_range,
                          item.count ? `${item.count} 项` : "",
                        ]
                          .filter(Boolean)
                          .map(escapeHtml)
                          .join(" · ")}</small>
                      </div>
                    </div>
                  `;
                })
                .join("")}
            </div>
          </details>
        `;
      }

      function renderVisualJourneyWorkbench(journeyData, options = {}) {
        if (!isVisualJourneyData(journeyData)) return "";
        const overview = journeyData.overview || {};
        const days = Array.isArray(journeyData.days) ? journeyData.days : [];
        const pois = Array.isArray(journeyData.pois) ? journeyData.pois : [];
        const previewState = buildVisualJourneyPreviewState(journeyData);
        const atlas = previewState.shouldRender ? renderJourneyPreview(previewState) : "";
        return `
          <section
            class="visual-journey-workbench"
            data-journey-data="${serializeMapPayload(journeyData)}"
          >
            <div class="visual-journey-head">
              <div>
                <span>可视化旅程草案</span>
                <strong>${escapeHtml(overview.title || "经典路线")}</strong>
                <p>${escapeHtml(overview.summary || "先生成地图路线，再继续核验交通、酒店和预算。")}</p>
              </div>
              <div class="visual-journey-badges">
                <span>${escapeHtml(overview.date_range || "日期待确认")}</span>
                <span>${escapeHtml(String(overview.duration_days || days.length || "多"))} 天</span>
                <span>${escapeHtml(overview.route_label || "路线待核验")}</span>
              </div>
            </div>
            ${renderVisualJourneyStats(journeyData)}
            ${renderPlanningTrace(getPlanningTraceFromOptions(options))}
            ${atlas}
            ${renderVisualJourneyDayEditor(previewState.dayPlans, previewState.recommendations)}
            <div class="visual-day-strip">
              ${days
                .map(
                  (day) => `
                    <article>
                      <button
                        class="visual-day-focus-btn"
                        type="button"
                        data-map-day-focus="visual-day-${escapeHtml(String(day.day_number || 1))}"
                      >
                      <span>${escapeHtml(day.date ? String(day.date).slice(5) : `Day ${day.day_number}`)}</span>
                      <strong>${escapeHtml(day.title || day.summary || "当天安排")}</strong>
                      <p>${escapeHtml(day.summary || "")}</p>
                      ${renderJourneyDayStatusChips(day)}
                      </button>
                    </article>
                  `
                )
                .join("")}
            </div>
            ${renderVisualPoiDetails(pois)}
            <div class="visual-journey-pending">
              ${(journeyData.pending_checks || [])
                .map((item) => `<span>${escapeHtml(item)}</span>`)
                .join("")}
            </div>
          </section>
        `;
      }

      function renderAssistantText(text, options = {}) {
        const structuredReport = reportRenderer?.renderTravelReportFromData?.(
          getReportDataFromOptions(options),
          options
        );
        if (structuredReport) return structuredReport;

        const journeyData = getJourneyDataFromOptions(options);
        if (isVisualJourneyData(journeyData)) {
          return renderVisualJourneyWorkbench(journeyData, options);
        }

        if (!text) return "";
        const blocks = splitAssistantBlocks(text);
        return (
          reportRenderer?.renderTravelReport?.(blocks, options) ||
          renderStructuredTravelPlan(blocks, options) ||
          renderAssistantFallback(blocks)
        );
      }

      function renderMessageText(role, text, options = {}) {
        if (role === "assistant") {
          return renderAssistantText(text, options);
        }
        return escapeHtml(text);
      }

      function buildMessageMarkup(role, text, timestamp = new Date(), options = {}) {
        return `
                <div class="message-avatar"><i class="fa-solid ${
                  role === "user" ? "fa-user" : "fa-compass"
                }"></i></div>
                <div class="message-content">
                    <div class="message-text">${renderMessageText(
                      role,
                      text,
                      options
                    )}</div>
                    <div class="message-time">${formatClock(timestamp)}</div>
                </div>
            `;
      }

      function bindStaticActionEvents() {
        const introOverlay = document.getElementById("introOverlay");
        introOverlay?.addEventListener("click", enterAuthPortal);
        introOverlay?.addEventListener("keydown", handleIntroKeydown);
        document.querySelectorAll(".auth-tab[data-tab]").forEach((tab) => {
          tab.addEventListener("click", () => switchAuthTab(tab.dataset.tab));
        });
        document.getElementById("authForm")?.addEventListener("submit", handleAuth);
        document
          .getElementById("newChatBtn")
          ?.addEventListener("click", createNewConversation);
        document.getElementById("logoutBtn")?.addEventListener("click", logout);
        document
          .getElementById("mobileChatBackBtn")
          ?.addEventListener("click", exitMobileChatFocus);
        document
          .getElementById("retryHealthBtn")
          ?.addEventListener("click", retryHealthCheck);
        document
          .getElementById("plannerToggleBtn")
          ?.addEventListener("click", () => togglePlannerPanel());
        document
          .getElementById("resetPlannerDraftBtn")
          ?.addEventListener("click", () => resetPlannerDraft());
        guideImport?.bindGuideImportEvents?.();
        document
          .getElementById("chatInput")
          ?.addEventListener("keydown", handleInputKeydown);
        document.getElementById("sendBtn")?.addEventListener("click", sendMessage);
        document
          .getElementById("governanceRefreshBtn")
          ?.addEventListener("click", refreshGovernanceConsole);
        document
          .getElementById("createDemoApprovalBtn")
          ?.addEventListener("click", createDemoApproval);
      }

      function getClosestActionTarget(event, selector) {
        return event.target?.closest?.(selector) || null;
      }

      function handleDelegatedActionClick(event) {
        const approvalDecision = getClosestActionTarget(
          event,
          "[data-approval-decision-id][data-approval-decision]"
        );
        if (approvalDecision) {
          decideApproval(
            approvalDecision.dataset.approvalDecisionId,
            approvalDecision.dataset.approvalDecision,
            event
          );
          return true;
        }

        const approvalCard = getClosestActionTarget(event, "[data-approval-select-id]");
        if (approvalCard) {
          selectApprovalRecord(approvalCard.dataset.approvalSelectId);
          return true;
        }

        const saveConversation = getClosestActionTarget(
          event,
          "[data-conversation-save-id]"
        );
        if (saveConversation) {
          submitConversationRename(event, saveConversation.dataset.conversationSaveId);
          return true;
        }

        if (getClosestActionTarget(event, "[data-conversation-cancel]")) {
          cancelConversationRename(event);
          return true;
        }

        const editConversation = getClosestActionTarget(
          event,
          "[data-conversation-edit-id]"
        );
        if (editConversation) {
          renameConversation(event, editConversation.dataset.conversationEditId);
          return true;
        }

        const deleteConversationBtn = getClosestActionTarget(
          event,
          "[data-conversation-delete-id]"
        );
        if (deleteConversationBtn) {
          deleteConversation(event, deleteConversationBtn.dataset.conversationDeleteId);
          return true;
        }

        if (getClosestActionTarget(event, ".conversation-title-edit-form")) {
          event.stopPropagation();
          return true;
        }

        if (getClosestActionTarget(event, "[data-create-conversation]")) {
          createNewConversation();
          return true;
        }

        const conversationItem = getClosestActionTarget(
          event,
          "[data-conversation-switch-id]"
        );
        if (conversationItem) {
          switchConversation(conversationItem.dataset.conversationSwitchId);
          return true;
        }

        const suggestion = getClosestActionTarget(event, "[data-suggestion-text]");
        if (suggestion) {
          applySuggestion(suggestion.dataset.suggestionText || "");
          return true;
        }

        const plannerStyle = getClosestActionTarget(event, "[data-planner-style]");
        if (plannerStyle) {
          appendPlannerStyle(plannerStyle.dataset.plannerStyle || "");
          return true;
        }

        const plannerDraft = getClosestActionTarget(
          event,
          "[data-compose-planner-draft]"
        );
        if (plannerDraft) {
          composePlannerDraft(plannerDraft.dataset.composePlannerDraft);
          return true;
        }

        const plannerTemplate = getClosestActionTarget(
          event,
          "[data-fill-planner-template]"
        );
        if (plannerTemplate) {
          fillPlannerTemplate(plannerTemplate.dataset.fillPlannerTemplate);
          return true;
        }

        const approvalFilter = getClosestActionTarget(event, "[data-approval-filter]");
        if (approvalFilter) {
          setApprovalFilter(approvalFilter.dataset.approvalFilter || "all");
          return true;
        }

        return false;
      }

      function handleDelegatedActionSubmit(event) {
        const renameForm = getClosestActionTarget(
          event,
          "[data-conversation-rename-form-id]"
        );
        if (!renameForm) return false;
        submitConversationRename(event, renameForm.dataset.conversationRenameFormId);
        return true;
      }

      function handleDelegatedActionKeydown(event) {
        const renameInput = getClosestActionTarget(
          event,
          "[data-conversation-rename-input-id]"
        );
        if (!renameInput) return false;
        handleConversationRenameKeydown(
          event,
          renameInput.dataset.conversationRenameInputId
        );
        return true;
      }

      function handleDelegatedActionDblClick(event) {
        const renameTitle = getClosestActionTarget(
          event,
          "[data-conversation-rename-title-id]"
        );
        if (!renameTitle) return false;
        beginConversationRename(event, renameTitle.dataset.conversationRenameTitleId);
        return true;
      }

      document.addEventListener("DOMContentLoaded", async () => {
        const apiBaseInput = document.getElementById("apiBase");
        apiBaseInput.value = getDefaultApiBase();
        apiBaseInput.addEventListener("input", updateEndpointUI);
        bindStaticActionEvents();
        scheduleIntroSecondaryImages();
        window.addEventListener("resize", () => {
          if (!isMobileViewport()) {
            setMobileChatFocus(false);
          } else if (state.currentConversationId && state.mobileChatFocus) {
            setMobileChatFocus(true);
          }
        });
        window.addEventListener("online", () =>
          checkServiceHealth({ silent: true, reason: "browser-online" })
        );
        document.addEventListener("click", (event) => {
          if (reportActions?.handleReportClick?.(event)) {
            return;
          }

          if (mapControls?.handleMapClick?.(event)) {
            return;
          }

          if (journeyEditor?.handleWorkbenchClick?.(event)) {
            return;
          }

          if (journeyOverlayActions?.handleOverlayClick?.(event)) {
            return;
          }

          if (handleDelegatedActionClick(event)) {
            return;
          }
        });
        document.addEventListener("keydown", (event) => {
          if (handleDelegatedActionKeydown(event)) {
            return;
          }

          if (event.key === "Escape") {
            journeyOverlayActions?.closeJourneyMapModal?.();
          }
        });
        document.addEventListener("submit", (event) => {
          handleDelegatedActionSubmit(event);
        });
        document.addEventListener("dblclick", (event) => {
          handleDelegatedActionDblClick(event);
        });
        document.addEventListener("visibilitychange", () => {
          if (
            document.visibilityState === "visible" &&
            Date.now() - state.lastHealthCheckAt > 60000
          ) {
            checkServiceHealth({ silent: true, reason: "tab-visible" });
          }
        });
        syncUiAvailability();
        updateEndpointUI();
        renderReadinessPanel();
        renderApprovalList();
        renderApprovalEvents();
        renderToolAuditList();
        renderTurnObservability();
        applyPlannerPanelState();
        await checkServiceHealth({ silent: false, reason: "startup" });
        const restoredSession = await restoreSessionFromCookie();
        if (state.user && restoredSession) {
          hideIntroOverlay();
          hideAuthOverlay();
          updateUserInfo();
          setRuntimeStatus("正在同步会话", "loading");
          await loadConversations();
          await loadApprovals({ silent: true });
        } else {
          showIntroOverlay();
          hideAuthOverlay();
          if (isServiceUsable()) {
            setRuntimeStatus("等待登录", "idle");
          }
          setMobileChatFocus(false);
          updateSessionOverview();
          setAuthFeedback(
            "如果你是第一次来，可以先注册；如果之前用过，直接登录即可继续会话，最后我会帮你整理成旅游规划报告。",
            "info"
          );
        }
        autoResizeTextarea();
        restoreDrafts();
        updatePlannerAssistStrip();
        ["username", "email", "password"].forEach((field) => {
          const input = document.getElementById(field);
          input?.addEventListener("input", () => {
            setFieldError(field, "");
            if (document.getElementById("authFeedback")?.classList.contains("error")) {
              setAuthFeedback("", "info");
            }
          });
        });
        document
          .getElementById("chatInput")
          ?.addEventListener("input", persistComposerDraft);
        window.addEventListener("pagehide", flushAllDraftStorageWrites);
        document
          .getElementById("chatTitle")
          ?.addEventListener("dblclick", () => renameCurrentConversation());
        [
          "plannerOrigin",
          "plannerDestination",
          "plannerDate",
          "plannerDays",
          "plannerTravelers",
          "plannerBudget",
          "plannerTransport",
          "plannerStay",
          "plannerStyle",
        ].forEach((field) => {
          document
            .getElementById(field)
            ?.addEventListener("input", persistPlannerDraft);
        });
      });

      function switchAuthTab(tab) {
        const tabs = document.querySelectorAll(".auth-tab");
        const emailField = document.getElementById("emailField");
        const emailInput = document.getElementById("email");
        const authBtn = document.getElementById("authBtn");
        const authFormMeta = document.getElementById("authFormMeta");

        tabs.forEach((t) => t.classList.remove("active"));
        document.querySelector(`[data-tab="${tab}"]`).classList.add("active");
        clearAuthErrors();

        if (tab === "register") {
          emailField.classList.add("show");
          emailInput.required = true;
          authBtn.textContent = "注册通行证";
          if (authFormMeta) {
            authFormMeta.textContent =
              "注册后会自动登录，并立即为你同步空白会话列表。";
          }
          setAuthFeedback(
            "建议使用常用邮箱注册，后续排查问题和找回账号会更方便。",
            "info"
          );
        } else {
          emailField.classList.remove("show");
          emailInput.required = false;
          authBtn.textContent = "开启旅程";
          if (authFormMeta) {
            authFormMeta.textContent =
              "登录后可以继续之前的行程记录，也可以新建一段旅程。";
          }
          setAuthFeedback(
            "如果你之前已经创建过账号，直接输入用户名和密码即可继续会话。",
            "info"
          );
        }
      }

      async function handleAuth(e) {
        e.preventDefault();
        const isRegister =
          document.querySelector(".auth-tab.active").dataset.tab === "register";
        const formData = validateAuthForm(isRegister);
        if (!formData) return;
        if (!(await ensureServiceReady("登录或注册"))) return;
        const { username, email, password } = formData;
        const btn = document.getElementById("authBtn");

        state.isAuthLoading = true;
        syncUiAvailability();
        setAuthFeedback(
          isRegister ? "正在创建账号并同步会话…" : "正在验证身份并拉取会话…",
          "info"
        );
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 验证中...';

        try {
          let response;
          const endpoint = isRegister
            ? "/api/v1/users/register"
            : "/api/v1/users/login";
          const body = isRegister
            ? { username, email, password }
            : { username, password };

          ({ response, data } = await sessionApi.submitAuthForm({
            apiBase: getApiBase(),
            endpoint,
            body,
            stateToken: state.token,
          }));

          if (response.ok) {
            state.token = data.access_token || "";
            state.user = data.user;
            setAuthFeedback(
              isRegister
                ? "账号创建成功，正在进入你的旅行工作台。"
                : "登录成功，正在恢复你的会话列表。",
              "success"
            );
            showToast(isRegister ? "欢迎加入知行！" : "欢迎回来！");
            hideIntroOverlay();
            hideAuthOverlay();
            updateUserInfo();
            state.currentConversationId = null;
            state.conversations = [];
            resetConversationDrafts({ silent: true });
            renderConversationsList();
            setRuntimeStatus("正在同步会话", "loading");
            await loadConversations();
            await loadApprovals({ silent: true });
          } else {
            setRuntimeStatus("登录失败", "error");
            setAuthFeedback(data.detail || "认证失败，请检查用户名和密码。", "error");
            showToast(data.detail || "操作失败", true);
          }
        } catch (error) {
          setRuntimeStatus("连接异常", "error");
          setAuthFeedback("网络连接出现波动，请稍后重试。", "error");
          showToast("网络连接异常", true);
        } finally {
          state.isAuthLoading = false;
          btn.innerHTML = isRegister ? "注册通行证" : "开启旅程";
          syncUiAvailability();
        }
      }

      function hideAuthOverlay() {
        document.getElementById("authOverlay").classList.add("hidden");
      }
      function showAuthOverlay() {
        enableAuthHeroImages();
        document.getElementById("authOverlay").classList.remove("hidden");
      }

      function updateUserInfo() {
        if (state.user) {
          document.getElementById("userName").textContent =
            state.user.username || "旅行者";
          // 提取首字母
          const name = state.user.username || state.user.email || "U";
          document.getElementById("userAvatar").textContent =
            name[0].toUpperCase();
        }
      }

      function clearClientSession(options = {}) {
        const showToastMessage =
          typeof options === "boolean" ? options : options?.showToastMessage !== false;
        resetConversationDrafts({ silent: true });
        state.token = "";
        state.user = null;
        state.currentConversationId = null;
        state.conversations = [];
        state.governance.approvals = [];
        state.governance.approvalEvents = [];
        state.governance.selectedApprovalId = null;
        state.governance.toolAuditEvents = [];
        state.governance.turnObservability = null;
        resetPlannerDraft({ silent: true });
        showIntroOverlay();
        hideAuthOverlay();
        clearChatMessages();
        document.getElementById("conversationsList").innerHTML = "";
        document.getElementById("chatTitle").textContent = "行程助手";
        document.getElementById("userName").textContent = "访客";
        document.getElementById("userAvatar").textContent = "U";
        setMobileChatFocus(false);
        setRuntimeStatus("等待登录", "idle");
        updateSessionOverview();
        renderApprovalList();
        renderApprovalEvents();
        renderToolAuditList();
        renderTurnObservability();
        if (showToastMessage) {
          showToast("已登出账号");
        }
      }

      async function logout() {
        try {
          await sessionApi.remoteLogout({
            apiBase: getApiBase(),
            stateToken: state.token,
          });
        } catch (error) {
          console.warn("Remote logout failed", error);
        } finally {
          clearClientSession({ showToastMessage: true });
        }
      }

      async function loadConversations(options = {}) {
        if (!(await ensureServiceReady("加载会话"))) return;
        const preserveCurrentConversationId = Boolean(
          options?.preserveCurrentConversationId
        );
        try {
          const { response, data } = await conversationApi.fetchConversations({
            apiBase: getApiBase(),
            stateToken: state.token,
          });
          if (response.ok) {
            state.conversations = Array.isArray(data)
              ? data
              : data.conversations || [];
            if (
              state.currentConversationId &&
              !state.conversations.some(
                (conv) => conv.id === state.currentConversationId
              )
            ) {
              if (!preserveCurrentConversationId) {
                state.currentConversationId = null;
                restoreChatTitleLabel();
                clearChatMessages();
                setMobileChatFocus(false);
              }
            }
            renderConversationsList();
            setRuntimeStatus("已连接", "online");
          } else if (response.status === 401) clearClientSession({ showToastMessage: false });
        } catch (error) {
          console.error(error);
          renderConversationsList();
          setRuntimeStatus("会话同步失败", "error");
        }
      }

      function renderConversationsList() {
        const container = document.getElementById("conversationsList");
        updateSessionOverview();
        if (state.conversations.length === 0) {
          container.innerHTML = `
            <div class="empty-conversations">
              <i class="fa-regular fa-map" style="display:block; font-size:18px; margin-bottom:8px; color:var(--accent);"></i>
              <span class="empty-conversations-title">还没有保存的行程</span>
              <p class="empty-conversations-text">先创建一段新会话，后面每次回来都能从这里继续追问、补充交通和住宿细节。</p>
              <button
                class="empty-conversations-btn"
                type="button"
                data-create-conversation="true"
              >
                <i class="fa-solid fa-compass"></i>
                立即创建第一段行程
              </button>
            </div>`;
          return;
        }
        container.innerHTML = state.conversations
          .map(
            (conv) => `
                <div class="conversation-item ${
                  conv.id === state.currentConversationId ? "active" : ""
                } ${conv.id === state.editingConversationId ? "editing" : ""}"
                     data-conversation-switch-id="${escapeAttribute(conv.id)}">
                    <div class="conversation-top">
                      ${
                        conv.id === state.editingConversationId
                          ? `
                              <form
                                class="conversation-title conversation-title-edit-form"
                                data-conversation-rename-form-id="${escapeAttribute(conv.id)}"
                              >
                                <i class="fa-solid fa-map-pin" style="font-size:10px; color:var(--accent)"></i>
                                <input
                                  id="conversationRenameInput-${escapeAttribute(conv.id)}"
                                  class="conversation-title-input"
                                  type="text"
                                  value="${escapeAttribute(conv.title || DEFAULT_CONVERSATION_TITLE)}"
                                  maxlength="40"
                                  aria-label="编辑行程名称"
                                  data-conversation-rename-input-id="${escapeAttribute(conv.id)}"
                                />
                              </form>
                            `
                          : `
                              <div
                                class="conversation-title"
                                data-conversation-rename-title-id="${escapeAttribute(conv.id)}"
                              >
                                <i class="fa-solid fa-map-pin" style="font-size:10px; color:var(--accent)"></i>
                                <span class="conversation-title-text">${escapeHtml(
                                  conv.title || "未知行程"
                                )}</span>
                              </div>
                            `
                      }
                      <div class="conversation-actions">
                        ${
                          conv.id === state.currentConversationId
                            ? '<span class="conversation-badge">当前</span>'
                            : ""
                        }
                        ${
                          conv.id === state.editingConversationId
                            ? `
                                <button
                                  class="conversation-save-btn"
                                  type="button"
                                  aria-label="保存行程名称"
                                  data-conversation-save-id="${escapeAttribute(conv.id)}"
                                >
                                  <i class="fa-solid fa-check"></i>
                                </button>
                                <button
                                  class="conversation-cancel-btn"
                                  type="button"
                                  aria-label="取消编辑"
                                  data-conversation-cancel="true"
                                >
                                  <i class="fa-solid fa-xmark"></i>
                                </button>
                              `
                            : `
                                <button
                                  class="conversation-edit-btn"
                                  type="button"
                                  aria-label="编辑这段行程名称"
                                  data-conversation-edit-id="${escapeAttribute(conv.id)}"
                                >
                                  <i class="fa-regular fa-pen-to-square"></i>
                                </button>
                                <button
                                  class="conversation-delete-btn"
                                  type="button"
                                  aria-label="删除这段行程"
                                  data-conversation-delete-id="${escapeAttribute(conv.id)}"
                                >
                                  <i class="fa-regular fa-trash-can"></i>
                                </button>
                              `
                        }
                      </div>
                    </div>
                    <div class="conversation-time">
                        <i class="fa-regular fa-clock" style="font-size:10px;"></i> ${formatConversationStamp(
                          conv.updated_at || conv.created_at
                        )}
                    </div>
                    <div class="conversation-subline">
                        <div class="conversation-detail">
                          ${
                            conv.id === state.currentConversationId
                              ? "当前正在查看这段行程，可继续追问细节。"
                              : `最近活跃：${formatRelativeTime(
                                  conv.updated_at || conv.created_at
                                )}`
                          }
                        </div>
                        <span class="conversation-status ${
                          conv.id === state.currentConversationId ? "active" : ""
                        }">${
                          conv.id === state.currentConversationId
                            ? "进行中"
                            : "待继续"
                        }</span>
                    </div>
                </div>
            `
          )
          .join("");
      }

      async function deleteConversation(event, id) {
        event?.stopPropagation();
        const conv = state.conversations.find((item) => item.id === id);
        const label = conv?.title || "这段行程";
        if (!window.confirm(`确定删除“${label}”吗？删除后会从当前账号的列表中移除。`)) {
          return;
        }
        if (!(await ensureServiceReady("删除行程"))) return;

        try {
          const { response } = await conversationApi.deleteConversation({
            apiBase: getApiBase(),
            stateToken: state.token,
            id,
          });
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }

          const wasCurrent = state.currentConversationId === id;
          state.conversations = state.conversations.filter((item) => item.id !== id);
          if (wasCurrent) {
            state.currentConversationId = null;
            document.getElementById("chatTitle").textContent = "行程助手";
            clearChatMessages();
            resetConversationDrafts({ silent: true });
            renderConversationsList();
            setMobileChatFocus(false);
          }
          renderConversationsList();

          if (wasCurrent && state.conversations.length) {
            await switchConversation(state.conversations[0].id);
          } else if (!state.conversations.length) {
            setRuntimeStatus("可以开始新的行程", "online");
          }

          showToast("行程已删除");
        } catch (error) {
          console.error(error);
          setRuntimeStatus("删除失败", "error");
          showToast("删除失败，请稍后重试。", true);
        }
      }

      function focusConversationRenameInput(id, preferHeader = false) {
        requestAnimationFrame(() => {
          const input =
            (preferHeader && document.getElementById("chatTitleRenameInput")) ||
            document.getElementById(`conversationRenameInput-${id}`) ||
            document.getElementById("chatTitleRenameInput");
          if (!input) return;
          input.focus();
          input.select();
        });
      }

      function renderChatTitleRenameInput(id) {
        const chatTitle = document.getElementById("chatTitle");
        const conv = state.conversations.find((item) => item.id === id);
        if (!chatTitle || !conv) return;
        chatTitle.classList.add("editing");
        chatTitle.innerHTML = `
          <input
            id="chatTitleRenameInput"
            class="chat-title-input"
            type="text"
            value="${escapeAttribute(conv.title || DEFAULT_CONVERSATION_TITLE)}"
            maxlength="40"
            aria-label="编辑当前行程名称"
            data-conversation-rename-input-id="${escapeAttribute(id)}"
          />
        `;
      }

      function restoreChatTitleLabel() {
        const chatTitle = document.getElementById("chatTitle");
        if (!chatTitle) return;
        chatTitle.classList.remove("editing");
        chatTitle.textContent =
          getCurrentConversation()?.title || "行程助手";
      }

      function beginConversationRename(event, id, options = {}) {
        event?.stopPropagation();
        const conv = state.conversations.find((item) => item.id === id);
        if (!conv) return;
        state.editingConversationId = id;
        renderConversationsList();
        if (options.focusHeader || state.currentConversationId === id) {
          renderChatTitleRenameInput(id);
        }
        focusConversationRenameInput(id, Boolean(options.focusHeader));
      }

      function cancelConversationRename(event) {
        event?.preventDefault();
        event?.stopPropagation();
        state.editingConversationId = null;
        renderConversationsList();
        restoreChatTitleLabel();
        updateSessionOverview();
      }

      function handleConversationRenameKeydown(event, id) {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          submitConversationRename(event, id);
        } else if (event.key === "Escape") {
          event.preventDefault();
          cancelConversationRename(event);
        }
      }

      async function submitConversationRename(event, id) {
        event?.preventDefault();
        event?.stopPropagation();
        if (state.renamingConversationId) return;
        const conv = state.conversations.find((item) => item.id === id);
        const currentTitle = conv?.title || DEFAULT_CONVERSATION_TITLE;
        const input =
          (event?.target?.matches?.(".conversation-title-input, .chat-title-input")
            ? event.target
            : null) ||
          event?.target?.closest?.(".conversation-title-edit-form")?.querySelector?.(
            ".conversation-title-input"
          ) ||
          document.getElementById(`conversationRenameInput-${id}`) ||
          document.getElementById("chatTitleRenameInput");
        const trimmed = input?.value?.trim() || "";
        if (!trimmed || trimmed === currentTitle) {
          cancelConversationRename(event);
          return;
        }
        if (!(await ensureServiceReady("修改行程名称"))) return;
        state.renamingConversationId = id;
        document
          .querySelectorAll(".conversation-save-btn, .conversation-cancel-btn, .conversation-title-input, .chat-title-input")
          .forEach((el) => {
            el.disabled = true;
          });
        try {
          await updateConversationTitle(id, trimmed);
          state.editingConversationId = null;
        } catch (error) {
          console.error(error);
          showToast("修改名称失败，请稍后重试。", true);
          focusConversationRenameInput(id);
        } finally {
          document
            .querySelectorAll(".conversation-save-btn, .conversation-cancel-btn, .conversation-title-input, .chat-title-input")
            .forEach((el) => {
              el.disabled = false;
            });
          state.renamingConversationId = null;
        }
      }

      async function renameConversation(event, id) {
        beginConversationRename(event, id);
      }

      async function renameCurrentConversation() {
        if (!state.currentConversationId) return;
        beginConversationRename(null, state.currentConversationId, {
          focusHeader: true,
        });
      }

      async function createNewConversation() {
        if (!(await ensureServiceReady("创建新行程"))) return;
        try {
          const { response, data } = await conversationApi.createConversation({
            apiBase: getApiBase(),
            stateToken: state.token,
            title: "新行程",
          });
          if (response.ok) {
            state.currentConversationId = data.id;
            if (!state.conversations.some((item) => item.id === data.id)) {
              state.conversations = [data, ...state.conversations];
            }
            setMobileChatFocus(true);
            clearChatMessages();
            resetConversationDrafts({ silent: true });
            document.getElementById("chatTitle").textContent = "新行程";
            setMobileChatFocus(true);
            document.getElementById("chatTitle").textContent =
              data.title || DEFAULT_CONVERSATION_TITLE;
            renderConversationsList();
            await loadConversations({ preserveCurrentConversationId: true });
            await loadApprovals({ silent: true });
            updateSessionOverview();
            setRuntimeStatus("新会话已创建", "online");
            showToast("新行程已创建");
          }
        } catch (error) {
          setRuntimeStatus("创建会话失败", "error");
          showToast("创建失败", true);
        }
      }

      async function switchConversation(id) {
        if (!(await ensureServiceReady("切换会话"))) return;
        state.currentConversationId = id;
        setMobileChatFocus(true);
        renderConversationsList();
        setRuntimeStatus("正在加载会话", "loading");

        // 获取标题
        try {
          const { response: res, data } = await conversationApi.fetchConversationDetail({
            apiBase: getApiBase(),
            stateToken: state.token,
            id,
          });
          if (res.ok) {
            document.getElementById("chatTitle").textContent = data.title;
            const current = state.conversations.find((conv) => conv.id === id);
            if (current) current.title = data.title;
            updateSessionOverview();
          }
        } catch (e) {}

        // 获取历史
        try {
          const { response: res, data } = await conversationApi.fetchChatHistory({
            apiBase: getApiBase(),
            stateToken: state.token,
            id,
          });
          if (res.ok) {
            const msgs = Array.isArray(data) ? data : data.messages || [];
            renderMessages(msgs);
            setRuntimeStatus("历史会话已就绪", "online");
          } else clearChatMessages();
        } catch (e) {
          clearChatMessages();
          setRuntimeStatus("加载失败", "error");
        }
        await loadApprovals({ silent: true });
      }

      function hydrateGovernanceFromMessages(messages = []) {
        state.governance.toolAuditEvents = [];
        state.governance.turnObservability = null;
        state.governance.progressSnapshot = null;
        (Array.isArray(messages) ? messages : []).forEach((msg) => {
          if (msg.role !== "assistant") return;
          const extra = msg.extra_info || msg.extraInfo || {};
          const auditEvents = Array.isArray(extra.tool_audit_events)
            ? extra.tool_audit_events
            : [];
          auditEvents.forEach((event) => {
            const normalized = normalizeToolAuditEvent(event);
            state.governance.toolAuditEvents.unshift(normalized);
          });
          if (extra.fast_mode_split) {
            rememberProgressSnapshot(progressSnapshotFromFastSplit(extra.fast_mode_split));
          }
          const reportData = extra.report_data || extra.reportData;
          if (reportData) {
            rememberProgressSnapshot(progressSnapshotFromReportData(reportData));
          }
          const observation = extra.observability?.metrics || extra.observability;
          if (observation) {
            rememberTurnObservability(observation);
          }
        });
        state.governance.toolAuditEvents = state.governance.toolAuditEvents.slice(0, 20);
        renderToolAuditList();
        renderTurnObservability();
      }

      function renderMessages(messages) {
        const container = document.getElementById("chatMessages");
        hydrateGovernanceFromMessages(messages);
        if (messages.length === 0) {
          clearChatMessages();
          return;
        }
        const lastAssistantIndex = messages
          .map((msg, index) => (msg.role === "assistant" ? index : -1))
          .filter((index) => index >= 0)
          .pop();
        container.innerHTML = messages
          .map(
            (msg, index) => `
                <div class="message ${
                  msg.role
                }" id="msg-${Date.now()}-${Math.random()}">
                    ${buildMessageMarkup(
                      msg.role,
                      msg.content,
                      msg.created_at || msg.updated_at || new Date(),
                      {
                        extraInfo: msg.extra_info || msg.extraInfo || {},
                        suppressJourneyPreview:
                          msg.role === "assistant" && index !== lastAssistantIndex,
                      }
                    )}
                </div>
            `
          )
          .join("");
        scheduleJourneyMapHydration(container);
        container.scrollTop = container.scrollHeight;
      }

      function clearChatMessages() {
        document.getElementById("chatMessages").innerHTML = getWelcomeMarkup();
      }

      async function sendMessage() {
        if (!(await ensureServiceReady("发送消息"))) return;
        const input = document.getElementById("chatInput");
        const content = input.value.trim();
        if (!content || state.isLoading) return;

        if (!state.currentConversationId) {
          await createNewConversation();
          if (!state.currentConversationId) return;
        }

        await maybeAutoNameCurrentConversation(content);

        state.isLoading = true;
        setSendButtonLoading(true);
        setRuntimeStatus("正在规划行程", "loading");

        // 移除欢迎页
        const welcome = document.querySelector(".welcome-screen");
        if (welcome) welcome.remove();

        // 用户消息
        addMessage("user", content);
        const optimisticFacts = parseOptimisticTripFactsFromText(content);
        if (Object.keys(optimisticFacts).length) {
          const existingProgress = getGovernanceProgressSnapshot();
          rememberProgressSnapshot(
            progressSnapshotFromFastSplit({
              facts: {
                ...optimisticFacts,
                planning_mode:
                  existingProgress.planning_mode || optimisticFacts.planning_mode || "",
                active_workflow:
                  existingProgress.active_workflow || existingProgress.planning_mode || "",
                agency_step: existingProgress.agency_step || optimisticFacts.agency_step || "",
              },
            })
          );
          renderReadinessPanel();
        }
        input.value = "";
        input.style.height = "auto";
        persistComposerDraft({ immediate: true });

        // 助手Loading
        const loadingId = addLoading();
        const requestStartedAt = Date.now();
        let reachedSlowStage = false;
        let reachedVerySlowStage = false;
        let streamingMessageId = "";
        let streamingFullText = "";
        let streamingReportData = null;
        let streamingJourneyData = null;
        let streamingPlanningTrace = [];
        let pendingStreamingChunk = "";
        let streamingRenderFrame = null;
        let flushPendingVisibleChunks = () => {};
        const streamingThinkingFilter = createAssistantThinkingFilter();
        const slowHintTimer = setTimeout(() => {
          reachedSlowStage = true;
          updateLoadingCopy(
            loadingId,
            "正在继续整理这次行程建议。如果这轮涉及交通、住宿、地图或外部服务，等待时间会比普通回答更长一些。"
          );
          setRuntimeStatus("外部信息查询中", "loading");
        }, 18000);
        const verySlowHintTimer = setTimeout(() => {
          reachedVerySlowStage = true;
          updateLoadingCopy(
            loadingId,
            "这轮等待时间比平时更久，可能正在查询外部信息，或整理较长的分日建议。页面可以继续保持打开，我会在结果返回后直接补上。"
          );
          setRuntimeStatus("仍在处理中", "loading");
        }, 45000);

        try {
          const res = await conversationApi.openChatStream({
            apiBase: getApiBase(),
            stateToken: state.token,
            conversationId: state.currentConversationId,
            content,
          });

          if (
            res.ok &&
            res.headers.get("content-type")?.includes("event-stream")
          ) {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            const buildStreamingRenderOptions = (overrides = {}) => ({
              suppressJourneyPreview: true,
              pinToTop: true,
              reportData: streamingReportData,
              journeyData: streamingJourneyData,
              planningTrace: streamingPlanningTrace,
              ...overrides,
            });

            const renderVisibleChunk = (chunk) => {
              if (!chunk) return;
              if (!streamingMessageId) {
                streamingFullText = chunk;
                streamingMessageId = convertLoadingToAssistant(
                  loadingId,
                  streamingFullText,
                  buildStreamingRenderOptions()
                );
                return;
              }
              streamingFullText += chunk;
              updateMessage(
                streamingMessageId,
                streamingFullText,
                buildStreamingRenderOptions()
              );
            };

            flushPendingVisibleChunks = () => {
              if (streamingRenderFrame) {
                cancelAnimationFrame(streamingRenderFrame);
                streamingRenderFrame = null;
              }
              const chunk = pendingStreamingChunk;
              pendingStreamingChunk = "";
              renderVisibleChunk(chunk);
            };

            const appendVisibleChunk = (chunk) => {
              if (!chunk) return;
              if (!streamingMessageId) {
                renderVisibleChunk(chunk);
                return;
              }
              pendingStreamingChunk += chunk;
              if (streamingRenderFrame) return;
              streamingRenderFrame = requestAnimationFrame(() => {
                streamingRenderFrame = null;
                const nextChunk = pendingStreamingChunk;
                pendingStreamingChunk = "";
                renderVisibleChunk(nextChunk);
              });
            };
            const applyChunk = (chunk) => {
              const visibleChunk = streamingThinkingFilter.feed(chunk);
              if (visibleChunk) {
                appendVisibleChunk(visibleChunk);
              }
            };
            const applyStreamEvent = (event) => {
              if (event?.type === "report_data" && event.report_data) {
                streamingReportData = event.report_data;
              }
              if (event?.type === "planning_trace") {
                streamingPlanningTrace = [
                  ...streamingPlanningTrace,
                  {
                    phase: event.phase,
                    status: event.status,
                    title: event.title,
                    detail: event.detail,
                    count: event.count,
                    city: event.city,
                    date_range: event.date_range,
                    evidence_type: event.evidence_type,
                  },
                ].filter((item) => item.title || item.detail);
              }
              if (event?.type === "journey_data" && event.journey_data) {
                streamingJourneyData = event.journey_data;
                if (Array.isArray(event.planning_trace)) {
                  streamingPlanningTrace = event.planning_trace;
                }
              }
              if (event?.type === "tool_audit") {
                rememberToolAuditEvent(event);
              }
              if (event?.type === "turn_observability") {
                rememberTurnObservability(event);
              }
            };

            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              buffer = processSseBuffer(buffer, applyChunk, applyStreamEvent);
            }

            const tail = decoder.decode();
            if (tail) {
              buffer += tail;
            }
            if (buffer.trim()) {
              processSseBuffer(`${buffer}\n\n`, applyChunk, applyStreamEvent);
            }
            const visibleTail = streamingThinkingFilter.finish();
            if (visibleTail) {
              appendVisibleChunk(visibleTail);
            }
            flushPendingVisibleChunks();

            if (!streamingMessageId) {
              streamingMessageId = convertLoadingToAssistant(
                loadingId,
                streamingReportData
                  ? "结构化旅游规划报告已整理完成。"
                  : streamingJourneyData
                  ? "可视化旅程草案已整理完成。"
                  : "这次没有拿到可展示的内容，你可以再试一次，或者换个问法继续。",
                {
                  suppressJourneyPreview: false,
                  pinToTop: true,
                  reportData: streamingReportData,
                  journeyData: streamingJourneyData,
                  planningTrace: streamingPlanningTrace,
                }
              );
            } else {
              updateMessage(streamingMessageId, streamingFullText, {
                suppressJourneyPreview: false,
                pinToTop: true,
                reportData: streamingReportData,
                journeyData: streamingJourneyData,
                planningTrace: streamingPlanningTrace,
              });
            }
            setRuntimeStatus("行程建议已整理", "online");
          } else {
            clearTimeout(slowHintTimer);
            removeMessage(loadingId);
            const data = await res.json();
            addMessage(
              "assistant",
              data.content || data.message || JSON.stringify(data)
            );
            if (!res.ok) {
              setRuntimeStatus("请求失败", "error");
            } else {
              setRuntimeStatus("已连接", "online");
            }
          }
        } catch (e) {
          const elapsedMs = Date.now() - requestStartedAt;
          clearTimeout(slowHintTimer);
          clearTimeout(verySlowHintTimer);
          flushPendingVisibleChunks();
          if (streamingMessageId && streamingFullText.trim()) {
            updateMessage(
              streamingMessageId,
              `${streamingFullText}${buildStreamingFallbackMessage({
                elapsedMs,
                hasPartialContent: true,
                reachedVerySlowStage,
              })}`,
              {
                suppressJourneyPreview: true,
                pinToTop: true,
                reportData: streamingReportData,
                journeyData: streamingJourneyData,
                planningTrace: streamingPlanningTrace,
              }
            );
          } else {
            removeMessage(loadingId);
            addMessage(
              "assistant",
              buildStreamingFallbackMessage({
                elapsedMs,
                hasPartialContent: false,
                reachedVerySlowStage,
              })
            );
          }
          setRuntimeStatus("连接异常", "error");
        } finally {
          clearTimeout(slowHintTimer);
          clearTimeout(verySlowHintTimer);
        }

        state.isLoading = false;
        setSendButtonLoading(false);
      }

      function addMessage(role, text, options = {}) {
        const container = document.getElementById("chatMessages");
        const id = "msg-" + Date.now();
        const div = document.createElement("div");
        div.className = `message ${role}`;
        div.id = id;
        div.innerHTML = buildMessageMarkup(role, text, new Date(), options);
        container.appendChild(div);
        scheduleJourneyMapHydration(div);
        container.scrollTop = container.scrollHeight;
        return id;
      }

      function scrollChatMessageToTop(id, behavior = "smooth") {
        const container = document.getElementById("chatMessages");
        const el = document.getElementById(id);
        if (!container || !el) return;

        const targetTop = Math.max(
          el.offsetTop - container.offsetTop - 16,
          0
        );
        container.scrollTo({ top: targetTop, behavior });
      }

      function pinChatMessageToTop(id) {
        if (streamingScrollFrame) {
          cancelAnimationFrame(streamingScrollFrame);
        }
        streamingScrollFrame = requestAnimationFrame(() => {
          scrollChatMessageToTop(id, "auto");
          streamingScrollFrame = null;
        });
      }

      function updateMessage(id, text, options = {}) {
        const el = document.getElementById(id);
        if (el) {
          el.querySelector(".message-text").innerHTML = renderMessageText(
            "assistant",
            text,
            options
          );
          if (!options?.suppressJourneyPreview) {
            scheduleJourneyMapHydration(el);
          }
          if (options?.pinToTop) {
            pinChatMessageToTop(id);
          }
        }
      }

      function convertLoadingToAssistant(id, text, options = {}) {
        const el = document.getElementById(id);
        if (!el) {
          return addMessage("assistant", text, options);
        }
        const messageId = "msg-" + Date.now();
        el.id = messageId;
        el.className = "message assistant";
        el.innerHTML = buildMessageMarkup("assistant", text, new Date(), options);
        if (!options?.suppressJourneyPreview) {
          scheduleJourneyMapHydration(el);
        }
        scrollChatMessageToTop(messageId, options?.pinToTop ? "auto" : "smooth");
        return messageId;
      }

      function addLoading() {
        const container = document.getElementById("chatMessages");
        const id = "loading-" + Date.now();
        const div = document.createElement("div");
        div.className = "message assistant";
        div.id = id;
        div.innerHTML = `
                <div class="message-avatar"><i class="fa-solid fa-compass"></i></div>
                <div class="message-content thinking-card">
                    <div class="thinking-header">
                        <div class="thinking-title">
                            <i class="fa-solid fa-route"></i>
                            正在整理行程建议
                        </div>
                        <span class="thinking-badge">处理中</span>
                    </div>
                    <div class="thinking-copy">正在结合你的需求和已经聊到的信息，整理下一步更完整的建议。</div>
                    <div class="thinking-progress"></div>
                    <div class="typing-dots" style="margin-top: 12px;"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
                </div>
            `;
        container.appendChild(div);
        scrollChatMessageToTop(id);
        return id;
      }

      function updateLoadingCopy(id, text) {
        const el = document.getElementById(id);
        const copy = el?.querySelector(".thinking-copy");
        if (copy) {
          copy.textContent = text;
        }
      }

      function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
      }

      function handleInputKeydown(e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      }

      function autoResizeTextarea() {
        const el = document.getElementById("chatInput");
        el.addEventListener("input", function () {
          this.style.height = "auto";
          this.style.height = Math.min(this.scrollHeight, 120) + "px";
        });
      }

      function showToast(msg, isError = false) {
        const t = document.getElementById("toast");
        document.getElementById("toastMsg").textContent = msg;
        t.className = `toast show ${isError ? "error" : ""}`;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(() => t.classList.remove("show"), 3000);
      }

      function formatTime(str) {
        if (!str) return "";
        const d = new Date(str);
        return `${d.getMonth() + 1}月${d.getDate()}日`;
      }

      function formatConversationStamp(str) {
        if (!str) return "";
        const d = new Date(str);
        const now = new Date();
        const sameYear = d.getFullYear() === now.getFullYear();
        const day = `${d.getMonth() + 1}月${d.getDate()}日`;
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        return sameYear ? `${day} ${hh}:${mm}` : `${d.getFullYear()}年${day} ${hh}:${mm}`;
      }

      function formatRelativeTime(str) {
        if (!str) return "";
        const d = new Date(str);
        const diff = Date.now() - d.getTime();
        const minute = 60 * 1000;
        const hour = 60 * minute;
        const day = 24 * hour;

        if (diff < minute) return "刚刚更新";
        if (diff < hour) return `${Math.max(1, Math.floor(diff / minute))} 分钟前更新`;
        if (diff < day) return `${Math.floor(diff / hour)} 小时前更新`;
        if (diff < day * 2) return "昨天更新";
        if (diff < day * 7) return `${Math.floor(diff / day)} 天前更新`;
        return `更新于 ${formatTime(str)}`;
      }

      function escapeHtml(text) {
        if (!text) return "";
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, "<br>");
      }

      function escapeAttribute(text) {
        return escapeHtml(text).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
      }
