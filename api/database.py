"""
Database engine and session configuration.

Provides factory functions for SQLAlchemy engine and session creation.
"""

import os
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine


def build_engine_from_env() -> Engine:
    """
    Build SQLAlchemy engine from POSTGRES_URL environment variable.
    
    Returns:
        Configured SQLAlchemy Engine with connection pooling
    """
    postgres_url = os.getenv("POSTGRES_URL")
    if not postgres_url:
        raise ValueError("POSTGRES_URL environment variable not set")
    
    # Optional pool and timeout tuning via env
    pool_size = os.getenv("SQLALCHEMY_POOL_SIZE")
    max_overflow = os.getenv("SQLALCHEMY_MAX_OVERFLOW")
    pool_recycle = os.getenv("SQLALCHEMY_POOL_RECYCLE")
    pool_timeout = os.getenv("SQLALCHEMY_POOL_TIMEOUT")
    stmt_timeout_ms = os.getenv("PG_STATEMENT_TIMEOUT_MS")

    create_kwargs = dict(
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    if pool_size is not None:
        try:
            create_kwargs["pool_size"] = int(pool_size)
        except Exception:
            pass
    if max_overflow is not None:
        try:
            create_kwargs["max_overflow"] = int(max_overflow)
        except Exception:
            pass
    if pool_recycle is not None:
        try:
            create_kwargs["pool_recycle"] = int(pool_recycle)
        except Exception:
            pass
    if pool_timeout is not None:
        try:
            create_kwargs["pool_timeout"] = int(pool_timeout)
        except Exception:
            pass

    # Per-connection statement timeout (psycopg2)
    connect_args = {}
    if stmt_timeout_ms:
        try:
            ms = int(stmt_timeout_ms)
            connect_args["options"] = f"-c statement_timeout={ms}"
        except Exception:
            pass
    if connect_args:
        create_kwargs["connect_args"] = connect_args

    engine = create_engine(postgres_url, **create_kwargs)
    
    return engine


def get_sessionmaker(engine: Engine) -> sessionmaker:
    """
    Create sessionmaker bound to the given engine.
    
    Args:
        engine: SQLAlchemy Engine instance
    
    Returns:
        Configured sessionmaker class
    """
    Session = sessionmaker(
        bind=engine,
        expire_on_commit=False,  # Don't expire objects after commit
    )
    
    return Session


# --- Day9.1 compatibility shim: provide get_db for DI ---

# Cache for engine and SessionLocal
_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None

# Alternative DATABASE_URL support (in addition to POSTGRES_URL)
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")


def get_session_local() -> sessionmaker:
    """
    Returns an available SessionLocal. Prioritizes existing global SessionLocal.
    Provides compatibility with both DATABASE_URL and POSTGRES_URL env vars.
    """
    global _SessionLocal, _engine
    
    if _SessionLocal is not None:
        return _SessionLocal
    
    # Try to use existing SessionLocal if available in globals
    try:
        return globals()["SessionLocal"]  # type: ignore
    except KeyError:
        pass
    
    if DATABASE_URL:
        if _engine is None:
            _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        return _SessionLocal
    
    # Fallback to using build_engine_from_env if available
    try:
        _engine = build_engine_from_env()
        _SessionLocal = get_sessionmaker(_engine)
        return _SessionLocal
    except ValueError:
        pass
    
    raise RuntimeError("Neither DATABASE_URL nor POSTGRES_URL is set and no existing SessionLocal found")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency injection DB session generator.
    Usage: Depends(get_db)
    
    Yields:
        Database session that auto-closes after use
    """
    SessionLocal = get_session_local()
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def with_db() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    Usage: with with_db() as db: ...
    
    Yields:
        Database session that auto-closes after use
    """
    SessionLocal = get_session_local()
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
