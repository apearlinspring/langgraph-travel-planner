(function (global) {
  function createJourneyMapHydration({
    document,
    hydrateJourneyMap,
    requestAnimationFrame: scheduleFrame = (...args) =>
      global.requestAnimationFrame(...args),
    WeakSet: WeakSetCtor = global.WeakSet,
  } = {}) {
    const scheduledJourneyMapHydrationRoots = new WeakSetCtor();

    function getHydratableJourneyMapNodes(root = document) {
      if (!root) return [];
      const nodes = [];
      if (root.matches?.(".journey-live-map[data-map-payload]")) {
        nodes.push(root);
      }
      root
        .querySelectorAll?.(".journey-live-map[data-map-payload]")
        .forEach((node) => {
          if (node !== root) nodes.push(node);
        });
      return nodes;
    }

    function hydrateJourneyMaps(root = document) {
      getHydratableJourneyMapNodes(root).forEach((node) => hydrateJourneyMap(node));
    }

    function scheduleJourneyMapHydration(root = document) {
      if (
        !getHydratableJourneyMapNodes(root).length ||
        scheduledJourneyMapHydrationRoots.has(root)
      ) {
        return;
      }
      scheduledJourneyMapHydrationRoots.add(root);
      scheduleFrame(() => {
        scheduledJourneyMapHydrationRoots.delete(root);
        hydrateJourneyMaps(root);
      });
    }

    return {
      getHydratableJourneyMapNodes,
      hydrateJourneyMaps,
      scheduleJourneyMapHydration,
    };
  }

  global.ZhiXingJourneyMapHydration = {
    createJourneyMapHydration,
  };
})(window);
