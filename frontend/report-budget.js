(function (global) {
  function createReportBudget(deps = {}) {
    const {
      normalizeSectionTitle,
      getMarkdownTableSpan,
      splitTableCells,
      isMeaningfulBudgetAmount,
      renderAssistantLines,
      formatInlineText,
      escapeHtml,
    } = deps;

    function normalizeTravelBudgetTitle(title = "") {
      return /预算|费用|花费|价格|成本/u.test(title)
        ? "预算参考"
        : normalizeSectionTitle?.(title);
    }

    function stripDisplayListPrefix(line = "") {
      return String(line || "")
        .replace(/^[-*•]\s*/, "")
        .replace(/^\d+\.\s*/, "")
        .trim();
    }

    function extractTravelBudgetRows(lines = []) {
      const compactLines = lines
        .map((line) => line.trim())
        .filter((line) => line && !/^-{1,3}$/.test(line));

      const tableStart = compactLines.findIndex((_, index) =>
        Boolean(getMarkdownTableSpan?.(compactLines, index))
      );
      const tableSpan =
        tableStart >= 0 ? getMarkdownTableSpan?.(compactLines, tableStart) : 0;
      if (tableStart >= 0 && tableSpan) {
        const tableLines = compactLines.slice(tableStart, tableStart + tableSpan);
        const rows = tableLines
          .slice(2)
          .map((line) => splitTableCells?.(line))
          .filter((cells) => cells?.some(Boolean))
          .map((cells) => ({
            label: stripDisplayListPrefix(cells[0] || "费用项"),
            amount: (cells[1] || cells[cells.length - 1] || "待核验").trim(),
            note: cells.slice(2).filter(Boolean).join("；"),
          }));
        return rows.filter(
          (row) => row.label && row.amount && isMeaningfulBudgetAmount?.(row.amount)
        );
      }

      const joined = compactLines.join("；");
      const rows = [];
      const pattern =
        /(交通|大交通|往返|住宿|酒店|民宿|餐饮|美食|门票|游船|景点|体验|市内交通|服务\/预留|服务|预留|伴手礼|其他|机动|合计|总计)[^~￥¥\d]{0,14}([~约￥¥]?\s*\d[\d,.]*(?:\s*[-~]\s*\d[\d,.]*)?\s*元?)/gu;
      let match;
      while ((match = pattern.exec(joined))) {
        const label = match[1].replace(/往返$/, "交通");
        const amount = match[2].replace(/\s+/g, "");
        if (!isMeaningfulBudgetAmount?.(amount)) continue;
        const key = `${label}-${amount}`;
        if (!amount || rows.some((row) => `${row.label}-${row.amount}` === key)) continue;
        rows.push({ label, amount, note: "" });
      }
      return rows.slice(0, 8);
    }

    function getTravelBudgetIcon(label = "") {
      if (/交通|往返|高铁|火车|航班|机票|车/u.test(label)) return "fa-train-subway";
      if (/住宿|酒店|民宿|房/u.test(label)) return "fa-bed";
      if (/餐|美食|吃/u.test(label)) return "fa-utensils";
      if (/门票|景点|游船|体验/u.test(label)) return "fa-ticket";
      if (/服务|预留|机动|缓冲/u.test(label)) return "fa-shield-heart";
      if (/合计|总计|预算/u.test(label)) return "fa-calculator";
      return "fa-wallet";
    }

    function parseBudgetAmountRange(amount = "") {
      const raw = String(amount || "").replace(/,/g, "");
      const matches = Array.from(raw.matchAll(/(\d+(?:\.\d+)?)/g)).map((item) =>
        Number(item[1])
      );
      const values = matches.filter((value) => Number.isFinite(value) && value > 0);
      if (!values.length) return null;
      if (values.length >= 2 && /[-~到至]/u.test(raw)) {
        return { min: Math.min(values[0], values[1]), max: Math.max(values[0], values[1]) };
      }
      return { min: values[0], max: values[0] };
    }

    function formatBudgetAmountRange(range) {
      if (!range || !Number.isFinite(range.min) || !Number.isFinite(range.max)) return "待核验";
      const min = Math.round(range.min);
      const max = Math.round(range.max);
      return min === max ? `${min}元` : `${min}-${max}元`;
    }

    function estimateBudgetTotalRow(rows = []) {
      const explicit = rows.find((row) => /合计|总计|总预算/u.test(row.label));
      if (explicit) return { row: explicit, synthetic: false };
      const subtotalRows = rows.filter(
        (row) => !/当前估算|预算参考|预算|人均|每人/u.test(row.label)
      );
      const ranges = subtotalRows
        .map((row) => parseBudgetAmountRange(row.amount))
        .filter(Boolean);
      if (!ranges.length) {
        return { row: rows[rows.length - 1], synthetic: false };
      }
      const total = ranges.reduce(
        (sum, range) => ({
          min: sum.min + range.min,
          max: sum.max + range.max,
        }),
        { min: 0, max: 0 }
      );
      return {
        row: {
          label: "估算合计",
          amount: formatBudgetAmountRange(total),
          note: "按分项加总，待出发前核验",
        },
        synthetic: true,
      };
    }

    function renderTravelBudgetCardBody(lines = [], reminderLines = []) {
      const rows = extractTravelBudgetRows(lines);
      const reminders = reminderLines.map(stripDisplayListPrefix).filter(Boolean).slice(0, 4);
      if (!rows.length) {
        return `
            <div class="travel-budget-layout">
              <div class="travel-budget-main">${renderAssistantLines?.(lines)}</div>
              ${
                reminders.length
                  ? `<aside class="travel-budget-reminders">
                      <span>出发前确认</span>
                      <ul>${reminders
                        .map((item) => `<li>${formatInlineText?.(item)}</li>`)
                        .join("")}</ul>
                    </aside>`
                  : ""
              }
            </div>
          `;
      }

      const totalInfo = estimateBudgetTotalRow(rows);
      const totalRow = totalInfo.row;
      return `
          <div class="travel-budget-layout">
            <div class="travel-budget-main">
              <div class="travel-budget-total">
                <span>当前估算</span>
                <strong>${escapeHtml?.(totalRow.amount || "待核验")}</strong>
              </div>
              <div class="travel-budget-rows">
                ${rows
                  .filter((row) => totalInfo.synthetic || row !== totalRow || rows.length === 1)
                  .map(
                    (row) => `
                      <div class="travel-budget-row">
                        <span class="travel-budget-row-icon">
                          <i class="fa-solid ${getTravelBudgetIcon(row.label)}"></i>
                        </span>
                        <div>
                          <strong>${escapeHtml?.(row.label)}</strong>
                          ${row.note ? `<small>${formatInlineText?.(row.note)}</small>` : ""}
                        </div>
                        <em>${escapeHtml?.(row.amount || "待核验")}</em>
                      </div>
                    `
                  )
                  .join("")}
              </div>
            </div>
            <aside class="travel-budget-reminders">
              <span>出发前确认</span>
              ${
                reminders.length
                  ? `<ul>${reminders
                      .map((item) => `<li>${formatInlineText?.(item)}</li>`)
                      .join("")}</ul>`
                  : `<p>交通票价、住宿价格和热门项目名额会随日期变化，正式出发前再核验一次。</p>`
              }
            </aside>
          </div>
        `;
    }

    function isPrematureTravelBudgetSection(section = {}) {
      if (section.tone !== "budget") return false;
      const rows = extractTravelBudgetRows(section.rawLines || []);
      if (!rows.length) return false;
      const labels = rows.map((row) => String(row.label || ""));
      const hasTripCostItem = labels.some((label) =>
        /交通|大交通|机票|高铁|酒店|住宿|门票|景点|服务|地接|专车|合计|总计|总预算/u.test(label)
      );
      const onlyMealEstimate = labels.every((label) =>
        /美食|餐饮|餐厅|吃|用餐/u.test(label)
      );
      return rows.length <= 1 && (!hasTripCostItem || onlyMealEstimate);
    }

    return {
      normalizeTravelBudgetTitle,
      renderTravelBudgetCardBody,
      isPrematureTravelBudgetSection,
      extractTravelBudgetRows,
    };
  }

  global.ZhiXingReportBudget = {
    createReportBudget,
  };
})(window);
