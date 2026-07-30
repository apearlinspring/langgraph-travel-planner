"""服务端固定条款与客户同意证据的规范化构造。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from app.agency.transaction_payloads import canonical_payload_hash


CUSTOMER_CONSENT_EVIDENCE_SCHEMA = "agency_customer_consent_evidence.v1"
CUSTOMER_CONSENT_VERSION = "agency-customer-consent.v1"
CUSTOMER_CONSENT_DOCUMENT_SHA256 = (
    "c04d7a7792dcd190e0cc8b738d40ea217da40fffac7dfdeeabe8537830449e67"
)
CUSTOMER_CONSENT_CHANNEL = "authenticated_api"
CUSTOMER_CONSENT_NOTICE_MARKDOWN = """# 旅行社客户关系授权告知 v1

版本：`agency-customer-consent.v1`

本告知用于记录平台内旅行社客户关系的技术授权事实，不替代旅行社依法应当提供的隐私政策、合同条款、身份核验或法务审查。

客户确认后，同意当前旅行社在平台内：

- 将已登录的平台账号与该旅行社的客户关系关联；
- 为需求沟通、方案制作、报价、订单内部审核和旅行服务交付处理该关系产生的业务数据；
- 由获得相应门店权限的工作人员在授权范围内查看和处理相关业务记录；
- 保存授权决定、条款版本、服务端时间和不可逆摘要，用于平台内审计。

客户可以拒绝或撤回授权。拒绝、撤回或停用关系会阻止新的平台内交易，并收口仍可安全处理的内部报价和订单状态；这不等于供应商预订已经取消、款项已经退款或通知已经送达。

当前客户生命周期模块不保存姓名、电话、证件号码等个人可识别信息，也未接入邀请通知、供应商取消或退款。真实业务上线前，旅行社仍须完成适用法律下的告知、最小必要性、留存期限、主体权利和外部处理者审查。
"""

if (
    hashlib.sha256(
        CUSTOMER_CONSENT_NOTICE_MARKDOWN.encode("utf-8")
    ).hexdigest()
    != CUSTOMER_CONSENT_DOCUMENT_SHA256
):
    raise RuntimeError("customer consent notice hash is out of sync")

CONSENT_DECISION_TO_STATUS = {
    "grant": "granted",
    "deny": "denied",
    "revoke": "revoked",
}


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_customer_consent_evidence(
    *,
    agency_id: uuid.UUID,
    branch_id: uuid.UUID,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    claim_invitation_id: uuid.UUID | None,
    decision: str,
    recorded_at: datetime,
    action: str = "consent",
) -> tuple[dict[str, Any], str]:
    """构造可复算的服务端证据负载及 SHA-256 摘要。"""

    consent_status = CONSENT_DECISION_TO_STATUS[decision]
    payload: dict[str, Any] = {
        "schema": CUSTOMER_CONSENT_EVIDENCE_SCHEMA,
        "source": "server_canonical",
        "channel": CUSTOMER_CONSENT_CHANNEL,
        "action": action,
        "agency_id": str(agency_id),
        "branch_id": str(branch_id),
        "customer_id": str(customer_id),
        "user_id": str(user_id),
        "claim_invitation_id": (
            str(claim_invitation_id)
            if claim_invitation_id is not None
            else None
        ),
        "decision": decision,
        "consent_status": consent_status,
        "consent_version": CUSTOMER_CONSENT_VERSION,
        "terms_document_sha256": CUSTOMER_CONSENT_DOCUMENT_SHA256,
        "recorded_at": _utc_text(recorded_at),
    }
    return payload, canonical_payload_hash(payload)
