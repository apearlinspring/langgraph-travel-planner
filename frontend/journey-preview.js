(function (global) {
  function createJourneyPreview({
    escapeHtml,
    summarizeJourneyTransportMetric,
    summarizeJourneyStayMetric,
    isLowValueJourneyMetric,
    cleanJourneyLocationValue,
    truncateJourneyNote,
    renderJourneyAtlas,
    extractJourneyCityPairFromConversationTitle,
    getCurrentConversationTitle,
    extractJourneyCityPair,
    extractJourneyPrimaryOrigin,
    extractJourneyPrimaryDestination,
    splitJourneyFragments,
    extractJourneyHighlights,
    buildJourneyHighlightCards,
    extractJourneyRhythm,
    extractJourneyDayPlans,
    hasJourneyClarificationSignal,
    hasJourneyPlanSignal,
  } = {}) {
    function renderJourneyPreview(previewState) {
      if (!previewState?.shouldRender) {
        return "";
      }
      const {
        cityPair,
        destinationSection,
        transportSection,
        staySection,
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
        ? [overviewSection.title, ...overviewSection.rawLines]
            .join(" ")
            .replace(/\s+/g, " ")
            .trim()
        : "";
      const conversationTitlePair = extractJourneyCityPairFromConversationTitle(
        getCurrentConversationTitle() || ""
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

    return {
      renderJourneyPreview,
      buildJourneyPreviewState,
      shouldRenderJourneyPreviewBlock,
    };
  }

  global.ZhiXingJourneyPreview = {
    createJourneyPreview,
  };
})(window);
