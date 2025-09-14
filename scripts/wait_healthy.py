#!/usr/bin/env python3
import os
import sys
import time
import json
import urllib.request

url = os.environ.get("API_HEALTH_URL", "http://localhost:8000/healthz")
timeout = int(os.environ.get("HEALTH_TIMEOUT", "120"))
start = time.time()
ok = False

while time.time() - start < timeout:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            data = r.read().decode("utf-8").lower()
            if '"ok"' in data or '"healthy"' in data or 'ok' in data or 'healthy' in data:
                ok = True
                break
    except Exception:
        pass
    time.sleep(2)

print("healthy:", ok)
sys.exit(0 if ok else 1)