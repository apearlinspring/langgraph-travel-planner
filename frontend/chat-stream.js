(function (global) {
  function getLongestTagPrefixSuffix(text = "", tag = "") {
    const lowerText = String(text || "").toLowerCase();
    const maxSize = Math.min(tag.length - 1, lowerText.length);
    for (let size = maxSize; size > 0; size -= 1) {
      if (tag.startsWith(lowerText.slice(-size))) {
        return size;
      }
    }
    return 0;
  }

  function createAssistantThinkingFilter() {
    const openTag = "<think>";
    const closeTag = "</think>";
    let buffer = "";
    let insideThinking = false;

    return {
      feed(value = "") {
        buffer += String(value || "");
        const chunks = [];

        while (buffer) {
          const lowerBuffer = buffer.toLowerCase();
          if (insideThinking) {
            const closeIndex = lowerBuffer.indexOf(closeTag);
            if (closeIndex >= 0) {
              buffer = buffer.slice(closeIndex + closeTag.length);
              insideThinking = false;
              continue;
            }
            const keepSize = getLongestTagPrefixSuffix(buffer, closeTag);
            buffer = keepSize ? buffer.slice(-keepSize) : "";
            break;
          }

          const openIndex = lowerBuffer.indexOf(openTag);
          if (openIndex >= 0) {
            chunks.push(buffer.slice(0, openIndex));
            buffer = buffer.slice(openIndex + openTag.length);
            insideThinking = true;
            continue;
          }

          const keepSize = getLongestTagPrefixSuffix(buffer, openTag);
          if (keepSize) {
            chunks.push(buffer.slice(0, -keepSize));
            buffer = buffer.slice(-keepSize);
          } else {
            chunks.push(buffer);
            buffer = "";
          }
          break;
        }

        return chunks.join("");
      },
      finish() {
        if (insideThinking) {
          buffer = "";
          insideThinking = false;
          return "";
        }
        if (buffer && openTag.startsWith(buffer.toLowerCase())) {
          buffer = "";
          return "";
        }
        const remainder = buffer;
        buffer = "";
        return remainder;
      },
    };
  }

  function extractStreamContent(rawData) {
    if (!rawData || rawData === "[DONE]") return "";
    try {
      const parsed = JSON.parse(rawData);
      if (typeof parsed.content === "string") return parsed.content;
      if (typeof parsed.delta === "string") return parsed.delta;
      if (typeof parsed.message === "string") return parsed.message;
      return "";
    } catch (error) {
      return rawData;
    }
  }

  function processSseBuffer(buffer, onContent, onEvent = null) {
    const events = buffer.split("\n\n");
    const remainder = events.pop() || "";
    events.forEach((eventBlock) => {
      const dataLines = eventBlock
        .split("\n")
        .filter((line) => line.startsWith("data: "));
      dataLines.forEach((line) => {
        const rawData = line.slice(6).trim();
        if (onEvent) {
          try {
            onEvent(JSON.parse(rawData));
          } catch (error) {
            // Non-JSON SSE chunks are still handled as plain text deltas.
          }
        }
        const content = extractStreamContent(rawData);
        if (content) {
          onContent(content);
        }
      });
    });
    return remainder;
  }

  function buildStreamingFallbackMessage({
    elapsedMs = 0,
    hasPartialContent = false,
    reachedVerySlowStage = false,
  } = {}) {
    if (hasPartialContent) {
      return "\n\n补充说明：这轮回复在中途断开了。你可以直接继续追问，我会尽量接着当前上下文往下补全。";
    }
    if (reachedVerySlowStage || elapsedMs >= 45000) {
      return "这轮等待时间比较久，可能是规划链路较慢，或者交通、住宿这类外部查询还没来得及返回。你可以稍后再试一次，或直接继续追问，我会尽量接着当前上下文继续。";
    }
    return "这轮连接没有顺利完成。你可以稍后重试一次，或换个问法继续，我会接着当前会话往下帮你规划。";
  }

  function createChatStream() {
    return {
      createAssistantThinkingFilter,
      processSseBuffer,
      buildStreamingFallbackMessage,
    };
  }

  global.ZhiXingChatStream = {
    createChatStream,
  };
  global.createAssistantThinkingFilter = createAssistantThinkingFilter;
  global.processSseBuffer = processSseBuffer;
  global.buildStreamingFallbackMessage = buildStreamingFallbackMessage;
  if (typeof globalThis !== "undefined") {
    globalThis.createAssistantThinkingFilter = createAssistantThinkingFilter;
    globalThis.processSseBuffer = processSseBuffer;
    globalThis.buildStreamingFallbackMessage = buildStreamingFallbackMessage;
  }
})(window);
