(function (global) {
  function createReportTextStructured({
    escapeHtml,
    expandStructuredTravelBlocks,
    isEmbeddedSectionHeading,
    getTravelSectionMeta,
    inferSectionMetaFromBody,
    normalizeSectionTitle,
    renderAssistantLines,
    dedupeTravelReportSections,
    buildJourneyPreviewState,
    shouldRenderJourneyPreviewBlock,
    filterReportSummaryLines,
    renderJourneyPreview,
    resolveTravelCardMapFocus,
    reportBudget,
  } = {}) {
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

    return {
      renderStructuredTravelPlan,
    };
  }

  global.ZhiXingReportTextStructured = {
    createReportTextStructured,
  };
})(window);
