"""M5-2:備份/還原的純邏輯與 RBAC。實際 pg_dump/pg_restore(需 PostgreSQL 與
pg 工具)由 docker 整合測試涵蓋;這裡測檔頭驗證、輪替、清單、權限、非法上傳拒絕。
"""

import pytest

from app.core.config import settings
from app.models.user import Role
from app.services import backup as bk
from tests.conftest import make_user

PW = "password123"
PGDMP = b"PGDMP" + b"\x00" * 100  # 假的 custom 格式檔頭


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    return tmp_path


def _touch(dir_, name: str, content: bytes = PGDMP):
    (dir_ / name).write_bytes(content)


# ── 檔頭驗證(驗收②)───────────────────────────────────────
def test_is_valid_dump(backup_dir):
    _touch(backup_dir, "good.dump", PGDMP)
    _touch(backup_dir, "bad.dump", b"not a dump")
    assert bk.is_valid_dump(str(backup_dir / "good.dump")) is True
    assert bk.is_valid_dump(str(backup_dir / "bad.dump")) is False


def test_save_uploaded_rejects_non_dump(backup_dir):
    with pytest.raises(bk.BackupError):
        bk.save_uploaded("x.dump", b"garbage bytes")
    # 拒絕的檔案不落地
    assert list(backup_dir.iterdir()) == []


def test_save_uploaded_accepts_valid(backup_dir):
    name = bk.save_uploaded("x.dump", PGDMP)
    assert name.endswith("_upload.dump")
    assert (backup_dir / name).exists()


# ── 清單 / 輪替(驗收③)───────────────────────────────────
def test_list_backups_newest_first(backup_dir):
    _touch(backup_dir, "backup_20260101_010101_manual.dump")
    _touch(backup_dir, "backup_20260301_010101_auto.dump")
    _touch(backup_dir, "notabackup.txt")
    names = [b.name for b in bk.list_backups()]
    assert names == [
        "backup_20260301_010101_auto.dump",
        "backup_20260101_010101_manual.dump",
    ]  # 非備份檔被忽略


def test_prune_keeps_newest(backup_dir):
    for i in range(1, 6):
        _touch(backup_dir, f"backup_2026010{i}_010101_auto.dump")
    removed = bk.prune(keep=2)
    remaining = sorted(b.name for b in bk.list_backups())
    assert len(remaining) == 2
    assert remaining == [
        "backup_20260104_010101_auto.dump",
        "backup_20260105_010101_auto.dump",
    ]
    assert len(removed) == 3


def test_path_traversal_rejected(backup_dir):
    with pytest.raises(bk.BackupError):
        bk.restore_backup("../../etc/passwd")


# ── RBAC:僅管理員 ─────────────────────────────────────────
def _login(client, db, username, roles):
    make_user(db, username, PW, roles=roles)
    client.post("/api/auth/login", json={"username": username, "password": PW})


def test_list_backups_admin_only(env, backup_dir):
    client, db = env
    _login(client, db, "sch", [Role.scheduler])
    assert client.get("/api/backups").status_code == 403
    client.post("/api/auth/logout")
    _login(client, db, "adm", [Role.admin])
    r = client.get("/api/backups")
    assert r.status_code == 200
    assert r.json() == []


def test_restore_upload_rejects_garbage_before_touching_db(env, backup_dir):
    client, db = env
    _login(client, db, "adm", [Role.admin])
    r = client.post(
        "/api/backups/restore-upload",
        files={"file": ("evil.dump", b"rm -rf /", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "格式不符" in r.json()["detail"]
    assert list(backup_dir.iterdir()) == []  # 系統無損:沒有檔案落地


def test_scheduler_cannot_restore(env, backup_dir):
    client, db = env
    _login(client, db, "sch", [Role.scheduler])
    assert client.post("/api/backups/some.dump/restore").status_code == 403


# ── 還原不得留著一條會被 pg_restore 砍掉的 session(M6-6 實測發現)────────
def test_restore_closes_the_request_session_before_touching_the_database(
    env, backup_dir, monkeypatch
):
    """pg_restore --clean 會中止資料庫上的所有連線,包含本請求驗證身分時開的那條。

    yield 依賴是在**回應送出後**才收尾,屆時 db.close() 會對一條已死的連線送 ROLLBACK,
    在 log 噴出 AdminShutdown traceback——回應與資料都是對的,但剛按下「還原」的人看到
    那段紅字只會以為還原失敗了。故還原派工前必須先把這條 session 關掉。
    """
    from app.api import backups as backups_api
    from app.core.db import get_db

    client, db = env
    _touch(backup_dir, "backup_20260101_010101_manual.dump")
    _login(client, db, "adm", [Role.admin])

    # 攔下請求用的 session,記下它是否被關閉
    original = client.app.dependency_overrides[get_db]
    closed: dict[str, bool] = {}

    def spy_get_db():
        gen = original()
        session = next(gen)
        real_close = session.close

        def close():
            closed["yes"] = True
            real_close()

        session.close = close  # type: ignore[method-assign]
        try:
            yield session
        finally:
            next(gen, None)

    client.app.dependency_overrides[get_db] = spy_get_db

    seen: dict[str, bool] = {}

    def fake_restore(name):
        # 這一刻 pg_restore 正要砍掉所有連線:請求的 session 必須已經關了
        seen["closed_before_restore"] = closed.get("yes", False)
        return []

    monkeypatch.setattr(backups_api.job_queue, "solver_busy", lambda: False)
    monkeypatch.setattr(
        backups_api.job_queue, "run_backup",
        lambda reason: {"name": f"backup_20260102_010101_{reason}.dump"},
    )
    monkeypatch.setattr(backups_api.job_queue, "run_restore", fake_restore)

    try:
        r = client.post("/api/backups/backup_20260101_010101_manual.dump/restore")
    finally:
        client.app.dependency_overrides[get_db] = original

    assert r.status_code == 200
    assert r.json()["restored_from"] == "backup_20260101_010101_manual.dump"
    assert seen["closed_before_restore"] is True


def test_get_db_teardown_never_raises(monkeypatch, caplog):
    """收尾關 session 失敗不該變成一段沒有請求可歸屬的 ASGI traceback——
    使用者早就拿到(正確的)回應了。真正的失敗會在查詢當下就報錯,不會被這裡蓋掉。"""
    from app.core import db as db_mod

    class _DeadSession:
        def close(self):
            raise RuntimeError("terminating connection due to administrator command")

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _DeadSession())

    gen = db_mod.get_db()
    next(gen)
    with caplog.at_level("WARNING"), pytest.raises(StopIteration):
        next(gen)  # 觸發 finally:不得擲出
    assert "還原" in caplog.text
