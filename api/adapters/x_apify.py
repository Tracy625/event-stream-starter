"""
Adapters for Apify X (Twitter) actor outputs to unified schema.

Unified tweet schema:
- id: str
- author: str (handle)
- text: str
- created_at: str (ISO8601 or original string)
- urls: List[str]
"""

from typing import Any, Dict, List


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _extract_urls(item: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    # Common Apify fields: urls, url, entities.urls[*].expanded_url
    if isinstance(item.get("urls"), list):
        for u in item.get("urls"):
            if isinstance(u, str) and u:
                urls.append(u)
            elif isinstance(u, dict):
                val = u.get("expanded_url") or u.get("url")
                if val:
                    urls.append(str(val))
    if item.get("url") and isinstance(item.get("url"), str):
        urls.append(item["url"])  # include original tweet URL if present
    ents = item.get("entities", {}) or {}
    if isinstance(ents, dict):
        for u in ents.get("urls", []) or []:
            if isinstance(u, dict):
                val = u.get("expanded_url") or u.get("url")
                if val:
                    urls.append(str(val))
    # De-duplicate while preserving order
    seen = set()
    out: List[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def map_apify_tweet(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map a single Apify dataset item to unified tweet schema."""
    # Apify Tweet Scraper often provides id, userScreenName, fullText/text, createdAt
    tid = _norm_str(item.get("id") or item.get("rest_id") or item.get("tweetId") or item.get("id_str"))
    # Prefer nested user.screen_name when present
    user = item.get("user") if isinstance(item.get("user"), dict) else None
    author = _norm_str(
        (user.get("screen_name") if user else None)
        or item.get("userScreenName")
        or item.get("screenName")
        or item.get("author")
    )
    text = _norm_str(item.get("fullText") or item.get("full_text") or item.get("text") or item.get("body"))
    created = _norm_str(item.get("createdAt") or item.get("created_at") or item.get("time") or item.get("ts"))
    urls = _extract_urls(item)
    return {
        "id": tid,
        "author": author,
        "text": text,
        "created_at": created,
        "urls": urls,
    }


def map_apify_user(item: Dict[str, Any]) -> Dict[str, Any]:
    """Map Apify user-like object to minimal user profile schema."""
    user = item.get("user") if isinstance(item.get("user"), dict) else None
    handle = _norm_str(
        (user.get("screen_name") if user else None)
        or item.get("userScreenName")
        or item.get("screenName")
        or item.get("handle")
        or item.get("username")
    )
    avatar = _norm_str(
        (user.get("profile_image_url_https") if user else None)
        or item.get("profileImageUrl")
        or item.get("avatarUrl")
        or item.get("avatar_url")
        or item.get("profile_image_url")
    )
    ts = _norm_str(item.get("ts") or item.get("time") or item.get("createdAt") or item.get("updatedAt") or "")
    return {"handle": handle, "avatar_url": avatar, "ts": ts}
