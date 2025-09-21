#!/usr/bin/env python
"""Utilities for maintaining replay_state table."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sys
from typing import Iterable, Optional

import psycopg2
import psycopg2.extras

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS replay_state (
    unique_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    payload JSONB NOT NULL,
    last_status TEXT NOT NULL,
    last_attempt_at TIMESTAMPTZ NOT NULL,
    last_latency_ms INTEGER,
    last_error TEXT
);
"""


def get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL or POSTGRES_URL must be set")
    return dsn


def get_conn():
    return psycopg2.connect(get_dsn())


def ensure_table() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(TABLE_SQL)


def parse_since(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    if value.endswith("h"):
        hours = float(value[:-1])
        return dt.datetime.utcnow() - dt.timedelta(hours=hours)
    if value.endswith("m"):
        minutes = float(value[:-1])
        return dt.datetime.utcnow() - dt.timedelta(minutes=minutes)
    if value.endswith("s"):
        seconds = float(value[:-1])
        return dt.datetime.utcnow() - dt.timedelta(seconds=seconds)
    # assume ISO timestamp
    return dt.datetime.fromisoformat(value)


def list_failed(since: Optional[str], start: Optional[str], end: Optional[str]) -> Iterable[dict]:
    ensure_table()
    with get_conn() as conn:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            query = [
                "SELECT unique_key, source, payload, last_status, last_error, last_attempt_at"
                " FROM replay_state WHERE last_status <> 'success'"
            ]
            params = {}
            ts_since = parse_since(since)
            if ts_since:
                query.append("AND last_attempt_at >= %(since)s")
                params["since"] = ts_since
            if start and end:
                params["start"] = dt.datetime.fromisoformat(start)
                params["end"] = dt.datetime.fromisoformat(end)
                query.append("AND last_attempt_at BETWEEN %(start)s AND %(end)s")
            query.append("ORDER BY last_attempt_at ASC")
            cur.execute(" ".join(query), params)
            for row in cur:
                yield dict(row)


def upsert(unique_key: str, source: str, payload: str, status: str,
           latency_ms: Optional[int], error: Optional[str]) -> None:
    ensure_table()
    payload_json = json.loads(payload)
    now = dt.datetime.utcnow()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO replay_state (unique_key, source, payload, last_status,
                                      last_attempt_at, last_latency_ms, last_error)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (unique_key)
            DO UPDATE SET
                source = EXCLUDED.source,
                payload = EXCLUDED.payload,
                last_status = EXCLUDED.last_status,
                last_attempt_at = EXCLUDED.last_attempt_at,
                last_latency_ms = EXCLUDED.last_latency_ms,
                last_error = EXCLUDED.last_error
            """,
            (unique_key, source, psycopg2.extras.Json(payload_json), status, now, latency_ms, error),
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Replay state utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ensure", help="Ensure replay_state table exists")

    list_failed_parser = sub.add_parser("list-failed", help="List failed replay entries")
    list_failed_parser.add_argument("--since", default=None)
    list_failed_parser.add_argument("--start", default=None)
    list_failed_parser.add_argument("--end", default=None)

    upsert_parser = sub.add_parser("upsert", help="Upsert replay state for an entry")
    upsert_parser.add_argument("unique_key")
    upsert_parser.add_argument("source")
    upsert_parser.add_argument("payload_json")
    upsert_parser.add_argument("status")
    upsert_parser.add_argument("latency_ms", type=int)
    upsert_parser.add_argument("error", nargs="?", default=None)

    args = parser.parse_args(argv)

    if args.command == "ensure":
        ensure_table()
        return 0
    if args.command == "list-failed":
        rows = list_failed(args.since, args.start, args.end)
        for row in rows:
            print(json.dumps(row, default=str))
        return 0
    if args.command == "upsert":
        upsert(args.unique_key, args.source, args.payload_json, args.status, args.latency_ms, args.error)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
