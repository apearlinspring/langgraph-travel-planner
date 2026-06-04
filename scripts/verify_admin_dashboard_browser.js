const fs = require("fs");
const path = require("path");

let playwright;
try {
  playwright = require("playwright");
} catch (error) {
  console.log("admin-dashboard-browser-skip");
  console.log("Playwright is not installed in this checkout.");
  process.exit(0);
}

const repoRoot = path.resolve(__dirname, "..");
const adminPath = path.join(repoRoot, "frontend", "admin.html");
const runtimeDir = path.join(repoRoot, ".runtime");
const xssProbeUsername = 'alice <img src=x onerror="window.__adminDashboardXss=1">';
const xssProbeTitle = '川西 3 天 2 晚 <svg onload="window.__adminDashboardXss=1"></svg>';
const xssProbeReason = '验证后台审批卡片渲染。<img src=x onerror="window.__adminDashboardXss=1">';
const xssProbeMessage = '这里是最近一条助手消息摘要。<script>window.__adminDashboardXss=1</script>';

async function main() {
  fs.mkdirSync(runtimeDir, { recursive: true });
  const browser = await playwright.chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
  });

  await context.route("https://cdn.bootcdn.net/**", async (route) => {
    if (route.request().url().endsWith(".css")) {
      await route.fulfill({
        status: 200,
        contentType: "text/css",
        body: "body{font-family:sans-serif}",
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/javascript",
      body: "",
    });
  });

  await context.addInitScript(
    ({ xssProbeUsername, xssProbeTitle, xssProbeReason, xssProbeMessage }) => {
    window.localStorage.setItem("browser-regression-admin-session", "1");
    const originalFetch = window.fetch.bind(window);
    let approvalStatus = "pending";
    let approvalEvents = [
      {
        approval_id: "approval-1",
        action: "real_payment",
        event_type: "created",
        from_status: null,
        to_status: "pending",
        reason: "未来真实支付接入前必须经过人工确认。",
        created_at: 1780471200,
      },
    ];
    const json = (body, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json; charset=utf-8" },
      });

    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string" ? input : input?.url || "";
      const url = String(rawUrl);
      if (url.includes("/api/v1/users/me")) {
        if (window.localStorage.getItem("browser-regression-admin-session") !== "1") {
          return json({ detail: { message: "缺少认证令牌" } }, 401);
        }
        return json({
          id: "admin-browser-user",
          username: "dashboard-admin",
          email: "admin@example.com",
          preferences: { role: "admin" },
          created_at: "2026-06-03T10:00:00Z",
        });
      }
      if (url.includes("/api/v1/admin/overview")) {
        return json({
          total_users: 18,
          total_conversations: 42,
          active_conversations: 16,
          pending_approvals: 2,
          generated_at: "2026-06-03T10:00:00Z",
        });
      }
      if (url.includes("/api/v1/admin/users")) {
        if (/\/api\/v1\/admin\/users\/[^/?]+/.test(url)) {
          return json({
            user: {
              id: "00000000-0000-0000-0000-000000000001",
              username: xssProbeUsername,
              email: "alice@example.com",
              role: "admin",
              created_at: "2026-06-03T09:00:00Z",
              conversation_count: 5,
            },
            runtime: {
              active_conversation_count: 2,
              pending_approval_count: 1,
              latest_conversation_at: "2026-06-03T10:00:00Z",
            },
            recent_conversations: [
              {
                id: "00000000-0000-0000-0000-000000000011",
                user_id: "00000000-0000-0000-0000-000000000001",
                username: xssProbeUsername,
                email: "alice@example.com",
                role: "admin",
                title: xssProbeTitle,
                status: "active",
                created_at: "2026-06-03T09:00:00Z",
                updated_at: "2026-06-03T10:00:00Z",
                message_count: 8,
              },
              {
                id: "00000000-0000-0000-0000-000000000012",
                user_id: "00000000-0000-0000-0000-000000000001",
                username: "alice",
                email: "alice@example.com",
                role: "admin",
                title: "云南已归档样例",
                status: "archived",
                created_at: "2026-06-01T09:00:00Z",
                updated_at: "2026-06-02T10:00:00Z",
                message_count: 4,
              },
            ],
            recent_approvals: [
              {
                approval_id: "approval-1",
                action: "real_payment",
                label: "真实支付审批",
                status: approvalStatus,
                reason: xssProbeReason,
                created_at: "2026-06-03T10:00:00Z",
              },
            ],
          });
        }
        const parsed = new URL(url);
        const keyword = parsed.searchParams.get("q");
        return json({
          users:
            keyword === "bob"
              ? []
              : [
                  {
                    id: "00000000-0000-0000-0000-000000000001",
                    username: xssProbeUsername,
                    email: "alice@example.com",
                    role: "admin",
                    created_at: "2026-06-03T09:00:00Z",
                    conversation_count: 5,
                  },
                ],
          total: keyword === "bob" ? 0 : 1,
        });
      }
      if (url.includes("/api/v1/admin/conversations")) {
        if (/\/api\/v1\/admin\/conversations\/[^/?]+/.test(url)) {
          return json({
            conversation: {
              id: "00000000-0000-0000-0000-000000000011",
              user_id: "00000000-0000-0000-0000-000000000001",
              username: xssProbeUsername,
              email: "alice@example.com",
              role: "admin",
              title: xssProbeTitle,
              status: "active",
              created_at: "2026-06-03T09:00:00Z",
              updated_at: "2026-06-03T10:00:00Z",
              message_count: 8,
            },
            runtime: {
              active_workflow: "free_planning",
              current_step: "budget_summarization",
              message_breakdown: { user: 3, assistant: 5, system: 0 },
              has_latest_journey: true,
              has_final_report: true,
              latest_journey_saved_at: 1780471200,
              latest_report_title: "川西轻松 3 日旅行规划",
            },
            recent_messages: [
              {
                id: "00000000-0000-0000-0000-000000000021",
                role: "assistant",
                content_preview: xssProbeMessage,
                created_at: "2026-06-03T10:00:00Z",
                has_journey_data: true,
                has_report_data: true,
              },
            ],
            related_approvals: [
              {
                approval_id: "approval-1",
                action: "real_payment",
                label: "真实支付审批",
                status: approvalStatus,
                reason: xssProbeReason,
                created_at: "2026-06-03T10:00:00Z",
              },
            ],
          });
        }
        return json({
          conversations: [
            {
              id: "00000000-0000-0000-0000-000000000011",
              user_id: "00000000-0000-0000-0000-000000000001",
              username: xssProbeUsername,
              email: "alice@example.com",
              role: "admin",
              title: xssProbeTitle,
              status: "active",
              created_at: "2026-06-03T09:00:00Z",
              updated_at: "2026-06-03T10:00:00Z",
              message_count: 8,
            },
          ],
          total: 1,
        });
      }
      if (url.includes("/api/v1/approvals?")) {
        return json({
          approvals: [
            {
              approval_id: "approval-1",
              action: "real_payment",
              label: "真实支付审批",
              reason: xssProbeReason,
              status: approvalStatus,
              conversation_id: "00000000-0000-0000-0000-000000000011",
              created_at: "2026-06-03T10:00:00Z",
            },
          ],
          total: 1,
        });
      }
      if (url.includes("/api/v1/approvals/approval-1/approve")) {
        approvalStatus = "approved";
        approvalEvents = [
          ...approvalEvents,
          {
            approval_id: "approval-1",
            action: "real_payment",
            event_type: "approved",
            from_status: "pending",
            to_status: "approved",
            reason: "人工批准：确认当前仍不触发真实支付或预订。",
            created_at: 1780471500,
          },
        ];
        return json({
          approval_id: "approval-1",
          status: "approved",
        });
      }
      if (url.includes("/api/v1/approvals/approval-1/events")) {
        return json({
          events: approvalEvents,
          total: approvalEvents.length,
        });
      }
      return originalFetch(input, init);
    };
  },
    {
      xssProbeUsername,
      xssProbeTitle,
      xssProbeReason,
      xssProbeMessage,
    }
  );

  const page = await context.newPage();
  try {
    await page.goto(`file:///${adminPath.replace(/\\/g, "/")}`);
    await page.waitForSelector("#metricUsers", { state: "visible", timeout: 5000 });
    await page.waitForFunction(() => {
      return document.getElementById("metricUsers")?.textContent?.trim() === "18";
    });
    await page.waitForSelector("#adminUsersTable tr", { state: "visible", timeout: 5000 });
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminUserRuntime")
        ?.textContent?.includes("活跃会话");
    });
    await page.waitForSelector("#adminConversationsTable tr", {
      state: "visible",
      timeout: 5000,
    });
    await page.waitForSelector(".approval-item", { state: "visible", timeout: 5000 });
    await page.fill("#adminUserSearch", "bob");
    await page.waitForFunction(() => {
      return document.querySelector("#adminUsersTable")?.textContent?.includes("当前没有可展示的用户记录。");
    });
    await page.fill("#adminUserSearch", "");
    await page.waitForFunction(() => {
      return document.querySelector("#adminUsersTable")?.textContent?.includes("alice");
    });
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminUsersTable")
        ?.textContent?.includes("<img src=x onerror=");
    });
    const injectedNodeCount = await page
      .locator("#adminUsersTable script, #adminUsersTable img, #adminUsersTable svg, #adminApprovalsList script, #adminApprovalsList img, #adminApprovalsList svg, #adminConversationMessages script, #adminConversationMessages img, #adminConversationMessages svg")
      .count();
    if (injectedNodeCount > 0 || (await page.evaluate(() => window.__adminDashboardXss === 1))) {
      throw new Error("Admin dashboard rendered or executed unsafe HTML from API payloads.");
    }
    await page.click("[data-user-detail-id]");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminUserDetailHint")
        ?.textContent?.includes("alice");
    });
    await page.fill("#adminUserConversationSearch", "云南");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminUserConversations")
        ?.textContent?.includes("云南已归档样例");
    });
    await page.selectOption("#adminUserConversationStatusFilter", "archived");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminUserConversations")
        ?.textContent?.includes("云南已归档样例");
    });
    await page.fill("#adminUserConversationSearch", "");
    await page.selectOption("#adminUserConversationStatusFilter", "all");
    await page.click("[data-conversation-detail-id]");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminConversationRuntime")
        ?.textContent?.includes("free_planning");
    });
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminConversationMessages")
        ?.textContent?.includes("这里是最近一条助手消息摘要。");
    });
    const unsafeDetailNodeCount = await page
      .locator("#adminUserDetail script, #adminUserDetail img, #adminUserDetail svg, #adminConversationDetail script, #adminConversationDetail img, #adminConversationDetail svg, #adminApprovalEvents script, #adminApprovalEvents img, #adminApprovalEvents svg")
      .count();
    if (unsafeDetailNodeCount > 0 || (await page.evaluate(() => window.__adminDashboardXss === 1))) {
      throw new Error("Admin dashboard detail panels rendered or executed unsafe HTML.");
    }
    await page.click("[data-approval-events-id='approval-1']");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminApprovalEvents")
        ?.textContent?.includes("创建");
    });
    await page.click("#adminApprovalQuickPending");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminApprovalQuickPending")
        ?.classList.contains("active");
    });
    await page.click("[data-approval-decision='approve']");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminApprovalEvents")
        ?.textContent?.includes("批准");
    });
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminApprovalsList")
        ?.textContent?.includes("当前没有审批记录。");
    });
    await page.click("#adminApprovalQuickAll");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminApprovalsList")
        ?.textContent?.includes("approved");
    });
    await page.click("[data-approval-conversation-id='00000000-0000-0000-0000-000000000011']");
    await page.waitForFunction(() => {
      return document
        .querySelector("#adminConversationDetailHint")
        ?.textContent?.includes("川西 3 天 2 晚");
    });
    const screenshotPath = path.join(runtimeDir, "admin-dashboard-browser.png");
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log("admin-dashboard-browser-ok");
    console.log(`screenshot=${screenshotPath}`);
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error("admin-dashboard-browser-failed");
  console.error(error);
  process.exit(1);
});
