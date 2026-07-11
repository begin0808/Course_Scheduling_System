"""M4 里程碑複審(Fable 5)修正的回歸測試:條件 A / B / C。

A. 「已完成」為讀取時推導:銷假不得抹除已上過的課(鐘點照算)、已上過的處置不得再變更。
B. availability 的 swap 補課判定只擋「該筆調課的補課方」,不誤傷全校。
C. 推薦引擎的本月代課公平計數排除已銷假的幽靈代課。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core import clock
from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.user import Role
from app.services.availability import Availability, Interval
from tests.conftest import make_user
from tests.test_substitutions import _find_entry, _World

PW = "password123"
SEM_START = date(2026, 9, 1)
SEM_END = date(2027, 1, 20)
WED = date(2026, 11, 11)    # 週三
WED2 = date(2026, 11, 18)   # 下週三
AFTER = datetime(2026, 12, 1, tzinfo=ZoneInfo("Asia/Taipei"))  # 兩個週三都已過


@pytest.fixture
def w(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


def _stats(w, month=11):
    return w.client.get(f"/api/substitution-stats{w.q}&year=2026&month={month}").json()


# ── 條件 A:已完成推導 ───────────────────────────────────────
def test_cancelling_leave_keeps_already_taught_period(w, monkeypatch):
    """代課上完後才銷假:那節不轉取消、鐘點照算。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    ap_id = leave["affected_periods"][0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert _stats(w)["summaries"], "指派後應計入"

    # 時間快轉到兩節課都上完之後才銷假
    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    w.client.post(f"/api/leaves/{leave['id']}/cancel")

    w.db.expire_all()
    ap = w.db.get(AffectedPeriod, ap_id)
    assert ap.status == AffectedStatus.resolved.value, "已上過的課不該被銷假轉為取消"
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陳師")
    assert chen["billable_count"] == 1, "已上過的代課鐘點照算"


def test_future_period_still_cancelled_on_leave_cancel(w):
    """對照組:未上過的課,銷假照常轉取消(真實今天 < WED)。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    ap_id = leave["affected_periods"][0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陳師"])
    w.client.post(f"/api/leaves/{leave['id']}/cancel")
    w.db.expire_all()
    assert w.db.get(AffectedPeriod, ap_id).status == AffectedStatus.cancelled.value


def test_cannot_assign_or_clear_past_period(w, monkeypatch):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    ap_id = w.leave("王師")[0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陳師"])  # 現在(未來日)可指派

    monkeypatch.setattr(clock, "school_now", lambda: AFTER)  # 課上過了
    code, body = w.assign(ap_id, type="merge", handler_teacher_id=w.teachers["陳師"])
    assert code == 409 and "已結束" in body["detail"]
    r = w.client.delete(f"/api/affected-periods/{ap_id}/substitution")
    assert r.status_code == 409 and "已結束" in r.json()["detail"]


def test_past_resolved_shows_completed(w, monkeypatch):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    ap_id = w.leave("王師")[0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陳師"])

    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    leaves = w.client.get(f"/api/leaves{w.q}").json()
    ap = next(p for lv in leaves for p in lv["affected_periods"] if p["id"] == ap_id)
    assert ap["status"] == "completed", "已上過的已指派節次顯示為已完成"


# ── 條件 B:swap 補課只擋補課方 ─────────────────────────────
def test_swap_makeup_blocks_only_the_makeup_teacher(w):
    """甲乙成立調課後,只有補課方(甲)在補課時段被判已佔用,第三人不受影響。"""
    w.teacher("王師", ["國文"])   # 甲:請假、日後補課
    w.teacher("陳師", ["數學"])   # 乙:代課、放掉一節由甲補
    w.teacher("林師", ["體育"])   # 丙:完全無關的第三人
    w.place("王師", "國文", "701", 0)             # 甲 週三第一節(被請假)
    w.place("陳師", "數學", "702", 1)             # 乙 週三第二節(swap 目標,甲於 WED2 補)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]
    entry_id = _find_entry(w, "陳師", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 200, body

    av = Availability(w.db, w.sid)
    makeup_slot = Interval(3, w.wed[1]["period_no"], None, None)  # WED2 週三第二節
    # 甲(王師)承諾在 WED2 第二節補課 → 已佔用
    c_wang = av.conflict_for(w.teachers["王師"], WED2, makeup_slot)
    assert c_wang is not None and c_wang.kind == "already_covering"
    # 丙(林師)與這筆調課無關 → 不該被誤判佔用
    assert av.conflict_for(w.teachers["林師"], WED2, makeup_slot) is None


# ── 條件 D:重新發布課表提醒未來的調代課依舊課表 ───────────
def test_republish_flags_stale_future_affected(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    # 依已發布課表登記一張未來假單 → 受影響節次以此版課表展開
    w.leave("王師")

    # 重新發布另一版課表:回應應提醒有未來的調代課依舊課表安排
    tt2 = w.client.post(f"/api/timetables{w.q}", json={"name": "草稿B"}).json()["id"]
    r = w.client.post(f"/api/timetables/{tt2}/publish?force=true")
    assert r.status_code == 200
    assert r.json()["stale_affected"] >= 1


def test_first_publish_has_no_stale(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    r = w.client.post(f"/api/timetables/{w.tt}/publish?force=true")
    assert r.status_code == 200
    assert r.json()["stale_affected"] == 0


# ── 條件 C:公平計數排除幽靈代課 ───────────────────────────
def test_monthly_fair_count_excludes_cancelled(w):
    """林師代的那節被銷假後,推薦別節時他的『本月已代』應回到 0。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.teacher("林師", ["國文"])
    w.place("王師", "國文", "701", 0)   # 王師 週三第一節
    w.place("陳師", "國文", "702", 1)   # 陳師 週三第二節(供另一張假單)
    w.publish()

    leave1 = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    w.assign(leave1["affected_periods"][0]["id"],
             type="substitute", handler_teacher_id=w.teachers["林師"])
    w.client.post(f"/api/leaves/{leave1['id']}/cancel")  # 銷假 → 那節取消(未來日)

    # 陳師 WED2 第二節請假,替它找代課
    leave2 = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["陳師"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()}).json()
    rec = w.recommend(leave2["affected_periods"][0]["id"])
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林師")
    assert lin["sub_periods_this_month"] == 0, "已銷假的代課不計入公平計數"
    assert "本月已代 0 節" in lin["reasons"]
