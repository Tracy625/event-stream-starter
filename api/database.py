"""
Database engine and session configuration.

Provides factory functions for SQLAlchemy engine and session creation.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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
    
    # Create engine with recommended settings
    engine = create_engine(
        postgres_url,
        echo=False,  # Don't log SQL statements
        future=True,  # Use SQLAlchemy 2.0 style
        pool_pre_ping=True,  # Verify connections before using from pool
    )
    
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