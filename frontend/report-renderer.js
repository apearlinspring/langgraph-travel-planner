(function (global) {
  function createReportRenderer(deps = {}) {
    const {
      escapeHtml,
      normalizeReportDataList,
      renderTravelReportNextAction,
      isStructuredTravelReportData,
      buildReportDataViewModel,
      parseReportDataExpectedDays,
      formatReportDataMoney,
      buildReportDataJourneyPreviewState,
      renderJourneyPreview,
      renderReportDataList,
      renderReportDataDailyItinerary,
      renderReportDataBudgetItems,
      renderReportDataBudgetConfidence,
      renderReportDataHandoffPanel,
      renderReportDataGovernancePanel,
      extractReportDayGroups,
      parseJourneyDayNumber,
      renderReportDailyNotReadyState,
      renderAssistantLines,
      formatInlineText,
      renderReportBudgetBreakdown,
      expandStructuredTravelBlocks,
      hasTravelReportSignal,
      extractTravelReportSections,
      extractJourneyCityPair,
      extractJourneyCityPairFromConversationTitle,
      getCurrentConversationTitle,
      extractReportExpectedDayCount,
      filterReportSummaryLines,
      buildJourneyPreviewState,
      dedupeTravelReportSections,
      mergeTravelReportDailySections,
      shouldRenderJourneyPreviewBlock,
      inferTextTravelReportMode,
      getReportPlanningModeMeta,
      reportBudget,
    } = deps;

    function renderReportDataCard({
      tone = "summary",
      icon = "fa-file-lines",
      label = "",
      title = "",
      body = "",
    }) {
      return `
          <section class="travel-report-card ${tone}">
            <div class="travel-report-card-head">
              <span class="travel-report-card-icon">
                <i class="fa-solid ${icon}"></i>
              </span>
              <div>
                <div class="travel-report-card-label">${escapeHtml?.(label || title)}</div>
                <h4>${escapeHtml?.(title)}</h4>
              </div>
            </div>
            <div class="travel-report-card-body">${body}</div>
          </section>
        `;
    }

    function renderReportDataMapDigest(reportData = {}) {
      const previewState = buildReportDataJourneyPreviewState?.(reportData);
      if (!previewState?.shouldRender) return "";
      return renderJourneyPreview?.(previewState);
    }

    function buildCustomerRiskLines(reportData = {}, viewModel = {}) {
      return normalizeReportDataList?.([
        ...(Array.isArray(reportData.risks) ? reportData.risks : []),
        ...(viewModel.handoff?.pendingChecks || []),
      ])?.filter((item, index, list) => list.indexOf(item) === index);
    }

    function renderStructuredReportNextAction(reportData = {}) {
      const explicitLines = normalizeReportDataList?.([
        reportData.next_action,
        reportData.next_steps,
        reportData.follow_up,
      ]);
      const lines = explicitLines?.length
        ? explicitLines
        : [
            "请评价这版方案：",
            "如果满意，我将按此结构生成最终可导出的旅行规划报告。",
            "如果想调整，请告诉我具体想改哪里（例如：节奏太快/太慢、想替换景点、住宿想换区域或预算想压缩等）。",
          ];
      return renderTravelReportNextAction?.([
        {
          tone: "next",
          reportTone: "next",
          rawLines: lines,
        },
      ]);
    }

    function renderTravelReportFromData(reportData, options = {}) {
      if (!isStructuredTravelReportData?.(reportData)) return null;

      const viewMode = options.view || reportData.default_view || "customer";
      const showAdvisorSections = viewMode === "advisor" || viewMode === "debug";
      const overview = reportData.overview || {};
      const budget = reportData.budget || {};
      const viewModel = buildReportDataViewModel?.(reportData);
      const routeLabel = overview.route_label || "专属旅程";
      const dayCount = overview.duration || "分日规划";
      const expectedDayCount = parseReportDataExpectedDays?.(reportData);
      const budgetLabel =
        formatReportDataMoney?.(budget.total) ||
        reportData.budget_confidence?.level ||
        "预算已估算";
      const mapDigest = !options?.suppressJourneyPreview
        ? renderReportDataMapDigest(reportData)
        : "";
      const customerRiskLines = buildCustomerRiskLines(reportData, viewModel);

      return `
          <div class="travel-report travel-report--${escapeHtml?.(
            viewModel.mode.tone
          )}" data-report-source="structured" data-planning-mode="${escapeHtml?.(
            viewModel.mode.mode
          )}">
            <div class="travel-report-hero">
              <div class="travel-report-kicker">
                <i class="fa-solid ${escapeHtml?.(viewModel.mode.icon)}"></i>
                ${escapeHtml?.(viewModel.mode.label)}
              </div>
              <h3>${escapeHtml?.(routeLabel)}</h3>
              <p>${escapeHtml?.(viewModel.mode.copy)}</p>
              <div class="travel-report-metrics">
                <span><i class="fa-solid ${escapeHtml?.(
                  viewModel.mode.icon
                )}"></i>${escapeHtml?.(viewModel.mode.shortLabel)}</span>
                <span><i class="fa-solid fa-route"></i>${escapeHtml?.(routeLabel)}</span>
                <span><i class="fa-regular fa-calendar"></i>${escapeHtml?.(dayCount)}</span>
                <span><i class="fa-solid fa-wallet"></i>${escapeHtml?.(budgetLabel)}</span>
              </div>
              <div class="travel-report-actions">
                <button type="button" data-report-action="tweak">
                  <i class="fa-solid fa-pen-nib"></i> 继续微调
                </button>
                <button type="button" data-report-action="map">
                  <i class="fa-solid fa-map-location-dot"></i> 查看路线地图
                </button>
                <button type="button" data-report-action="copy-summary">
                  <i class="fa-solid fa-copy"></i> 复制摘要
                </button>
                <button type="button" data-report-action="export">
                  <i class="fa-solid fa-file-export"></i> 导出报告
                </button>
              </div>
            </div>
            <div class="travel-report-grid">
              ${renderReportDataCard({
                tone: "summary",
                icon: "fa-compass",
                label: "行程概览",
                title: "你的旅行骨架",
                body: renderReportDataList?.([
                  overview.people ? `出行人数：${overview.people}` : "",
                  overview.travel_styles?.length
                    ? `主题偏好：${overview.travel_styles.join("、")}`
                    : "",
                  overview.special_needs ? `特殊需求：${overview.special_needs}` : "",
                ]),
              })}
              ${renderReportDataCard({
                tone: "transport",
                icon: "fa-train-subway",
                label: "交通与住宿",
                title: "出行与落脚建议",
                body: renderReportDataList?.([
                  reportData.transport?.summary ? `交通：${reportData.transport.summary}` : "",
                  reportData.accommodation?.summary
                    ? `住宿：${reportData.accommodation.summary}`
                    : "",
                  reportData.food_preferences?.summary
                    ? `餐饮：${reportData.food_preferences.summary}`
                    : "",
                ]),
              })}
              ${renderReportDataCard({
                tone: "daily",
                icon: "fa-calendar-days",
                label: "每日行程",
                title: "按天执行",
                body: renderReportDataDailyItinerary?.(
                  reportData.itinerary,
                  reportData.map_routes,
                  reportData.route_map,
                  expectedDayCount
                ),
              })}
              ${renderReportDataCard({
                tone: "budget",
                icon: "fa-wallet",
                label: "费用拆分",
                title: "预算明细与依据",
                body: renderReportDataBudgetItems?.(budget),
              })}
              ${renderReportDataCard({
                tone: "warning",
                icon: "fa-triangle-exclamation",
                label: "风险提醒",
                title: "重要提醒",
                body: `
                  ${renderReportDataList?.(customerRiskLines, "风险提醒待补充")}
                `,
              })}
              ${renderReportDataCard({
                tone: "summary",
                icon: "fa-shield-heart",
                label: "方案依据",
                title:
                  viewModel.mode.mode === "free_planning"
                    ? "规划依据与执行提醒"
                    : "服务标准与交付依据",
                body: renderReportDataList?.([
                  viewModel.agency.summary || "",
                  viewModel.agency.modeReason ? `模式依据：${viewModel.agency.modeReason}` : "",
                  ...viewModel.agency.highlights,
                ]),
              })}
              ${
                showAdvisorSections
                  ? `
                    ${renderReportDataCard({
                      tone: "confidence",
                      icon: "fa-gauge-high",
                      label: "预算核验",
                      title: "置信度与价格边界",
                      body: renderReportDataBudgetConfidence?.(viewModel),
                    })}
                    ${renderReportDataCard({
                      tone: "handoff",
                      icon: "fa-list-check",
                      label: "交付清单",
                      title: "顾问核验与下一步",
                      body: renderReportDataHandoffPanel?.(viewModel),
                    })}
                    ${renderReportDataCard({
                      tone: "governance",
                      icon: "fa-shield-halved",
                      label: "治理边界",
                      title: "人工确认与不可承诺项",
                      body: renderReportDataGovernancePanel?.(viewModel),
                    })}
                  `
                  : ""
              }
            </div>
            ${mapDigest ? `<div class="travel-report-map">${mapDigest}</div>` : ""}
            ${renderStructuredReportNextAction(reportData)}
          </div>
        `;
    }

    function buildReportDayEntries(lines = [], previewState = {}, expectedDayCount = 0) {
      const groups = extractReportDayGroups?.(lines);
      const planMap = new Map((previewState.dayPlans || []).map((plan) => [plan.dayNumber, plan]));
      const entries = [];
      groups?.forEach((group, index) => {
        const dayNumber =
          parseJourneyDayNumber?.(group.label) ||
          parseJourneyDayNumber?.(group.title) ||
          index + 1;
        const plan = planMap.get(dayNumber);
        entries.push({
          ...group,
          dayNumber,
          label: `Day ${dayNumber}`,
          title: group.title || plan?.title || "当天安排",
          lines: group.lines,
          plan,
          missing: false,
        });
      });

      return entries.sort((left, right) => left.dayNumber - right.dayNumber);
    }

    function renderReportDayTimeline(lines = [], options = {}) {
      const { previewState = {}, expectedDayCount = 0 } = options;
      const entries = buildReportDayEntries(lines, previewState, expectedDayCount);

      if (!entries.length) {
        if (/待补齐当天安排|这一天还没有|待补齐路线|行程明细待补充/u.test(lines.join(" "))) {
          return renderReportDailyNotReadyState?.();
        }
        return renderAssistantLines?.(lines);
      }

      return `<div class="travel-report-days">${entries
        .map(
          (day) => `
              <article class="travel-report-day ${day.missing ? "missing" : ""}">
                <div class="travel-report-day-badge">${formatInlineText?.(day.label)}</div>
                <div class="travel-report-day-main">
                  <h5>${formatInlineText?.(day.title)}</h5>
                  ${
                    day.lines.length
                      ? `<div class="travel-report-day-copy">${renderAssistantLines?.(
                          day.lines
                        )}</div>`
                      : ""
                  }
                </div>
              </article>
            `
        )
        .join("")}</div>`;
    }

    function renderReportSectionBody(tone, lines = [], options = {}) {
      if (tone === "daily") return renderReportDayTimeline(lines, options);
      if (tone === "budget") {
        return renderReportBudgetBreakdown?.(lines, options.combinedText || "");
      }
      return renderAssistantLines?.(lines);
    }

    function extractReportMetric(text = "", pattern, fallback = "待补充") {
      const match = String(text || "").match(pattern);
      return match?.[1] || fallback;
    }

    function renderTravelReportMapDigest(previewState = {}, routeLabel = "") {
      if (!previewState?.shouldRender) return "";
      return renderJourneyPreview?.(previewState);
    }

    function renderTravelReport(blocks, options = {}) {
      const expandedBlocks = expandStructuredTravelBlocks?.(blocks);
      const combinedText = expandedBlocks.join("\n\n");
      if (!hasTravelReportSignal?.(combinedText)) return null;

      const { summaryBlocks, sections } = extractTravelReportSections?.(expandedBlocks);
      if (sections.length < 2) return null;

      const cityPair =
        extractJourneyCityPair?.(combinedText) ||
        extractJourneyCityPairFromConversationTitle?.(getCurrentConversationTitle?.() || "");
      const routeLabel =
        cityPair?.origin && cityPair?.destination
          ? `${cityPair.origin} → ${cityPair.destination}`
          : cityPair?.destination || "专属旅程";
      const expectedDayCount = extractReportExpectedDayCount?.(combinedText);
      const dayCount = extractReportMetric(
        combinedText,
        /(\d+\s*天\s*\d*\s*[晚夜]?|[一二三四五六七八九十]\s*天\s*[一二三四五六七八九十]?\s*[晚夜]?)/u,
        "分日规划"
      );
      const budgetLabel =
        extractReportMetric(combinedText, /(?:总计|总预算|合计)[^\d]{0,12}([\d,.]+\s*元)/u, "") ||
        extractReportMetric(
          combinedText,
          /预算(?:希望|控制|范围)?[^\d]{0,12}([\d,.]+\s*元)/u,
          "预算已估算"
        );
      const summaryLines = filterReportSummaryLines?.(summaryBlocks.flat());
      const summaryHtml = summaryLines.length ? renderAssistantLines?.(summaryLines) : "";
      const previewState = buildJourneyPreviewState?.(summaryBlocks, sections);
      const mergedReportSections = dedupeTravelReportSections?.(
        mergeTravelReportDailySections?.(sections)
      );
      const nextActionHtml = renderTravelReportNextAction?.(mergedReportSections);
      const reportSections = mergedReportSections.filter(
        (section) => (section.reportTone || section.tone) !== "next"
      );
      const renderOptions = {
        combinedText,
        expectedDayCount,
        previewState,
        routeLabel,
      };
      const shouldRenderMap =
        !options?.suppressJourneyPreview &&
        (Boolean(renderTravelReportMapDigest(previewState, routeLabel)) ||
          shouldRenderJourneyPreviewBlock?.(previewState, sections));
      const textReportMode = inferTextTravelReportMode?.(combinedText);
      const textReportMeta = getReportPlanningModeMeta?.({
        agency_context: { mode: textReportMode },
      });

      return `
          <div class="travel-report travel-report--${escapeHtml?.(
            textReportMeta.tone
          )}" data-planning-mode="${escapeHtml?.(textReportMeta.mode)}">
            <div class="travel-report-hero">
              <div class="travel-report-kicker">
                <i class="fa-solid ${escapeHtml?.(textReportMeta.icon)}"></i> ${escapeHtml?.(
                  textReportMeta.label
                )}报告
              </div>
              <h3>${escapeHtml?.(routeLabel)}</h3>
              <p>${escapeHtml?.(textReportMeta.copy)}</p>
              <div class="travel-report-metrics">
                <span><i class="fa-solid fa-route"></i>${escapeHtml?.(routeLabel)}</span>
                <span><i class="fa-regular fa-calendar"></i>${escapeHtml?.(dayCount)}</span>
                <span><i class="fa-solid fa-wallet"></i>${escapeHtml?.(budgetLabel)}</span>
              </div>
              <div class="travel-report-actions">
                <button type="button" data-report-action="tweak">
                  <i class="fa-solid fa-pen-nib"></i> 继续微调
                </button>
                <button type="button" data-report-action="map">
                  <i class="fa-solid fa-map-location-dot"></i> 查看路线地图
                </button>
                <button type="button" data-report-action="copy-summary">
                  <i class="fa-solid fa-copy"></i> 复制摘要
                </button>
                <button type="button" data-report-action="export">
                  <i class="fa-solid fa-file-export"></i> 导出报告
                </button>
              </div>
            </div>
            ${summaryHtml ? `<div class="travel-report-summary">${summaryHtml}</div>` : ""}
            <div class="travel-report-grid">
              ${reportSections
                .filter((section) => (section.reportTone || section.tone) !== "map")
                .map((section) => {
                  const sectionTone = section.reportTone || section.tone;
                  const sectionTitle =
                    sectionTone === "budget"
                      ? "费用说明"
                      : sectionTone === "service"
                        ? "涵盖服务"
                        : section.title;
                  const sectionLabel =
                    sectionTone === "budget"
                      ? "预算拆分"
                      : sectionTone === "service"
                        ? "服务范围"
                        : section.reportLabel || section.title;
                  return `
                    <section class="travel-report-card ${section.reportTone || section.tone}">
                      <div class="travel-report-card-head">
                        <span class="travel-report-card-icon">
                          <i class="fa-solid ${section.icon}"></i>
                        </span>
                        <div>
                          <div class="travel-report-card-label">${escapeHtml?.(sectionLabel)}</div>
                          <h4>${escapeHtml?.(sectionTitle)}</h4>
                        </div>
                      </div>
                      <div class="travel-report-card-body">${renderReportSectionBody(
                        sectionTone,
                        section.rawLines,
                        renderOptions
                      )}</div>
                    </section>
                  `;
                })
                .join("")}
            </div>
            ${
              shouldRenderMap
                ? `<div class="travel-report-map">${renderTravelReportMapDigest(
                    previewState,
                    routeLabel
                  )}</div>`
                : ""
            }
            ${nextActionHtml}
          </div>
        `;
    }

    return {
      renderReportSectionBody,
      renderTravelReportFromData,
      renderTravelReport,
    };
  }

  global.ZhiXingReportRenderer = {
    createReportRenderer,
  };
})(window);
