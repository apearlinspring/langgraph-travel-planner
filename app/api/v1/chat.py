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
from app.utils.logger import app_logger

router = APIRouter(prefix="/chat", tags=["对话"])


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
    tool_name_by_run = {}

    try:
        app_logger.info(
            "SSE chat started: "
            f"conversation_id={conversation_id}, user_id={user.id}, "
            f"message_length={len(user_message)}"
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
                    tool_name_by_run[run_id] = tool_name
                app_logger.info(
                    "SSE tool started: "
                    f"conversation_id={conversation_id}, user_id={user.id}, tool={tool_name}"
                )
                yield sse({
                    "type": "tool_call",
                    "tool": tool_name,
                })
            elif kind == "on_tool_end":
                run_id = event.get("run_id", "")
                tool_name = event.get("name", "") or tool_name_by_run.get(run_id, "")
                started_at = tool_started_at.pop(run_id, None)
                tool_name_by_run.pop(run_id, None)
                if started_at is not None:
                    elapsed = time.perf_counter() - started_at
                    app_logger.info(
                        "SSE tool finished: "
                        f"conversation_id={conversation_id}, user_id={user.id}, "
                        f"tool={tool_name}, elapsed_seconds={elapsed:.2f}"
                    )

            await asyncio.sleep(0)

        # 5. 保存 AI 回复
        if assistant_message.strip():
            await save_message(
                db,
                conversation_id,
                "assistant",
                assistant_message,
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

    except Exception as e:
        total_elapsed = time.perf_counter() - request_started_at
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
