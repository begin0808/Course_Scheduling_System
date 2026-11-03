"""修改假別與計費方式(v1.4.4,LINE 社群組長回報)。

請假登記的假別預設是病假,組長沒改到,公假被登成病假;計費方式依假別帶入,也跟著錯。
登記後兩個都改不了,已經過去的節次連撤回重派都不行。使用者定案:
- 假單可以修改假別與事由(日期、時間不能改);計費方式**不會跟著自動改**,畫面提醒。
- 代課可以修改計費方式與是否計入鐘點,**已經過去的節次也可以**(代課老師不變,只改怎麼付錢)。
"""

from sqlalchemy import select

from app.core import clock
from app.models.audit import AuditLog
from app.models.notification import Notification
from app.models.user import Role
from tests.conftest import make_user
from tests.test_m4_hardening import AFTER, PW, _stats, w  # noqa: F401 - w 為 fixture


def _setup(world, n: int = 2) -> dict:
    """王師週三 n 節課,登成病假(預設值),全部由陳師代課。"""
    world.teacher("王師", ["國文"])
    world.teacher("陳師", ["國文"])
    for i in range(n):
        world.place("王師", "國文", f"70{i + 1}", i)
    world.publish()
    periods = world.leave("王師", leave_type="sick")
    for p in periods:
        code, body = world.assign(
            p["id"], type="substitute", handler_teacher_id=world.teachers["陳師"])
        assert code == 200, body
    return world.client.get(f"/api/leaves{world.q}").json()[0]


def _audit(world, action: str) -> str:
    return world.db.scalars(
        select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)).all()[-1].detail


def _notes(world) -> int:
    return len(world.db.scalars(select(Notification)).all())


# ── 修改假別 ──────────────────────────────────────────
def test_change_leave_type_keeps_periods_and_billing(w):  # noqa: F811
    leave = _setup(w)
    before = leave["affected_periods"]
    assert {p["funding_source"] for p in before} == {"公費代課"}
    notes = _notes(w)

    r = w.client.patch(f"/api/leaves/{leave['id']}",
                       json={"leave_type": "official", "reason": "研習"})
    assert r.status_code == 200, r.json()
    after = r.json()
    assert after["leave_type"] == "official" and after["leave_type_label"] == "公假"
    assert after["reason"] == "研習"
    assert [(p["id"], p["status"], p["handler_name"]) for p in after["affected_periods"]] == \
        [(p["id"], p["status"], p["handler_name"]) for p in before], "節次與代課老師都不動"
    assert {p["funding_source"] for p in after["affected_periods"]} == {"公費代課"}, \
        "計費方式不會跟著假別自動改"
    assert _notes(w) == notes, "改假別不通知"
    assert "假別 病假 → 公假" in _audit(w, "update_leave")


def test_change_leave_type_validates(w):  # noqa: F811
    leave = _setup(w, 1)
    r = w.client.patch(f"/api/leaves/{leave['id']}", json={"leave_type": "vacation"})
    assert r.status_code == 400
    w.client.post(f"/api/leaves/{leave['id']}/cancel")
    r = w.client.patch(f"/api/leaves/{leave['id']}", json={"leave_type": "official"})
    assert r.status_code == 409 and "已銷假" in r.json()["detail"]


def test_teacher_cannot_change_leave(w):  # noqa: F811
    leave = _setup(w, 1)
    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    r = w.client.patch(f"/api/leaves/{leave['id']}", json={"leave_type": "official"})
    assert r.status_code == 403


# ── 修改計費方式 ──────────────────────────────────────
def test_change_billing_of_past_period(w, monkeypatch):  # noqa: F811
    """已經上過的代課:改不了代課老師,但可以改計費方式;改成日薪就從鐘點移到日薪。"""
    leave = _setup(w, 1)
    ap = leave["affected_periods"][0]
    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    notes = _notes(w)

    r = w.client.patch(f"/api/affected-periods/{ap['id']}/substitution/billing",
                       json={"funding_source": "日薪代課"})
    assert r.status_code == 200 and r.json() == {"updated": 1}, r.json()
    got = w.client.get(f"/api/leaves/{leave['id']}").json()["affected_periods"][0]
    assert got["status"] == "completed" and got["funding_source"] == "日薪代課"
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陳師")
    assert chen["billable_count"] == 0 and chen["daily_days"] == 1
    assert _notes(w) == notes, "改計費方式不通知"
    assert "計費方式改為「日薪代課」" in _audit(w, "update_substitution_billing")

    # 仍然不能改代課老師
    code, body = w.assign(ap["id"], type="self_study")
    assert code == 409 and "已結束" in body["detail"]


def test_change_billing_counts_toward_hours(w):  # noqa: F811
    leave = _setup(w, 1)
    ap = leave["affected_periods"][0]
    r = w.client.patch(f"/api/affected-periods/{ap['id']}/substitution/billing",
                       json={"funding_source": "不支鐘點", "counts_toward_hours": False})
    assert r.status_code == 200
    got = w.client.get(f"/api/leaves/{leave['id']}").json()["affected_periods"][0]
    assert got["funding_source"] == "不支鐘點" and got["counts_toward_hours"] is False
    chen = next(s for s in _stats(w)["summaries"] if s["teacher_name"] == "陳師")
    assert chen["billable_count"] == 0
    assert "鐘點不計" in _audit(w, "update_substitution_billing")


def test_change_billing_for_whole_leave_only_touches_substitutes(w):  # noqa: F811
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    for i in range(3):
        w.place("王師", "國文", f"70{i + 1}", i)
    w.publish()
    periods = w.leave("王師")
    w.assign(periods[0]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    w.assign(periods[1]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    w.assign(periods[2]["id"], type="self_study")
    leave_id = w.client.get(f"/api/leaves{w.q}").json()[0]["id"]

    r = w.client.patch(f"/api/leaves/{leave_id}/substitutions/billing",
                       json={"funding_source": "自費代課"})
    assert r.status_code == 200 and r.json() == {"updated": 2}, r.json()
    got = w.client.get(f"/api/leaves/{leave_id}").json()["affected_periods"]
    assert [p["funding_source"] for p in got] == ["自費代課", "自費代課", ""]
    assert "2 節" in _audit(w, "update_substitution_billing")


def test_change_billing_needs_a_substitute(w):  # noqa: F811
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    ap = w.leave("王師")[0]
    r = w.client.patch(f"/api/affected-periods/{ap['id']}/substitution/billing",
                       json={"funding_source": "公費代課"})
    assert r.status_code == 409 and "沒有可以修改" in r.json()["detail"]
    w.assign(ap["id"], type="self_study")
    r = w.client.patch(f"/api/affected-periods/{ap['id']}/substitution/billing",
                       json={"funding_source": "公費代課"})
    assert r.status_code == 409
    r = w.client.patch(f"/api/affected-periods/{ap['id']}/substitution/billing",
                       json={"funding_source": ""})
    assert r.status_code == 422, "計費方式不能空白"
