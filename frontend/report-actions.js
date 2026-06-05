(function (global) {
  function createReportActions(deps = {}) {
    const {
      appendToComposer,
      setRuntimeStatus,
      showToast,
      exportTravelReport,
      focusJourneyMapTarget,
      getJourneyMapEntry,
      setJourneyMapDaySelection,
    } = deps;

    function cleanReportText(value = "") {
      return String(value || "").replace(/\s+/g, " ").trim();
    }

    function limitReportText(value = "", maxLength = 120) {
      const text = cleanReportText(value);
      if (text.length <= maxLength) return text;
      return `${text.slice(0, maxLength - 1)}…`;
    }

    function getReportCardDigest(card) {
      const label = cleanReportText(
        card.querySelector(".travel-report-card-label")?.textContent
      );
      const title = cleanReportText(card.querySelector("h4")?.textContent);
      const body = limitReportText(card.querySelector(".travel-report-card-body")?.textContent);
      const heading = [label, title].filter(Boolean).join(" - ");
      return [heading, body].filter(Boolean).join("：");
    }

    function buildReportShareSummary(report) {
      const title =
        cleanReportText(report.querySelector(".travel-report-hero h3")?.textContent) ||
        "知行旅游报告";
      const metrics = Array.from(report.querySelectorAll(".travel-report-metrics span"))
        .map((node) => cleanReportText(node.textContent))
        .filter(Boolean)
        .slice(0, 4);
      const cardDigests = Array.from(report.querySelectorAll(".travel-report-card"))
        .map((card) => getReportCardDigest(card))
        .filter(Boolean)
        .slice(0, 4);
      const lines = [`知行旅游报告：${title}`];
      if (metrics.length) lines.push(`关键要素：${metrics.join(" | ")}`);
      if (cardDigests.length) {
        lines.push("核心内容：");
        cardDigests.forEach((digest) => lines.push(`- ${digest}`));
      }
      lines.push("待核验项：出发前请重新确认交通、住宿、门票/体验、天气、排队预约和价格库存。");
      lines.push("交付边界：本摘要不代表真实支付、预订、出票、锁价或履约成功。");
      return lines.join("\n");
    }

    function copyTextWithFallback(text) {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "0";
      document.body.appendChild(textarea);
      try {
        textarea.focus();
        textarea.select();
        textarea.setSelectionRange?.(0, textarea.value.length);
        if (!document.execCommand?.("copy")) {
          throw new Error("document.execCommand('copy') returned false");
        }
      } finally {
        textarea.remove();
      }
    }

    async function copyTextToClipboard(text) {
      if (!text) throw new Error("Nothing to copy");
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          return;
        } catch (error) {
          // 本地 file:// 或权限不足时继续走传统复制兜底。
        }
      }
      copyTextWithFallback(text);
    }

    function focusJourneyMapFromPlan(button, target = "destination") {
      const plan = button.closest(".travel-plan");
      const shell = plan?.querySelector(".journey-live-map-shell");
      const node = plan?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      shell?.scrollIntoView({ behavior: "smooth", block: "start" });
      const entry = getJourneyMapEntry?.(node);
      focusJourneyMapTarget?.(entry, target);
      if (target === "stay") {
        showToast?.("已定位到落脚点和周边参考");
      } else if (target === "highlights") {
        showToast?.("已定位到沿途看点");
      } else {
        showToast?.("已定位到路线地图");
      }
      return true;
    }

    function focusJourneyMapDayFromPlan(button) {
      const dayKey = button.dataset.mapDayFocus || "all";
      const plan = button.closest(".travel-plan");
      const node = plan?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return false;
      const entry = getJourneyMapEntry?.(node);
      setJourneyMapDaySelection?.(entry, dayKey);
      return true;
    }

    function handleTravelReportAction(button) {
      const report = button.closest(".travel-report");
      const action = button.dataset.reportAction || "";
      if (!report || !action) return false;

      if (action === "tweak") {
        appendToComposer?.(
          "我想基于这份旅游报告继续微调：请先帮我列出可以调整的方向，比如交通、住宿、每日行程顺序、预算或景点取舍。",
          "replace"
        );
        setRuntimeStatus?.("已准备继续微调报告", "online");
        showToast?.("已把微调指令放到输入框");
        return true;
      }

      if (action === "map") {
        const map = report.querySelector(".travel-report-map, .journey-live-map-shell");
        if (!map) {
          showToast?.("这份报告暂时还没有可视化路线地图。", true);
          return true;
        }
        map.scrollIntoView({ behavior: "smooth", block: "start" });
        showToast?.("已定位到路线地图");
        return true;
      }

      if (action === "copy-summary") {
        const summaryText = buildReportShareSummary(report);
        copyTextToClipboard(summaryText)
          .then(() => {
            setRuntimeStatus?.("报告交付摘要已复制", "online");
            showToast?.("已复制报告交付摘要");
          })
          .catch((error) => {
            console.error(error);
            showToast?.("复制失败，请手动选择报告内容。", true);
          });
        return true;
      }

      if (action === "export") {
        exportTravelReport?.(report)
          .then(() => showToast?.("旅游报告文件已开始导出"))
          .catch((error) => {
            console.error(error);
            showToast?.("导出失败，请稍后重试。", true);
          });
        return true;
      }

      return false;
    }

    function handleReportClick(event) {
      const reportActionBtn = event.target.closest("[data-report-action]");
      if (reportActionBtn) {
        return handleTravelReportAction(reportActionBtn);
      }

      const cardLinkBtn = event.target.closest(".travel-card-link-btn");
      if (cardLinkBtn) {
        return focusJourneyMapFromPlan(
          cardLinkBtn,
          cardLinkBtn.dataset.mapFocus || "destination"
        );
      }

      const rhythmFocusBtn = event.target.closest(".journey-rhythm-focus-btn");
      if (rhythmFocusBtn) {
        return focusJourneyMapFromPlan(
          rhythmFocusBtn,
          rhythmFocusBtn.dataset.mapFocus || "destination"
        );
      }

      const dayFocusBtn = event.target.closest(".journey-day-map-btn");
      if (dayFocusBtn) {
        return focusJourneyMapDayFromPlan(dayFocusBtn);
      }

      return false;
    }

    return {
      focusJourneyMapFromPlan,
      focusJourneyMapDayFromPlan,
      handleTravelReportAction,
      handleReportClick,
    };
  }

  global.ZhiXingReportActions = {
    createReportActions,
  };
})(window);
