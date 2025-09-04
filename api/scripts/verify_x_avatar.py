#!/usr/bin/env python
import os, sys, json, time
from datetime import datetime, timezone, timedelta
import redis

def jlog(stage, **kw):
    kw["stage"] = stage
    kw["ts_iso"] = datetime.now(timezone.utc).isoformat()
    print("[JSON] " + json.dumps(kw, ensure_ascii=False), file=sys.stderr)

def main():
    r = redis.from_url(os.getenv("REDIS_URL","redis://redis:6379/0"), decode_responses=True)
    # 读取 KOL 列表（与 worker 同源）
    handles = []
    cfg = "/app/configs/x_kol.yaml"
    if os.path.exists(cfg):
        import yaml
        with open(cfg, "r") as f:
            y = yaml.safe_load(f) or {}
            handles = [k["handle"] for k in y.get("kol",[]) if "handle" in k]
    if not handles:
        env = os.getenv("X_KOL_HANDLES","")
        handles = [h.strip() for h in env.split(",") if h.strip()]

    if not handles:
        out = {"pass": False, "error": "no_handles"}
        print(json.dumps(out))
        sys.exit(1)

    now = datetime.now(timezone.utc)
    ok_seen = 0
    ok_change = 0
    for h in handles:
        base = f"x:avatar:{h}"
        last_hash = r.get(f"{base}:last_hash")
        last_seen = r.get(f"{base}:last_seen_ts")
        last_change = r.get(f"{base}:last_change_ts")
        if last_hash and last_seen:
            try:
                seen_dt = datetime.fromisoformat(last_seen.replace("Z","+00:00"))
                if now - seen_dt <= timedelta(minutes=10):
                    ok_seen += 1
            except Exception:
                pass
        if last_change:
            ok_change += 1  # 至少发生过一次变更即计数

    passed = ok_seen >= 1  # 至少一个 handle 最近 10 分钟被观测
    out = {
        "pass": bool(passed),
        "details": {"ok_seen": ok_seen, "ok_change": ok_change, "total": len(handles)}
    }
    jlog("verify.x_avatar", **out)
    print(json.dumps(out))
    sys.exit(0 if passed else 1)

if __name__ == "__main__":
    main()