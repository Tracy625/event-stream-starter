from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()
metadata = Base.metadata

__all__ = ["Base", "metadata"]


class RawPost(Base):
    __tablename__ = "raw_posts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    author = Column(Text)
    text = Column(Text, nullable=False)
    ts = Column(TIMESTAMP(timezone=True), nullable=False)
    urls = Column(JSONB, server_default=sa_text("'[]'::jsonb"))
    token_ca = Column(Text)
    symbol = Column(Text)
    is_candidate = Column(Boolean, server_default=sa_text("FALSE"))
    sentiment_label = Column(Text)
    sentiment_score = Column(Float)
    keywords = Column(ARRAY(Text))


class Event(Base):
    __tablename__ = "events"

    event_key = Column(Text, primary_key=True)
    type = Column(Text)
    summary = Column(Text)
    score = Column(Float, nullable=False, server_default=sa_text("0"))
    evidence = Column(JSONB, server_default=sa_text("'[]'::jsonb"))
    impacted_assets = Column(ARRAY(Text))
    start_ts = Column(TIMESTAMP(timezone=True), nullable=False)
    last_ts = Column(TIMESTAMP(timezone=True), nullable=False)
    heat_10m = Column(Integer, server_default=sa_text("0"))
    heat_30m = Column(Integer, server_default=sa_text("0"))


class Signal(Base):
    __tablename__ = "signals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_key = Column(Text, ForeignKey("events.event_key", ondelete="CASCADE"))
    type = Column(Text, nullable=False)
    market_type = Column(Text)
    advice_tag = Column(Text)
    confidence = Column(Integer)
    goplus_risk = Column(Text)
    goplus_tax = Column(Float)
    lp_lock_days = Column(Integer)
    dex_liquidity = Column(Float)
    dex_volume_1h = Column(Float)
    ts = Column(TIMESTAMP(timezone=True), server_default=sa_text("now()"))
