(function (global) {
  function createRuntimeStatus({ document = global.document } = {}) {
    function setRuntimeStatus(label, tone = "idle") {
      const el = document.getElementById("assistantStatus");
      if (!el) return;
      el.textContent = label;
      el.className = `assistant-status ${tone}`.trim();
    }

    function updateEndpointTone(tone = "idle") {
      const endpointHint = document.getElementById("endpointHint");
      if (!endpointHint) return;
      endpointHint.className = "endpoint-pill";
      if (tone === "warning") endpointHint.classList.add("warning");
      if (tone === "error") endpointHint.classList.add("error");
    }

    function setServiceBanner({
      visible = false,
      tone = "loading",
      title = "",
      text = "",
      meta = "",
    } = {}) {
      const banner = document.getElementById("serviceBanner");
      if (!banner) return;
      banner.className = `service-banner ${visible ? "show" : ""} ${
        tone || ""
      }`.trim();
      document.getElementById("serviceBannerTitle").textContent = title;
      document.getElementById("serviceBannerText").textContent = text;
      document.getElementById("serviceBannerMeta").textContent = meta;
    }

    function setAuthServiceHint(message, tone = "loading") {
      const hint = document.getElementById("authServiceHint");
      if (!hint) return;
      hint.textContent = message;
      hint.className = `auth-service-hint ${tone}`.trim();
    }

    function setAuthFeedback(message, tone = "info") {
      const el = document.getElementById("authFeedback");
      if (!el) return;
      if (!message) {
        el.className = "auth-feedback";
        el.textContent = "";
        return;
      }
      el.textContent = message;
      el.className = `auth-feedback show ${tone}`.trim();
    }

    function setFieldError(field, message = "") {
      const input = document.getElementById(field);
      const error = document.getElementById(`${field}Error`);
      const wrapper = input?.closest(".form-group");
      if (wrapper) {
        wrapper.classList.toggle("error", Boolean(message));
      }
      if (error) {
        error.textContent = message;
      }
    }

    function clearAuthErrors() {
      ["username", "email", "password"].forEach((field) =>
        setFieldError(field, "")
      );
      setAuthFeedback("", "info");
    }

    return {
      setRuntimeStatus,
      updateEndpointTone,
      setServiceBanner,
      setAuthServiceHint,
      setAuthFeedback,
      setFieldError,
      clearAuthErrors,
    };
  }

  global.ZhiXingRuntimeStatus = {
    createRuntimeStatus,
  };
})(window);
