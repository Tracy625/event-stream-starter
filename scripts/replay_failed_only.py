#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import api  # noqa: F401 ensures instrumentation installed
import requests

sys.path.insert(0, os.getcwd())
from scripts import _replay_state as replay_state  # type: ignore

HEADERS_BASE = {
    "Content-Type": "application/json",
}

ENDPOINTS = {
    "x": os.getenv("REPLAY_ENDPOINT_X", ""),
    "dex": os.getenv("REPLAY_ENDPOINT_DEX", ""),
    "topic": os.getenv("REPLAY_ENDPOINT_TOPIC", ""),
}

REPLAY_HEADER_NOW = os.getenv("REPLAY_HEADER_NOW", "X-Replay-Now")
REPLAY_HEADER_SEED = os.getenv("REPLAY_HEADER_SEED", "X-Replay-Seed")
REPLAY_SEED = os.getenv("REPLAY_SEED", "42")

_lock = threading.Lock()


def ensure_endpoints_present(provider: str) -> str:
    endpoint = ENDPOINTS.get(provider)
    if not endpoint:
        raise RuntimeError(f"Missing endpoint for provider '{provider}'. Set REPLAY_ENDPOINT_{provider.upper()}")
    return endpoint


def format_entry(row: Dict[str, object]) -> str:
    return f"{row['unique_key']}\t{row['source']}\t{row['last_status']}\t{row.get('last_error','')}"


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay only failed batches")
    parser.add_argument("--since", help="Time delta like 24h or ISO timestamp", default="24h")
    parser.add_argument("--between", help="Start,end timestamps (ISO)", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Only print counts")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Concurrent workers")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retries per entry")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    return parser.parse_args(argv)


def fetch_failed_entries(args: argparse.Namespace) -> List[Dict[str, object]]:
    start = end = None
    if args.between:
        try:
            start, end = args.between.split(",", 1)
        except ValueError as exc:
            raise SystemExit(f"Invalid --between format: {args.between}") from exc
    rows = list(replay_state.list_failed(args.since, start, end))
    return rows


def prepare_output_dir(path: Optional[str]) -> Path:
    if path:
        out = Path(path)
    else:
        out = Path("logs/replay_failed") / datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    return out


def send_request(entry: Dict[str, object], args: argparse.Namespace) -> Dict[str, object]:
    provider = entry["source"]
    unique_key = entry["unique_key"]
    try:
        endpoint = ensure_endpoints_present(provider)
    except RuntimeError as exc:
        replay_state.upsert(str(unique_key), provider, json.dumps(entry["payload"]), "fail:no_endpoint", 0, str(exc))
        return {
            "unique_key": unique_key,
            "status_code": 0,
            "latency_ms": 0,
            "success": False,
            "error": str(exc),
            "attempts": 0,
        }

    payload = json.dumps(entry["payload"])
    headers = HEADERS_BASE.copy()
    freeze_ts = entry.get("last_attempt_at")
    if not freeze_ts:
        freeze_ts = datetime.utcnow().isoformat()
    if isinstance(freeze_ts, str):
        headers[REPLAY_HEADER_NOW] = freeze_ts
    else:
        headers[REPLAY_HEADER_NOW] = freeze_ts.isoformat()
    headers[REPLAY_HEADER_SEED] = str(REPLAY_SEED)
    headers["Idempotency-Key"] = str(entry["unique_key"])

    retries = args.max_retries
    attempt = 0
    while True:
        attempt += 1
        start = time.perf_counter()
        try:
            response = requests.post(endpoint, data=payload, headers=headers, timeout= float(os.getenv("REPLAY_TIMEOUT_SEC", "6")))
            latency = int((time.perf_counter() - start) * 1000)
            status = response.status_code
            success = 200 <= status < 300
            error_message = None if success else response.text[:200]
        except requests.RequestException as exc:
            latency = int((time.perf_counter() - start) * 1000)
            status = 0
            success = False
            error_message = str(exc)

        update_payload = payload
        replay_state.upsert(str(unique_key), provider, update_payload, "success" if success else f"fail:{status}", latency, error_message)

        result = {
            "unique_key": unique_key,
            "status_code": status,
            "latency_ms": latency,
            "success": success,
            "error": error_message,
            "attempts": attempt,
        }
        if success or attempt >= retries:
            return result

        sleep_for = min(30, 2 ** attempt)
        time.sleep(sleep_for)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    entries = fetch_failed_entries(args)
    if not entries:
        print("No failed items to replay.")
        return 0

    output_dir = prepare_output_dir(args.output_dir)
    input_tsv = output_dir / "replay_input.tsv"
    result_tsv = output_dir / "replay_result.tsv"
    leftovers_tsv = output_dir / "replay_leftovers.tsv"

    with input_tsv.open("w", encoding="utf-8") as f:
        for row in entries:
            f.write(format_entry(row) + "\n")

    if args.dry_run:
        print(f"Would replay {len(entries)} entries. Sample:")
        for row in entries[:5]:
            print(json.dumps(row, default=str))
        return 0

    successes = 0
    failures: List[Dict[str, object]] = []
    futures = []

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for entry in entries:
            futures.append(executor.submit(send_request, entry, args))

        with result_tsv.open("w", encoding="utf-8") as result_file:
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - surfaced as failure entry
                    result = {
                        "unique_key": "unknown",
                        "status_code": 0,
                        "latency_ms": 0,
                        "success": False,
                        "error": str(exc),
                        "attempts": 0,
                    }
                line = "\t".join([
                    str(result["unique_key"]),
                    str(result["status_code"]),
                    str(result["latency_ms"]),
                    "success" if result["success"] else "failed",
                    str(result.get("error", "")),
                ])
                result_file.write(line + "\n")
                if result["success"]:
                    successes += 1
                else:
                    failures.append(result)

    if failures:
        with leftovers_tsv.open("w", encoding="utf-8") as f:
            for item in failures:
                f.write(json.dumps(item) + "\n")

    print(f"Replayed {len(entries)} entries. Success={successes}, Fail={len(failures)}")

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
