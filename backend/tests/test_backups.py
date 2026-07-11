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
