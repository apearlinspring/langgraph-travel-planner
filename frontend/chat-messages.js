(function (global) {
  function createChatMessages({
    document,
    Date: DateCtor = global.Date,
    Math: MathCtor = global.Math,
    requestAnimationFrame: scheduleFrame = (...args) =>
      global.requestAnimationFrame(...args),
    cancelAnimationFrame: cancelFrame = (...args) =>
      global.cancelAnimationFrame(...args),
    hydrateGovernanceFromMessages,
    getWelcomeMarkup,
    buildMessageMarkup,
    renderMessageText,
    scheduleJourneyMapHydration,
    collapsePlannerPanelForVisualJourney,
  } = {}) {
    let streamingScrollFrame = null;

    function renderMessages(messages = []) {
      const container = document.getElementById("chatMessages");
      hydrateGovernanceFromMessages(messages);
      if (messages.length === 0) {
        clearChatMessages();
        return;
      }
      const lastAssistantIndex = messages
        .map((msg, index) => (msg.role === "assistant" ? index : -1))
        .filter((index) => index >= 0)
        .pop();
      container.innerHTML = messages
        .map(
          (msg, index) => `
                <div class="message ${
                  msg.role
                }" id="msg-${DateCtor.now()}-${MathCtor.random()}">
                    ${buildMessageMarkup(
                      msg.role,
                      msg.content,
                      msg.created_at || msg.updated_at || new DateCtor(),
                      {
                        extraInfo: msg.extra_info || msg.extraInfo || {},
                        suppressJourneyPreview:
                          msg.role === "assistant" && index !== lastAssistantIndex,
                      }
                    )}
                </div>
            `
        )
        .join("");
      scheduleJourneyMapHydration(container);
      container.scrollTop = container.scrollHeight;
    }

    function clearChatMessages() {
      document.getElementById("chatMessages").innerHTML = getWelcomeMarkup();
    }

    function addMessage(role, text, options = {}) {
      const container = document.getElementById("chatMessages");
      const id = "msg-" + DateCtor.now();
      const div = document.createElement("div");
      if (role === "assistant") {
        collapsePlannerPanelForVisualJourney(options);
      }
      div.className = `message ${role}`;
      div.id = id;
      div.innerHTML = buildMessageMarkup(role, text, new DateCtor(), options);
      container.appendChild(div);
      scheduleJourneyMapHydration(div);
      container.scrollTop = container.scrollHeight;
      return id;
    }

    function scrollChatMessageToTop(id, behavior = "smooth") {
      const container = document.getElementById("chatMessages");
      const el = document.getElementById(id);
      if (!container || !el) return;

      const targetTop = MathCtor.max(
        el.offsetTop - container.offsetTop - 16,
        0
      );
      container.scrollTo({ top: targetTop, behavior });
    }

    function pinChatMessageToTop(id) {
      if (streamingScrollFrame) {
        cancelFrame(streamingScrollFrame);
      }
      streamingScrollFrame = scheduleFrame(() => {
        scrollChatMessageToTop(id, "auto");
        streamingScrollFrame = null;
      });
    }

    function updateMessage(id, text, options = {}) {
      const el = document.getElementById(id);
      if (el) {
        collapsePlannerPanelForVisualJourney(options);
        el.querySelector(".message-text").innerHTML = renderMessageText(
          "assistant",
          text,
          options
        );
        if (!options?.suppressJourneyPreview) {
          scheduleJourneyMapHydration(el);
        }
        if (options?.pinToTop) {
          pinChatMessageToTop(id);
        }
      }
    }

    function convertLoadingToAssistant(id, text, options = {}) {
      const el = document.getElementById(id);
      if (!el) {
        return addMessage("assistant", text, options);
      }
      const messageId = "msg-" + DateCtor.now();
      el.id = messageId;
      el.className = "message assistant";
      el.innerHTML = buildMessageMarkup("assistant", text, new DateCtor(), options);
      if (!options?.suppressJourneyPreview) {
        scheduleJourneyMapHydration(el);
      }
      scrollChatMessageToTop(messageId, options?.pinToTop ? "auto" : "smooth");
      return messageId;
    }

    function addLoading() {
      const container = document.getElementById("chatMessages");
      const id = "loading-" + DateCtor.now();
      const div = document.createElement("div");
      div.className = "message assistant";
      div.id = id;
      div.innerHTML = `
                <div class="message-avatar"><i class="fa-solid fa-compass"></i></div>
                <div class="message-content thinking-card">
                    <div class="thinking-header">
                        <div class="thinking-title">
                            <i class="fa-solid fa-route"></i>
                            正在整理行程建议
                        </div>
                        <span class="thinking-badge">处理中</span>
                    </div>
                    <div class="thinking-copy">正在结合你的需求和已经聊到的信息，整理下一步更完整的建议。</div>
                    <div class="thinking-progress"></div>
                    <div class="typing-dots" style="margin-top: 12px;"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
                </div>
            `;
      container.appendChild(div);
      scrollChatMessageToTop(id);
      return id;
    }

    function updateLoadingCopy(id, text) {
      const el = document.getElementById(id);
      const copy = el?.querySelector(".thinking-copy");
      if (copy) {
        copy.textContent = text;
      }
    }

    function removeMessage(id) {
      const el = document.getElementById(id);
      if (el) el.remove();
    }

    return {
      renderMessages,
      clearChatMessages,
      addMessage,
      updateMessage,
      convertLoadingToAssistant,
      addLoading,
      updateLoadingCopy,
      removeMessage,
    };
  }

  global.ZhiXingChatMessages = {
    createChatMessages,
  };
})(window);
