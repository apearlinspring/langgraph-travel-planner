(function (global) {
  function createReportDataItinerary({
    escapeHtml,
    cleanJourneyLocationValue,
    renderReportDataList,
    normalizeRouteMapDayPoints,
    normalizeReportRouteSegmentsForDay,
    getVisualRouteSegmentView,
  } = {}) {
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

    function renderReportDataRouteSegments(segments = []) {
      const normalized = (Array.isArray(segments) ? segments : []).filter(
        (segment) => segment && typeof segment === "object"
      );
      if (!normalized.length) return "";
      return `
          <div class="travel-report-route-segments">
            ${normalized
              .slice(0, 4)
              .map((segment) => {
                const view = getVisualRouteSegmentView(segment);
                const alternatives = (view.alternatives || [])
                  .filter((option) => option.mode !== view.selectedMode)
                  .map((option) => option.label)
                  .filter(Boolean)
                  .slice(0, 2)
                  .join(" / ");
                const routeText = `${cleanJourneyLocationValue(
                  segment.from_name || "上一站"
                )} → ${cleanJourneyLocationValue(segment.to_name || "下一站")}`;
                return `
                  <div class="travel-report-route-segment ${escapeHtml(view.tone || "pending")}">
                    <div>
                      <strong>${escapeHtml(view.modeText)}</strong>
                      <span>${escapeHtml(routeText)}</span>
                    </div>
                    <small>${escapeHtml(view.metricText)}</small>
                    <em>${escapeHtml(view.statusText)}${segment.locked_by_user ? " · 已锁定" : ""}</em>
                    ${
                      alternatives
                        ? `<p>候选：${escapeHtml(alternatives)}</p>`
                        : ""
                    }
                  </div>
                `;
              })
              .join("")}
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
                const routeSegments = normalizeReportRouteSegmentsForDay(
                  routeMapDay,
                  route,
                  day,
                  routePoints.map((point) => point.name).filter(Boolean)
                );
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
                      ${renderReportDataRouteSegments(routeSegments)}
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

    return {
      renderReportDailyNotReadyState,
      renderReportDataDailyItinerary,
    };
  }

  global.ZhiXingReportDataItinerary = {
    createReportDataItinerary,
  };
})(window);
