"""
流式对话 API（SSE）
"""
import json
import asyncio
import time
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from app.models.base import get_db
from app.models.user import User
from app.models.conversation import Conversation
from app.models.message import Message
from app.schemas.message import MessageCreate
from app.api.dependencies import get_current_user
from app.agents.handoffs.travel_agent import create_travel_agent
from app.config import settings
from app.core.session_lock import SessionLockBusy, acquire_session_lock
from app.core.approval import ApprovalGovernanceManager
from app.tools.audit import (
    build_tool_audit_event,
    persist_tool_audit_events,
    start_tool_audit,
    summarize_tool_input,
    summarize_tool_output,
)
from app.tools.result_validation import (
    evidence_type_for_tool_name,
    validate_tool_output_for_audit,
)
from app.utils.logger import app_logger

router = APIRouter(prefix="/chat", tags=["对话"])

SESSION_BUSY_MESSAGE = "当前会话正在处理上一轮消息，请稍后再试。"


async def save_message(
        db: AsyncSession,
        conversation_id: str,
        role: str,
        content: str,
        extra_info: dict = None
) -> Message:
    """保存消息到数据库"""

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        extra_info=extra_info or {}
    )

    db.add(message)
    await db.commit()
    await db.refresh(message)

    return message


def sse(data: dict) -> str:
    """
    SSE 标准 data 帧
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _session_busy_payload(
    conversation_id: str,
    active_lock=None,
) -> dict:
    payload = {
        "type": "session_busy",
        "content": SESSION_BUSY_MESSAGE,
        "conversation_id": conversation_id,
        "retry_after_seconds": settings.session_lock_busy_retry_after_seconds,
    }
    if active_lock is not None:
        payload["lock_backend"] = active_lock.backend
        payload["active_seconds"] = round(time.time() - active_lock.acquired_at, 2)
        if active_lock.expires_at is not None:
            payload["expires_in_seconds"] = max(
                round(active_lock.expires_at - time.time(), 2),
                0,
            )
    return payload


def _extract_command_update(output) -> dict:
    """Extract LangGraph Command.update from a tool event output."""
    update = getattr(output, "update", None)
    if isinstance(update, dict):
        return update
    if isinstance(output, dict):
        nested_update = output.get("update")
        if isinstance(nested_update, dict):
            return nested_update
    return {}


def _report_extra_info_from_tool_output(output) -> dict:
    """Build persisted message metadata from generate_order_tool output."""
    update = _extract_command_update(output)
    report_data = update.get("report_data")
    if not isinstance(report_data, dict):
        return {}

    extra_info = {
        "message_type": "travel_report",
        "report_data": report_data,
    }
    if update.get("order_id"):
        extra_info["order_id"] = update["order_id"]
    return extra_info


def _report_content_from_tool_output(output) -> str:
    """Extract a user-visible report string from generate_order_tool output."""
    update = _extract_command_update(output)
    report = update.get("report")
    if isinstance(report, str) and report.strip():
        return report

    messages = update.get("messages")
    if isinstance(messages, list):
        for message in messages:
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content
    return ""


def _is_transient_stream_disconnect(exc: Exception) -> bool:
    message = str(exc)
    return (
        "peer closed connection without sending complete message body" in message
        or "incomplete chunked read" in message
    )


def _extract_embedded_tool_audit_events(output) -> list[dict]:
    update = getattr(output, "update", None)
    if isinstance(output, dict):
        update = output.get("update", update)
    if not isinstance(update, dict):
        return []
    events = update.get("tool_audit_events") or []
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _audit_event_key(event: dict) -> tuple:
    return (
        event.get("name"),
        event.get("started_at"),
        event.get("status"),
        event.get("error_type"),
    )


def _new_tool_audit_events(events: list[dict], existing_events: list[dict]) -> list[dict]:
    existing_keys = {_audit_event_key(event) for event in existing_events}
    new_events: list[dict] = []
    for event in events:
        key = _audit_event_key(event)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        new_events.append(event)
    return new_events


async def _persist_tool_audit_events_safely(
        db: AsyncSession,
        *,
        events: list[dict],
        user_id: str,
        conversation_id: str,
) -> dict:
    if not events:
        return {"status": "skipped", "reason": "no_events"}
    if not callable(getattr(db, "add", None)):
        return {
            "status": "skipped",
            "reason": "non_sqlalchemy_session",
            "persistent": False,
        }
    try:
        await persist_tool_audit_events(
            db,
            events,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return {"status": "persisted", "count": len(events), "persistent": True}
    except Exception as error:
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            await rollback()
        error_type = error.__class__.__name__
        ApprovalGovernanceManager.mark_tool_audit_persistence_failed(error)
        app_logger.exception(
            "工具审计事件持久化失败，已保留在消息 extra_info 中: "
            f"conversation_id={conversation_id}, user_id={user_id}"
        )
        return {
            "status": "degraded",
            "persistent": False,
            "error_type": error_type,
            "message": "工具审计事件未能写入 PostgreSQL，已记录降级状态。",
        }


async def generate_sse_stream(
        conversation_id: str,
        user_message: str,
        db: AsyncSession,
        user: User
):
    assistant_message = ""
    request_started_at = time.perf_counter()
    first_token_elapsed = None
    tool_started_at = {}
    tool_audit_context_by_run = {}
    tool_input_by_run = {}
    tool_name_by_run = {}
    tool_audit_events = []
    emitted_tool_call_names = set()
    assistant_extra_info = {}
    fallback_assistant_message = ""
    session_lock = None
    final_report_emitted = False

    try:
        try:
            session_lock = await acquire_session_lock(
                conversation_id,
                wait_seconds=settings.session_lock_acquire_wait_seconds,
            )
        except SessionLockBusy as lock_error:
            active_lock = lock_error.active_lock
            active_since = (
                round(time.time() - active_lock.acquired_at, 2)
                if active_lock is not None
                else None
            )
            app_logger.warning(
                "SSE chat rejected because conversation is busy: "
                f"conversation_id={conversation_id}, user_id={user.id}, "
                f"active_seconds={active_since}, "
                f"lock_backend={(active_lock.backend if active_lock else 'unknown')}"
            )
            yield sse(_session_busy_payload(conversation_id, active_lock))
            yield sse({"type": "done"})
            return

        session_lock.start_auto_renew(
            settings.session_lock_renew_interval_seconds
        )
        app_logger.info(
            "SSE chat started: "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"message_length={len(user_message)}, "
            f"lock_backend={session_lock.snapshot.backend}, "
            f"lock_wait_seconds={session_lock.snapshot.wait_seconds:.3f}, "
            f"lock_ttl_seconds={session_lock.snapshot.ttl_seconds:.1f}"
        )
        # 1. 保存用户消息
        await save_message(db, conversation_id, "user", user_message)

        # 2. 创建 agent
        agent = await create_travel_agent()

        # 3. 关键修复：输入必须是字典格式！
        # LangGraph StateGraph 期望输入是 state 的部分更新
        input_data = {
            "messages": [HumanMessage(content=user_message)],
            "user_id": str(user.id),
        }

        # 4. 使用 astream_events 获取更细粒度的流式输出
        async for event in agent.astream_events(
                input_data,
                config={
                    "recursion_limit": settings.langgraph_recursion_limit,
                    "configurable": {
                        "thread_id": conversation_id
                    }
                },
                version="v2"
        ):
            kind = event.get("event")

            # 捕获 LLM 流式输出
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    token = chunk.content
                    assistant_message += token
                    if first_token_elapsed is None:
                        first_token_elapsed = time.perf_counter() - request_started_at
                        app_logger.info(
                            "SSE first token emitted: "
                            f"conversation_id={conversation_id}, user_id={user.id}, "
                            f"elapsed_seconds={first_token_elapsed:.2f}"
                        )
                    yield sse({
                        "type": "token",
                        "content": token,
                    })

            # 或者捕获工具调用信息
            elif kind == "on_tool_start":
                tool_name = event.get("name", "")
                run_id = event.get("run_id", "")
                if run_id:
                    tool_started_at[run_id] = time.perf_counter()
                    tool_audit_context_by_run[run_id] = start_tool_audit(tool_name)
                    tool_input_by_run[run_id] = summarize_tool_input(
                        event.get("data", {}).get("input") or {}
                    )
                    tool_name_by_run[run_id] = tool_name
                app_logger.info(
                    "SSE tool started: "
                    f"conversation_id={conversation_id}, user_id={user.id}, tool={tool_name}"
                )
                if tool_name and tool_name in emitted_tool_call_names:
                    app_logger.info(
                        "SSE duplicate tool_call event suppressed: "
                        f"conversation_id={conversation_id}, user_id={user.id}, tool={tool_name}"
                    )
                else:
                    if tool_name:
                        emitted_tool_call_names.add(tool_name)
                    yield sse({
                        "type": "tool_call",
                        "tool": tool_name,
                    })
            elif kind == "on_tool_end":
                run_id = event.get("run_id", "")
                tool_name = event.get("name", "") or tool_name_by_run.get(run_id, "")
                started_at = tool_started_at.pop(run_id, None)
                audit_context = tool_audit_context_by_run.pop(run_id, None)
                input_summary = tool_input_by_run.pop(run_id, {})
                tool_name_by_run.pop(run_id, None)
                tool_output = event.get("data", {}).get("output")
                if tool_name == "generate_order_tool":
                    report_extra_info = _report_extra_info_from_tool_output(
                        tool_output
                    )
                    if report_extra_info:
                        if not fallback_assistant_message:
                            fallback_assistant_message = _report_content_from_tool_output(
                                tool_output
                            )
                        assistant_extra_info.update(report_extra_info)
                        yield sse(
                            {
                                "type": "report_data",
                                "report_data": report_extra_info["report_data"],
                                "order_id": report_extra_info.get("order_id"),
                            }
                        )
                        app_logger.info(
                            "Captured structured report metadata from generate_order_tool: "
                            f"conversation_id={conversation_id}, user_id={user.id}"
                        )
                        final_report_emitted = True
                if started_at is not None:
                    elapsed = time.perf_counter() - started_at
                    app_logger.info(
                        "SSE tool finished: "
                        f"conversation_id={conversation_id}, user_id={user.id}, "
                        f"tool={tool_name}, elapsed_seconds={elapsed:.2f}"
                    )
                embedded_audit_events = _extract_embedded_tool_audit_events(tool_output)
                if embedded_audit_events:
                    new_audit_events = _new_tool_audit_events(
                        embedded_audit_events,
                        tool_audit_events,
                    )
                    tool_audit_events.extend(new_audit_events)
                    for audit_event in new_audit_events:
                        yield sse({
                            "type": "tool_audit",
                            "event": audit_event,
                        })
                elif audit_context is not None:
                    result_validation = validate_tool_output_for_audit(
                        tool_name,
                        tool_output,
                    )
                    audit_event = build_tool_audit_event(
                        audit_context,
                        status=result_validation.status,
                        input_summary=input_summary,
                        output_summary=(
                            result_validation.output_summary
                            or summarize_tool_output(tool_output)
                        ),
                        error_type=result_validation.error_type,
                        evidence_type=evidence_type_for_tool_name(tool_name),
                    )
                    tool_audit_events.append(audit_event)
                    yield sse({
                        "type": "tool_audit",
                        "event": audit_event,
                    })
                if final_report_emitted:
                    app_logger.info(
                        "SSE final report emitted; ending stream without model post-processing: "
                        f"conversation_id={conversation_id}, user_id={user.id}"
                    )
                    break
            elif kind == "on_tool_error":
                run_id = event.get("run_id", "")
                tool_name = event.get("name", "") or tool_name_by_run.pop(run_id, "")
                tool_started_at.pop(run_id, None)
                audit_context = tool_audit_context_by_run.pop(run_id, None)
                input_summary = tool_input_by_run.pop(run_id, {})
                error = event.get("data", {}).get("error")
                error_type = getattr(error, "__class__", type(error)).__name__ if error else "ToolError"
                if audit_context is not None:
                    audit_event = build_tool_audit_event(
                        audit_context,
                        status="failed",
                        input_summary=input_summary,
                        output_summary={"message": str(error)[:180] if error else ""},
                        error_type=error_type,
                        evidence_type="mcp_live_query",
                    )
                    tool_audit_events.append(audit_event)
                    yield sse({
                        "type": "tool_audit",
                        "event": audit_event,
                    })

            await asyncio.sleep(0)

        # 5. 保存 AI 回复
        if not assistant_message.strip() and fallback_assistant_message:
            assistant_message = fallback_assistant_message
        if tool_audit_events:
            assistant_extra_info["tool_audit_events"] = tool_audit_events
            audit_persistence = await _persist_tool_audit_events_safely(
                db,
                events=tool_audit_events,
                user_id=str(user.id),
                conversation_id=conversation_id,
            )
            if audit_persistence.get("status") == "degraded":
                assistant_extra_info["tool_audit_persistence"] = audit_persistence
        if assistant_message.strip():
            await save_message(
                db,
                conversation_id,
                "assistant",
                assistant_message,
                extra_info=assistant_extra_info,
            )

        total_elapsed = time.perf_counter() - request_started_at
        app_logger.info(
            "SSE chat completed: "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"elapsed_seconds={total_elapsed:.2f}, "
            f"first_token_seconds={(first_token_elapsed if first_token_elapsed is not None else -1):.2f}, "
            f"assistant_chars={len(assistant_message)}"
        )
        yield sse({"type": "done"})

    except asyncio.CancelledError:
        app_logger.info(
            "SSE chat stream cancelled: "
            f"conversation_id={conversation_id}, user_id={user.id}"
        )
        raise
    except Exception as e:
        total_elapsed = time.perf_counter() - request_started_at
        if _is_transient_stream_disconnect(e):
            app_logger.warning(
                "SSE upstream stream disconnected after partial generation; "
                "finishing turn without emitting user-facing error: "
                f"conversation_id={conversation_id}, user_id={user.id}, "
                f"elapsed_seconds={total_elapsed:.2f}, assistant_chars={len(assistant_message)}"
            )
            if not assistant_message.strip() and fallback_assistant_message:
                assistant_message = fallback_assistant_message
            if not assistant_message.strip():
                assistant_message = (
                    "本轮模型流式连接中断，已保留当前规划状态；"
                    "可以继续下一步处理。"
                )
                if first_token_elapsed is None:
                    first_token_elapsed = total_elapsed
                    yield sse({
                        "type": "token",
                        "content": assistant_message,
                    })
            if tool_audit_events:
                assistant_extra_info["tool_audit_events"] = tool_audit_events
                audit_persistence = await _persist_tool_audit_events_safely(
                    db,
                    events=tool_audit_events,
                    user_id=str(user.id),
                    conversation_id=conversation_id,
                )
                if audit_persistence.get("status") == "degraded":
                    assistant_extra_info["tool_audit_persistence"] = audit_persistence
            if assistant_message.strip():
                await save_message(
                    db,
                    conversation_id,
                    "assistant",
                    assistant_message,
                    extra_info=assistant_extra_info,
                )
            yield sse({"type": "done"})
            return
        app_logger.exception(
            "SSE chat failed: "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"elapsed_seconds={total_elapsed:.2f}"
        )
        app_logger.exception("❌ SSE 流式对话错误")
        yield sse({
            "type": "error",
            "message": str(e),
        })
    finally:
        if session_lock is not None:
            await session_lock.release()
            app_logger.info(
                "SSE chat session lock released: "
                f"conversation_id={conversation_id}, user_id={user.id}"
            )



@router.post("/stream/{conversation_id}")
async def stream_chat(
        conversation_id: str,
        data: MessageCreate,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """
    流式对话（SSE）

    Returns:
        StreamingResponse: SSE 流式响应
    """

    # 验证会话归属
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user.id)
    )

    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    # 返回 SSE 流
    return StreamingResponse(
        generate_sse_stream(conversation_id, data.content, db, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲
        }
    )


@router.get("/history/{conversation_id}")
async def get_chat_history(
        conversation_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """获取会话历史消息"""

    # 验证会话归属
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .where(Conversation.user_id == user.id)
    )

    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在"
        )

    # 查询消息
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )

    messages = result.scalars().all()

    return {
        "conversation": conversation.to_dict(),
        "messages": [m.to_dict() for m in messages]
    }
