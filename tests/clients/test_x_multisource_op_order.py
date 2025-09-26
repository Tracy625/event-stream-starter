import os
import pytest

from api.clients.x_client import XClient, MultiSourceXClient


class _RecClient(XClient):
    def __init__(self, name, rec):
        self.name = name
        self.rec = rec
    def fetch_user_tweets(self, handle: str, since_id=None, limit: int = 20):
        self.rec.append((self.name, 'tweets'))
        return []
    def fetch_user_profile(self, handle: str):
        self.rec.append((self.name, 'profile'))
        return None


def test_order_per_operation(monkeypatch):
    calls = []
    def fake_get_x_client(name: str):
        return _RecClient(name, calls)
    from api import clients as pkg
    monkeypatch.setattr(pkg.x_client, 'get_x_client', fake_get_x_client)

    os.environ['X_BACKENDS_TWEETS'] = 'apify,graphql'
    os.environ['X_BACKENDS_PROFILE'] = 'graphql,apify'

    ms = MultiSourceXClient([])
    ms.fetch_user_tweets('alice')
    ms.fetch_user_profile('alice')
    # First call should use apify for tweets, second graphql for profile
    assert calls[0] == ('apify', 'tweets')
    assert calls[1] == ('graphql', 'profile')
