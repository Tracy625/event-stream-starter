import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

BASE = "/app"


def load_as(pkg_name: str, file_path: str):
    """
    将磁盘文件加载为指定的包名模块，并确保父包都在 sys.modules 中。
    这样可以兼容模块内部的 `from api.db.models...` 这类导入。
    """
    # 确保父包存在
    parts = pkg_name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        if pkg not in sys.modules:
            sys.modules[pkg] = types.ModuleType(pkg)
            sys.modules[pkg].__path__ = []  # 标记为包

    spec = importlib.util.spec_from_file_location(pkg_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    assert spec and spec.loader, f"Failed to load spec for {pkg_name} from {file_path}"
    spec.loader.exec_module(mod)
    return mod


# 先加载 api.models，让 push_outbox.py 能 import Base
load_as("api.models", f"{BASE}/api/models.py")
# 再加载模型与仓储（仓储内部会 from api.db.models.push_outbox import ...）
models = load_as("api.db.models.push_outbox", f"{BASE}/api/db/models/push_outbox.py")
repo = load_as(
    "api.db.repositories.outbox_repo", f"{BASE}/api/db/repositories/outbox_repo.py"
)

# 连接真实数据库（用你的 DATABASE_URL）
engine = create_engine(os.environ["DATABASE_URL"])
Session = sessionmaker(bind=engine)


def test_outbox_crud_path_loading():
    with Session() as s:
        # 1) enqueue
        rid = repo.enqueue(
            s,
            channel_id=-1003006310940,
            thread_id=None,
            event_key="ev_test_path",
            payload_json={"ok": True},
        )
        s.commit()
        assert isinstance(rid, int) and rid > 0

        # 2) dequeue
        rows = repo.dequeue_batch(s, limit=50)
        ids = [r.id for r in rows]
        assert rid in ids

        # 3) mark_retry
        nt = datetime.now(timezone.utc) + timedelta(seconds=30)
        repo.mark_retry(s, row_id=rid, next_try_at=nt, last_error="retry_test")
        s.commit()

        obj = s.get(models.PushOutbox, rid)
        assert obj is not None
        assert (
            str(obj.status)
            in ("retry", "OutboxStatus.RETRY", "OutboxStatus.retry", "RETRY")
            or obj.status == "retry"
        )
        assert obj.attempt >= 1

        # 4) mark_done
        repo.mark_done(s, row_id=rid)
        s.commit()
        obj = s.get(models.PushOutbox, rid)
        assert obj is not None
        assert str(obj.status).lower().endswith("done") or obj.status == "done"

        # 5) move_to_dlq
        repo.move_to_dlq(s, row_id=rid, last_error="final", snapshot={"k": "v"})
        s.commit()
        obj = s.get(models.PushOutbox, rid)
        assert obj is not None
        assert str(obj.status).lower().endswith("dlq") or obj.status == "dlq"
