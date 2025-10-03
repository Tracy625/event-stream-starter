#!/usr/bin/env python3
"""Simple test for heat persistence."""

import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy import text as sa_text

# Setup path
sys.path.insert(0, "/app")

from api.signals.heat import compute_heat, persist_heat


def main():
    # Enable persistence
    os.environ["HEAT_ENABLE_PERSIST"] = "true"

    engine = create_engine(os.getenv("POSTGRES_URL"))

    # Test data
    symbol = "SIMPLETEST"
    token_ca = "0xsimple123"

    with engine.begin() as db:  # Use begin() for auto-commit
        # Ensure test row exists
        db.execute(
            sa_text(
                """
            INSERT INTO signals (symbol, token_ca, features_snapshot, last_ts)
            VALUES (:symbol, :token_ca, '{}'::jsonb, NOW())
            ON CONFLICT (symbol, token_ca) DO NOTHING
        """
            ),
            {"symbol": symbol, "token_ca": token_ca},
        )

    # Now test persistence
    with engine.connect() as db:
        heat = {
            "cnt_10m": 99,
            "cnt_30m": 299,
            "slope": 5.5,
            "trend": "up",
            "asof_ts": datetime.now(timezone.utc).isoformat(),
        }

        result = persist_heat(
            db, token=symbol, token_ca=token_ca, heat=heat, strict_match=False
        )

        print(f"Persist result: {result}")

        if result:
            # Verify stored data
            row = db.execute(
                sa_text(
                    """
                SELECT features_snapshot->'heat' as heat
                FROM signals
                WHERE symbol = :symbol AND token_ca = :token_ca
            """
                ),
                {"symbol": symbol, "token_ca": token_ca},
            ).fetchone()

            if row and row[0]:
                stored = row[0]
                print(f"Stored heat: {json.dumps(stored, indent=2)}")
                print(f"✓ Heat persistence test passed")
            else:
                print("✗ No heat data found after persist")
        else:
            print("✗ Persistence failed")


if __name__ == "__main__":
    main()
