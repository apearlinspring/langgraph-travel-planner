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
      return `知行-${safeTitle || "专属旅程"}-旅游报告.html`;
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

    function buildStandaloneReportHtml(report, stylesText = "") {
      const reportClone = prepareReportCloneForExport(report);
      const title =
        reportClone.querySelector(".travel-report-hero h3")?.textContent?.trim() ||
        "知行旅游报告";
      const generatedAt = new Date().toLocaleString("zh-CN", {
        hour12: false,
      });
      const stylesheetLinks = stylesText
        ? ""
        : Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
            .map((link) => link.href)
            .filter((href) => href && /styles\.css|font-awesome|fontawesome/i.test(href))
            .map((href) => `<link rel="stylesheet" href="${escapeHtml?.(href)}" />`)
            .join("\n");

      return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml?.(title)} - 知行旅游报告</title>
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
      .message.assistant .message-text {
        max-width: none;
      }
      .travel-report-actions,
      button {
        display: none !important;
      }
      @media print {
        body {
          background: #fff;
          padding: 0;
        }
        .report-export-meta {
          padding: 16px 18px 0;
        }
      }
    </style>
  </head>
  <body>
    <main class="report-export-shell">
      <div class="report-export-meta">
        <strong>知行 ZhiXing 旅游报告</strong>
        <span>导出时间：${escapeHtml?.(generatedAt)}</span>
      </div>
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
