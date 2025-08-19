"""
Deduplication service for event processing.

Supports both Redis-backed and in-memory storage modes.
Maintains a time-window cache to prevent duplicate event processing.
"""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)


class DeduplicationService:
    """
    Service for detecting and recording duplicate events within a time window.
    
    Uses Redis when available, falls back to in-memory storage.
    """
    
    def __init__(self, redis_url: Optional[str] = None, window_sec: int = 3600):
        """
        Initialize deduplication service.
        
        Args:
            redis_url: Redis connection URL, None for in-memory mode
            window_sec: Deduplication window in seconds (default 1 hour)
        """
        self.window_sec = window_sec
        self.redis_url = redis_url
        self.redis_client = None
        self.memory_store: Dict[str, float] = {}  # event_key -> timestamp
        
        # Try to connect to Redis if URL provided
        if redis_url:
            try:
                import redis
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                # Test connection
                self.redis_client.ping()
                logger.info(f"Connected to Redis at {redis_url}")
            except ImportError:
                logger.warning("Redis library not installed, using in-memory mode")
                self.redis_client = None
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using in-memory mode")
                self.redis_client = None
    
    def is_duplicate(self, event_key: str, ts: Optional[datetime] = None) -> bool:
        """
        Check if event_key has been seen within the time window.
        
        Args:
            event_key: Unique event identifier
            ts: Timestamp to check against (default: now)
        
        Returns:
            True if event is a duplicate within window, False otherwise
        """
        if ts is None:
            ts = datetime.now(timezone.utc)
        
        current_ts = ts.timestamp()
        
        if self.redis_client:
            # Redis mode
            try:
                redis_key = f"dedup:{event_key}"
                stored_value = self.redis_client.get(redis_key)
                
                if stored_value is None:
                    return False
                
                # Parse stored timestamp
                try:
                    stored_ts = float(stored_value)
                except (ValueError, TypeError):
                    # Try ISO format for backward compatibility
                    stored_dt = datetime.fromisoformat(stored_value)
                    stored_ts = stored_dt.timestamp()
                
                # Check if within window
                return (current_ts - stored_ts) < self.window_sec
                
            except Exception as e:
                logger.error(f"Redis error in is_duplicate: {e}")
                # Fall back to memory check
                return self._is_duplicate_memory(event_key, current_ts)
        else:
            # Memory mode
            return self._is_duplicate_memory(event_key, current_ts)
    
    def _is_duplicate_memory(self, event_key: str, current_ts: float) -> bool:
        """Check duplicate in memory store."""
        if event_key not in self.memory_store:
            return False
        
        stored_ts = self.memory_store[event_key]
        return (current_ts - stored_ts) < self.window_sec
    
    def record(self, event_key: str, ts: Optional[datetime] = None) -> None:
        """
        Record an event_key with timestamp.
        
        Args:
            event_key: Unique event identifier
            ts: Timestamp to record (default: now)
        """
        if ts is None:
            ts = datetime.now(timezone.utc)
        
        current_ts = ts.timestamp()
        
        if self.redis_client:
            # Redis mode
            try:
                redis_key = f"dedup:{event_key}"
                # Store timestamp as float string for precision
                self.redis_client.setex(
                    redis_key,
                    self.window_sec,
                    str(current_ts)
                )
                logger.debug(f"Recorded {event_key} in Redis with TTL {self.window_sec}s")
            except Exception as e:
                logger.error(f"Redis error in record: {e}")
                # Fall back to memory storage
                self.memory_store[event_key] = current_ts
        else:
            # Memory mode
            self.memory_store[event_key] = current_ts
            logger.debug(f"Recorded {event_key} in memory")
    
    def prune(self) -> int:
        """
        Remove expired entries from memory store.
        
        Only needed for in-memory mode. Redis handles TTL automatically.
        
        Returns:
            Number of entries pruned
        """
        if self.redis_client:
            # Redis handles TTL automatically
            return 0
        
        current_ts = time.time()
        expired_keys = [
            key for key, ts in self.memory_store.items()
            if (current_ts - ts) >= self.window_sec
        ]
        
        for key in expired_keys:
            del self.memory_store[key]
        
        logger.debug(f"Pruned {len(expired_keys)} expired entries")
        return len(expired_keys)
    
    def clear(self) -> None:
        """Clear all entries (useful for testing)."""
        if self.redis_client:
            try:
                # Use SCAN to avoid KEYS command
                cursor = 0
                while True:
                    cursor, keys = self.redis_client.scan(
                        cursor, 
                        match="dedup:*",
                        count=100
                    )
                    if keys:
                        self.redis_client.delete(*keys)
                    if cursor == 0:
                        break
                logger.info("Cleared all dedup entries from Redis")
            except Exception as e:
                logger.error(f"Redis error in clear: {e}")
        
        self.memory_store.clear()
        logger.info("Cleared memory store")