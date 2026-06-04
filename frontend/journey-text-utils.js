(function (global) {
  function createJourneyTextUtils(options = {}) {
    const sanitizeConversationTitleSegment =
      typeof options.sanitizeConversationTitleSegment === "function"
        ? options.sanitizeConversationTitleSegment
        : (value = "") => String(value || "").replace(/\s+/g, " ").trim();
    const isDefaultConversationTitle =
      typeof options.isDefaultConversationTitle === "function"
        ? options.isDefaultConversationTitle
        : () => false;

    function extractJourneyCityPairFromConversationTitle(title = "") {
      const normalized = (title || "").replace(/\s+/g, " ").trim();
      if (!normalized || isDefaultConversationTitle(normalized)) return null;
      const coreTitle = normalized.split("·")[0].trim();
      const routePair = extractJourneyCityPair(coreTitle);
      if (routePair?.origin || routePair?.destination) return routePair;
      const destinationOnly = sanitizeConversationTitleSegment(coreTitle)
        .replace(/(?:玩|游)?\s*\d+\s*天.*$/u, "")
        .replace(/\s*(?:方案|行程|规划|报告)$/u, "")
        .trim();
      if (
        destinationOnly &&
        destinationOnly.length >= 2 &&
        destinationOnly.length <= 8 &&
        !/(?:新行程|专属旅程|自然醒|路线|预算|交通|住宿)/u.test(destinationOnly)
      ) {
        return { origin: "", destination: destinationOnly };
      }
      return null;
    }

    function parseJourneyChineseDayNumber(value = "") {
      if (/^\d+$/.test(value)) return Number(value);
      const mapping = {
        "\u4e00": 1,
        "\u4e8c": 2,
        "\u4e09": 3,
        "\u56db": 4,
        "\u4e94": 5,
        "\u516d": 6,
        "\u4e03": 7,
        "\u516b": 8,
        "\u4e5d": 9,
        "\u5341": 10,
      };
      if (value === "\u5341") return 10;
      if (value.startsWith("\u5341")) {
        return 10 + (mapping[value.slice(1)] || 0);
      }
      if (value.endsWith("\u5341")) {
        return (mapping[value[0]] || 0) * 10;
      }
      if (value.includes("\u5341")) {
        const [tens, ones] = value.split("\u5341");
        return (mapping[tens] || 0) * 10 + (mapping[ones] || 0);
      }
      return mapping[value] || 0;
    }

    function normalizeJourneyDayHeading(text = "") {
      return String(text || "")
        .replace(/^#{1,6}\s+/, "")
        .replace(/^\*\*/, "")
        .replace(/\*\*$/, "")
        .replace(/^[-*•]\s*/, "")
        .replace(/^[\u{1F300}-\u{1FAFF}\u2600-\u27BF]+\s*/u, "")
        .trim();
    }

    function parseJourneyDayNumber(text = "") {
      const normalized = normalizeJourneyDayHeading(text);
      const dayMatch = normalized.match(/\bday\s*(\d+)\b/i);
      if (dayMatch) return Number(dayMatch[1]);
      const chineseMatch = normalized.match(/^第\s*([一二三四五六七八九十\d]+)\s*天/);
      if (chineseMatch) {
        return parseJourneyChineseDayNumber(chineseMatch[1]);
      }
      return 0;
    }

    function extractJourneyCityPair(text = "") {
      const normalized = (text || "").replace(/\s+/g, " ").trim();
      if (!normalized) return null;
      const cleanRouteCity = (value = "") =>
        sanitizeConversationTitleSegment(value)
          .split(/[！!：:，,。；;、]/)
          .map((part) => part.trim())
          .filter(Boolean)
          .pop()
          ?.replace(/^(行程概览|旅行计划|方案概览|路线|主路线)\s*[：:]?\s*/u, "")
          .trim() || "";

      const labeledOrigin = normalized.match(
        /(?:\u51fa\u53d1\u5730|\u51fa\u53d1)[：:]\s*([^\s，。；、\n]{1,12})/u
      )?.[1];
      const labeledDestination = normalized.match(
        /(?:\u76ee\u7684\u5730|\u76ee\u7684\u5730\u70b9|\u76ee\u7684\u57ce\u5e02)[：:]\s*([^\s，。；、\n]{1,12})/u
      )?.[1];
      if (labeledOrigin || labeledDestination) {
        return {
          origin: sanitizeConversationTitleSegment(labeledOrigin || ""),
          destination: sanitizeConversationTitleSegment(labeledDestination || ""),
        };
      }

      const routeMatch = normalized.match(
        /\u4ece\s*([^\s，。；、]{1,12})\s*(?:\u51fa\u53d1)?\s*(?:\u53bb|\u5230)\s*([^\s，。；、]{1,12})/u
      );
      if (routeMatch) {
        return {
          origin: sanitizeConversationTitleSegment(routeMatch[1]),
          destination: sanitizeConversationTitleSegment(routeMatch[2]),
        };
      }

      const arrowMatch = normalized.match(
        /([^\s，。；、]{1,12})\s*(?:→|->)\s*([^\s，。；、]{1,12})/u
      );
      if (arrowMatch) {
        return {
          origin: cleanRouteCity(arrowMatch[1]),
          destination: cleanRouteCity(arrowMatch[2]),
        };
      }

      return null;
    }

    function extractJourneyPrimaryOrigin(text = "") {
      const normalized = (text || "").replace(/\s+/g, " ").trim();
      if (!normalized) return "";
      return (
        normalized.match(/(?:\u51fa\u53d1\u5730|\u51fa\u53d1)[：:]\s*([^\s，。；、\n]{1,12})/u)?.[1] ||
        normalized.match(/\u4ece\s*([^\s，。；、]{1,12})\s*(?:\u51fa\u53d1|\u53bb|\u5230)/u)?.[1] ||
        ""
      );
    }

    function extractJourneyPrimaryDestination(text = "") {
      const normalized = (text || "").replace(/\s+/g, " ").trim();
      if (!normalized) return "";
      return (
        normalized.match(
          /(?:\u76ee\u7684\u5730|\u76ee\u7684\u5730\u70b9|\u76ee\u7684\u57ce\u5e02)[：:]\s*([^\s，。；、\n]{1,12})/u
        )?.[1] ||
        normalized.match(/(?:\u53bb|\u5230)\s*([^\s，。；、]{1,12})(?:\u65c5\u6e38|\u65c5\u884c|\u6e38\u73a9|\u73a9)?/u)?.[1] ||
        ""
      );
    }

    return {
      extractJourneyCityPairFromConversationTitle,
      parseJourneyChineseDayNumber,
      normalizeJourneyDayHeading,
      parseJourneyDayNumber,
      extractJourneyCityPair,
      extractJourneyPrimaryOrigin,
      extractJourneyPrimaryDestination,
    };
  }

  global.ZhiXingJourneyTextUtils = {
    createJourneyTextUtils,
  };
})(window);
