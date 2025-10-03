import pytest

from api.adapters.x_apify import map_apify_tweet, map_apify_user
from api.clients.x_client import MultiSourceXClient, XClient


def test_map_apify_tweet_basic():
    item = {
        "id": "123",
        "userScreenName": "alice",
        "fullText": "Hello $PEPE",
        "createdAt": "2025-09-25T00:00:00Z",
        "entities": {"urls": [{"expanded_url": "https://x.com/t/123"}]},
    }
    tw = map_apify_tweet(item)
    assert tw["id"] == "123"
    assert tw["author"] == "alice"
    assert "PEPE" in tw["text"]
    assert tw["urls"] == ["https://x.com/t/123"]


def test_map_apify_user_basic():
    item = {
        "userScreenName": "bob",
        "profileImageUrl": "https://img.example/bob.png",
        "ts": "2025-09-25T00:00:00Z",
    }
    u = map_apify_user(item)
    assert u["handle"] == "bob"
    assert u["avatar_url"].endswith("bob.png")


class _FailClient(XClient):
    def fetch_user_tweets(self, handle: str, since_id=None):
        raise RuntimeError("fail")

    def fetch_user_profile(self, handle: str):
        return None


class _OkClient(XClient):
    def fetch_user_tweets(self, handle: str, since_id=None):
        return [
            {"id": "1", "author": handle, "text": "ok", "created_at": "", "urls": []}
        ]

    def fetch_user_profile(self, handle: str):
        return {"handle": handle, "avatar_url": "", "ts": ""}


def test_multisource_failover(monkeypatch):
    from api import clients as pkg

    # Patch factory to return our stubs for order [graphql, apify]
    def fake_get_x_client(name: str):
        return _FailClient() if name == "graphql" else _OkClient()

    monkeypatch.setattr(pkg.x_client, "get_x_client", fake_get_x_client)

    ms = MultiSourceXClient(["graphql", "apify"])
    tweets = ms.fetch_user_tweets("alice")
    assert tweets and tweets[0]["text"] == "ok"
