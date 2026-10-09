(function (global) {
  function createPlannerControls({
    document,
    state,
    localStorage,
    composerDraftKey,
    plannerDraftKey,
    plannerCollapseKey,
    readDraftStorage,
    writeDraftStorage,
    clearDraftStorage,
    setRuntimeStatus,
    escapeHtml,
    escapeAttribute,
  }) {
    function persistComposerDraft(options = {}) {
      const input = document.getElementById("chatInput");
      if (!input) return;
      writeDraftStorage(composerDraftKey, input.value || "", options);
    }

    function readPlannerFields() {
      return {
        origin: document.getElementById("plannerOrigin").value.trim(),
        destination: document.getElementById("plannerDestination").value.trim(),
        date: document.getElementById("plannerDate").value.trim(),
        days: document.getElementById("plannerDays").value.trim(),
        travelers: document.getElementById("plannerTravelers").value.trim(),
        budget: document.getElementById("plannerBudget").value.trim(),
        transport: document.getElementById("plannerTransport").value.trim(),
        stay: document.getElementById("plannerStay").value.trim(),
        style: document.getElementById("plannerStyle").value.trim(),
      };
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

    function persistPlannerDraft() {
      const payload = {
        origin: document.getElementById("plannerOrigin")?.value || "",
        destination: document.getElementById("plannerDestination")?.value || "",
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

    function renderSuggestionButton(label, text) {
      return `
        <button
          class="suggestion-btn"
          type="button"
          data-suggestion-text="${escapeAttribute(text)}"
        >${escapeHtml(label)}</button>
      `;
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

    return {
      persistComposerDraft,
      persistPlannerDraft,
      restoreDrafts,
      resetComposerDraft,
      applyPlannerPanelState,
      togglePlannerPanel,
      getWelcomeMarkup,
      updatePlannerSummary,
      updatePlannerAssistStrip,
      appendToComposer,
      applySuggestion,
      appendPlannerStyle,
      fillPlannerTemplate,
      readPlannerFields,
      composePlannerDraft,
      resetPlannerDraft,
      resetConversationDrafts,
    };
  }

  global.ZhiXingPlannerControls = {
    createPlannerControls,
  };
})(window);
