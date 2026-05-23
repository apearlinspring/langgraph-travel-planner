"""
消息相关的 Pydantic 模型
"""
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import uuid


class MessageCreate(BaseModel):
    """创建消息"""
    content: str


class MessageResponse(BaseModel):
    """消息响应"""
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    extra_info: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
