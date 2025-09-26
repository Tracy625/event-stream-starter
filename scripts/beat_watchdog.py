# scripts/beat_watchdog.py
import os, sys, time, subprocess, signal
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
KEY = os.getenv("BEAT_HEARTBEAT_KEY", "beat:last_heartbeat")
STALE_SEC = int(os.getenv("BEAT_STALE_SEC", "15"))

def get_ts(r):
    v = r.get(KEY)
    if not v:
        return None
    try:
        return float(v)
    except Exception:
        return None

def main():
    # 启动 celery beat 作为子进程
    beat_cmd = os.getenv("BEAT_CMD", "celery -A worker.app beat --loglevel=INFO")
    proc = subprocess.Popen(beat_cmd, shell=True, preexec_fn=os.setsid)

    try:
        r = redis.from_url(REDIS_URL)
    except Exception as exc:
        print(f"[watchdog] failed to connect redis: {exc}", file=sys.stderr)
        os.killpg(proc.pid, signal.SIGKILL)
        sys.exit(1)
    last_ok = time.time()

    try:
        while True:
            # 子进程意外退出，直接用其退出码退出，触发 Docker 重启
            if proc.poll() is not None:
                sys.exit(proc.returncode or 1)

            try:
                ts = get_ts(r)
            except Exception as exc:
                print(f"[watchdog] redis error: {exc}", file=sys.stderr)
                ts = None
            now = time.time()
            if ts is not None and now - ts <= STALE_SEC:
                last_ok = now
            # 心跳超时，杀掉子进程并退出非零
            if now - last_ok > STALE_SEC:
                print(f"[watchdog] heartbeat stale > {STALE_SEC}s; restarting beat", flush=True)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                sys.exit(1)

            time.sleep(2)
    finally:
        # 收尾避免僵尸
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass

if __name__ == "__main__":
    main()
