"""M1-only mock checkout endpoints.

The endpoints are intentionally local and non-transactional. They support an
internal demo redirect for generated ORDER ids without creating real payment,
booking, inventory, or fulfillment side effects.
"""
from __future__ import annotations

from html import escape
import re

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter(prefix="/mock-checkout", tags=["M1模拟订单跳转"])

ORDER_ID_PATTERN = re.compile(r"^ORDER-[A-Z0-9]{8,32}$")


def _normalize_order_id(order_id: str) -> str:
    normalized = str(order_id or "").strip().upper()
    if not ORDER_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_mock_order_id",
                "message": "Mock checkout only accepts generated ORDER ids.",
            },
        )
    return normalized


@router.get("/{order_id}", response_class=HTMLResponse)
async def show_mock_checkout(order_id: str) -> HTMLResponse:
    """Render a local demo checkout page for a generated mock order."""

    safe_order_id = _normalize_order_id(order_id)
    escaped_order_id = escape(safe_order_id)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M1 模拟确认 - {escaped_order_id}</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #17202a;
    }}
    main {{
      width: min(720px, calc(100% - 32px));
      margin: 10vh auto;
      padding: 28px;
      background: #fff;
      border: 1px solid #d7dde5;
      border-radius: 8px;
      box-shadow: 0 10px 30px rgba(20, 34, 48, 0.08);
    }}
    h1 {{ margin: 0 0 12px; font-size: 24px; }}
    p {{ line-height: 1.7; }}
    .order {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    .actions {{ margin-top: 22px; display: flex; gap: 12px; flex-wrap: wrap; }}
    a {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      padding: 0 14px;
      border-radius: 6px;
      text-decoration: none;
      color: #fff;
      background: #0f766e;
    }}
    a.secondary {{ background: #475569; }}
  </style>
</head>
<body>
  <main>
    <h1>M1 模拟订单确认</h1>
    <p>订单号：<span class="order">{escaped_order_id}</span></p>
    <p>这是受控试运行的演示确认页，只证明报告到确认页的跳转链路可用。它不会发起真实支付、扣款、锁库存、出票、预订酒店或通知供应商。</p>
    <div class="actions">
      <a href="/api/v1/mock-checkout/{escaped_order_id}/complete">模拟确认并返回</a>
      <a class="secondary" href="/">返回首页</a>
    </div>
  </main>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/{order_id}/complete")
async def complete_mock_checkout(order_id: str) -> RedirectResponse:
    """Redirect back to the frontend with a mock confirmation marker."""

    safe_order_id = _normalize_order_id(order_id)
    return RedirectResponse(
        url=f"/?mock_checkout=confirmed&order_id={safe_order_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{order_id}/status")
async def get_mock_checkout_status(order_id: str) -> dict[str, object]:
    """Return a redacted machine-readable mock checkout status."""

    safe_order_id = _normalize_order_id(order_id)
    return {
        "order_id": safe_order_id,
        "status": "demo_only",
        "payment_status": "not_applicable",
        "booking_status": "not_applicable",
        "real_payment": False,
        "real_booking": False,
        "inventory_locked": False,
        "fulfillment_triggered": False,
        "boundary": "M1 mock checkout only proves internal redirect behavior.",
    }
