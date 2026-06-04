(function (global) {
  function createGovernanceProgress(options = {}) {
    const parseJourneyChineseDayNumber =
      typeof options.parseJourneyChineseDayNumber === "function"
        ? options.parseJourneyChineseDayNumber
        : (value = "") => Number(value) || 0;
    const extractJourneyCityPair =
      typeof options.extractJourneyCityPair === "function"
        ? options.extractJourneyCityPair
        : () => null;
    const getStatusLabel =
      typeof options.getStatusLabel === "function"
        ? options.getStatusLabel
        : (status = "") => status || "待确认";
    const redactClientText =
      typeof options.redactClientText === "function"
        ? options.redactClientText
        : (value = "", maxLength = 180) => {
            const text = String(value || "").trim();
            return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
          };

    function normalizeObservabilityField(value = "", fallback = "pending_confirmation") {
      const text = String(value || "").trim();
      if (!text || text.toLowerCase() === "unknown") return fallback;
      return text;
    }

    function isConfirmedPlanningMode(value = "") {
      return ["agency_plan", "free_planning"].includes(String(value || "").trim());
    }

    function mergeProgressFactItems(previous = [], incoming = []) {
      const byKey = new Map();
      const order = [];
      [...(Array.isArray(previous) ? previous : []), ...(Array.isArray(incoming) ? incoming : [])]
        .forEach((item) => {
          if (!item || typeof item !== "object") return;
          const key = String(item.key || item.label || "").trim();
          const value = item.value;
          if (!key || value === undefined || value === null || value === "") return;
          if (!byKey.has(key)) order.push(key);
          byKey.set(key, item);
        });
      return order.map((key) => byKey.get(key));
    }

    function mergeProgressStringItems(previous = [], incoming = []) {
      const merged = [];
      const seen = new Set();
      [...(Array.isArray(previous) ? previous : []), ...(Array.isArray(incoming) ? incoming : [])]
        .forEach((item) => {
          const marker = typeof item === "string"
            ? item
            : item?.key || item?.label || item?.value || JSON.stringify(item || "");
          if (!marker || seen.has(marker)) return;
          seen.add(marker);
          merged.push(item);
        });
      return merged;
    }

    function mergeGovernanceProgressSnapshots(previous = {}, incoming = {}) {
      if (!previous || typeof previous !== "object") previous = {};
      if (!incoming || typeof incoming !== "object") incoming = {};
      if (!Object.keys(previous).length) return { ...incoming };
      if (!Object.keys(incoming).length) return { ...previous };

      const merged = { ...previous, ...incoming };
      const previousMode = previous.planning_mode || "";
      const incomingMode = incoming.planning_mode || "";
      if (isConfirmedPlanningMode(previousMode) && !isConfirmedPlanningMode(incomingMode)) {
        merged.planning_mode = previousMode;
      }
      const previousWorkflow = previous.active_workflow || "";
      const incomingWorkflow = incoming.active_workflow || "";
      if (
        isConfirmedPlanningMode(previousWorkflow) &&
        !isConfirmedPlanningMode(incomingWorkflow)
      ) {
        merged.active_workflow = previousWorkflow;
      }
      if (previous.agency_step && !incoming.agency_step) {
        merged.agency_step = previous.agency_step;
      }
      const facts = mergeProgressFactItems(
        previous.confirmed_facts,
        incoming.confirmed_facts
      );
      if (facts.length) merged.confirmed_facts = facts;
      ["long_term_preferences", "current_trip_preferences", "pending_items"].forEach((key) => {
        const values = mergeProgressStringItems(previous[key], incoming[key]);
        if (values.length) merged[key] = values;
      });
      return merged;
    }

    function factItem(key, label, value) {
      if (value === undefined || value === null || value === "" || value === "待确认") {
        return null;
      }
      return { key, label, value: String(value) };
    }

    function normalizeOptimisticTripDate(monthText = "", dayText = "") {
      const month = Number(monthText);
      const day = Number(dayText);
      if (!month || !day) return "";
      const now = new Date();
      let year = now.getFullYear();
      const candidate = new Date(year, month - 1, day);
      if (candidate.getTime() < new Date(year, now.getMonth(), now.getDate()).getTime()) {
        year += 1;
      }
      return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }

    function parseOptimisticTripFactsFromText(text = "") {
      const normalized = String(text || "").replace(/\s+/g, " ").trim();
      if (!normalized) return {};
      const facts = {};
      const directionalPatterns = [
        /从\s*([\u4e00-\u9fa5A-Za-z]{2,12})\s*(?:出发)?\s*(?:去|到|前往)\s*([\u4e00-\u9fa5A-Za-z]{2,12})/u,
        /([\u4e00-\u9fa5A-Za-z]{2,12})\s*(?:->|→|到)\s*([\u4e00-\u9fa5A-Za-z]{2,12})/u,
      ];
      const routeMatch = directionalPatterns
        .map((pattern) => normalized.match(pattern))
        .find(Boolean);
      if (routeMatch) {
        facts.departure_city = routeMatch[1];
        facts.destination = routeMatch[2];
      } else {
        const destinationMatch = normalized.match(/(?:想去|去|到|前往)\s*([\u4e00-\u9fa5A-Za-z]{2,12})(?:玩|旅游|旅行|休闲|度假)?/u);
        if (destinationMatch) facts.destination = destinationMatch[1];
      }
      const dateMatch = normalized.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?\s*(?:出发)?/u);
      if (dateMatch) {
        facts.departure_date = normalizeOptimisticTripDate(dateMatch[1], dateMatch[2]);
      }
      const dayMatch = normalized.match(/([一二两三四五六七八九十\d]+)\s*天(?:左右|以内|以上)?/u);
      if (dayMatch) {
        const days = /^\d+$/.test(dayMatch[1])
          ? Number(dayMatch[1])
          : parseJourneyChineseDayNumber(dayMatch[1]);
        if (days) facts.travel_days = days;
      }
      const peopleMatch = normalized.match(/([一二两三四五六七八九十\d]+)\s*(?:个)?(?:人|成人|大人)/u);
      if (peopleMatch) {
        const people = /^\d+$/.test(peopleMatch[1])
          ? Number(peopleMatch[1])
          : parseJourneyChineseDayNumber(peopleMatch[1]);
        if (people) facts.adult_count = people;
      }
      const budgetMatch = normalized.match(/((?:预算\s*(?:人均|每人)?|(?:人均|每人)\s*预算?)\s*(?:约|大概|左右)?\s*\d+(?:\.\d+)?\s*(?:万|千)?\s*元?(?:左右|以内|上下)?)/u);
      if (budgetMatch) facts.budget_text = budgetMatch[1].replace(/\s+/g, "");
      return facts;
    }

    function progressSnapshotFromFastSplit(fastSplit = {}) {
      const facts = fastSplit.facts || fastSplit || {};
      if (!facts || typeof facts !== "object") return {};
      const confirmed = [
        factItem("departure_city", "出发地", facts.departure_city),
        factItem("destination", "目的地", facts.destination),
        factItem("departure_date", "出发时间", facts.departure_date),
        factItem(
          "travel_days",
          "行程天数",
          facts.travel_days ? `${facts.travel_days}天` : ""
        ),
        factItem("adult_count", "人数", facts.adult_count ? `${facts.adult_count}人` : ""),
        factItem("budget_text", "预算", facts.budget_text),
      ].filter(Boolean);
      return {
        version: "travel_progress_snapshot.v1",
        planning_mode:
          facts.planning_mode || fastSplit.planning_mode || "pending_confirmation",
        active_workflow:
          facts.active_workflow || facts.planning_mode || fastSplit.active_workflow || "",
        agency_step: facts.agency_step || fastSplit.agency_step || "",
        confirmed_facts: confirmed,
      };
    }

    function progressSnapshotFromReportData(reportData = {}) {
      if (!reportData || typeof reportData !== "object") return {};
      const overview = reportData.overview || {};
      const agencyContext = reportData.agency_context || {};
      const cityPair = extractJourneyCityPair(overview.route_label || "");
      const budget = reportData.budget || {};
      const budgetValue =
        budget.total || budget.per_person
          ? [
              budget.total ? `总计约${budget.total}元` : "",
              budget.per_person ? `人均约${budget.per_person}元` : "",
            ].filter(Boolean).join("，")
          : "";
      const confirmed = [
        factItem("departure_city", "出发地", cityPair?.origin),
        factItem("destination", "目的地", cityPair?.destination),
        factItem("travel_days", "行程天数", overview.duration),
        factItem("adult_count", "人数", overview.people),
        factItem("budget_text", "预算", budgetValue),
      ].filter(Boolean);
      return {
        version: "travel_progress_snapshot.v1",
        planning_mode: agencyContext.mode || reportData.planning_mode || "",
        active_workflow: agencyContext.mode || reportData.active_workflow || "",
        agency_step: agencyContext.mode === "agency_plan" ? "agency_feedback" : "",
        confirmed_facts: confirmed,
        long_term_preferences: Array.isArray(overview.travel_styles)
          ? overview.travel_styles
          : [],
      };
    }

    function progressSnapshotFromObservability(event = {}) {
      const observability = event.observability || event;
      if (!observability || typeof observability !== "object") return {};
      const snapshot = {
        ...(observability.progress_snapshot || {}),
      };
      if (isConfirmedPlanningMode(observability.planning_mode)) {
        snapshot.planning_mode = observability.planning_mode;
        snapshot.active_workflow = snapshot.active_workflow || observability.planning_mode;
      }
      if (
        observability.step &&
        String(observability.step).startsWith("agency_") &&
        !snapshot.agency_step
      ) {
        snapshot.agency_step = observability.step;
      }
      return snapshot;
    }

    function normalizeTurnObservability(event = {}, mergedProgress = {}) {
      const observability = event.observability || event;
      if (!observability || typeof observability !== "object") return null;
      const step = normalizeObservabilityField(
        observability.step || observability.current_step,
        "requirement_collection"
      );
      let planningMode = normalizeObservabilityField(
        observability.planning_mode,
        mergedProgress.planning_mode || "pending_confirmation"
      );
      if (!isConfirmedPlanningMode(planningMode) && isConfirmedPlanningMode(mergedProgress.planning_mode)) {
        planningMode = mergedProgress.planning_mode;
      }
      const status = normalizeObservabilityField(observability.status, "completed");
      const degradationStatus = normalizeObservabilityField(
        observability.degradation_status,
        "ok"
      );
      return {
        turnId: redactClientText(observability.turn_id || "", 80),
        status,
        statusLabel: getStatusLabel(status),
        step,
        stepLabel: getStatusLabel(step),
        planningMode,
        planningModeLabel: getStatusLabel(planningMode),
        firstTokenSeconds: observability.first_token_seconds,
        totalElapsedSeconds: observability.total_elapsed_seconds,
        toolCallCount: Number(observability.tool_call_count || 0),
        toolFailureCount: Number(observability.tool_failure_count || 0),
        fallbackCount: Number(observability.fallback_count || 0),
        degradationStatus,
        degradationLabel: getStatusLabel(degradationStatus),
        estimatedTotalTokens: Number(observability.estimated_total_tokens || 0),
        progressSnapshot: mergedProgress,
      };
    }

    return {
      normalizeObservabilityField,
      isConfirmedPlanningMode,
      mergeGovernanceProgressSnapshots,
      parseOptimisticTripFactsFromText,
      progressSnapshotFromFastSplit,
      progressSnapshotFromReportData,
      progressSnapshotFromObservability,
      normalizeTurnObservability,
    };
  }

  global.ZhiXingGovernanceProgress = {
    createGovernanceProgress,
  };
})(window);
