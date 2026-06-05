(function (global) {
  function createGuideImport(options = {}) {
    const {
      getPlannerFields = () => ({}),
      appendToComposer = () => {},
      updatePlannerSummary = () => {},
      setRuntimeStatus = () => {},
      showToast = () => {},
      fetchGuideUrl = null,
      sendMessage = null,
    } = options;
    const maxGuideTextLength = 2400;
    let fetchedGuideSource = null;
    let fetchedGuideText = "";
    let isFetchingGuide = false;

    function getGuideImportNodes() {
      return {
        panel: document.getElementById("guideImportPanel"),
        urlInput: document.getElementById("guideImportUrl"),
        fetchBtn: document.getElementById("guideImportFetchBtn"),
        textarea: document.getElementById("guideImportText"),
        count: document.getElementById("guideImportCount"),
        status: document.getElementById("guideImportStatus"),
        composeBtn: document.getElementById("guideImportComposeBtn"),
        sendBtn: document.getElementById("guideImportSendBtn"),
        clearBtn: document.getElementById("guideImportClearBtn"),
      };
    }

    function normalizeGuideText(value = "") {
      return String(value || "")
        .replace(/\r\n/g, "\n")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim()
        .slice(0, maxGuideTextLength);
    }

    function formatPlannerContext(fields = {}) {
      const items = [
        ["出发地", fields.origin],
        ["目的地", fields.destination],
        ["出发时间", fields.date],
        ["行程天数", fields.days],
        ["出行人数", fields.travelers],
        ["预算范围", fields.budget],
        ["交通偏好", fields.transport],
        ["住宿偏好", fields.stay],
        ["偏好关键词", fields.style],
      ].filter(([, value]) => String(value || "").trim());
      if (!items.length) {
        return "基础信息暂未填写，请优先从攻略里识别目的地、天数和地点顺序；缺失项请继续追问。";
      }
      return items.map(([label, value]) => `- ${label}：${String(value).trim()}`).join("\n");
    }

    function formatGuideSource(source) {
      if (!source?.url) return "";
      const lines = ["", "【攻略来源】", `- 原始链接：${source.url}`];
      if (source.finalUrl && source.finalUrl !== source.url) {
        lines.push(`- 最终链接：${source.finalUrl}`);
      }
      if (source.title) {
        lines.push(`- 网页标题：${source.title}`);
      }
      if (source.sourceDomain) {
        lines.push(`- 来源域名：${source.sourceDomain}`);
      }
      lines.push("- 网页抓取只提取公开静态正文，可能不完整；动态信息必须二次核验。");
      return lines.join("\n");
    }

    function getActiveGuideSource(guideText) {
      const normalizedText = normalizeGuideText(guideText);
      if (!fetchedGuideSource || !fetchedGuideText) return null;
      return normalizedText === fetchedGuideText ? fetchedGuideSource : null;
    }

    function buildGuideImportDraft(guideText, fields = {}, source = null) {
      const normalizedText = normalizeGuideText(guideText);
      const wasTruncated =
        String(guideText || "").trim().length > maxGuideTextLength || Boolean(source?.truncated);
      const truncateNote = wasTruncated
        ? "\n\n注：攻略原文较长，我已先截取前半段关键内容；如果信息不够，请继续追问。"
        : "";
      return [
        source?.url
          ? "我导入了一篇公开网页旅行攻略，请把它当作候选素材，整理成可继续编辑的可视化旅程草案。"
          : "我粘贴了一段旅行攻略，请把它当作候选素材，整理成可继续编辑的可视化旅程草案。",
        formatGuideSource(source),
        "",
        "【基础信息】",
        formatPlannerContext(fields),
        "",
        "【导入要求】",
        "- 提取目的地、天数、分日地点顺序、适合停留时段和明显偏好。",
        "- 尽量生成或更新可视化旅程草案数据，方便前台展示地图、分日路线和候选 POI。",
        "- 不要承诺开放时间、票价、交通距离、酒店库存或真实价格；无法确认的内容放入待核验项。",
        "- 如果攻略只有零散地点，请先按地理距离和游玩节奏分组，再说明仍需确认的缺口。",
        "",
        "【攻略原文】",
        normalizedText,
        truncateNote,
      ].join("\n");
    }

    function setGuideStatus(message = "", tone = "idle") {
      const { status } = getGuideImportNodes();
      if (!status) return;
      status.textContent = message;
      status.dataset.guideImportTone = tone;
    }

    function setFetchLoading(loading) {
      isFetchingGuide = loading;
      const { fetchBtn, urlInput } = getGuideImportNodes();
      if (fetchBtn) {
        fetchBtn.disabled = loading;
        fetchBtn.textContent = loading ? "抓取中..." : "抓取网页";
      }
      if (urlInput) {
        urlInput.disabled = loading;
      }
    }

    function updateGuideImportCount(options = {}) {
      const { textarea, count } = getGuideImportNodes();
      const length = String(textarea?.value || "").trim().length;
      if (count) {
        count.textContent = length ? `${Math.min(length, maxGuideTextLength)} 字` : "粘贴文本";
      }
      if (options.preserveStatus || isFetchingGuide) return;
      if (length > maxGuideTextLength) {
        setGuideStatus(`已超过 ${maxGuideTextLength} 字，将先截取前半段。`, "warning");
      } else if (length) {
        setGuideStatus("攻略文本已准备好。", "ready");
      } else {
        setGuideStatus("粘贴攻略文本或抓取公开网页后，我会整理成一条规划请求。", "idle");
      }
    }

    function handleGuideTextInput() {
      const { textarea } = getGuideImportNodes();
      const currentText = normalizeGuideText(textarea?.value || "");
      if (fetchedGuideText && currentText !== fetchedGuideText) {
        fetchedGuideSource = null;
        fetchedGuideText = "";
      }
      updateGuideImportCount();
    }

    function getGuideFetchErrorMessage(data) {
      return (
        data?.detail?.message ||
        data?.message ||
        "网页抓取失败；可以复制正文后粘贴导入。"
      );
    }

    async function fetchGuideImportUrl() {
      const { panel, urlInput, textarea } = getGuideImportNodes();
      const url = String(urlInput?.value || "").trim();
      if (!url) {
        setGuideStatus("请先粘贴一个公开网页链接。", "warning");
        showToast("请先粘贴网页链接", true);
        return false;
      }
      if (typeof fetchGuideUrl !== "function") {
        setGuideStatus("当前前端未加载网页抓取接口，请改用粘贴文本。", "warning");
        showToast("网页抓取接口未加载", true);
        return false;
      }
      setFetchLoading(true);
      panel?.setAttribute("open", "");
      setGuideStatus("正在抓取网页正文...", "busy");
      setRuntimeStatus("正在抓取攻略网页", "checking");
      try {
        const { response, data } = await fetchGuideUrl(url);
        if (!response?.ok || !data?.text) {
          const message = getGuideFetchErrorMessage(data);
          setGuideStatus(message, "warning");
          setRuntimeStatus("攻略网页抓取失败", "degraded");
          showToast("网页抓取失败", true);
          return false;
        }
        const guideText = normalizeGuideText(data.text);
        if (textarea) {
          textarea.value = guideText;
        }
        fetchedGuideSource = {
          url,
          finalUrl: data.final_url || "",
          sourceDomain: data.source_domain || "",
          title: data.title || "",
          truncated: Boolean(data.truncated),
        };
        fetchedGuideText = guideText;
        updateGuideImportCount({ preserveStatus: true });
        const message = data.message || "已抓取网页正文；动态信息仍需核验。";
        setGuideStatus(message, data.truncated ? "warning" : "ready");
        setRuntimeStatus("攻略网页已抓取", "online");
        updatePlannerSummary("攻略网页已抓取：整理后会提取地点、天数、分日路线和待核验项。");
        return true;
      } catch (error) {
        console.warn("Guide webpage fetch failed", error);
        setGuideStatus("网页抓取失败；可以复制正文后粘贴导入。", "warning");
        setRuntimeStatus("攻略网页抓取失败", "degraded");
        showToast("网页抓取失败", true);
        return false;
      } finally {
        setFetchLoading(false);
      }
    }

    function composeGuideImportDraft(options = {}) {
      const { textarea, panel } = getGuideImportNodes();
      const guideText = normalizeGuideText(textarea?.value || "");
      if (guideText.length < 20) {
        setGuideStatus("攻略内容太短，请至少粘贴或抓取一段包含地点或路线的文本。", "warning");
        showToast("攻略内容太短", true);
        return false;
      }
      const draft = buildGuideImportDraft(guideText, getPlannerFields(), getActiveGuideSource(guideText));
      appendToComposer(draft, "replace");
      panel?.setAttribute("open", "");
      updatePlannerSummary("攻略已整理到输入框：发送后会提取地点、天数、分日路线和待核验项。");
      setRuntimeStatus("攻略导入草稿已整理", "online");
      setGuideStatus(
        options.send ? "已整理并准备发送。" : "已整理到输入框，可以继续微调后发送。",
        "ready"
      );
      return true;
    }

    async function sendGuideImportDraft() {
      if (!composeGuideImportDraft({ send: true })) return false;
      if (typeof sendMessage === "function") {
        await sendMessage();
      }
      return true;
    }

    function clearGuideImport() {
      const { textarea, urlInput } = getGuideImportNodes();
      if (textarea) textarea.value = "";
      if (urlInput) urlInput.value = "";
      fetchedGuideSource = null;
      fetchedGuideText = "";
      updateGuideImportCount();
      setRuntimeStatus("攻略导入已清空", "idle");
    }

    function bindGuideImportEvents() {
      const { urlInput, fetchBtn, textarea, composeBtn, sendBtn, clearBtn } = getGuideImportNodes();
      urlInput?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          fetchGuideImportUrl();
        }
      });
      fetchBtn?.addEventListener("click", () => {
        fetchGuideImportUrl();
      });
      textarea?.addEventListener("input", handleGuideTextInput);
      composeBtn?.addEventListener("click", () => composeGuideImportDraft());
      sendBtn?.addEventListener("click", () => {
        sendGuideImportDraft();
      });
      clearBtn?.addEventListener("click", clearGuideImport);
      updateGuideImportCount();
    }

    return {
      buildGuideImportDraft,
      bindGuideImportEvents,
      composeGuideImportDraft,
      fetchGuideImportUrl,
      sendGuideImportDraft,
      updateGuideImportCount,
    };
  }

  global.ZhiXingGuideImport = {
    createGuideImport,
  };
})(window);
