(function (global) {
  function createDraftStorage({ getScope, storage = global.localStorage } = {}) {
    const writeTimers = new Map();
    const pendingValues = new Map();
    const writeDelayMs = 250;

    function getStorageScope() {
      return getScope?.() || "guest";
    }

    function getScopedStorageKey(baseKey) {
      return `${baseKey}:${getStorageScope()}`;
    }

    function readDraftStorage(baseKey) {
      return (
        storage.getItem(getScopedStorageKey(baseKey)) ??
        storage.getItem(baseKey)
      );
    }

    function commitDraftStorage(storageKey, value) {
      storage.setItem(storageKey, value);
    }

    function flushDraftStorageWrite(storageKey) {
      if (!pendingValues.has(storageKey)) return;
      const value = pendingValues.get(storageKey);
      pendingValues.delete(storageKey);
      const timer = writeTimers.get(storageKey);
      if (timer) {
        global.clearTimeout(timer);
        writeTimers.delete(storageKey);
      }
      commitDraftStorage(storageKey, value);
    }

    function flushAllDraftStorageWrites() {
      Array.from(pendingValues.keys()).forEach((storageKey) =>
        flushDraftStorageWrite(storageKey)
      );
    }

    function writeDraftStorage(baseKey, value, options = {}) {
      const storageKey = getScopedStorageKey(baseKey);
      if (options.immediate) {
        pendingValues.set(storageKey, value);
        flushDraftStorageWrite(storageKey);
        return;
      }
      pendingValues.set(storageKey, value);
      if (writeTimers.has(storageKey)) return;
      const timer = global.setTimeout(() => {
        flushDraftStorageWrite(storageKey);
      }, writeDelayMs);
      writeTimers.set(storageKey, timer);
    }

    function clearDraftStorage(baseKey) {
      const storageKey = getScopedStorageKey(baseKey);
      const timer = writeTimers.get(storageKey);
      if (timer) global.clearTimeout(timer);
      writeTimers.delete(storageKey);
      pendingValues.delete(storageKey);
      storage.removeItem(storageKey);
      storage.removeItem(baseKey);
    }

    return {
      readDraftStorage,
      writeDraftStorage,
      clearDraftStorage,
      flushAllDraftStorageWrites,
    };
  }

  global.ZhiXingDraftStorage = {
    createDraftStorage,
  };
})(window);
