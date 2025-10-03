"""GoPlus API client with authentication, rate limiting, and retry logic"""

import os
import threading
import time
from typing import Any, Dict, Optional

import httpx

from api.core.metrics_store import log_json


class GoPlusClientError(Exception):
    """GoPlus client error"""

    pass


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = float(refill_rate)  # tokens per second
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> float:
        # 计算需要等待多久，但**不要在持锁时睡眠**
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            deficit = tokens - self.tokens
            wait_time = deficit / self.refill_rate

        # 释放锁后睡
        time.sleep(wait_time)

        # 醒来后再扣一次，保证并发正确
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            # 此时应足够
            if self.tokens >= tokens:
                self.tokens -= tokens
                return wait_time
            # 极端情况下再给一丢丢，避免负数
            needed = max(0.0, tokens - self.tokens)
            if needed > 0:
                extra = needed / self.refill_rate
                time.sleep(extra)
                now = time.monotonic()
                elapsed = now - self.last_refill
                self.tokens = min(
                    self.capacity, self.tokens + elapsed * self.refill_rate
                )
                self.last_refill = now
                self.tokens = max(0.0, self.tokens - tokens)
                return wait_time + extra
            return wait_time


class GoPlusClient:
    """GoPlus API client with rate limiting and retry"""

    BASE_URL = "https://api.gopluslabs.io"

    def __init__(
        self,
        access_token: Optional[str] = None,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        timeout_ms: int = 4000,
        retry: int = 2,
    ):
        """Initialize GoPlus client with authentication"""
        # Load from env if not provided
        self.access_token = access_token or os.getenv("GOPLUS_ACCESS_TOKEN")
        self.api_key = api_key or os.getenv("GOPLUS_API_KEY")
        self.client_id = client_id or os.getenv("GOPLUS_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("GOPLUS_CLIENT_SECRET")

        # Validate we have at least one auth method
        if not any(
            [self.access_token, self.api_key, (self.client_id and self.client_secret)]
        ):
            raise GoPlusClientError("No authentication method configured")

        self.timeout_ms = timeout_ms or int(os.getenv("GOPLUS_TIMEOUT_MS", "4000"))
        self.retry = retry or int(os.getenv("GOPLUS_RETRY", "2"))

        # Rate limiter: 28 requests per minute
        rpm = int(os.getenv("GOPLUS_RATELIMIT_RPM", "28"))
        self.rate_limiter = TokenBucket(capacity=rpm, refill_rate=rpm / 60.0)

        # Lazy init for httpx client
        self._client = None

    # ---- in GoPlusClient._get_client ----
    def _get_client(self) -> httpx.Client:
        """Lazy initialize httpx client"""
        if self._client is None:
            # 优先级：access_token / api_key 使用 headers；client_id/secret 走 httpx.BasicAuth
            auth = None
            if not (self.access_token or self.api_key) and (
                self.client_id and self.client_secret
            ):
                auth = httpx.BasicAuth(self.client_id, self.client_secret)

            self._client = httpx.Client(
                base_url=self.BASE_URL,
                # 细化超时：连接/池子快失败，读写遵循超时预算
                timeout=httpx.Timeout(
                    connect=2.0,
                    read=self.timeout_ms / 1000.0,
                    write=self.timeout_ms / 1000.0,
                    pool=2.0,
                ),
                headers=self._build_headers(),
                auth=auth,
            )
        return self._client

    # ---- in GoPlusClient._build_headers ----
    def _build_headers(self) -> Dict[str, str]:
        """Build authentication headers"""
        headers = {"Content-Type": "application/json"}

        # Priority: access_token > api_key > client_id/secret
        if self.access_token:
            headers["Authorization"] = (
                f"Bearer {self.access_token}"  # httpx 会用这个发请求，但日志里别打印
            )
        elif self.api_key:
            headers["X-API-KEY"] = self.api_key
        # client_id/secret 使用 httpx.BasicAuth，不手搓 Basic 头
        return headers

    def _request(
        self, method: str, endpoint: str, params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Execute HTTP request with retry and rate limiting"""
        # Rate limiting
        wait_ms = self.rate_limiter.acquire() * 1000
        if wait_ms > 0:
            log_json(stage="goplus.ratelimit", wait_ms=int(wait_ms))

        # Log request (sanitized)
        log_json(
            stage="goplus.http.request",
            method=method,
            endpoint=endpoint,
            params_keys=list(params.keys()) if params else [],
        )

        client = self._get_client()
        last_error = None
        backoff_times = [0.5, 1.0]  # Exponential backoff

        for attempt in range(self.retry + 1):
            start_time = time.monotonic()

            try:
                response = client.request(method, endpoint, params=params)
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                # Log response
                log_json(
                    stage="goplus.http.response",
                    status=response.status_code,
                    latency_ms=elapsed_ms,
                )

                # Success
                if response.status_code == 200:
                    return response.json()

                # 在 _request 的 401 分支补一行日志并立即失败（不重试）
                if response.status_code == 401:
                    last_error = "HTTP 401: unauthorized"
                    log_json(stage="goplus.error", error=last_error)
                    break

                # Rate limiting or server error - retry
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt < self.retry:
                        backoff = backoff_times[min(attempt, len(backoff_times) - 1)]
                        log_json(
                            stage="goplus.retry",
                            attempt=attempt + 1,
                            reason=f"HTTP {response.status_code}",
                            backoff_s=backoff,
                        )
                        time.sleep(backoff)
                        continue

                # Other errors
                last_error = f"HTTP {response.status_code}: {response.text}"

            except httpx.TimeoutException as e:
                last_error = f"Request timeout after {self.timeout_ms}ms"
                if attempt < self.retry:
                    log_json(
                        stage="goplus.retry", attempt=attempt + 1, reason="timeout"
                    )
                    time.sleep(backoff_times[min(attempt, len(backoff_times) - 1)])
                    continue

            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < self.retry:
                    log_json(
                        stage="goplus.retry",
                        attempt=attempt + 1,
                        reason="network_error",
                    )
                    time.sleep(backoff_times[min(attempt, len(backoff_times) - 1)])
                    continue

        # All retries exhausted
        log_json(stage="goplus.error", error=last_error, retries_exhausted=True)
        raise GoPlusClientError(
            f"Request failed after {self.retry} retries: {last_error}"
        )

    def token_security(self, chain_id: str, address: str) -> Dict[str, Any]:
        """Check token security"""
        return self._request(
            "GET",
            f"/api/v1/token_security/{chain_id}",
            params={"contract_addresses": address},
        )

    def address_security(self, address: str) -> Dict[str, Any]:
        """Check address security"""
        return self._request(
            "GET", "/api/v1/address_security", params={"address": address}
        )

    def approval_security(
        self, chain_id: str, address: str, type: str = "erc20"
    ) -> Dict[str, Any]:
        """Check approval security"""
        return self._request(
            "GET",
            f"/api/v1/approval_security/{chain_id}",
            params={"contract_address": address, "type": type},
        )

    def close(self):
        """Close underlying HTTP client and release resources."""
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):
        """Clean up client on deletion"""
        self.close()
