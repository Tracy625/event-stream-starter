"""Push outbox models for Telegram retry mechanism"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

# 使用项目内的 Base（如果你的路径不同，这里改成你项目的 Base）
from api.models import Base  # TODO: 确认真实路径


class OutboxStatus(str, Enum):
    PENDING = "pending"
    RETRY = "retry"
    DONE = "done"
    DLQ = "dlq"


class PushOutbox(Base):
    __tablename__ = "push_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, nullable=False)
    thread_id = Column(BigInteger, nullable=True)
    event_key = Column(String(128), nullable=False)
    payload_json = Column(JSONB, nullable=False)
    status = Column(String(16), nullable=False, default=OutboxStatus.PENDING)
    attempt = Column(Integer, nullable=False, default=0)
    next_try_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','retry','done','dlq')", name="ck_push_outbox_status"
        ),
        Index("ix_push_outbox_status_next_try_at", "status", "next_try_at"),
        Index("ix_push_outbox_event_key", "event_key"),
        Index("ix_push_outbox_channel_id", "channel_id"),
    )


class PushOutboxDLQ(Base):
    __tablename__ = "push_outbox_dlq"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ref_id = Column(BigInteger, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    failed_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
