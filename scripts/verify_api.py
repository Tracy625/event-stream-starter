#!/usr/bin/env python3
import json
import sys
import urllib.request

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/healthz"

try:
    with urllib.request.urlopen(url, timeout=5) as r:
        j = json.loads(r.read().decode("utf-8"))
        s = str(j.get("status", "")).lower()
        if s in ["ok", "healthy"] or "ok" in s or "healthy" in s:
            print("API health check: OK")
            sys.exit(0)
        else:
            print(f"API health check failed: status={s}")
            sys.exit(1)
except Exception as e:
    print(f"API health check error: {e}")
    sys.exit(1)
