#!/usr/bin/env python3
"""Healthcheck for Celery beat service based on heartbeat timestamp."""
import os
import sys
import time

from api.tasks.beat import get_last_heartbeat


def main() -> int:
    max_lag = float(os.getenv("BEAT_MAX_LAG_SEC", "10"))
    last = get_last_heartbeat()
    if last is None:
        print("heartbeat timestamp missing", file=sys.stderr)
        return 1

    lag = time.time() - last
    if lag > max_lag:
        print(f"heartbeat lag {lag:.2f}s exceeds threshold {max_lag}s", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
