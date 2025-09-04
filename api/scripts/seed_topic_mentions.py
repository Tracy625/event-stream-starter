#!/usr/bin/env python3
"""Seed topic mention data for testing slope calculations"""

import sys
from datetime import datetime, timedelta, timezone
from api.cache import get_redis_client

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m api.scripts.seed_topic_mentions <topic_id>")
        sys.exit(1)
    topic_id = sys.argv[1]
    rc = get_redis_client()
    if rc is None:
        print("Redis not available")
        sys.exit(2)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # Create simple upward trend to ensure different 10m and 30m slopes
    samples = [
        (now - timedelta(minutes=30), 10),
        (now - timedelta(minutes=20), 25),
        (now - timedelta(minutes=10), 55),
        (now, 80),
    ]
    for ts, count in samples:
        # Ensure consistency with analyzer/postprocess's _iso_minute
        ts = ts.replace(second=0, microsecond=0, tzinfo=timezone.utc)
        key = f"topic:mentions:{topic_id}:{ts.isoformat()}"
        rc.setex(key, 24 * 3600, str(count))
    print(f"Seeded {len(samples)} points for {topic_id}")

if __name__ == "__main__":
    main()