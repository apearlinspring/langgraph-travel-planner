(function (global) {
  function createAssistantRenderer({
    formatInlineText,
    splitTableCells,
    isMarkdownTable,
    getMarkdownTableSpan,
  } = {}) {
    function renderMarkdownTable(lines) {
      const headers = splitTableCells(lines[0]);
      const rows = lines
        .slice(2)
        .map(splitTableCells)
        .filter((cells) => cells.some(Boolean));

      if (!headers.length || !rows.length) {
        return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
      }

      if (isTransportTable(headers)) {
        return renderTransportTable(headers, rows);
      }

      return `
          <div class="message-table-wrap">
            <table class="message-table">
              <thead>
                <tr>${headers
                  .map((header) => `<th>${formatInlineText(header)}</th>`)
                  .join("")}</tr>
              </thead>
              <tbody>
                ${rows
                  .map(
                    (cells) => `<tr>${headers
                      .map(
                        (_, index) =>
                          `<td>${formatInlineText(cells[index] || "")}</td>`
                      )
                      .join("")}</tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        `;
    }

    function normalizeTransportHeader(header = "") {
      const normalized = header.replace(/\s+/g, "").toLowerCase();
      if (
        normalized.includes("车次") ||
        normalized.includes("车次/航班") ||
        normalized.includes("航班") ||
        normalized.includes("班次") ||
        normalized.includes("方案")
      ) {
        return "code";
      }
      if (
        normalized.includes("出发时间") ||
        normalized.includes("到达时间") ||
        normalized.includes("出发→到达") ||
        normalized.includes("出发->到达") ||
        normalized.includes("时间")
      ) {
        return "schedule";
      }
      if (normalized.includes("耗时") || normalized.includes("历时")) {
        return "duration";
      }
      if (
        normalized.includes("票价") ||
        normalized.includes("价格") ||
        normalized.includes("费用") ||
        normalized.includes("二等座") ||
        normalized.includes("一等座") ||
        normalized.includes("商务座")
      ) {
        return "price";
      }
      if (
        normalized.includes("推荐理由") ||
        normalized.includes("备注") ||
        normalized.includes("说明") ||
        normalized.includes("建议")
      ) {
        return "reason";
      }
      if (normalized.includes("余票") || normalized.includes("舱位")) {
        return "inventory";
      }
      return "extra";
    }

    function isTransportTable(headers = []) {
      const mapped = headers.map(normalizeTransportHeader);
      const hasCode = mapped.includes("code");
      const hasCoreInfo =
        mapped.includes("schedule") ||
        mapped.includes("duration") ||
        mapped.includes("price");
      return hasCode && hasCoreInfo;
    }

    function detectTransportCardKind(code = "", reason = "") {
      const source = `${code} ${reason}`.toUpperCase();
      if (
        /^(G|D|C|K|T|Z)\d+/.test(code.toUpperCase()) ||
        source.includes("高铁") ||
        source.includes("火车")
      ) {
        return { label: "铁路方案", icon: "fa-train-subway" };
      }
      if (
        /^[A-Z]{2}\d+/.test(code.toUpperCase()) ||
        source.includes("航班") ||
        source.includes("飞机")
      ) {
        return { label: "航班方案", icon: "fa-plane-departure" };
      }
      if (source.includes("自驾") || source.includes("驾车")) {
        return { label: "自驾方案", icon: "fa-car-side" };
      }
      return { label: "交通方案", icon: "fa-route" };
    }

    function splitScheduleText(text = "") {
      const compact = text.replace(/\s+/g, " ").trim();
      const parts = compact.split(/\s*(?:→|->|➜|至)\s*/);
      if (parts.length >= 2) {
        return {
          departure: parts[0].trim(),
          arrival: parts.slice(1).join(" → ").trim(),
        };
      }
      return { departure: compact, arrival: "" };
    }

    function renderTransportTable(headers, rows) {
      const keyOrder = headers.map(normalizeTransportHeader);
      const cards = rows.map((cells) => {
        const entry = {};
        headers.forEach((header, index) => {
          const key = keyOrder[index];
          const value = cells[index] || "";
          if (key === "extra") {
            if (!entry.extra) entry.extra = [];
            if (value) {
              entry.extra.push({ label: header, value });
            }
            return;
          }
          if (entry[key]) {
            entry[key] = `${entry[key]} ${value}`.trim();
          } else {
            entry[key] = value;
          }
        });

        const kind = detectTransportCardKind(entry.code || "", entry.reason || "");
        const schedule = splitScheduleText(entry.schedule || "");
        const recommendationTone =
          /(推荐|首选|优先)/.test(entry.reason || "") ? "recommended" : "";

        return `
            <article class="transport-option-card ${recommendationTone}">
              <div class="transport-option-head">
                <div class="transport-option-kind">
                  <i class="fa-solid ${kind.icon}"></i>
                  <span>${kind.label}</span>
                </div>
                <div class="transport-option-code">${formatInlineText(entry.code || "待确认")}</div>
              </div>
              <div class="transport-option-times">
                <div class="transport-stop">
                  <span class="transport-stop-label">出发</span>
                  <strong>${formatInlineText(schedule.departure || "待确认")}</strong>
                </div>
                <div class="transport-stop-arrow">
                  <i class="fa-solid fa-arrow-right-long"></i>
                </div>
                <div class="transport-stop">
                  <span class="transport-stop-label">到达</span>
                  <strong>${formatInlineText(schedule.arrival || "待确认")}</strong>
                </div>
              </div>
              <div class="transport-option-meta">
                ${
                  entry.duration
                    ? `<span class="transport-meta-pill"><i class="fa-regular fa-clock"></i> ${formatInlineText(
                        entry.duration
                      )}</span>`
                    : ""
                }
                ${
                  entry.price
                    ? `<span class="transport-meta-pill price"><i class="fa-solid fa-yen-sign"></i> ${formatInlineText(
                        entry.price
                      )}</span>`
                    : ""
                }
                ${
                  entry.inventory
                    ? `<span class="transport-meta-pill"><i class="fa-solid fa-ticket"></i> ${formatInlineText(
                        entry.inventory
                      )}</span>`
                    : ""
                }
              </div>
              ${
                entry.reason
                  ? `<div class="transport-option-reason">${formatInlineText(entry.reason)}</div>`
                  : ""
              }
              ${
                entry.extra?.length
                  ? `<dl class="transport-extra-list">${entry.extra
                      .map(
                        (item) => `
                          <div class="transport-extra-item">
                            <dt>${formatInlineText(item.label)}</dt>
                            <dd>${formatInlineText(item.value)}</dd>
                          </div>
                        `
                      )
                      .join("")}</dl>`
                  : ""
              }
            </article>
          `;
      });

      return `<div class="transport-options-board">${cards.join("")}</div>`;
    }

    function renderAssistantLineGroup(lines) {
      if (!lines.length) return "";

      if (isMarkdownTable(lines)) {
        return renderMarkdownTable(lines);
      }

      if (lines.every((line) => /^[-*•]\s+/.test(line))) {
        return `<ul>${lines
          .map(
            (line) =>
              `<li>${formatInlineText(line.replace(/^[-*•]\s+/, ""))}</li>`
          )
          .join("")}</ul>`;
      }

      if (lines.every((line) => /^\d+\.\s+/.test(line))) {
        return `<ol>${lines
          .map(
            (line) =>
              `<li>${formatInlineText(line.replace(/^\d+\.\s+/, ""))}</li>`
          )
          .join("")}</ol>`;
      }

      if (/^#{1,3}\s+/.test(lines[0])) {
        const title = lines[0].replace(/^#{1,3}\s+/, "");
        const bodyLines = lines.slice(1);
        return `${title ? `<h4>${formatInlineText(title)}</h4>` : ""}${
          bodyLines.length
            ? `<p>${bodyLines.map((line) => formatInlineText(line)).join("<br>")}</p>`
            : ""
        }`;
      }

      return `<p>${lines.map((line) => formatInlineText(line)).join("<br>")}</p>`;
    }

    function renderAssistantLines(lines) {
      if (!lines.length) return "";

      const chunks = [];
      let current = [];
      const flushCurrent = () => {
        if (!current.length) return;
        chunks.push(renderAssistantLineGroup(current));
        current = [];
      };

      for (let index = 0; index < lines.length; index += 1) {
        const tableSpan = getMarkdownTableSpan(lines, index);
        if (tableSpan) {
          flushCurrent();
          chunks.push(renderMarkdownTable(lines.slice(index, index + tableSpan)));
          index += tableSpan - 1;
          continue;
        }
        current.push(lines[index]);
      }

      flushCurrent();
      return chunks.join("");
    }

    function dedupeAssistantFallbackBlocks(blocks = []) {
      const seen = new Set();
      return (Array.isArray(blocks) ? blocks : []).filter((block) => {
        const lines = String(block || "")
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        if (!lines.length) return false;
        const title = lines[0].replace(/^#{1,4}\s+/, "").trim();
        const normalizedTitle = title.replace(/[【】\[\]\s*_#|:-]+/g, "");
        const normalizedBody = lines
          .join(" ")
          .replace(/[【】\[\]\s*_#|:-]+/g, "")
          .replace(/\s+/g, "")
          .toLowerCase();
        const isBudget = /预算|费用|价格|花费/u.test(normalizedTitle);
        const key = isBudget
          ? `budget:${normalizedTitle || "section"}`
          : `${normalizedTitle}:${normalizedBody}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }

    function renderAssistantFallback(blocks) {
      const uniqueBlocks = dedupeAssistantFallbackBlocks(blocks);
      return `<div class="travel-fallback">${uniqueBlocks
        .map((block) => {
          const lines = block
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean);
          return renderAssistantLines(lines);
        })
        .join("")}</div>`;
    }

    return {
      renderAssistantLines,
      renderAssistantFallback,
      renderMarkdownTable,
    };
  }

  global.ZhiXingAssistantRenderer = {
    createAssistantRenderer,
  };
})(window);
