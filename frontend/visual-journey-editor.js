(function (global) {
  function createVisualJourneyEditor({
    escapeHtml,
    cleanJourneyLocationValue,
    normalizeJourneyPoiAsStop,
  } = {}) {
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

    function normalizeVisualRouteMode(value = "") {
      const raw = String(value || "").toLowerCase();
      if (/walk|walking|步行/.test(raw)) return "walking";
      if (/bus|公交|metro|subway|地铁|transit/.test(raw)) return "transit";
      if (/taxi|ride|打车|网约车/.test(raw)) return "taxi";
      if (/drive|driving|car|驾车|自驾/.test(raw)) return "taxi";
      if (/train|rail|火车|高铁/.test(raw)) return "rail";
      if (/flight|air|航班|飞机/.test(raw)) return "flight";
      return raw || "taxi";
    }

    function getVisualRouteModeLabel(mode = "") {
      const normalized = normalizeVisualRouteMode(mode);
      if (normalized === "walking") return "步行";
      if (normalized === "transit") return "公交/地铁";
      if (normalized === "taxi") return "打车";
      if (normalized === "rail") return "铁路";
      if (normalized === "flight") return "航班";
      return "交通";
    }

    function normalizeVisualRouteVerificationStatus(segment = {}) {
      const statusText = [
        segment.verification_status,
        segment.confidence,
        segment.source,
        segment.verification_note,
      ]
        .filter(Boolean)
        .join(" ");
      if (/amap|verified|已核验|高德/i.test(statusText) && !/待/.test(statusText)) {
        return "verified";
      }
      if (/estimated|估算/i.test(statusText)) {
        return "estimated";
      }
      return "needs_live_route";
    }

    function visualRouteDurationMatchesMode(mode = "", durationText = "") {
      const text = String(durationText || "").toLowerCase();
      if (!text) return true;
      const normalized = normalizeVisualRouteMode(mode);
      const explicitModes = [];
      if (/walk|walking|步行/.test(text)) explicitModes.push("walking");
      if (/bus|公交|metro|subway|地铁|transit/.test(text)) explicitModes.push("transit");
      if (/taxi|ride|打车|网约车|drive|driving|驾车|自驾/.test(text)) {
        explicitModes.push("taxi");
      }
      if (/train|rail|火车|高铁/.test(text)) explicitModes.push("rail");
      if (/flight|air|航班|飞机/.test(text)) explicitModes.push("flight");
      return !explicitModes.length || explicitModes.includes(normalized);
    }

    function buildVisualRouteModeAlternatives(segment = {}) {
      const rawAlternatives = Array.isArray(segment.alternatives)
        ? segment.alternatives
        : [];
      const baseDuration = String(segment.duration_text || "").trim();
      const baseMode = normalizeVisualRouteMode(
        segment.selected_mode ||
          segment.mode ||
          segment.transport_mode ||
          segment.duration_text ||
          segment.source ||
          ""
      );
      const canReuseBaseDuration =
        Boolean(baseDuration) &&
        !/待|unknown/i.test(baseDuration) &&
        visualRouteDurationMatchesMode(baseMode, baseDuration);
      const durationForMode = (mode, fallback) =>
        canReuseBaseDuration && baseMode === mode ? baseDuration : fallback;
      const fallbackAlternatives = rawAlternatives.length
        ? rawAlternatives
        : [
            {
              mode: "taxi",
              duration_text: durationForMode("taxi", "约10-20分钟"),
              cost_text: "费用待核验",
              reason: "省体力，适合赶时间或带行李",
            },
            {
              mode: "transit",
              duration_text: durationForMode("transit", "约25-40分钟"),
              cost_text: "约2-8元",
              reason: "更省预算，班次和换乘待核验",
            },
            {
              mode: "walking",
              duration_text: durationForMode("walking", "约30-45分钟"),
              cost_text: "0元",
              reason: "适合短距离慢游，体力消耗更高",
            },
          ];
      const seen = new Set();
      return fallbackAlternatives
        .map((option) => {
          const mode = normalizeVisualRouteMode(option.mode || option.transport_mode || "");
          return {
            mode,
            label: option.label || getVisualRouteModeLabel(mode),
            durationText: option.duration_text || option.duration || "时间待核验",
            costText: option.cost_text || option.cost || "费用待核验",
            reason: option.reason || option.note || "适配性待核验",
          };
        })
        .filter((option) => {
          if (!option.mode || seen.has(option.mode)) return false;
          seen.add(option.mode);
          return true;
        })
        .slice(0, 3)
        .map((option) => ({
          ...option,
          metricText: [option.durationText, option.costText].filter(Boolean).join(" · "),
        }));
    }

    function getVisualRouteSegmentView(segment = {}) {
      const rawMode = String(
        segment.selected_mode ||
          segment.mode ||
          segment.transport_mode ||
          segment.duration_text ||
          segment.source ||
          ""
      );
      const selectedMode = normalizeVisualRouteMode(rawMode);
      const alternatives = buildVisualRouteModeAlternatives(segment);
      const selectedAlternative =
        alternatives.find((option) => option.mode === selectedMode) || alternatives[0];
      const modeText = selectedAlternative?.label || getVisualRouteModeLabel(selectedMode);
      const metricText = [segment.distance_text, segment.duration_text]
        .filter(Boolean)
        .join(" · ");
      const confidenceText = [
        segment.confidence,
        segment.source,
        segment.verification_status,
        segment.verification_label,
        segment.verification_note,
      ]
        .filter(Boolean)
        .join(" ");
      const isVerified = /amap|高德|verified|已核验/i.test(confidenceText);
      const isEstimated = /estimated|估算/i.test(confidenceText);
      const metricTextIsPending =
        !metricText || /待|needs|unknown/i.test(metricText);
      const metricMatchesMode = visualRouteDurationMatchesMode(
        selectedMode,
        segment.duration_text || ""
      );
      const isPending =
        metricTextIsPending ||
        !metricMatchesMode ||
        /needs|unknown/i.test(confidenceText);
      const displayMetricText =
        metricTextIsPending
          ? "待高德路线核验"
          : metricMatchesMode
          ? metricText
          : selectedAlternative?.metricText || "距离/用时待核验";
      return {
        selectedMode,
        modeText,
        metricText: displayMetricText,
        reasonText: selectedAlternative?.reason || "交通方式待核验",
        alternatives,
        isModeLocked: Boolean(segment.locked_by_user || segment.mode_locked),
        tone:
          metricMatchesMode && isVerified
            ? "ready"
            : metricMatchesMode && isEstimated
            ? "estimated"
            : isPending
            ? "pending"
            : "",
        statusText:
          metricMatchesMode && isVerified
            ? "已核验"
            : metricMatchesMode && isEstimated
            ? "估算"
            : "待核验",
      };
    }

    function renderVisualRouteModeOptions(view = {}, segmentMeta = "") {
      if (!Array.isArray(view.alternatives) || !view.alternatives.length) return "";
      return `
          <details class="visual-route-mode-options" data-route-mode-options="true">
            <summary>
              <span>交通候选</span>
              <strong>${escapeHtml(view.isModeLocked ? "已锁定" : "可切换")}</strong>
            </summary>
            <div class="visual-route-mode-menu">
              ${view.alternatives
                .map(
                  (option) => `
                    <button
                      type="button"
                      class="${option.mode === view.selectedMode ? "is-selected" : ""}"
                      data-journey-edit-action="select-segment-mode"
                      data-map-day-segment="${escapeHtml(segmentMeta)}"
                      data-segment-mode="${escapeHtml(option.mode)}"
                      aria-pressed="${option.mode === view.selectedMode ? "true" : "false"}"
                    >
                      <strong>${escapeHtml(option.label)}</strong>
                      <span>${escapeHtml(option.metricText)}</span>
                      <small>${escapeHtml(option.reason)}</small>
                    </button>
                  `
                )
                .join("")}
              <button
                class="visual-route-mode-lock ${view.isModeLocked ? "is-locked" : ""}"
                type="button"
                data-journey-edit-action="toggle-segment-lock"
                data-map-day-segment="${escapeHtml(segmentMeta)}"
              >
                ${escapeHtml(view.isModeLocked ? "解除锁定" : "锁定当前")}
              </button>
            </div>
          </details>
        `;
    }

    function renderVisualRouteSegment(segment = {}, fromStop = {}, toStop = {}, segmentMeta = "") {
      const view = getVisualRouteSegmentView(segment);
      const fromName = cleanJourneyLocationValue(fromStop.name || segment.from_name || "上一站");
      const toName = cleanJourneyLocationValue(toStop.name || segment.to_name || "下一站");
      return `
          <div class="visual-route-segment ${escapeHtml(view.tone)}${
          view.isModeLocked ? " is-mode-locked" : ""
        }" data-route-segment="true" data-map-day-segment="${escapeHtml(segmentMeta)}">
            <span class="visual-route-segment-line" aria-hidden="true"></span>
            <div class="visual-route-segment-main">
              <strong>${escapeHtml(view.modeText)}</strong>
              <small>${escapeHtml(`${fromName} → ${toName}`)}</small>
              <small class="visual-route-segment-reason">${escapeHtml(view.reasonText)}</small>
            </div>
            <em>${escapeHtml(view.metricText)}</em>
            <span class="visual-route-segment-status">${escapeHtml(view.statusText)}</span>
            ${renderVisualRouteModeOptions(view, segmentMeta)}
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
        return { tone: "pending", label: "预约核验", requiresCheck: true };
      }
      if (/门票|票价|香花券|购票/u.test(combined)) {
        return { tone: "pending", label: "票务核验", requiresCheck: true };
      }
      if (/游船|体验|演出|项目/u.test(combined)) {
        return { tone: "pending", label: "活动核验", requiresCheck: true };
      }
      if (/餐饮|茶饮|购物|消费自理|自理/u.test(combined)) {
        return { tone: "neutral", label: "消费自理", requiresCheck: false };
      }
      if (/免费|无需门票|免票/u.test(combined)) {
        return { tone: "ready", label: "无需门票", requiresCheck: false };
      }
      if (/待核验|待确认|待定|参考/u.test(combined)) {
        return { tone: "pending", label: "待核验", requiresCheck: true };
      }
      return { tone: "pending", label: "行前确认", requiresCheck: true };
    }

    function getVisualStopDurationValue(stop = {}) {
      const value = Number(stop.duration_minutes);
      return Number.isFinite(value) && value > 0 ? String(Math.round(value)) : "";
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

    function renderVisualRouteTimeEditor(stop = {}, stopMeta = "", stopLabel = "") {
      const timeValue = stop.time_range || stop.suggested_time || "";
      const durationValue = getVisualStopDurationValue(stop);
      return `
          <details class="visual-route-time-editor" data-route-time-editor="true">
            <summary
              aria-label="${escapeHtml(`调整时间：${stopLabel}`)}"
              title="调整时间"
            >
              <span>时间</span>
            </summary>
            <div class="visual-route-time-fields">
              <label>
                <span>时间段</span>
                <input
                  type="text"
                  name="time_range"
                  maxlength="40"
                  value="${escapeHtml(timeValue)}"
                  placeholder="例如 10:00-12:00"
                />
              </label>
              <label>
                <span>停留分钟</span>
                <input
                  type="number"
                  name="duration_minutes"
                  min="1"
                  max="1440"
                  step="5"
                  value="${escapeHtml(durationValue)}"
                  placeholder="120"
                />
              </label>
              <button
                class="visual-route-time-save"
                type="button"
                data-journey-edit-action="save-time"
                data-map-day-stop="${escapeHtml(stopMeta)}"
              >
                保存
              </button>
            </div>
          </details>
        `;
    }

    function buildVisualRouteCheckTasks(dayPlans = []) {
      const tasks = [];
      (Array.isArray(dayPlans) ? dayPlans : []).forEach((day, dayIndex) => {
        const dayLabel = day.label || `Day ${dayIndex + 1}`;
        const stops = Array.isArray(day.stops) ? day.stops : [];
        const segments = Array.isArray(day.segments) ? day.segments : [];
        stops.forEach((stop, stopIndex) => {
          const stopLabel = cleanJourneyLocationValue(stop.name || "地点待确认");
          const taskTitle = `${dayLabel} · ${stopIndex + 1}. ${stopLabel}`;
          const timeText = String(stop.time_range || stop.suggested_time || "").trim();
          const durationValue = Number(stop.duration_minutes);
          if (!timeText || !Number.isFinite(durationValue) || durationValue <= 0) {
            tasks.push({
              tone: "pending",
              kind: "时间",
              title: taskTitle,
              detail: !timeText
                ? "补充开始时段或时间范围，便于后续排冲突。"
                : "补充建议停留分钟，便于估算当天节奏。",
            });
          }
          const ticketStatus = getVisualStopTicketStatus(stop);
          if (ticketStatus.requiresCheck) {
            const detail = [
              stop.reservation_note,
              stop.estimated_cost,
              stop.verification_note,
            ]
              .filter(Boolean)
              .join(" · ");
            tasks.push({
              tone: ticketStatus.tone,
              kind: ticketStatus.label,
              title: taskTitle,
              detail: detail || "出发前确认开放、预约、票价和现场规则。",
            });
          }
        });
        segments.forEach((segment, segmentIndex) => {
          const view = getVisualRouteSegmentView(segment);
          if (view.statusText === "已核验") return;
          const fromStop = stops[segmentIndex] || {};
          const toStop = stops[segmentIndex + 1] || {};
          tasks.push({
            tone: view.tone || "pending",
            kind: "路线",
            title: `${dayLabel} · ${cleanJourneyLocationValue(
              fromStop.name || segment.from_name || "上一站"
            )} → ${cleanJourneyLocationValue(toStop.name || segment.to_name || "下一站")}`,
            detail: `${view.modeText} · ${view.metricText}`,
          });
        });
      });
      return tasks.slice(0, 10);
    }

    function renderVisualRouteCheckList(dayPlans = []) {
      const tasks = buildVisualRouteCheckTasks(dayPlans);
      return `
          <section class="visual-route-checklist" data-route-checklist="true">
            <div class="visual-route-checklist-head">
              <div>
                <span>行前核验清单</span>
                <strong>只记录待确认事项，不代表支付或预订完成</strong>
              </div>
              <small>${escapeHtml(tasks.length ? `${tasks.length} 项待核验` : "已清爽")}</small>
            </div>
            ${
              tasks.length
                ? `<div class="visual-route-checklist-list">
                    ${tasks
                      .map(
                        (task) => `
                          <article class="visual-route-check-task ${escapeHtml(
                            task.tone || "pending"
                          )}" data-route-check-task="true">
                            <span>${escapeHtml(task.kind)}</span>
                            <div>
                              <strong>${escapeHtml(task.title)}</strong>
                              <small>${escapeHtml(task.detail)}</small>
                            </div>
                          </article>
                        `
                      )
                      .join("")}
                  </div>`
                : `<p class="visual-route-checklist-empty">当前没有明显待核验项；真实开放、交通和票务仍建议出发前再确认。</p>`
            }
          </section>
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
            ${renderVisualRouteCheckList(dayPlans)}
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
                                            ${renderVisualRouteTimeEditor(stop, stopMeta, stopLabel)}
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
                                              stops[stopIndex + 1],
                                              `${dayKey}:${stopIndex}`
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

    return {
      getVisualRouteSegmentView,
      normalizeVisualRouteVerificationStatus,
      renderVisualJourneyDayEditor,
      renderVisualJourneyStats,
    };
  }

  global.ZhiXingVisualJourneyEditor = {
    createVisualJourneyEditor,
  };
})(window);
