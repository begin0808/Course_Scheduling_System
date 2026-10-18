"""結構升級前自動備份(v1.3.0)。

v1.3.0 首次改動資料表結構,用 latest 映像的學校看不到「升級前請備份」的說明,
所以 api 容器啟動時由系統自己在升級前備份。使用者定案:備份失敗照常升級並提示;
升級前備份不參與每日備份的輪替。
"""

import os

import pytest

from app.models.user import Role
from app.scripts.migrate import Outcome, prepare_and_upgrade
from app.services import backup, upgrade_notice
from tests.conftest import make_user


class _Spy:
    def __init__(self, fail: bool = False):
        self.fail, self.backups, self.upgrades = fail, 0, 0

    def backup(self) -> str:
        self.backups += 1
        if self.fail:
            raise backup.BackupError("磁碟空間不足")
        return "backup_20261018_100000_preupgrade.dump"

    def upgrade(self) -> None:
        self.upgrades += 1


def test_pending_migration_backs_up_first_then_upgrades():
    spy = _Spy()
    out = prepare_and_upgrade("0017_class_name_unique", "0018_alternate_weeks",
                              spy.backup, spy.upgrade)
    assert (spy.backups, spy.upgrades) == (1, 1)
    assert out == Outcome(upgraded=True, backup="backup_20261018_100000_preupgrade.dump")


def test_backup_failure_still_upgrades_and_reports_why():
    """備份失敗照常升級——拒絕啟動會讓用 latest 的學校整套系統停擺。"""
    spy = _Spy(fail=True)
    out = prepare_and_upgrade("0017_class_name_unique", "0018_alternate_weeks",
                              spy.backup, spy.upgrade)
    assert spy.upgrades == 1
    assert out.upgraded and out.backup == "" and "磁碟空間不足" in out.error


def test_no_backup_when_already_up_to_date():
    spy = _Spy()
    out = prepare_and_upgrade("0018_alternate_weeks", "0018_alternate_weeks",
                              spy.backup, spy.upgrade)
    assert spy.backups == 0 and spy.upgrades == 1   # 與先前的 alembic upgrade head 相同(無動作)
    assert out == Outcome(upgraded=False)


def test_no_backup_on_a_fresh_install():
    """全新安裝:資料庫沒有任何遷移紀錄,沒有資料可備份。"""
    spy = _Spy()
    out = prepare_and_upgrade(None, "0018_alternate_weeks", spy.backup, spy.upgrade)
    assert spy.backups == 0 and spy.upgrades == 1
    assert out.upgraded and out.backup == "" and out.error == ""


# ── 升級前備份不參與輪替 ────────────────
@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.settings, "backup_dir", str(tmp_path))
    return tmp_path


def _touch(d, name):
    (d / name).write_bytes(b"PGDMP")


def test_rotation_never_removes_the_pre_upgrade_backup(backup_dir):
    _touch(backup_dir, "backup_20261001_030000_preupgrade.dump")  # 最舊的一份
    for day in range(2, 9):
        _touch(backup_dir, f"backup_202610{day:02d}_030000_auto.dump")

    removed = backup.prune(keep=3)
    left = sorted(os.listdir(backup_dir))
    assert "backup_20261001_030000_preupgrade.dump" in left
    assert len([n for n in left if n.endswith("_auto.dump")]) == 3
    assert len(removed) == 4 and all("_auto" in n for n in removed)
    # 清單上照常列出,並標示「升級前自動備份」
    reasons = {b.name: b.reason for b in backup.list_backups()}
    assert reasons["backup_20261001_030000_preupgrade.dump"] == "preupgrade"


# ── 系統管理員看到的提示 ───────────────
def test_upgrade_notice_is_shown_to_admins_until_dismissed(env):
    client, db = env
    make_user(db, "root", "password123", roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "root", "password": "password123"})
    assert client.get("/api/system/upgrade-notice").json() is None

    upgrade_notice.save(db, {
        "version": "v1.3.0", "from_revision": "0017_class_name_unique",
        "to_revision": "0018_alternate_weeks", "at": "2026-10-18 10:00",
        "backup": "backup_20261018_100000_preupgrade.dump", "error": "",
    })
    db.commit()
    notice = client.get("/api/system/upgrade-notice").json()
    assert notice == {"version": "v1.3.0", "at": "2026-10-18 10:00",
                      "backup": "backup_20261018_100000_preupgrade.dump", "error": ""}

    assert client.post("/api/system/upgrade-notice/dismiss").status_code == 204
    assert client.get("/api/system/upgrade-notice").json() is None


def test_upgrade_notice_is_admin_only(env):
    client, db = env
    make_user(db, "s", "password123", roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": "password123"})
    assert client.get("/api/system/upgrade-notice").status_code == 403
