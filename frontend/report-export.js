(function (global) {
  function createReportExport(deps = {}) {
    const {
      getCurrentConversationTitle,
      escapeHtml,
    } = deps;

    function buildTravelReportFilename(report) {
      const title =
        report.querySelector(".travel-report-hero h3")?.textContent?.trim() ||
        getCurrentConversationTitle?.() ||
        "专属旅程";
      const safeTitle = title
        .replace(/[\\/:*?"<>|]/g, "-")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 40);
      return `知行-${safeTitle || "专属旅程"}-旅游报告-${formatExportDateStamp()}.html`;
    }

    function formatExportDateStamp(date = new Date()) {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${year}${month}${day}`;
    }

    function safeHtml(value = "") {
      if (typeof escapeHtml === "function") return escapeHtml(value);
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function cleanExportText(value = "") {
      return String(value || "").replace(/\s+/g, " ").trim();
    }

    function limitExportText(value = "", maxLength = 110) {
      const text = cleanExportText(value);
      if (text.length <= maxLength) return text;
      return `${text.slice(0, maxLength - 1)}…`;
    }

    function collectLoadedExportStyles() {
      const chunks = [];
      Array.from(document.styleSheets || []).forEach((sheet) => {
        try {
          const rules = Array.from(sheet.cssRules || []);
          if (rules.length) {
            chunks.push(rules.map((rule) => rule.cssText).join("\n"));
          }
        } catch (error) {
          // 跨域图标样式可能不可读；导出只需要保留本地报告样式。
        }
      });
      return chunks.join("\n");
    }

    async function loadExportStyles() {
      const loadedStyles = collectLoadedExportStyles();
      if (loadedStyles) return loadedStyles;
      if (window.location.protocol === "file:") return "";
      try {
        const response = await fetch("./styles.css", { cache: "no-store" });
        if (response.ok) {
          return await response.text();
        }
      } catch (error) {
        console.warn("Failed to load export styles", error);
      }
      return "";
    }

    function prepareReportCloneForExport(report) {
      const clone = report.cloneNode(true);
      clone
        .querySelectorAll(
          [
            ".travel-report-actions",
            ".journey-map-action-btn",
            ".journey-map-style-btn",
            ".journey-map-focus-btn",
            ".journey-map-day-btn",
            ".journey-map-day-mode-btn",
            ".travel-card-link-btn",
            "button",
          ].join(",")
        )
        .forEach((node) => node.remove());
      return clone;
    }

    function buildReportExportDigest(reportClone) {
      const title =
        cleanExportText(reportClone.querySelector(".travel-report-hero h3")?.textContent) ||
        "知行旅游报告";
      const sourceLabel =
        reportClone.dataset.reportSource === "structured"
          ? "结构化 report_data 报告"
          : "当前前台报告视图";
      const metrics = Array.from(reportClone.querySelectorAll(".travel-report-metrics span"))
        .map((node) => cleanExportText(node.textContent))
        .filter(Boolean)
        .slice(0, 4);
      const highlights = Array.from(reportClone.querySelectorAll(".travel-report-card"))
        .map((card) => {
          const label = cleanExportText(
            card.querySelector(".travel-report-card-label")?.textContent
          );
          const titleText = cleanExportText(card.querySelector("h4")?.textContent);
          const body = limitExportText(card.querySelector(".travel-report-card-body")?.textContent);
          return {
            title: [label, titleText].filter(Boolean).join(" - "),
            body,
          };
        })
        .filter((item) => item.title || item.body)
        .slice(0, 3);
      return { title, sourceLabel, metrics, highlights };
    }

    function renderReportExportDigest(digest, generatedAt) {
      const metricsHtml = digest.metrics.length
        ? digest.metrics.map((item) => `<li>${safeHtml(item)}</li>`).join("")
        : "<li>报告要素待核验</li>";
      const highlightsHtml = digest.highlights.length
        ? digest.highlights
            .map(
              (item) => `
                <article>
                  <strong>${safeHtml(item.title || "报告要点")}</strong>
                  ${item.body ? `<p>${safeHtml(item.body)}</p>` : ""}
                </article>
              `
            )
            .join("")
        : "";

      return `
        <section class="report-export-cover" aria-label="报告交付摘要">
          <div class="report-export-kicker">报告交付摘要</div>
          <h1>${safeHtml(digest.title)}</h1>
          <p>
            这份 HTML 报告来自当前知行前台报告视图，可离线查看和转发；动态票价、库存、天气、
            预约状态和真实价格仍需出发前核验。
          </p>
          <div class="report-export-stamps">
            <span>来源：${safeHtml(digest.sourceLabel)}</span>
            <span>导出时间：${safeHtml(generatedAt)}</span>
          </div>
          <ul class="report-export-facts">
            ${metricsHtml}
          </ul>
          ${highlightsHtml ? `<div class="report-export-highlights">${highlightsHtml}</div>` : ""}
          <div class="report-export-boundary">
            <strong>待核验项</strong>
            <span>导出不代表真实支付、预订、出票、锁价或履约完成；请在成交或出发前人工确认关键服务。</span>
          </div>
        </section>
      `;
    }

    function buildStandaloneReportHtml(report, stylesText = "") {
      const reportClone = prepareReportCloneForExport(report);
      const exportDigest = buildReportExportDigest(reportClone);
      const title = exportDigest.title;
      const generatedAt = new Date().toLocaleString("zh-CN", {
        hour12: false,
      });
      const stylesheetLinks = stylesText
        ? ""
        : Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
            .map((link) => link.href)
            .filter((href) => href && /styles\.css|font-awesome|fontawesome/i.test(href))
            .map((href) => `<link rel="stylesheet" href="${safeHtml(href)}" />`)
            .join("\n");

      return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${safeHtml(title)} - 知行旅游报告</title>
    <link rel="stylesheet" href="https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    ${stylesheetLinks}
    <style>
      ${stylesText}
      body {
        margin: 0;
        min-height: 100vh;
        padding: 34px;
        background:
          radial-gradient(circle at top left, rgba(194, 142, 92, 0.14), transparent 34%),
          linear-gradient(135deg, #f7f3ea, #eef6f3);
        color: #2c3e50;
      }
      .report-export-shell {
        max-width: 1120px;
        margin: 0 auto;
      }
      .report-export-meta {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: center;
        margin-bottom: 16px;
        color: rgba(26, 77, 84, 0.72);
        font-size: 13px;
      }
      .report-export-cover {
        display: grid;
        gap: 16px;
        margin-bottom: 18px;
        padding: 24px;
        border-radius: 24px;
        background:
          linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(246, 251, 249, 0.94));
        border: 1px solid rgba(26, 77, 84, 0.12);
        box-shadow: 0 18px 42px rgba(19, 52, 57, 0.08);
      }
      .report-export-kicker {
        color: #1a4d54;
        font-size: 12px;
        font-weight: 900;
      }
      .report-export-cover h1 {
        margin: 0;
        color: #173f45;
        font-size: 30px;
        line-height: 1.18;
      }
      .report-export-cover p {
        margin: 0;
        max-width: 820px;
        color: rgba(34, 53, 56, 0.78);
        line-height: 1.8;
      }
      .report-export-stamps,
      .report-export-facts {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .report-export-stamps span,
      .report-export-facts li {
        padding: 8px 11px;
        border-radius: 999px;
        background: rgba(26, 77, 84, 0.08);
        color: #1a4d54;
        font-size: 12px;
        font-weight: 800;
      }
      .report-export-highlights {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 10px;
      }
      .report-export-highlights article,
      .report-export-boundary {
        padding: 14px;
        border-radius: 16px;
        background: rgba(255, 252, 246, 0.92);
        border: 1px solid rgba(194, 142, 92, 0.16);
      }
      .report-export-highlights strong,
      .report-export-boundary strong {
        display: block;
        margin-bottom: 6px;
        color: #173f45;
        font-size: 13px;
      }
      .report-export-boundary span {
        color: rgba(34, 53, 56, 0.78);
        line-height: 1.7;
      }
      .message.assistant .message-text {
        max-width: none;
      }
      .report-export-shell .message.assistant {
        margin: 0;
      }
      .report-export-shell .message.assistant .message-text .travel-report {
        display: grid;
        gap: 16px;
        color: #173f45;
      }
      .report-export-shell .message.assistant .message-text .travel-report-hero {
        padding: 24px;
        border-radius: 24px;
        background:
          linear-gradient(135deg, #0f5159 0%, #1d6063 62%, #8b5a38 100%);
        color: #fffaf0;
        box-shadow: 0 18px 42px rgba(19, 52, 57, 0.12);
      }
      .report-export-shell .message.assistant .message-text .travel-report-hero h3 {
        margin: 14px 0 8px;
        font-size: 30px;
        line-height: 1.18;
        color: #fffaf0;
      }
      .report-export-shell .message.assistant .message-text .travel-report-hero p {
        margin: 0;
        max-width: 720px;
        color: rgba(255, 250, 240, 0.86);
        line-height: 1.75;
      }
      .report-export-shell .message.assistant .message-text .travel-report-kicker,
      .report-export-shell .message.assistant .message-text .travel-report-metrics span {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 11px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: #fffaf0;
        font-size: 12px;
        font-weight: 800;
      }
      .report-export-shell .message.assistant .message-text .travel-report-metrics {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 16px;
      }
      .report-export-shell .message.assistant .message-text .travel-report-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card,
      .report-export-shell .message.assistant .message-text .travel-report-next-action,
      .report-export-shell .message.assistant .message-text .travel-report-map {
        padding: 18px;
        border-radius: 20px;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(26, 77, 84, 0.1);
        box-shadow: 0 12px 28px rgba(19, 52, 57, 0.06);
      }
      .report-export-shell .message.assistant .message-text .travel-report-card.daily,
      .report-export-shell .message.assistant .message-text .travel-report-card.budget,
      .report-export-shell .message.assistant .message-text .travel-report-map,
      .report-export-shell .message.assistant .message-text .travel-report-next-action {
        grid-column: 1 / -1;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card-head {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        margin-bottom: 12px;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card-icon {
        width: 38px;
        height: 38px;
        border-radius: 14px;
        background: rgba(26, 77, 84, 0.08);
        flex: 0 0 auto;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card-label {
        color: #b06a2a;
        font-size: 12px;
        font-weight: 800;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card h4,
      .report-export-shell .message.assistant .message-text .travel-report-next-action h4 {
        margin: 2px 0 0;
        color: #0f5159;
        font-size: 20px;
      }
      .report-export-shell .message.assistant .message-text .travel-report-card-body,
      .report-export-shell .message.assistant .message-text .travel-report-day-copy,
      .report-export-shell .message.assistant .message-text .travel-report-next-action {
        color: #20383c;
        line-height: 1.75;
      }
      .report-export-shell .message.assistant .message-text .travel-report-days {
        display: grid;
        gap: 12px;
      }
      .report-export-shell .message.assistant .message-text .travel-report-day {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 14px;
        padding: 14px;
        border-radius: 16px;
        background: rgba(237, 247, 245, 0.68);
        border: 1px solid rgba(26, 77, 84, 0.1);
      }
      .report-export-shell .message.assistant .message-text .travel-report-day-badge {
        min-width: 44px;
        height: 44px;
        border-radius: 14px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #0f5159;
        color: #fffaf0;
        font-weight: 900;
      }
      .report-export-shell .message.assistant .message-text .travel-report-day h5 {
        margin: 0 0 8px;
        color: #0f5159;
        font-size: 17px;
      }
      .report-export-shell .message.assistant .message-text table {
        width: 100%;
        border-collapse: collapse;
        overflow-wrap: anywhere;
      }
      .report-export-shell .message.assistant .message-text th,
      .report-export-shell .message.assistant .message-text td {
        padding: 10px 12px;
        border-bottom: 1px solid rgba(26, 77, 84, 0.1);
        text-align: left;
      }
      .report-export-shell .message.assistant .message-text th:nth-child(2),
      .report-export-shell .message.assistant .message-text td:nth-child(2) {
        white-space: nowrap;
      }
      .travel-report-actions,
      button {
        display: none !important;
      }
      @media (max-width: 720px) {
        body {
          padding: 18px;
        }
        .report-export-meta {
          align-items: flex-start;
          flex-direction: column;
        }
        .report-export-cover,
        .report-export-shell .message.assistant .message-text .travel-report-hero {
          padding: 18px;
          border-radius: 20px;
        }
        .report-export-cover h1,
        .report-export-shell .message.assistant .message-text .travel-report-hero h3 {
          font-size: 25px;
        }
        .report-export-shell .message.assistant .message-text .travel-report-grid {
          grid-template-columns: 1fr;
        }
        .report-export-shell .message.assistant .message-text .travel-report-day {
          grid-template-columns: 1fr;
        }
        .report-export-shell .message.assistant .message-text table {
          font-size: 14px;
        }
        .report-export-shell .message.assistant .message-text th,
        .report-export-shell .message.assistant .message-text td {
          padding: 9px 7px;
        }
      }
      @media print {
        body {
          background: #fff;
          padding: 0;
        }
        .report-export-meta {
          padding: 16px 18px 0;
        }
        .report-export-cover {
          border-radius: 0;
          box-shadow: none;
        }
      }
    </style>
  </head>
  <body>
    <main class="report-export-shell">
      <div class="report-export-meta">
        <strong>知行 ZhiXing 旅游报告</strong>
        <span>导出时间：${safeHtml(generatedAt)}</span>
      </div>
      ${renderReportExportDigest(exportDigest, generatedAt)}
      <section class="message assistant">
        <div class="message-text">
          ${reportClone.outerHTML}
        </div>
      </section>
    </main>
  </body>
</html>`;
    }

    async function exportTravelReport(report) {
      const stylesText = await loadExportStyles();
      const html = buildStandaloneReportHtml(report, stylesText);
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = buildTravelReportFilename(report);
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    return {
      exportTravelReport,
    };
  }

  global.ZhiXingReportExport = {
    createReportExport,
  };
})(window);
