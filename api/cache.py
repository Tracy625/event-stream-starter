"""
Cache module with TTL-based memoization and degradation path.

Provides:
- memoize_ttl: Thread-safe in-process cache decorator with TTL expiration
- memoize_ttl_redis: Redis-backed cache decorator (optional)

Features:
- Per-key locking for cache fill (prevents stampedes)
- TTL jitter (±10%) to prevent thundering herd
- Graceful degradation with fallback values
- Comprehensive metrics and structured logging
"""

import functools
import hashlib
import os
import random
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Optional, Tuple, TypeVar, Union

from api.core.metrics_store import log_json

try:
    from prometheus_client import Counter

    from api.core.metrics import PROM_REGISTRY

    # Cache metrics - register to shared PROM_REGISTRY
    cache_hits_total = Counter(
        "cache_hits_total",
        "Total number of cache hits",
        ["layer"],  # layer: local or redis
        registry=PROM_REGISTRY,
    )

    cache_misses_total = Counter(
        "cache_misses_total",
        "Total number of cache misses",
        ["layer"],  # layer: local or redis
        registry=PROM_REGISTRY,
    )

    cache_fill_total = Counter(
        "cache_fill_total",
        "Total number of cache fills",
        ["result"],  # result: success or error
        registry=PROM_REGISTRY,
    )

    cache_degrade_count_total = Counter(
        "cache_degrade_count_total",
        "Total number of cache degradations",
        ["cause"],  # cause: function_error, redis_error, double_fault
        registry=PROM_REGISTRY,
    )

    cache_lock_contention_total = Counter(
        "cache_lock_contention_total",
        "Total number of cache lock contentions",
        registry=PROM_REGISTRY,
    )
except ImportError:
    # Fallback to no-op metrics if prometheus_client not available
    class NoOpMetric:
        def labels(self, **kwargs):
            return self

        def inc(self, amount=1):
            pass

    cache_hits_total = NoOpMetric()
    cache_misses_total = NoOpMetric()
    cache_fill_total = NoOpMetric()
    cache_degrade_count_total = NoOpMetric()
    cache_lock_contention_total = NoOpMetric()

try:
    import redis  # type: ignore
except ImportError:
    redis = None  # type: ignore

# Global Redis client singleton
_redis_client = None
_redis_lock = threading.Lock()

T = TypeVar("T")


def get_redis_client() -> Optional["redis.Redis"]:
    """
    Get Redis client singleton with thread-safe initialization.

    Returns:
        Redis client if available, None otherwise
    """
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    if redis is None:
        return None

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client

        # Try to get Redis URL from environment
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                _redis_client = redis.from_url(redis_url, decode_responses=False)
                # Test connection
                _redis_client.ping()
                log_json(stage="redis.connect", status="success", url=redis_url)
            except Exception as e:
                log_json(stage="redis.connect.error", error=str(e))
                _redis_client = None
        else:
            # Fallback to individual env vars
            host = os.environ.get("REDIS_HOST", "redis")
            port = int(os.environ.get("REDIS_PORT", "6379"))
            db = int(os.environ.get("REDIS_DB", "0"))
            try:
                _redis_client = redis.Redis(
                    host=host, port=port, db=db, decode_responses=False
                )
                # Test connection
                _redis_client.ping()
                log_json(stage="redis.connect", status="success", host=host, port=port)
            except Exception as e:
                log_json(stage="redis.connect.error", error=str(e))
                _redis_client = None

    return _redis_client


def _make_cache_key_hash(func_name: str, args: Tuple, kwargs: dict) -> str:
    """
    Create a hashed cache key from function name, args, and kwargs.
    Uses SHA1 to create a fixed-length key suitable for Redis.

    Args:
        func_name: Name of the function
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        SHA1 hash (first 10 chars) of the cache key
    """
    # Convert kwargs to sorted tuple for consistent hashing
    kwargs_items = tuple(sorted(kwargs.items())) if kwargs else ()

    # Create key from function name and arguments
    key_parts = [func_name]

    # Add args
    if args:
        key_parts.append(str(args))

    # Add kwargs if present
    if kwargs_items:
        key_parts.append(str(kwargs_items))

    # Hash the key to avoid sensitive data exposure
    full_key = "|".join(key_parts)
    key_hash = hashlib.sha1(full_key.encode()).hexdigest()[:10]

    return key_hash


def _add_ttl_jitter(seconds: int) -> int:
    """
    Add ±10% jitter to TTL to prevent thundering herd.

    Args:
        seconds: Base TTL in seconds

    Returns:
        TTL with jitter applied (integer seconds)
    """
    jitter_range = int(seconds * 0.1)
    if jitter_range == 0:
        return seconds
    jitter = random.randint(-jitter_range, jitter_range)
    return max(1, seconds + jitter)


class CacheLockManager:
    """
    Manages per-key locks for cache operations to prevent stampedes.
    Uses defaultdict with RLock for thread safety.
    """

    def __init__(self):
        """Initialize the lock manager with a container lock and key locks dict."""
        self._locks = defaultdict(threading.RLock)
        self._container_lock = threading.Lock()
        self._waiting_counts = defaultdict(int)

    def acquire(self, key: str) -> threading.RLock:
        """
        Get or create a lock for a specific key.

        Args:
            key: Cache key to get lock for

        Returns:
            RLock for the specified key
        """
        with self._container_lock:
            lock = self._locks[key]
            if self._waiting_counts[key] > 0:
                # Someone else is waiting for this lock
                cache_lock_contention_total.inc()
            self._waiting_counts[key] += 1
        return lock

    def release(self, key: str):
        """
        Decrement waiting count for a key after lock release.

        Args:
            key: Cache key that was released
        """
        with self._container_lock:
            self._waiting_counts[key] = max(0, self._waiting_counts[key] - 1)
            # Clean up if no one is waiting
            if self._waiting_counts[key] == 0:
                self._waiting_counts.pop(key, None)


# Global lock manager instance
_lock_manager = CacheLockManager()


def memoize_ttl(
    seconds: int, fallback: Any = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Thread-safe in-process cache decorator with TTL expiration.

    Features:
    - Per-key locking to prevent cache stampedes
    - TTL jitter (±10%) to prevent thundering herd
    - Graceful degradation with fallback on errors
    - Structured logging and metrics

    Args:
        seconds: Time-to-live in seconds for cached values
        fallback: Value to return if function raises an exception

    Example:
        @memoize_ttl(seconds=60, fallback={})
        def analyze_sentiment(text: str) -> dict:
            # Expensive computation
            return {"sentiment": "positive", "score": 0.8}
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # Cache storage: key -> (value, expiry_time)
        cache = {}
        # Cache-level lock for dictionary operations
        cache_lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Generate cache key hash
            key_hash = _make_cache_key_hash(func.__name__, args, kwargs)

            # Get current time
            current_time = time.time()
            start_time = current_time

            # Check cache first (fast path, no lock needed for read)
            with cache_lock:
                if key_hash in cache:
                    cached_value, expiry_time = cache[key_hash]

                    # Check if still valid
                    if current_time < expiry_time:
                        # Cache hit
                        cache_hits_total.labels(layer="local").inc()
                        latency_ms = int((time.time() - start_time) * 1000)
                        log_json(
                            stage="cache.event",
                            status="get",
                            key_hash=key_hash,
                            ttl=int(expiry_time - current_time),
                            latency_ms=latency_ms,
                            hit=True,
                        )
                        return cached_value

            # Cache miss - need to compute
            cache_misses_total.labels(layer="local").inc()

            # Get per-key lock to prevent stampede
            key_lock = _lock_manager.acquire(key_hash)

            try:
                with key_lock:
                    # Double-check after acquiring lock (another thread might have filled it)
                    with cache_lock:
                        if key_hash in cache:
                            cached_value, expiry_time = cache[key_hash]
                            if current_time < expiry_time:
                                # Someone else filled it while we waited
                                cache_hits_total.labels(layer="local").inc()
                                latency_ms = int((time.time() - start_time) * 1000)
                                log_json(
                                    stage="cache.event",
                                    status="get",
                                    key_hash=key_hash,
                                    ttl=int(expiry_time - current_time),
                                    latency_ms=latency_ms,
                                    hit=True,
                                )
                                return cached_value

                    # Log cache miss
                    log_json(
                        stage="cache.event",
                        status="miss",
                        key_hash=key_hash,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                    # Compute new value
                    compute_start = time.time()
                    try:
                        result = func(*args, **kwargs)
                        compute_ms = int((time.time() - compute_start) * 1000)

                        # Store in cache with jittered TTL
                        jittered_ttl = _add_ttl_jitter(seconds)
                        expiry_time = current_time + jittered_ttl

                        with cache_lock:
                            cache[key_hash] = (result, expiry_time)

                        cache_fill_total.labels(result="success").inc()
                        log_json(
                            stage="cache.event",
                            status="fill",
                            key_hash=key_hash,
                            ttl=jittered_ttl,
                            latency_ms=compute_ms,
                        )

                        return result

                    except Exception as e:
                        # Function raised an exception - use fallback
                        compute_ms = int((time.time() - compute_start) * 1000)
                        cache_fill_total.labels(result="error").inc()
                        cache_degrade_count_total.labels(cause="function_error").inc()

                        log_json(
                            stage="cache.event",
                            status="degrade",
                            key_hash=key_hash,
                            cause="function_error",
                            error=str(e)[:200],
                            latency_ms=compute_ms,
                        )

                        return fallback

            finally:
                _lock_manager.release(key_hash)

        # Add cache management methods
        def clear_cache():
            """Clear all cached values."""
            with cache_lock:
                cache.clear()
                log_json(stage="cache.event", status="clear", func=func.__name__)

        def cache_info():
            """Get cache statistics."""
            with cache_lock:
                return {"size": len(cache), "keys": list(cache.keys())}

        # Attach utility methods to wrapper
        wrapper.clear_cache = clear_cache
        wrapper.cache_info = cache_info

        return wrapper

    return decorator


def memoize_ttl_redis(
    seconds: int, fallback: Any = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Redis-backed cache decorator with TTL expiration.
    Falls back to in-process cache if Redis is unavailable.

    Features:
    - Redis as primary cache layer
    - Automatic fallback to in-process cache on Redis errors
    - TTL jitter (±10%) to prevent thundering herd
    - Graceful degradation with fallback on errors
    - Structured logging and metrics

    Args:
        seconds: Time-to-live in seconds for cached values
        fallback: Value to return if function raises an exception

    Example:
        @memoize_ttl_redis(seconds=300, fallback=[])
        def fetch_data(user_id: str) -> list:
            # Database query
            return db.query(user_id)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        # Create local cache as fallback
        local_cache = {}
        local_lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            # Generate cache key hash
            key_hash = _make_cache_key_hash(func.__name__, args, kwargs)
            redis_key = f"cache:{func.__module__}.{func.__name__}:{key_hash}"

            current_time = time.time()
            start_time = current_time

            # Try Redis first
            rc = get_redis_client()
            if rc is not None:
                try:
                    # Check Redis cache
                    cached_bytes = rc.get(redis_key)
                    if cached_bytes is not None:
                        # Cache hit in Redis
                        cache_hits_total.labels(layer="redis").inc()
                        latency_ms = int((time.time() - start_time) * 1000)

                        # Deserialize (simple repr/eval for now)
                        try:
                            cached_value = eval(cached_bytes.decode())
                            log_json(
                                stage="cache.event",
                                status="get",
                                key_hash=key_hash,
                                layer="redis",
                                latency_ms=latency_ms,
                                hit=True,
                            )
                            return cached_value
                        except Exception:
                            # Deserialization failed, treat as miss
                            pass

                    # Redis miss
                    cache_misses_total.labels(layer="redis").inc()

                except Exception as e:
                    # Redis error - fall back to local cache
                    cache_degrade_count_total.labels(cause="redis_error").inc()
                    log_json(
                        stage="cache.event",
                        status="degrade",
                        key_hash=key_hash,
                        cause="redis_error",
                        error=str(e)[:200],
                    )
                    rc = None  # Mark Redis as unavailable for this request

            # Check local cache as fallback
            with local_lock:
                if key_hash in local_cache:
                    cached_value, expiry_time = local_cache[key_hash]
                    if current_time < expiry_time:
                        # Local cache hit
                        cache_hits_total.labels(layer="local").inc()
                        latency_ms = int((time.time() - start_time) * 1000)
                        log_json(
                            stage="cache.event",
                            status="get",
                            key_hash=key_hash,
                            layer="local",
                            ttl=int(expiry_time - current_time),
                            latency_ms=latency_ms,
                            hit=True,
                        )
                        return cached_value

            # Both caches missed
            cache_misses_total.labels(layer="local").inc()

            # Get per-key lock to prevent stampede
            key_lock = _lock_manager.acquire(key_hash)

            try:
                with key_lock:
                    # Double-check caches after acquiring lock
                    # Check Redis again if available
                    if rc is not None:
                        try:
                            cached_bytes = rc.get(redis_key)
                            if cached_bytes is not None:
                                try:
                                    cached_value = eval(cached_bytes.decode())
                                    cache_hits_total.labels(layer="redis").inc()
                                    return cached_value
                                except Exception:
                                    pass
                        except Exception:
                            rc = None

                    # Check local cache again
                    with local_lock:
                        if key_hash in local_cache:
                            cached_value, expiry_time = local_cache[key_hash]
                            if current_time < expiry_time:
                                cache_hits_total.labels(layer="local").inc()
                                return cached_value

                    # Log cache miss
                    log_json(
                        stage="cache.event",
                        status="miss",
                        key_hash=key_hash,
                        latency_ms=int((time.time() - start_time) * 1000),
                    )

                    # Compute new value
                    compute_start = time.time()
                    try:
                        result = func(*args, **kwargs)
                        compute_ms = int((time.time() - compute_start) * 1000)

                        # Add jitter to TTL
                        jittered_ttl = _add_ttl_jitter(seconds)

                        # Try to store in Redis
                        redis_success = False
                        if rc is not None:
                            try:
                                # Serialize and store
                                rc.setex(redis_key, jittered_ttl, repr(result))
                                redis_success = True
                            except Exception as e:
                                # Redis write failed
                                cache_degrade_count_total.labels(
                                    cause="redis_error"
                                ).inc()
                                log_json(
                                    stage="cache.event",
                                    status="error",
                                    key_hash=key_hash,
                                    cause="redis_write_error",
                                    error=str(e)[:200],
                                )

                        # Always store in local cache
                        expiry_time = current_time + jittered_ttl
                        with local_lock:
                            local_cache[key_hash] = (result, expiry_time)

                        cache_fill_total.labels(result="success").inc()
                        log_json(
                            stage="cache.event",
                            status="fill",
                            key_hash=key_hash,
                            ttl=jittered_ttl,
                            layer="redis" if redis_success else "local",
                            latency_ms=compute_ms,
                        )

                        return result

                    except Exception as e:
                        # Function raised an exception - use fallback
                        compute_ms = int((time.time() - compute_start) * 1000)
                        cache_fill_total.labels(result="error").inc()

                        # Determine cause
                        if rc is None:
                            # Redis was unavailable and function failed
                            cache_degrade_count_total.labels(cause="double_fault").inc()
                            cause = "double_fault"
                        else:
                            cache_degrade_count_total.labels(
                                cause="function_error"
                            ).inc()
                            cause = "function_error"

                        log_json(
                            stage="cache.event",
                            status="degrade",
                            key_hash=key_hash,
                            cause=cause,
                            error=str(e)[:200],
                            latency_ms=compute_ms,
                        )

                        return fallback

            finally:
                _lock_manager.release(key_hash)

        # Add cache management methods
        def clear_cache():
            """Clear all cached values in both Redis and local cache."""
            # Clear local cache
            with local_lock:
                local_cache.clear()

            # Try to clear Redis keys
            rc = get_redis_client()
            if rc is not None:
                try:
                    pattern = f"cache:{func.__module__}.{func.__name__}:*"
                    for key in rc.scan_iter(match=pattern):
                        rc.delete(key)
                except Exception as e:
                    log_json(
                        stage="cache.event",
                        status="error",
                        func=func.__name__,
                        error=str(e)[:200],
                    )

            log_json(stage="cache.event", status="clear", func=func.__name__)

        def cache_info():
            """Get cache statistics."""
            with local_lock:
                info = {
                    "local_size": len(local_cache),
                    "local_keys": list(local_cache.keys()),
                }

            # Try to get Redis info
            rc = get_redis_client()
            if rc is not None:
                try:
                    pattern = f"cache:{func.__module__}.{func.__name__}:*"
                    redis_keys = list(rc.scan_iter(match=pattern))
                    info["redis_size"] = len(redis_keys)
                    info["redis_available"] = True
                except Exception:
                    info["redis_available"] = False
            else:
                info["redis_available"] = False

            return info

        # Attach utility methods to wrapper
        wrapper.clear_cache = clear_cache
        wrapper.cache_info = cache_info

        return wrapper

    return decorator
