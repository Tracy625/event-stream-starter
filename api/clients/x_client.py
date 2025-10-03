"""
X (Twitter) client abstraction layer.

Provides unified interface for fetching tweets via different backends:
- GraphQL (default for Day8)
- API (placeholder)
- Apify (placeholder)
"""

import concurrent.futures
import json
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from api.adapters.x_apify import map_apify_tweet, map_apify_user
from api.cache import get_redis_client
from api.core import metrics as metrics_core
from api.core.metrics_store import log_json

# Cache (fallback to in-process if Redis unavailable)
_LOCAL_CACHE: Dict[str, Tuple[Any, float]] = {}


def _cache_set(key: str, value: Any, ttl_s: int) -> None:
    try:
        rc = get_redis_client()
        if rc is not None:
            rc.setex(key, ttl_s, repr(value))
            return
    except Exception:
        pass
    # local fallback
    _LOCAL_CACHE[key] = (value, time.time() + ttl_s)


def _cache_get(key: str) -> Optional[Any]:
    try:
        rc = get_redis_client()
        if rc is not None:
            val = rc.get(key)
            if val is not None:
                try:
                    return eval(val.decode())
                except Exception:
                    return None
    except Exception:
        pass
    item = _LOCAL_CACHE.get(key)
    if not item:
        return None
    value, exp = item
    if time.time() < exp:
        return value
    _LOCAL_CACHE.pop(key, None)
    return None


def _status_label(ok: Optional[bool], degrade: bool = False) -> str:
    if degrade:
        return "degrade"
    return "ok" if ok else "fail"


def _classify_exc(e: Exception, status_code: Optional[int] = None) -> str:
    if isinstance(e, httpx.TimeoutException):
        return "timeout"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 429:
            return "429"
        if 500 <= code < 600:
            return "5xx"
        if code in (401, 403):
            return "auth"
        return f"http_{code}"
    if status_code is not None:
        if status_code == 429:
            return "429"
        if 500 <= status_code < 600:
            return "5xx"
        if status_code in (401, 403):
            return "auth"
    # Generic classifications
    name = e.__class__.__name__.lower()
    if "schema" in name:
        return "schema_mismatch"
    return "other"


def _parse_backends_env(op: str) -> List[str]:
    # op in {tweets, profile, search}
    key = {
        "tweets": "X_BACKENDS_TWEETS",
        "profile": "X_BACKENDS_PROFILE",
        "search": "X_BACKENDS_SEARCH",
    }.get(op, "X_BACKENDS")
    env = (os.getenv(key) or os.getenv("X_BACKENDS") or "").strip()
    if env:
        return [b.strip().lower() for b in env.split(",") if b.strip()]
    # Fallback legacy single-backend
    b = (os.getenv("X_BACKEND", "graphql") or "graphql").strip().lower()
    return [b]


class XClient(ABC):
    """Abstract base class for X/Twitter data fetching."""

    @abstractmethod
    def fetch_user_tweets(
        self, handle: str, since_id: Optional[str] = None, limit: int = 20
    ) -> list[Dict[str, Any]]:
        """
        Fetch tweets from a specific user.

        Args:
            handle: Twitter handle (without @)
            since_id: Optional tweet ID to fetch tweets after

        Returns:
            List of tweet dicts with keys: id, author, text, created_at, urls
        """
        pass

    @abstractmethod
    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """
        Fetch user profile with avatar URL.

        Args:
            handle: Twitter handle (without @)

        Returns:
            Dict with keys: handle, avatar_url, ts or None if error
        """
        pass


class GraphQLXClient(XClient):
    """GraphQL implementation for X data fetching."""

    def __init__(self):
        self.auth_token = os.getenv("X_GRAPHQL_AUTH_TOKEN", "")
        self.ct0 = os.getenv("X_GRAPHQL_CT0", "")
        self.timeout = int(os.getenv("X_REQUEST_TIMEOUT", "10"))
        self.max_retries = 3
        # ensure mock flag exists (needed by avatar mock + Card B)
        self.use_mock = os.getenv("X_GRAPHQL_MOCK", "false").lower() == "true"
        self.q_user = os.getenv("X_GRAPHQL_USER_QUERY_ID", "UserByScreenName")
        self.q_tweets = os.getenv("X_GRAPHQL_TWEETS_QUERY_ID", "UserTweets")

        if (not self.auth_token or not self.ct0) and not self.use_mock:
            log_json(
                stage="x.fetch.error",
                backend="graphql",
                error="Missing X_GRAPHQL_AUTH_TOKEN or X_GRAPHQL_CT0",
            )

    def fetch_user_tweets(
        self, handle: str, since_id: Optional[str] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Fetch tweets using GraphQL API (or mock if X_GRAPHQL_MOCK=true)."""

        # Mock first: do not require credentials
        if self.use_mock:
            log_json(
                stage="x.fetch.request",
                backend="graphql",
                handle=handle,
                since_id=since_id,
                mock=True,
            )
            tweets = self._mock_graphql_response(handle)
            log_json(
                stage="x.fetch.success",
                backend="graphql",
                count=len(tweets),
                handle=handle,
                mock=True,
            )
            return tweets

        # Real path requires credentials
        if not self.auth_token or not self.ct0:
            log_json(
                stage="x.fetch.degrade", backend="graphql", reason="Missing credentials"
            )
            return []

        log_json(
            stage="x.fetch.request", backend="graphql", handle=handle, since_id=since_id
        )

        # real request path
        retries = 0
        while retries < self.max_retries:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    user_id = self._lookup_user_id(client, handle)
                    if not user_id:
                        log_json(
                            stage="x.fetch.error",
                            backend="graphql",
                            error="user_id_not_found",
                            handle=handle,
                        )
                        return []
                    items = self._fetch_user_tweets(client, user_id, since_id=since_id)
                    tweets = self._normalize_items(handle, items)
                    if isinstance(limit, int) and limit > 0:
                        tweets = tweets[:limit]
                    log_json(
                        stage="x.fetch.success",
                        backend="graphql",
                        count=len(tweets),
                        handle=handle,
                    )
                    return tweets

            except httpx.TimeoutException:
                retries += 1
                if retries >= self.max_retries:
                    log_json(
                        stage="x.fetch.error",
                        backend="graphql",
                        error="Timeout after retries",
                        handle=handle,
                    )
                    return []

                # Exponential backoff with jitter
                wait_time = (2**retries) + random.uniform(0, 1)
                time.sleep(wait_time)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit - apply backoff
                    retry_after = int(e.response.headers.get("retry-after", "60"))
                    log_json(
                        stage="x.fetch.error",
                        backend="graphql",
                        error="Rate limited",
                        retry_after=retry_after,
                    )

                    if retries < self.max_retries:
                        time.sleep(retry_after)
                        retries += 1
                        continue

                log_json(
                    stage="x.fetch.error",
                    backend="graphql",
                    error=f"HTTP {e.response.status_code}",
                    handle=handle,
                )
                return []

            except Exception as e:
                log_json(
                    stage="x.fetch.error",
                    backend="graphql",
                    error=str(e),
                    handle=handle,
                )
                return []

        return []

    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user profile with avatar URL (mock-only for now)."""
        log_json(stage="x.avatar.request", backend="graphql", handle=handle)

        # Mock & degrade path：缺凭证或显式 mock 时返回稳定可控的 mock
        if self.use_mock or not self.auth_token or not self.ct0:
            iso_ts = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
            # 允许通过 X_AVATAR_MOCK_BUMP 来"制造变化"，用于验收 Card B 的 change 日志
            bump = os.getenv("X_AVATAR_MOCK_BUMP", "").strip()
            suffix = f"?v={bump}" if bump else ""
            profile = {
                "handle": handle,
                "avatar_url": f"https://img.x.local/{handle}.png{suffix}",
                "ts": iso_ts,
            }
            log_json(
                stage="x.avatar.success", handle=handle, mock=True, bump=bump or None
            )
            return profile

        # Real request placeholder (not implemented yet)
        # TODO: Implement real GraphQL profile fetch if needed; degrade for now
        log_json(
            stage="x.avatar.error",
            error="graphql_profile_not_implemented",
            handle=handle,
        )
        return None

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "x-csrf-token": self.ct0,
            "Cookie": f"ct0={self.ct0}",
            "Content-Type": "application/json",
        }

    def _post(
        self, client: httpx.Client, op: str, variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        # op example: "UserByScreenName" or "UserTweets"
        url = f"https://api.twitter.com/graphql/{op}"
        resp = client.post(url, headers=self._headers(), json={"variables": variables})
        resp.raise_for_status()
        return resp.json()

    def _lookup_user_id(self, client: httpx.Client, handle: str) -> Optional[str]:
        # minimal user lookup by screen name
        try:
            data = self._post(client, self.q_user, {"screen_name": handle})
            # tolerate structural drift
            return data.get("data", {}).get("user", {}).get("result", {}).get("rest_id")
        except httpx.HTTPError as e:
            log_json(
                stage="x.fetch.error",
                backend="graphql",
                error=f"user_lookup:{e.__class__.__name__}",
            )
            return None

    def _fetch_user_tweets(
        self, client: httpx.Client, user_id: str, since_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        # minimal timeline fetch; ignore since_id if cursor model differs
        variables = {
            "userId": user_id,
            "count": 20,
            "withVoice": False,
            "withV2Timeline": True,
        }
        data = self._post(client, self.q_tweets, variables)
        return (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )

    def _normalize_items(
        self, handle: str, instructions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        # conservative walk: look for entries with tweet results
        for ins in instructions:
            for entry in ins.get("entries", []):
                content = entry.get("content", {})
                item = content.get("itemContent", {}) or content.get("content", {})
                result = (item.get("tweet_results", {}) or {}).get("result", {})
                legacy = result.get("legacy", {})
                if not legacy:
                    continue
                tid = result.get("rest_id") or legacy.get("id_str")
                text = legacy.get("full_text") or legacy.get("text") or ""
                created = legacy.get("created_at")
                urls = []
                ents = legacy.get("entities", {})
                for u in ents.get("urls", []) or []:
                    if isinstance(u, dict):
                        urls.append(u.get("expanded_url") or u.get("url"))
                if tid and text:
                    out.append(
                        {
                            "id": str(tid),
                            "author": handle,
                            "text": text,
                            "created_at": created if created else "",
                            "urls": [u for u in urls if u],
                        }
                    )
        return out

    def _mock_graphql_response(self, handle: str) -> List[Dict[str, Any]]:
        """Mock GraphQL response for testing."""
        # make ids unique per handle to avoid cross-handle dedup in tests
        suffix = abs(hash(handle)) % 10000
        base = ["1234567890123456789", "1234567890123456788", "1234567890123456787"]
        ids = [f"{b}{suffix}" for b in base]
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        iso = lambda dt: dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return [
            {
                "id": ids[0],
                "author": handle,
                "text": f"$PEPE is pumping! Contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933",
                "created_at": iso(now - timedelta(minutes=1)),
                "urls": ["https://x.com/elonmusk/status/1234567890123456789"],
            },
            {
                "id": ids[1],
                "author": handle,
                "text": f"Just bought more $BTC and $ETH",
                "created_at": iso(now - timedelta(minutes=3)),
                "urls": [],
            },
            {
                "id": ids[2],
                "author": handle,
                "text": f"Check out this new token $MEME",
                "created_at": iso(now - timedelta(minutes=5)),
                "urls": ["https://t.co/abc123"],
            },
        ]

    def ping(self) -> Dict[str, Any]:
        """Lightweight upstream probe for GraphQL endpoint.
        Returns dict with status and rtt_ms.
        """
        url = "https://api.twitter.com"  # public endpoint ok for reachability
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(url)
                rtt = int((time.perf_counter() - t0) * 1000)
                status = "ok" if r.status_code < 500 else "fail"
                if r.status_code in (401, 403):
                    status = "auth"
                return {"status": status, "rtt_ms": rtt, "code": r.status_code}
        except httpx.TimeoutException:
            return {
                "status": "timeout",
                "rtt_ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            return {"status": "net", "error": str(e)[:120]}


class APIXClient(XClient):
    """API v2 implementation (placeholder)."""

    def fetch_user_tweets(
        self, handle: str, since_id: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        raise NotImplementedError("API backend not implemented yet")

    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user profile (not implemented)."""
        raise NotImplementedError("API backend profile fetch not implemented yet")


class ApifyXClient(XClient):
    """Apify implementation via Tweet Scraper actor."""

    def __init__(self):
        # Support both APIFY_TOKEN and APIFY_API_TOKEN
        self.token = (
            os.getenv("APIFY_TOKEN", "").strip()
            or os.getenv("APIFY_API_TOKEN", "").strip()
        )
        # Default to official v2 actor name
        self.actor = os.getenv(
            "APIFY_TWEET_SCRAPER_ACTOR", "apidojo/tweet-scraper"
        ).strip()
        self.default_country = os.getenv("APIFY_DEFAULT_COUNTRY", "US")
        self.timeout_s = int(os.getenv("X_REQUEST_TIMEOUT_SEC", "5"))
        self.max_retries = int(os.getenv("X_RETRY_MAX", "2"))
        self.poll_attempts = int(os.getenv("APIFY_POLL_MAX", "3"))
        self.poll_sleep_s = max(
            0.1, float(int(os.getenv("APIFY_POLL_INTERVAL_MS", "800")) / 1000.0)
        )
        self.metrics_req = metrics_core.counter(
            "x_backend_request_total", "X backend requests by backend/op/status"
        )
        self.metrics_lat = metrics_core.histogram(
            "x_backend_latency_ms",
            "X backend latency in ms",
            buckets=[50, 100, 200, 500, 1000, 2000, 5000],
        )
        # Run mode: 'poll' (start+poll dataset) or 'sync' (single run-sync call)
        rm = (os.getenv("APIFY_RUN_MODE", "") or "").strip().lower()
        if not rm:
            # Backward-compat boolean toggle
            rs = (os.getenv("APIFY_RUN_SYNC", "") or "").strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            rm = "sync" if rs else "poll"
        self.run_mode = rm if rm in ("poll", "sync") else "poll"

    def _actor_path(self) -> str:
        """Return actor identifier formatted for Apify API path.
        Accepts env like 'user/actor' or 'user~actor' and normalizes to 'user~actor'.
        """
        act = (self.actor or "").strip()
        # Apify API expects ~ between username and actor name
        return act.replace("/", "~")

    def _api_url(self, path: str, **params) -> str:
        base = "https://api.apify.com/v2"
        qp = []
        token = self.token
        if token:
            qp.append(("token", token))
        for k, v in params.items():
            if v is not None:
                qp.append((k, v))
        from urllib.parse import urlencode

        return f"{base}{path}?{urlencode(qp)}" if qp else f"{base}{path}"

    def _start_run(
        self, client: httpx.Client, handle: str, limit: int
    ) -> Tuple[str, str]:
        # Start actor run; return (runId, datasetId)
        url = self._api_url(f"/acts/{self._actor_path()}/runs")
        # apidojo/tweet-scraper expects twitterHandles; keep tweetsDesired for limiting
        payload = {
            "twitterHandles": [handle],
            "tweetsDesired": max(1, min(50, limit or 20)),
            "maxRequestRetries": 1,
            "countryCode": self.default_country,
        }
        r = client.post(url, json=payload)
        r.raise_for_status()
        data = r.json().get("data", {})
        run_id = data.get("id") or data.get("id")
        ds_id = data.get("defaultDatasetId") or data.get("datasetId")
        if not ds_id:
            raise RuntimeError("apify_no_dataset_id")
        return run_id, ds_id

    def _fetch_items(
        self, client: httpx.Client, dataset_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        # Cap fetched items to protect cost: at most limit*2
        max_items = max(
            1,
            min(
                max(
                    1, (limit or 20) * int(os.getenv("APIFY_ITEMS_MAX_MULTIPLIER", "2"))
                ),
                200,
            ),
        )
        url = self._api_url(f"/datasets/{dataset_id}/items", limit=max_items)
        r = client.get(url)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            return []
        return items

    def _run_sync_items(
        self, client: httpx.Client, handle: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Run actor in sync mode and return dataset items directly (single request).
        Cost-efficient: avoids dataset polling.
        """
        # Apply hard cap on returned items to control billing
        max_items = max(
            1,
            min(
                max(
                    1, (limit or 20) * int(os.getenv("APIFY_ITEMS_MAX_MULTIPLIER", "1"))
                ),
                200,
            ),
        )
        url = self._api_url(
            f"/acts/{self._actor_path()}/run-sync-get-dataset-items",
            limit=max_items,
        )
        payload = {
            "twitterHandles": [handle],
            "tweetsDesired": max(1, min(50, limit or 20)),
            "maxRequestRetries": 1,
            "countryCode": self.default_country,
            # Best-effort hints; actor may ignore unknown fields
            "maxItems": max_items,
            "sort": "Latest",
        }
        r = client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        # Expect a list of items
        return data if isinstance(data, list) else []

    def _observe(self, elapsed_ms: float, status: str, op: str):
        self.metrics_lat.observe(elapsed_ms, labels={"backend": "apify", "op": op})
        self.metrics_req.inc(labels={"backend": "apify", "op": op, "status": status})

    def fetch_user_tweets(
        self, handle: str, since_id: Optional[str] = None, limit: int = 20
    ) -> list[Dict[str, Any]]:
        start = time.perf_counter()
        op = "tweets"
        try:
            if not self.token:
                log_json(
                    stage="x.fetch.degrade",
                    backend="apify",
                    reason="Missing APIFY_TOKEN",
                )
                self._observe((time.perf_counter() - start) * 1000, "err", op)
                return []
            log_json(
                stage="x.fetch.request", backend="apify", handle=handle, limit=limit
            )
            retries = 0
            with httpx.Client(timeout=self.timeout_s) as client:
                if self.run_mode == "sync":
                    items = self._run_sync_items(client, handle, limit)
                else:
                    run_id, ds_id = self._start_run(client, handle, limit)
                    items: List[Dict[str, Any]] = []
                    # Poll up to poll_attempts
                    for i in range(self.poll_attempts):
                        try:
                            items = self._fetch_items(client, ds_id, limit)
                            if items:
                                break
                            time.sleep(self.poll_sleep_s)
                        except httpx.TimeoutException:
                            pass
                tweets = [map_apify_tweet(it) for it in (items or [])]
                if isinstance(limit, int) and limit > 0:
                    tweets = tweets[:limit]
                log_json(
                    stage="x.fetch.success",
                    backend="apify",
                    count=len(tweets),
                    handle=handle,
                )
                self._observe((time.perf_counter() - start) * 1000, "ok", op)
                return tweets
        except httpx.TimeoutException:
            self._observe((time.perf_counter() - start) * 1000, "timeout", op)
            raise
        except httpx.HTTPStatusError as e:
            log_json(
                stage="x.fetch.error",
                backend="apify",
                error=f"HTTP {e.response.status_code}",
            )
            self._observe((time.perf_counter() - start) * 1000, "err", op)
            return []
        except Exception as e:
            log_json(stage="x.fetch.error", backend="apify", error=str(e))
            self._observe((time.perf_counter() - start) * 1000, "err", op)
            return []

    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        # Apify actor may not expose profile endpoint directly; best-effort via first tweet's user info
        tweets = self.fetch_user_tweets(handle, limit=1)
        if not tweets:
            return None
        # Build minimal profile from tweet author; avatar not guaranteed
        return {
            "handle": handle,
            "avatar_url": "",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def ping(self) -> Dict[str, Any]:
        # Try list my acts if token provided, else base endpoint
        t0 = time.perf_counter()
        try:
            url = self._api_url("/acts")
            with httpx.Client(timeout=2.0) as client:
                r = client.get(url)
                rtt = int((time.perf_counter() - t0) * 1000)
                if r.status_code in (401, 403):
                    return {"status": "auth", "rtt_ms": rtt, "code": r.status_code}
                return {
                    "status": "ok" if r.status_code < 500 else "fail",
                    "rtt_ms": rtt,
                    "code": r.status_code,
                }
        except httpx.TimeoutException:
            return {
                "status": "timeout",
                "rtt_ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:
            return {"status": "net", "error": str(e)[:120]}


class MultiSourceXClient(XClient):
    """Aggregates multiple backends with failover and cooldown."""

    def __init__(self, backends: List[str]):
        # Allow empty init; determine order per-operation from env
        self.backends_order = [b.strip().lower() for b in backends if b.strip()]
        if not self.backends_order:
            self.backends_order = _parse_backends_env("tweets")  # default seed
        self.backends: List[Tuple[str, XClient]] = [
            (b, get_x_client(b)) for b in self.backends_order
        ]
        self.cooldown_sec = int(os.getenv("X_FAILOVER_COOLDOWN_SEC", "60"))
        self.timeout_s = int(os.getenv("X_REQUEST_TIMEOUT_SEC", "5"))
        self.max_retries = int(os.getenv("X_RETRY_MAX", "2"))
        self._last_fail: Dict[str, float] = {}
        self._health: Dict[str, Dict[str, Any]] = {b: {} for b in self.backends_order}
        self.failover_counter = metrics_core.counter(
            "x_backend_failover_total", "Total count of X backend failovers"
        )
        self.req_counter = metrics_core.counter(
            "x_backend_request_total", "X backend requests by backend/op/status"
        )
        self.lat_hist = metrics_core.histogram(
            "x_backend_latency_ms",
            "X backend latency in ms",
            buckets=[50, 100, 200, 500, 1000, 2000, 5000],
        )
        self.degrade_counter = metrics_core.counter(
            "x_backend_degrade_total", "Degrades when all backends fail"
        )
        self.cache_ttl = int(os.getenv("X_CACHE_TTL_S", "180"))
        self.race_mode = os.getenv("X_RACE_MODE", "false").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self.race_guard_ms = int(os.getenv("X_RACE_GUARD_MS", "250"))

    def _in_cooldown(self, backend: str) -> bool:
        last = self._last_fail.get(backend)
        return last is not None and (time.time() - last) < self.cooldown_sec

    def _note_result(
        self,
        backend: str,
        op: str,
        ok: bool,
        elapsed_ms: float,
        error: Optional[str] = None,
        degrade: bool = False,
        reason: Optional[str] = None,
    ):
        self.lat_hist.observe(elapsed_ms, labels={"backend": backend, "op": op})
        self.req_counter.inc(
            labels={"backend": backend, "op": op, "status": _status_label(ok, degrade)}
        )
        st = self._health.setdefault(backend, {})
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if ok:
            st["last_ok_ts"] = now
            st["last_error"] = None
        else:
            st["last_err_ts"] = now
            st["last_error"] = reason or error or "error"
            st["cooldown_until"] = int(time.time() + self.cooldown_sec)
        # propagate to global health snapshot
        try:
            _X_HEALTH["status"][backend] = st
            if not _X_HEALTH.get("backends"):
                _X_HEALTH["backends"] = self.backends_order
        except Exception:
            pass

    def _order_for_op(self, op: str) -> List[Tuple[str, XClient]]:
        # Prefer explicit instance order if provided
        if getattr(self, "backends", None):
            return self.backends
        order = _parse_backends_env(op)
        pairs: List[Tuple[str, XClient]] = []
        for b in order:
            try:
                pairs.append((b, get_x_client(b)))
            except Exception:
                continue
        return pairs

    def _supports_limit(self, client: XClient) -> bool:
        """Detect whether backend fetch_user_tweets accepts a 'limit' arg (backward compat for stubs/tests)."""
        try:
            import inspect

            return "limit" in inspect.signature(client.fetch_user_tweets).parameters
        except Exception:
            return True

    def _merge_profile_fields(
        self,
        primary: Dict[str, Any],
        secondary: Dict[str, Any],
        backend: str,
        source_map: Dict[str, str],
    ) -> Dict[str, Any]:
        if not secondary:
            return primary
        # fields to consider for fill
        for k in ("avatar_url", "verified", "name", "id", "handle"):
            pv = primary.get(k)
            if not pv:
                sv = secondary.get(k)
                if sv:
                    primary[k] = sv
                    source_map[k] = backend
        return primary

    def _try(self, backend: str, client: XClient, op: str, fn):
        if self._in_cooldown(backend):
            log_json(stage="x.fetch.skip_cooldown", backend=backend)
            return None
        t0 = time.perf_counter()
        try:
            result = fn()
            ok = bool(result)
            self._note_result(backend, op, ok, (time.perf_counter() - t0) * 1000)
            return result
        except Exception as e:
            self._last_fail[backend] = time.time()
            reason = _classify_exc(e)
            self._note_result(
                backend,
                op,
                False,
                (time.perf_counter() - t0) * 1000,
                error=str(e),
                reason=reason,
            )
            log_json(
                stage="x.fetch.error", backend=backend, error=str(e), reason=reason
            )
            return None

    def fetch_user_tweets(
        self, handle: str, since_id: Optional[str] = None, limit: int = 20
    ) -> list[Dict[str, Any]]:
        # Cache key
        cache_key = f"x:tweets:{handle}:{limit}"
        order = self._order_for_op("tweets")
        # Race mode (optional): run first two backends in parallel
        if self.race_mode and len(order) >= 2:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                futs = []
                # Guard: delay second slightly to avoid immediate double fire
                (b1, c1), (b2, c2) = order[0], order[1]
                futs.append(
                    ex.submit(
                        lambda: (
                            b1,
                            self._try(
                                b1,
                                c1,
                                "tweets",
                                lambda: c1.fetch_user_tweets(handle, since_id, limit),
                            ),
                        )
                    )
                )
                time.sleep(self.race_guard_ms / 1000.0)
                futs.append(
                    ex.submit(
                        lambda: (
                            b2,
                            self._try(
                                b2,
                                c2,
                                "tweets",
                                lambda: c2.fetch_user_tweets(handle, since_id, limit),
                            ),
                        )
                    )
                )
                for fut in concurrent.futures.as_completed(futs):
                    b, res = fut.result()
                    if res:
                        _cache_set(cache_key, res, self.cache_ttl)
                        return res
        # Serial try
        for b, c in order:
            if self._supports_limit(c):
                res = self._try(
                    b, c, "tweets", lambda: c.fetch_user_tweets(handle, since_id, limit)
                )
            else:
                res = self._try(
                    b, c, "tweets", lambda: c.fetch_user_tweets(handle, since_id)
                )
            if res:
                _cache_set(cache_key, res, self.cache_ttl)
                return res
            self.failover_counter.inc(labels={"from": b})
            log_json(stage="x.fetch.failover", from_backend=b)
        # Degrade to cache
        cached = _cache_get(cache_key)
        if cached:
            # mark degrade
            self.degrade_counter.inc(labels={"backend": "multi", "op": "tweets"})
            self._note_result(
                "multi",
                "tweets",
                ok=False,
                elapsed_ms=0.0,
                degrade=True,
                error="degraded_cache",
            )
            return cached
        return []

    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        cache_key = f"x:profile:{handle}"
        order = self._order_for_op("profile")
        merge_enabled = os.getenv("X_FIELD_MERGE", "true").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        src_map: Dict[str, str] = {}
        primary: Optional[Dict[str, Any]] = None
        for idx, (b, c) in enumerate(order):
            res = self._try(b, c, "profile", lambda: c.fetch_user_profile(handle))
            if res:
                if primary is None:
                    primary = res
                    src_map["_primary"] = b
                    if not merge_enabled:
                        return primary
                else:
                    primary = self._merge_profile_fields(primary, res, b, src_map)
                    break
            else:
                self.failover_counter.inc(labels={"from": b})
                log_json(stage="x.avatar.failover", from_backend=b)
        if primary:
            diag = {
                "source_map": {k: v for k, v in src_map.items() if k != "_primary"},
                "stale": False,
            }
            primary["diagnostic"] = diag
            _cache_set(cache_key, primary, self.cache_ttl)
            return primary
        # Degrade to cache
        cached = _cache_get(cache_key)
        if cached:
            self.degrade_counter.inc(labels={"backend": "multi", "op": "profile"})
            self._note_result(
                "multi",
                "profile",
                ok=False,
                elapsed_ms=0.0,
                degrade=True,
                error="degraded_cache",
            )
            if isinstance(cached, dict):
                d = dict(cached)
                diag = d.get("diagnostic") or {}
                diag["stale"] = True
                d["diagnostic"] = diag
                return d
            return cached
        return None


# Global health snapshot updated by MultiSourceXClient (best-effort)
_X_HEALTH: Dict[str, Any] = {"backends": [], "status": {}}


def get_x_health() -> Dict[str, Any]:
    # Optionally include upstream probes
    data = {
        "backends": list(_X_HEALTH.get("backends", [])),
        "status": dict(_X_HEALTH.get("status", {})),
        "probes": {},
    }
    for b in data["backends"]:
        try:
            client = get_x_client(b)
            if hasattr(client, "ping"):
                data["probes"][b] = getattr(client, "ping")()
        except Exception as e:
            data["probes"][b] = {"status": "error", "error": str(e)[:120]}
    return data


def get_x_client(backend: str) -> XClient:
    """
    Factory method to get appropriate X client based on backend.

    Args:
        backend: Backend type ('graphql', 'api', 'apify', 'off')

    Returns:
        XClient instance

    Raises:
        ValueError: If backend is unknown
    """
    backend = backend.lower()

    if backend == "off":
        # Return a null client that returns empty results
        class NullXClient(XClient):
            def fetch_user_tweets(
                self, handle: str, since_id: Optional[str] = None
            ) -> list[Dict[str, Any]]:
                log_json(
                    stage="x.fetch.degrade", backend="off", reason="Backend disabled"
                )
                return []

            def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
                log_json(
                    stage="x.avatar.error", error="Backend disabled", handle=handle
                )
                return None

        return NullXClient()

    if backend == "graphql":
        return GraphQLXClient()
    elif backend == "api":
        return APIXClient()
    elif backend == "apify":
        return ApifyXClient()
    else:
        raise ValueError(f"Unknown backend: {backend}")


def get_x_client_from_env() -> XClient:
    """Construct X client from env: prefer X_BACKENDS (multi-source) over X_BACKEND."""
    backends_env = os.getenv("X_BACKENDS", "").strip()
    if backends_env:
        order = [b.strip() for b in backends_env.split(",") if b.strip()]
        client = MultiSourceXClient(order)
        # Update global health view
        _X_HEALTH["backends"] = order
        return client
    backend = os.getenv("X_BACKEND", "graphql")
    return get_x_client(backend)
