"""版本管理與發布(M2-5)測試。對應驗收標準①②③。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user
from tests.test_timetables import (
    MAIN_SLOTS,
    _assign,
    _class,
    _entries,
    _periods,
    _place,
    _subject,
    _teacher,
)

PW = "password123"


@pytest.fixture
def env3(env):
    """教學組長 + 學期 + 主節次表 + 一份草稿A。回傳 (client, sid, ttA_id, db)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()["id"]
    pt = client.post(
        f"/api/semesters/{sid}/period-tables", json={"name": "主表", "is_default": True}
    ).json()
    client.put(f"/api/period-tables/{pt['id']}/periods", json=_periods(MAIN_SLOTS))
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    return client, sid, tt["id"], db


def _one_period_course(client, sid, cname="301", sname="國文", tname="王師"):
    """建立一筆「每週 1 節」的配課,方便排滿。"""
    c = _class(client, sid, 3, cname)
    s = _subject(client, sid, sname)
    t = _teacher(client, sid, tname)
    return _assign(client, sid, class_id=c["id"], subject_id=s["id"],
                   teacher_ids=[t["id"]], periods=1)


# ── 完整性檢查 ────────────────────────
def test_completeness_reports_unplaced(env3):
    client, sid, tid, _ = env3
    a = _one_period_course(client, sid)  # 需 1 節
    # 再加一筆需 3 節的配課,完全未排
    c2 = _class(client, sid, 3, "302")
    s2 = _subject(client, sid, "數學")
    t2 = _teacher(client, sid, "李師")
    _assign(client, sid, class_id=c2["id"], subject_id=s2["id"],
            teacher_ids=[t2["id"]], periods=3)

    r = client.get(f"/api/timetables/{tid}/completeness").json()
    assert r["complete"] is False
    assert r["required"] == 4 and r["placed"] == 0 and r["remaining"] == 4
    assert len(r["unplaced"]) == 2

    _place(client, tid, a["id"], 1, 1)
    r = client.get(f"/api/timetables/{tid}/completeness").json()
    assert r["placed"] == 1
    assert [u["subject"] for u in r["unplaced"]] == ["數學"]
    assert r["unplaced"][0]["remaining"] == 3


def test_completeness_complete_when_all_placed(env3):
    client, sid, tid, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tid, a["id"], 1, 1)
    r = client.get(f"/api/timetables/{tid}/completeness").json()
    assert r["complete"] is True and r["remaining"] == 0 and r["unplaced"] == []


# ── 驗收②:未排完 → 警告;強制可發布 ──
def test_publish_blocked_when_incomplete_then_forced(env3):
    client, sid, tid, _ = env3
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "國文")
    t = _teacher(client, sid, "王師")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"],
                teacher_ids=[t["id"]], periods=5)
    for wd in (1, 2):
        _place(client, tid, a["id"], wd, 1)  # 只排 2 節,尚缺 3 節

    r = client.post(f"/api/timetables/{tid}/publish")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["completeness"]["remaining"] == 3
    assert detail["completeness"]["unplaced"][0]["remaining"] == 3

    # 確認後強制發布
    r = client.post(f"/api/timetables/{tid}/publish?force=true")
    assert r.status_code == 200
    assert r.json()["status"] == "published"


def test_publish_complete_without_force(env3):
    client, sid, tid, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tid, a["id"], 1, 1)
    r = client.post(f"/api/timetables/{tid}/publish")
    assert r.status_code == 200 and r.json()["status"] == "published"


# ── 驗收①:雙草稿並存 / 發布 B 後 A 仍可編輯 ──
def test_duplicate_creates_independent_draft(env3):
    client, sid, tidA, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tidA, a["id"], 1, 1)

    tidB = client.post(f"/api/timetables/{tidA}/duplicate", json={"name": "草稿B"}).json()["id"]
    assert tidB != tidA
    assert len(_entries(client, tidB)) == 1  # 格位一併複製

    # 改 B 不影響 A
    eB = _entries(client, tidB)[0]
    client.patch(f"/api/timetables/{tidB}/entries/{eB['id']}", json={"weekday": 2, "period_no": 2})
    assert _entries(client, tidA)[0]["weekday"] == 1
    assert _entries(client, tidB)[0]["weekday"] == 2

    # 刪 B 的格位不影響 A
    client.delete(f"/api/timetables/{tidB}/entries/{eB['id']}")
    assert len(_entries(client, tidA)) == 1
    assert len(_entries(client, tidB)) == 0


def test_publish_b_leaves_a_editable(env3):
    """驗收①:發布 B 後,查詢頁顯示 B,A 仍為草稿可編輯。"""
    client, sid, tidA, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tidA, a["id"], 1, 1)
    tidB = client.post(f"/api/timetables/{tidA}/duplicate", json={"name": "草稿B"}).json()["id"]

    assert client.post(f"/api/timetables/{tidB}/publish").status_code == 200

    lst = {t["id"]: t["status"] for t in client.get(f"/api/timetables?semester_id={sid}").json()}
    assert lst[tidB] == "published"
    assert lst[tidA] == "draft"

    # A 仍可編輯
    eA = _entries(client, tidA)[0]
    r = client.patch(f"/api/timetables/{tidA}/entries/{eA['id']}",
                     json={"weekday": 3, "period_no": 2})
    assert r.status_code == 200

    # 查詢頁顯示 B
    pubtt = client.get(f"/api/published/timetable?semester_id={sid}").json()
    assert pubtt["id"] == tidB and pubtt["name"] == "草稿B"


def test_publishing_new_archives_previous(env3):
    client, sid, tidA, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tidA, a["id"], 1, 1)
    tidB = client.post(f"/api/timetables/{tidA}/duplicate", json={"name": "草稿B"}).json()["id"]

    client.post(f"/api/timetables/{tidA}/publish")
    client.post(f"/api/timetables/{tidB}/publish")
    lst = {t["id"]: t["status"] for t in client.get(f"/api/timetables?semester_id={sid}").json()}
    assert lst[tidA] == "archived" and lst[tidB] == "published"
    # 同學期至多一份 published
    assert sum(1 for v in lst.values() if v == "published") == 1


# ── 已發布為快照,不可編輯 ─────────────
def test_published_timetable_is_read_only(env3):
    client, sid, tid, _ = env3
    a = _one_period_course(client, sid)
    _place(client, tid, a["id"], 1, 1)
    eid = _entries(client, tid)[0]["id"]
    client.post(f"/api/timetables/{tid}/publish")

    assert _place(client, tid, a["id"], 2, 1).status_code == 409
    assert client.patch(f"/api/timetables/{tid}/entries/{eid}",
                        json={"weekday": 2, "period_no": 2}).status_code == 409
    assert client.delete(f"/api/timetables/{tid}/entries/{eid}").status_code == 409
    assert client.post(f"/api/timetables/{tid}/entries/{eid}/lock?locked=true").status_code == 409
    # 再次發布也不行(已非草稿)
    assert client.post(f"/api/timetables/{tid}/publish").status_code == 409


def test_rename_timetable(env3):
    client, _sid, tid, _ = env3
    r = client.patch(f"/api/timetables/{tid}", json={"name": "重新命名"})
    assert r.status_code == 200 and r.json()["name"] == "重新命名"


# ── 全員查詢 API 與教師權限(驗收③後端面)──
def test_published_endpoints_readable_by_teacher(env3):
    client, sid, tid, db = env3
    a = _one_period_course(client, sid)
    _place(client, tid, a["id"], 1, 1)
    client.post(f"/api/timetables/{tid}/publish")

    # 綁定教師帳號:王師 ↔ e2e teacher user
    teacher = client.get(f"/api/teachers?semester_id={sid}").json()[0]
    tuser = make_user(db, "t", PW, roles=[Role.teacher])
    client.patch(f"/api/teachers/{teacher['id']}", json={"name": "王師", "user_id": tuser.id})

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "t", "password": PW})

    # 教師可讀已發布課表與學期
    sems = client.get("/api/published/semesters").json()
    assert [s["id"] for s in sems] == [sid]
    pubtt = client.get(f"/api/published/timetable?semester_id={sid}").json()
    assert pubtt["status"] == "published" and len(pubtt["entries"]) == 1
    assert pubtt["period_tables"] and pubtt["classes"]

    # my-teacher 解析出本人
    me = client.get(f"/api/published/my-teacher?semester_id={sid}").json()
    assert me["id"] == teacher["id"] and me["name"] == "王師"

    # 但不得動用教學組長 API
    assert client.get(f"/api/timetables?semester_id={sid}").status_code == 403
    assert client.post(f"/api/timetables/{tid}/publish").status_code == 403


def test_published_timetable_none_when_no_published(env3):
    client, sid, _tid, _ = env3
    assert client.get(f"/api/published/timetable?semester_id={sid}").json() is None
    assert client.get("/api/published/semesters").json() == []


def test_my_teacher_null_when_unbound(env3):
    client, sid, _tid, _ = env3
    assert client.get(f"/api/published/my-teacher?semester_id={sid}").json() is None


# ── audit_log ─────────────────────────
def test_publish_writes_audit_log(env3):
    client, sid, tid, db = env3
    a = _one_period_course(client, sid)
    _place(client, tid, a["id"], 1, 1)
    client.post(f"/api/timetables/{tid}/publish")

    make_user(db, "admin1", PW, roles=[Role.admin])
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "admin1", "password": PW})

    logs = client.get("/api/audit-logs?action=publish_timetable").json()
    assert len(logs) == 1
    assert logs[0]["username"] == "s"
    assert logs[0]["target_id"] == tid
    assert "草稿A" in logs[0]["detail"]


def test_forced_publish_marked_in_audit(env3):
    client, sid, tid, db = env3
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "國文")
    t = _teacher(client, sid, "王師")
    _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]], periods=5)
    client.post(f"/api/timetables/{tid}/publish?force=true")

    make_user(db, "admin1", PW, roles=[Role.admin])
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "admin1", "password": PW})
    logs = client.get("/api/audit-logs").json()
    assert "強制發布" in logs[0]["detail"]


def test_audit_logs_admin_only(env3):
    client, _sid, _tid, _ = env3  # 目前登入者為 scheduler
    assert client.get("/api/audit-logs").status_code == 403
