(function (global) {
  function createJourneyMapShell(options = {}) {
    const getJourneyMapEntry =
      typeof options.getJourneyMapEntry === "function"
        ? options.getJourneyMapEntry
        : () => null;

    function syncJourneyMapToggleLabels(shell) {
      if (!shell) return;
      const toolsCollapsed = shell.classList.contains("journey-map-tools-collapsed");
      shell
        .querySelectorAll('[data-map-action="toggle-tools"]')
        .forEach((button) => {
          button.textContent = toolsCollapsed ? "地图工具" : "收起工具";
          button.title = toolsCollapsed ? "展开地图工具" : "收起地图工具";
          button.setAttribute("aria-expanded", String(!toolsCollapsed));
        });

      const sidebarCollapsed = shell.classList.contains(
        "journey-map-sidebar-collapsed"
      );
      shell
        .querySelectorAll('[data-map-action="toggle-sidebar"]')
        .forEach((button) => {
          button.textContent = sidebarCollapsed ? "展开路线说明" : "收起路线说明";
          button.title = sidebarCollapsed ? "展开路线说明" : "收起路线说明";
          button.setAttribute("aria-expanded", String(!sidebarCollapsed));
        });

      shell
        .querySelectorAll('[data-map-action="toggle-day-routes"]')
        .forEach((button) => {
          const routesCard = button.closest(".journey-map-sidebar-routes");
          const collapsed = routesCard?.classList.contains("is-collapsed");
          button.textContent = collapsed ? "展开分日路线" : "收起分日路线";
          button.title = collapsed ? "展开分日路线" : "收起分日路线";
          button.setAttribute("aria-expanded", String(!collapsed));
        });
    }

    function getVisualJourneyMapEntry(control) {
      const workbench = control?.closest(".visual-journey-workbench");
      const node = workbench?.querySelector(".journey-live-map[data-map-payload]");
      if (!node) return null;
      return getJourneyMapEntry(node);
    }

    function getJourneyMapShellFromControl(control) {
      return (
        control?.closest(".journey-live-map-shell") ||
        control?.closest(".visual-journey-workbench")?.querySelector(".journey-live-map-shell") ||
        null
      );
    }

    return {
      syncJourneyMapToggleLabels,
      getVisualJourneyMapEntry,
      getJourneyMapShellFromControl,
    };
  }

  global.ZhiXingJourneyMapShell = {
    createJourneyMapShell,
  };
})(window);
