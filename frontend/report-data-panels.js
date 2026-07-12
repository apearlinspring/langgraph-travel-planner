(function (global) {
  function createReportDataPanels({
    escapeHtml,
    normalizeReportDataList,
    renderReportDataList,
    normalizeReportBudgetItems,
    formatReportDataMoney,
    getStatusLabel,
    escapeAttribute,
  } = {}) {
    function toSafeAttribute(value) {
      if (typeof escapeAttribute === "function") return escapeAttribute(value);
      return escapeHtml(value).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function renderReportDataInsightGroup({
      title = "",
      items = [],
      emptyText = "待补充",
      icon = "fa-circle-check",
      tone = "",
    } = {}) {
      const list = normalizeReportDataList(items);
      return `
          <div class="travel-report-insight-group ${tone}">
            <div class="travel-report-insight-group-head">
              <i class="fa-solid ${escapeHtml(icon)}"></i>
              <span>${escapeHtml(title)}</span>
            </div>
            ${
              list.length
                ? `<ul>${list.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
                : `<p>${escapeHtml(emptyText)}</p>`
            }
          </div>
        `;
    }

    function renderReportDataBudgetConfidence(viewModel) {
      const confidence = viewModel.budgetConfidence;
      return `
          <div class="travel-report-confidence travel-report-confidence--${escapeHtml(
            confidence.tone
          )}">
            <div class="travel-report-confidence-head">
              <span>预算置信度</span>
              <strong>${escapeHtml(confidence.level)}</strong>
              <p>把已确认价格、规则估算和出发前需要复核的项目分开看，避免把估算误当成锁价。</p>
            </div>
            <div class="travel-report-insight-grid">
              ${renderReportDataInsightGroup({
                title: "已确认 / 可追溯",
                items: confidence.confirmedItems,
                emptyText: "暂无已确认价格，正式预订前都需要二次核验。",
                icon: "fa-circle-check",
                tone: "confirmed",
              })}
              ${renderReportDataInsightGroup({
                title: "规则估算",
                items: confidence.estimatedItems,
                emptyText: "暂无估算项。",
                icon: "fa-calculator",
                tone: "estimated",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验",
                items: confidence.verificationItems,
                emptyText: "正式预订或出发前复核票价、酒店、景点开放和天气。",
                icon: "fa-clipboard-check",
                tone: "verification",
              })}
            </div>
          </div>
        `;
    }

    function renderReportDataHandoffPanel(viewModel) {
      return `
          <div class="travel-report-handoff">
            <div class="travel-report-handoff-status">
              <span>交付状态</span>
              <strong>${escapeHtml(viewModel.handoff.readiness)}</strong>
            </div>
            <div class="travel-report-insight-grid compact">
              ${renderReportDataInsightGroup({
                title: "已用依据",
                items: viewModel.handoff.usedSources,
                emptyText: "来源摘要待补充。",
                icon: "fa-file-shield",
                tone: "sources",
              })}
              ${renderReportDataInsightGroup({
                title: "待核验清单",
                items: viewModel.handoff.pendingChecks,
                emptyText: "暂无额外待核验项。",
                icon: "fa-list-check",
                tone: "verification",
              })}
              ${renderReportDataInsightGroup({
                title: "不支持承诺",
                items: viewModel.handoff.unsupportedActions,
                emptyText: "暂无额外限制说明。",
                icon: "fa-ban",
                tone: "unsupported",
              })}
            </div>
          </div>
        `;
    }

    function renderReportDataGovernancePanel(viewModel) {
      const approval = viewModel.approval || {};
      const mockCheckout = viewModel.mockCheckout || {};
      const hasMockCheckout = Boolean(mockCheckout.enabled && mockCheckout.checkoutUrl);
      const mockCheckoutBoundary =
        mockCheckout.boundary ||
        "M1 模拟确认页只验证站内跳转，不代表真实支付、真实预订、真实锁价或履约成功。";
      const unsupported = [
        "不接真实支付，不生成支付链接。",
        "不接真实预订、短信、客服或供应链下单。",
        "不承诺真实库存、真实锁价或履约成功。",
        ...normalizeReportDataList(approval.unsupportedWithoutIntegration),
      ].filter((item, index, list) => list.indexOf(item) === index);
      const statusText = approval.requiresApproval
        ? approval.pending
          ? "等待人工确认"
          : getStatusLabel(approval.status)
        : "边界记录";
      return `
          <div class="travel-report-governance">
            <div class="travel-report-governance-status">
              <div>
                <span>确认状态</span>
                <strong>${escapeHtml(statusText)}</strong>
              </div>
              <div>
                <span>动作</span>
                <strong>${escapeHtml(approval.action || "需确认动作")}</strong>
              </div>
              <div>
                <span>阻塞</span>
                <strong>${approval.isBlocking ? "阻塞真实动作" : "当前不阻塞报告交付"}</strong>
              </div>
            </div>
            <div class="travel-report-governance-boundary">
              <strong>确认边界</strong>
              <p>${escapeHtml(approval.boundary)}</p>
              ${renderReportDataList(unsupported, "暂无额外不可承诺项。")}
            </div>
            ${
              hasMockCheckout
                ? `
                  <div class="travel-report-governance-boundary">
                    <strong>M1 模拟确认页（非支付链接）</strong>
                    <p>${escapeHtml(mockCheckoutBoundary)}</p>
                    <a class="travel-report-inline-action" href="${toSafeAttribute(
                      mockCheckout.checkoutUrl
                    )}" target="_blank" rel="noopener">打开模拟确认页</a>
                    ${renderReportDataList(
                      [
                        `订单编号：${mockCheckout.orderId || "待生成"}`,
                        `真实支付：${mockCheckout.realPayment ? "是" : "否"}`,
                        `真实预订：${mockCheckout.realBooking ? "是" : "否"}`,
                        `库存锁定：${mockCheckout.inventoryLocked ? "是" : "否"}`,
                        `履约触发：${mockCheckout.fulfillmentTriggered ? "是" : "否"}`,
                      ],
                      "暂无模拟订单状态。"
                    )}
                  </div>
                `
                : ""
            }
          </div>
        `;
    }

    function renderReportDataBudgetItems(budget = {}) {
      const items = normalizeReportBudgetItems(budget);
      const total = formatReportDataMoney(budget.total);

      return `
          <div class="travel-report-budget-table-wrap">
            <table class="travel-report-budget-table">
              <thead>
                <tr>
                  <th>类别</th>
                  <th>金额</th>
                  <th>依据</th>
                </tr>
              </thead>
              <tbody>
                ${items
                  .map(
                    (item) => `
                      <tr>
                        <th scope="row">
                          <i class="fa-solid ${escapeHtml(item.icon || "fa-wallet")}"></i>
                          ${escapeHtml(item.label || "预算项")}
                        </th>
                        <td>${escapeHtml(formatReportDataMoney(item.amount) || "待核验")}</td>
                        <td>${escapeHtml(item.basis || "出发前需要二次核验")}</td>
                      </tr>
                    `
                  )
                  .join("")}
              </tbody>
            </table>
            <div class="travel-report-budget-total-line">
              <span>当前估算合计</span>
              <strong>${escapeHtml(total || "待核验")}</strong>
            </div>
            ${budget.fit ? `<p class="travel-report-budget-fit">${escapeHtml(budget.fit)}</p>` : ""}
          </div>
        `;
    }

    return {
      renderReportDataBudgetConfidence,
      renderReportDataHandoffPanel,
      renderReportDataGovernancePanel,
      renderReportDataBudgetItems,
    };
  }

  global.ZhiXingReportDataPanels = {
    createReportDataPanels,
  };
})(window);
