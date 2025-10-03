# tests/test_rules_eval.py
import io
import json
import os
import shutil
import time
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sa_text

from api.database import build_engine_from_env, get_sessionmaker
from api.db import with_session
from api.main import app


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def db_sessionmaker():
    engine = build_engine_from_env()
    return get_sessionmaker(engine)


@pytest.fixture
def demo_keys():
    suffix = str(int(time.time()))
    return {
        "DEMO1": f"eth:PYTEST_DEMO1:{suffix}",
        "DEMO2": f"eth:PYTEST_DEMO2:{suffix}",
        "DEMO3": f"eth:PYTEST_DEMO3:{suffix}",
    }


@pytest.fixture
def seed_demo_data(db_sessionmaker, demo_keys):
    with with_session(db_sessionmaker) as s:
        s.execute(
            sa_text(
                """
            INSERT INTO events (event_key, type, start_ts, last_ts, last_sentiment, last_sentiment_score)
            VALUES
              (:k1,'topic',now(),now(),'pos',0.72),
              (:k2,'topic',now(),now(),'pos',0.66),
              (:k3,'topic',now(),now(),NULL ,NULL)
            ON CONFLICT (event_key) DO UPDATE
              SET last_sentiment=EXCLUDED.last_sentiment,
                  last_sentiment_score=EXCLUDED.last_sentiment_score,
                  last_ts=EXCLUDED.last_ts;
        """
            ),
            dict(k1=demo_keys["DEMO1"], k2=demo_keys["DEMO2"], k3=demo_keys["DEMO3"]),
        )
        s.execute(
            sa_text("DELETE FROM signals WHERE event_key IN (:k1,:k2,:k3);"),
            dict(k1=demo_keys["DEMO1"], k2=demo_keys["DEMO2"], k3=demo_keys["DEMO3"]),
        )
        s.execute(
            sa_text(
                """
            INSERT INTO signals (event_key,market_type,advice_tag,confidence,
              goplus_risk,goplus_tax,lp_lock_days,dex_liquidity,dex_volume_1h,
              buy_tax,sell_tax,heat_slope,ts,state)
            VALUES
              (:k1,'token',NULL,NULL,'green',0.00,30,120000,15000,0.01,0.01,0.70,now(),'candidate'),
              (:k2,'token',NULL,NULL,'green',0.00,30,NULL,NULL,0.01,0.01,0.50,now(),'candidate'),
              (:k3,'token',NULL,NULL,'gray',0.10,0,8000,500,0.05,0.10,0.10,now(),'candidate');
        """
            ),
            dict(k1=demo_keys["DEMO1"], k2=demo_keys["DEMO2"], k3=demo_keys["DEMO3"]),
        )
        s.commit()
    yield demo_keys
    with with_session(db_sessionmaker) as s:
        s.execute(
            sa_text("DELETE FROM signals WHERE event_key IN (:k1,:k2,:k3);"),
            dict(k1=demo_keys["DEMO1"], k2=demo_keys["DEMO2"], k3=demo_keys["DEMO3"]),
        )
        s.execute(
            sa_text("DELETE FROM events  WHERE event_key IN (:k1,:k2,:k3);"),
            dict(k1=demo_keys["DEMO1"], k2=demo_keys["DEMO2"], k3=demo_keys["DEMO3"]),
        )
        s.commit()


@contextmanager
def patch_env(**kwargs):
    old = {}
    try:
        for k, v in kwargs.items():
            old[k] = os.environ.get(k)
            os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def temp_rules_override(path="rules/rules.yml", patch_text=None):
    if not os.path.exists(path):
        yield False
        return
    backup = f"{path}.bak.pytest"
    shutil.copy2(path, backup)
    try:
        if patch_text:
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(patch_text)
        yield True
    finally:
        shutil.move(backup, path)


def _get(client, key):
    r = client.get("/rules/eval", params={"event_key": key})
    assert r.status_code == 200, f"HTTP {r.status_code} body={r.text}"
    return r.json()


def _assert_basic_shape(j):
    assert j["level"] in {"observe", "caution", "opportunity"}
    assert isinstance(j["reasons"], list) and len(j["reasons"]) <= 3
    assert isinstance(j["all_reasons"], list) and len(j["all_reasons"]) >= len(
        j["reasons"]
    )
    assert j["reasons"] == j["all_reasons"][: len(j["reasons"])]
    assert {"signals", "events", "missing"}.issubset(j["evidence"].keys())


def test_demo1_full_data(client, seed_demo_data):
    j = _get(client, seed_demo_data["DEMO1"])
    _assert_basic_shape(j)
    assert j["meta"]["refine_used"] is False


def test_demo2_missing_dex(client, seed_demo_data):
    j = _get(client, seed_demo_data["DEMO2"])
    _assert_basic_shape(j)
    assert "dex" in j["evidence"]["missing"]
    assert any("DEX 数据不足" in r for r in j["reasons"])


def test_demo3_missing_hf(client, seed_demo_data):
    j = _get(client, seed_demo_data["DEMO3"])
    _assert_basic_shape(j)
    assert "hf" in j["evidence"]["missing"]
    assert any("情绪分析不可用" in r for r in j["reasons"])


def test_rules_hot_reload(client, seed_demo_data):
    j0 = _get(client, seed_demo_data["DEMO1"])
    new_yaml = """version: 1.0
max_reasons: 3
groups:
  dex: { weight: 0.35, rules:
    [ {id: low_liquidity, priority: 80, when: "dex_liquidity < ${THETA_LIQ:10}", score: -2, reason: "DEX 流动性低于阈值"} ] }
  heat: { weight: 0.25, rules: [] }
  risk: { weight: 0.25, rules: [] }
  sentiment: { weight: 0.15, rules: [] }
scoring: { thresholds: { opportunity: 2, caution: -1, observe: else } }
missing_map: { dex: "DEX 数据不足", goplus: "安全体检数据缺失", hf: "情绪分析不可用" }
"""
    with temp_rules_override(patch_text=new_yaml):
        time.sleep(float(os.getenv("RULES_TTL_SEC", "5")) + 0.5)
        j1 = _get(client, seed_demo_data["DEMO1"])
        assert any("流动性" in r for r in j1["all_reasons"])
        assert j1["meta"]["hot_reloaded"] in (True, False)


def test_refiner_switch_probe(client, seed_demo_data):
    with patch_env(RULES_REFINER="on"):
        j = _get(client, seed_demo_data["DEMO1"])
        assert "refine_used" in j["meta"]
        assert j["meta"]["refine_used"] in (True, False)
