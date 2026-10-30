"""補登(v1.4.2,組長回報):臨時找人代課,事後才登記請假。

那時節次已經過了,還是「待處理」,先前按下去只會回「此節次已結束」,鐘點也就漏算。
使用者定案:過去的待處理節次(與代導)可以補登,學期內都可以;補登**不通知**
(老師已經去上過課了),直接成為已完成並列入統計;已處理過、已過去的仍然不能改或撤回。
"""

from sqlalchemy import select

from app.core import clock
from app.models.audit import AuditLog
from app.models.notification import Notification
from tests.dates import MON, TUE, WED, WED2
from tests.test_homeroom_cover import _assign, _covers, _homeroom, _leave, _notes
from tests.test_m4_hardening import AFTER, _stats, w  # noqa: F401 - w 為 fixture
from tests.test_substitutions import env2  # noqa: F401 - env2 為 fixture


def _past_leave(world, monkeypatch, *days):
    """時間快轉到課都上完之後,才登記那幾天的假(事後補登記)。"""
    world.teacher("王師", ["國文"])
    world.teacher("陳師", ["國文"])
    world.place("王師", "國文", "701", 0)
    world.place("王師", "國文", "702", 1)
    world.publish()
    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    r = world.client.post(f"/api/leaves{world.q}", json={
        "teacher_id": world.teachers["王師"], "leave_type": "official",
        "start_date": days[0].isoformat(), "end_date": days[-1].isoformat()})
    assert r.status_code == 201, r.json()
    return r.json()


def _notifications(world, teacher: str) -> int:
    return len(world.db.scalars(
        select(Notification).where(Notification.teacher_id == world.teachers[teacher])).all())


def test_past_pending_period_is_marked_and_can_be_backfilled(w, monkeypatch):  # noqa: F811
    leave = _past_leave(w, monkeypatch, WED)
    ap = leave["affected_periods"][0]
    assert ap["status"] == "pending" and ap["is_past"] is True

    code, body = w.assign(ap["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 200, body

    w.db.expire_all()
    after = w.client.get(f"/api/leaves/{leave['id']}").json()["affected_periods"][0]
    assert after["status"] == "completed", "補登後直接是已完成"
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陳師")
    assert chen["billable_count"] == 1, "補登的代課列入鐘點"
    assert _notifications(w, "陳師") == 0, "補登不通知:老師已經去上過課了"
    audit = w.db.scalars(select(AuditLog).where(
        AuditLog.action == "assign_substitution")).all()[-1]
    assert audit.detail.startswith("補登 ")


def test_backfilled_period_cannot_be_changed_or_undone(w, monkeypatch):  # noqa: F811
    ap_id = _past_leave(w, monkeypatch, WED)["affected_periods"][0]["id"]
    w.assign(ap_id, type="substitute", handler_teacher_id=w.teachers["陳師"])

    code, body = w.assign(ap_id, type="self_study")
    assert code == 409 and "已結束" in body["detail"]
    r = w.client.delete(f"/api/affected-periods/{ap_id}/substitution")
    assert r.status_code == 409 and "已結束" in r.json()["detail"]


def test_backfill_other_dispositions(w, monkeypatch):  # noqa: F811
    """自習、不處理也能補登(沒有處理教師)。"""
    periods = _past_leave(w, monkeypatch, WED)["affected_periods"]
    assert w.assign(periods[0]["id"], type="self_study")[0] == 200
    assert w.assign(periods[1]["id"], type="cancel")[0] == 200


def test_backfill_rejects_swap(w, monkeypatch):  # noqa: F811
    ap_id = _past_leave(w, monkeypatch, WED)["affected_periods"][0]["id"]
    code, body = w.assign(ap_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=1, swap_date=WED2.isoformat())
    assert code == 409 and "無法補登調課" in body["detail"]


def test_batch_backfills_past_pending_periods(w, monkeypatch):  # noqa: F811
    leave = _past_leave(w, monkeypatch, WED, WED2)
    assert leave["pending_count"] == 4
    r = w.client.post(f"/api/leaves/{leave['id']}/substitutions/batch",
                      json={"handler_teacher_id": w.teachers["陳師"], "funding_source": ""})
    assert r.status_code == 200, r.json()
    assert r.json() == {"assigned": 4, "skipped": []}
    assert _notifications(w, "陳師") == 0
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陳師")
    assert chen["billable_count"] >= 2   # WED 那個月的兩節(WED2 可能跨月)


def test_future_period_is_not_past(w):  # noqa: F811
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    assert w.leave("王師")[0]["is_past"] is False


# ── 代導 ──────────────────────────────────────────
def test_past_cover_can_be_backfilled_without_notification(env2, monkeypatch):  # noqa: F811
    cw = env2
    cw.teacher("王師")
    cw.teacher("陳師")
    _homeroom(cw, "701", "王師")
    monkeypatch.setattr(clock, "school_today", lambda: WED)
    leave = _leave(cw, "王師", MON, TUE)          # 週三才補登週一、週二的假
    covers = leave["homeroom_covers"]
    assert all(c["is_past"] and c["status"] == "pending" for c in covers)

    code, body = _assign(cw, covers[0]["id"], handler_teacher_id=cw.teachers["陳師"],
                         whole_leave=True)
    assert code == 200 and body["assigned"] == 2, body
    assert [c["status"] for c in _covers(cw, leave["id"])] == ["completed", "completed"]
    assert _notes(cw, "陳師") == [], "補登不通知"

    # 補登後就跟其他過去的日子一樣,不能改、不能撤回
    code, body = _assign(cw, covers[0]["id"], no_cover=True)
    assert code == 409 and "已經過了" in body["detail"]
    r = cw.client.delete(f"/api/homeroom-covers/{covers[0]['id']}")
    assert r.status_code == 409


def test_whole_leave_from_future_day_includes_past_pending(env2, monkeypatch):  # noqa: F811
    """週二補登記週一到週三的假,從週三那筆「指派整段」:週一補登(不通知)、週二週三照常。"""
    cw = env2
    cw.teacher("王師")
    cw.teacher("陳師")
    _homeroom(cw, "701", "王師")
    monkeypatch.setattr(clock, "school_today", lambda: TUE)
    covers = _leave(cw, "王師", MON, WED)["homeroom_covers"]
    code, body = _assign(cw, covers[2]["id"], handler_teacher_id=cw.teachers["陳師"],
                         whole_leave=True)
    assert code == 200 and body["assigned"] == 3, body
    assert len(_notes(cw, "陳師")) == 2, "只有還沒過的週二、週三發通知"
