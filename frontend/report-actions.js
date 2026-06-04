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
