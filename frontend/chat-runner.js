(function (global) {
  function createChatRunner({
    document,
    state,
    ensureServiceReady,
    createNewConversation,
    maybeAutoNameCurrentConversation,
    setSendButtonLoading,
    setRuntimeStatus,
    addMessage,
    parseOptimisticTripFactsFromText,
    getGovernanceProgressSnapshot,
    rememberProgressSnapshot,
    progressSnapshotFromFastSplit,
    renderReadinessPanel,
    persistComposerDraft,
    addLoading,
    createAssistantThinkingFilter,
    updateLoadingCopy,
    conversationApi,
    getApiBase,
    processSseBuffer,
    convertLoadingToAssistant,
    updateMessage,
    rememberToolAuditEvent,
    rememberTurnObservability,
    removeMessage,
    buildStreamingFallbackMessage,
    TextDecoder: TextDecoderCtor = global.TextDecoder,
    Date: DateCtor = global.Date,
    setTimeout: scheduleTimeout = (...args) => global.setTimeout(...args),
    clearTimeout: cancelTimeout = (...args) => global.clearTimeout(...args),
    requestAnimationFrame: scheduleFrame = (...args) =>
      global.requestAnimationFrame(...args),
    cancelAnimationFrame: cancelFrame = (...args) =>
      global.cancelAnimationFrame(...args),
  } = {}) {
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

      const welcome = document.querySelector(".welcome-screen");
      if (welcome) welcome.remove();

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

      const loadingId = addLoading();
      const requestStartedAt = DateCtor.now();
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
      const slowHintTimer = scheduleTimeout(() => {
        updateLoadingCopy(
          loadingId,
          "正在继续整理这次行程建议。如果这轮涉及交通、住宿、地图或外部服务，等待时间会比普通回答更长一些。"
        );
        setRuntimeStatus("外部信息查询中", "loading");
      }, 18000);
      const verySlowHintTimer = scheduleTimeout(() => {
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
          const decoder = new TextDecoderCtor();
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
              cancelFrame(streamingRenderFrame);
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
            streamingRenderFrame = scheduleFrame(() => {
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
          cancelTimeout(slowHintTimer);
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
        const elapsedMs = DateCtor.now() - requestStartedAt;
        cancelTimeout(slowHintTimer);
        cancelTimeout(verySlowHintTimer);
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
        cancelTimeout(slowHintTimer);
        cancelTimeout(verySlowHintTimer);
      }

      state.isLoading = false;
      setSendButtonLoading(false);
    }

    return {
      sendMessage,
    };
  }

  global.ZhiXingChatRunner = {
    createChatRunner,
  };
})(window);
