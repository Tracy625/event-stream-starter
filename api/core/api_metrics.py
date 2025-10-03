"""HTTP API metrics instrumentation for outbound requests."""

from __future__ import annotations

import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from api.cache import get_redis_client
from api.core import metrics
from api.core.metrics_store import log_json

_API_CALL_COUNTER_HELP = "Total outbound API calls grouped by provider and status"
_REDIS_ZSET_KEY = "metrics:api_calls_success"
_WINDOW_SECONDS = 24 * 3600

_lock = threading.Lock()
_installed = False


def _identify_provider(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "unknown").lower()
        if host.startswith("api."):
            host = host[4:]
        return host or "unknown"
    except Exception:
        return "unknown"


def _record_api_call(provider: str, status: str, success: bool) -> None:
    counter = metrics.counter("api_calls_total", _API_CALL_COUNTER_HELP)
    counter.inc(labels={"provider": provider, "status": status})

    if not success:
        return

    redis = get_redis_client()
    if redis is None:
        return

    now = time.time()
    try:
        redis.zadd(_REDIS_ZSET_KEY, {provider + "|" + str(now): now})
        redis.zremrangebyscore(_REDIS_ZSET_KEY, 0, now - _WINDOW_SECONDS)
    except Exception as exc:  # pragma: no cover - metrics degradation only
        log_json(stage="api_metrics.redis_error", error=str(exc))


def install_requests_metrics() -> None:
    """Install monkey patch on requests.Session.request to capture metrics."""
    global _installed
    if _installed:
        return

    with _lock:
        if _installed:
            return

        original_request = requests.Session.request

        def instrumented_request(self, method, url, *args, **kwargs):  # type: ignore[override]
            provider = _identify_provider(url)
            start = time.perf_counter()
            try:
                response = original_request(self, method, url, *args, **kwargs)
            except requests.RequestException:
                _record_api_call(provider, "error", False)
                raise
            except Exception:
                _record_api_call(provider, "error", False)
                raise
            else:
                status_bucket = f"{response.status_code // 100}xx"
                success = 200 <= response.status_code < 300
                _record_api_call(provider, status_bucket, success)
                return response

        requests.Session.request = instrumented_request  # type: ignore[assignment]
        _installed = True


__all__ = ["install_requests_metrics", "_REDIS_ZSET_KEY", "_WINDOW_SECONDS"]
