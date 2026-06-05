(function (global) {
  function createGuideImport(options = {}) {
    const {
      getPlannerFields = () => ({}),
      appendToComposer = () => {},
      updatePlannerSummary = () => {},
      setRuntimeStatus = () => {},
      showToast = () => {},
      sendMessage = null,
    } = options;
    const maxGuideTextLength = 2400;

    function getGuideImportNodes() {
      return {
        panel: document.getElementById("guideImportPanel"),
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

    function buildGuideImportDraft(guideText, fields = {}) {
      const normalizedText = normalizeGuideText(guideText);
      const wasTruncated = String(guideText || "").trim().length > maxGuideTextLength;
      const truncateNote = wasTruncated
        ? "\n\n注：攻略原文较长，我已先截取前半段关键内容；如果信息不够，请继续追问。"
        : "";
      return [
        "我粘贴了一段旅行攻略，请把它当作候选素材，整理成可继续编辑的可视化旅程草案。",
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

    function updateGuideImportCount() {
      const { textarea, count } = getGuideImportNodes();
      const length = String(textarea?.value || "").trim().length;
      if (count) {
        count.textContent = length ? `${Math.min(length, maxGuideTextLength)} 字` : "粘贴文本";
      }
      if (length > maxGuideTextLength) {
        setGuideStatus(`已超过 ${maxGuideTextLength} 字，将先截取前半段。`, "warning");
      } else if (length) {
        setGuideStatus("攻略文本已准备好。", "ready");
      } else {
        setGuideStatus("粘贴攻略文本后，我会整理成一条规划请求。", "idle");
      }
    }

    function composeGuideImportDraft(options = {}) {
      const { textarea, panel } = getGuideImportNodes();
      const guideText = normalizeGuideText(textarea?.value || "");
      if (guideText.length < 20) {
        setGuideStatus("攻略内容太短，请至少粘贴一段包含地点或路线的文本。", "warning");
        showToast("攻略内容太短", true);
        return false;
      }
      const draft = buildGuideImportDraft(guideText, getPlannerFields());
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
      const { textarea } = getGuideImportNodes();
      if (textarea) textarea.value = "";
      updateGuideImportCount();
      setRuntimeStatus("攻略导入已清空", "idle");
    }

    function bindGuideImportEvents() {
      const { textarea, composeBtn, sendBtn, clearBtn } = getGuideImportNodes();
      textarea?.addEventListener("input", updateGuideImportCount);
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
      sendGuideImportDraft,
      updateGuideImportCount,
    };
  }

  global.ZhiXingGuideImport = {
    createGuideImport,
  };
})(window);
