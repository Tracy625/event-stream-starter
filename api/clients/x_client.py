"""
X (Twitter) client abstraction layer.

Provides unified interface for fetching tweets via different backends:
- GraphQL (default for Day8)
- API (placeholder)
- Apify (placeholder)
"""

import os
import time
import random
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
import json
import httpx
from api.core.metrics_store import log_json


class XClient(ABC):
    """Abstract base class for X/Twitter data fetching."""
    
    @abstractmethod
    def fetch_user_tweets(self, handle: str, since_id: Optional[str] = None) -> list[Dict[str, Any]]:
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
            log_json(stage="x.fetch.error", backend="graphql",
                     error="Missing X_GRAPHQL_AUTH_TOKEN or X_GRAPHQL_CT0")
    
    def fetch_user_tweets(self, handle: str, since_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch tweets using GraphQL API (or mock if X_GRAPHQL_MOCK=true)."""

        # Mock first: do not require credentials
        if self.use_mock:
            log_json(stage="x.fetch.request", backend="graphql", handle=handle, since_id=since_id, mock=True)
            tweets = self._mock_graphql_response(handle)
            log_json(stage="x.fetch.success", backend="graphql", count=len(tweets), handle=handle, mock=True)
            return tweets

        # Real path requires credentials
        if not self.auth_token or not self.ct0:
            log_json(stage="x.fetch.degrade", backend="graphql", reason="Missing credentials")
            return []

        log_json(stage="x.fetch.request", backend="graphql", handle=handle, since_id=since_id)
        
        # real request path
        retries = 0
        while retries < self.max_retries:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    user_id = self._lookup_user_id(client, handle)
                    if not user_id:
                        log_json(stage="x.fetch.error", backend="graphql", error="user_id_not_found", handle=handle)
                        return []
                    items = self._fetch_user_tweets(client, user_id, since_id=since_id)
                    tweets = self._normalize_items(handle, items)
                    log_json(stage="x.fetch.success", backend="graphql", count=len(tweets), handle=handle)
                    return tweets
                    
            except httpx.TimeoutException:
                retries += 1
                if retries >= self.max_retries:
                    log_json(stage="x.fetch.error", backend="graphql", 
                            error="Timeout after retries", handle=handle)
                    return []
                
                # Exponential backoff with jitter
                wait_time = (2 ** retries) + random.uniform(0, 1)
                time.sleep(wait_time)
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit - apply backoff
                    retry_after = int(e.response.headers.get("retry-after", "60"))
                    log_json(stage="x.fetch.error", backend="graphql", 
                            error="Rate limited", retry_after=retry_after)
                    
                    if retries < self.max_retries:
                        time.sleep(retry_after)
                        retries += 1
                        continue
                        
                log_json(stage="x.fetch.error", backend="graphql", 
                        error=f"HTTP {e.response.status_code}", handle=handle)
                return []
                
            except Exception as e:
                log_json(stage="x.fetch.error", backend="graphql", 
                        error=str(e), handle=handle)
                return []
        
        return []
    
    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user profile with avatar URL (mock-only for now)."""
        log_json(stage="x.avatar.request", backend="graphql", handle=handle)
        
        # Mock & degrade path：缺凭证或显式 mock 时返回稳定可控的 mock
        if self.use_mock or not self.auth_token or not self.ct0:
            iso_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            # 允许通过 X_AVATAR_MOCK_BUMP 来"制造变化"，用于验收 Card B 的 change 日志
            bump = os.getenv("X_AVATAR_MOCK_BUMP", "").strip()
            suffix = f"?v={bump}" if bump else ""
            profile = {
                "handle": handle,
                "avatar_url": f"https://img.x.local/{handle}.png{suffix}",
                "ts": iso_ts,
            }
            log_json(stage="x.avatar.success", handle=handle, mock=True, bump=bump or None)
            return profile
        
        # Real request placeholder (not implemented yet)
        try:
            # TODO: Implement real GraphQL request when needed
            # For now, just fail and return None
            raise NotImplementedError("Real GraphQL profile fetch not implemented")
            
        except Exception as e:
            log_json(
                stage="x.avatar.error", 
                error=str(e),
                handle=handle
            )
            return None
    
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.auth_token}",
            "x-csrf-token": self.ct0,
            "Cookie": f"ct0={self.ct0}",
            "Content-Type": "application/json",
        }
    
    def _post(self, client: httpx.Client, op: str, variables: Dict[str, Any]) -> Dict[str, Any]:
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
            return (
                data.get("data", {})
                    .get("user", {})
                    .get("result", {})
                    .get("rest_id")
            )
        except httpx.HTTPError as e:
            log_json(stage="x.fetch.error", backend="graphql", error=f"user_lookup:{e.__class__.__name__}")
            return None
    
    def _fetch_user_tweets(self, client: httpx.Client, user_id: str, since_id: Optional[str]) -> List[Dict[str, Any]]:
        # minimal timeline fetch; ignore since_id if cursor model differs
        variables = {
            "userId": user_id,
            "count": 20,
            "withVoice": False,
            "withV2Timeline": True,
        }
        data = self._post(client, self.q_tweets, variables)
        return data.get("data", {}).get("user", {}).get("result", {}).get("timeline_v2", {}).get("timeline", {}).get("instructions", [])
    
    def _normalize_items(self, handle: str, instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
                    out.append({
                        "id": str(tid),
                        "author": handle,
                        "text": text,
                        "created_at": created if created else "",
                        "urls": [u for u in urls if u],
                    })
        return out
    
    def _mock_graphql_response(self, handle: str) -> List[Dict[str, Any]]:
        """Mock GraphQL response for testing."""
        # make ids unique per handle to avoid cross-handle dedup in tests
        suffix = abs(hash(handle)) % 10000
        base = ["1234567890123456789", "1234567890123456788", "1234567890123456787"]
        ids = [f"{b}{suffix}" for b in base]
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        iso = lambda dt: dt.replace(microsecond=0).isoformat().replace("+00:00","Z")
        return [
            {
                "id": ids[0],
                "author": handle,
                "text": f"$PEPE is pumping! Contract: 0x6982508145454ce325ddbe47a25d4ec3d2311933",
                "created_at": iso(now - timedelta(minutes=1)),
                "urls": ["https://x.com/elonmusk/status/1234567890123456789"]
            },
            {
                "id": ids[1],
                "author": handle,
                "text": f"Just bought more $BTC and $ETH",
                "created_at": iso(now - timedelta(minutes=3)),
                "urls": []
            },
            {
                "id": ids[2],
                "author": handle,
                "text": f"Check out this new token $MEME",
                "created_at": iso(now - timedelta(minutes=5)),
                "urls": ["https://t.co/abc123"]
            }
        ]


class APIXClient(XClient):
    """API v2 implementation (placeholder)."""
    
    def fetch_user_tweets(self, handle: str, since_id: Optional[str] = None) -> list[Dict[str, Any]]:
        raise NotImplementedError("API backend not implemented yet")
    
    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user profile (not implemented)."""
        raise NotImplementedError("API backend profile fetch not implemented yet")


class ApifyXClient(XClient):
    """Apify implementation (placeholder)."""
    
    def fetch_user_tweets(self, handle: str, since_id: Optional[str] = None) -> list[Dict[str, Any]]:
        raise NotImplementedError("Apify backend not implemented yet")
    
    def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
        """Fetch user profile (not implemented)."""
        raise NotImplementedError("Apify backend profile fetch not implemented yet")


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
            def fetch_user_tweets(self, handle: str, since_id: Optional[str] = None) -> list[Dict[str, Any]]:
                log_json(stage="x.fetch.degrade", backend="off", reason="Backend disabled")
                return []
            def fetch_user_profile(self, handle: str) -> Optional[Dict[str, Any]]:
                log_json(stage="x.avatar.error", error="Backend disabled", handle=handle)
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