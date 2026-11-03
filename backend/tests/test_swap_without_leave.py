"""新增調課(未請假,v1.4.5,LINE 社群組長回報)。

老師沒請假,只是要和別人調課;先前調課只能從請假展開的節次做,組長只好硬登一張假。
使用者定案:「調代課處理」加「新增調課」——選老師、日期、勾節次,接著照一般調課選對調節次。
只允許調課;不出現在請假登記、不算請假(不產生代導、人仍在學校)。
"""

from sqlalchemy import select

from app.core import clock
from app.models.audit import AuditLog
from app.models.notification import Notification
from tests.dates import WED, WED2
from tests.test_m4_hardening import AFTER
from tests.test_substitutions import _find_entry, env2  # noqa: F401 - env2 為 fixture


def _school(w):
    """王師週三第一、二節(701、702);陳師週三第三節(703),當調課對象。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "國文", "702", 1)
    w.place("陳師", "數學", "703", 2)
    w.publish()


def _day(w, teacher: str = "王師", day=WED) -> list[dict]:
    r = w.client.get(f"/api/teachers/{w.teachers[teacher]}/day-periods{w.q}&date={day}")
    assert r.status_code == 200, r.json()
    return r.json()


def _create(w, period_nos: list[int], teacher: str = "王師", day=WED):
    r = w.client.post(f"/api/swap-requests{w.q}", json={
        "teacher_id": w.teachers[teacher], "date": day.isoformat(), "period_nos": period_nos})
    return r.status_code, r.json()


def test_lists_the_teachers_periods_that_day(env2):  # noqa: F811
    w = env2
    _school(w)
    periods = _day(w)
    assert [p["period_name"] for p in periods] == [w.wed[0]["name"], w.wed[1]["name"]]
    assert {p["class_names"] for p in periods} == {"701", "702"}
    assert not any(p["is_past"] or p["taken_by"] for p in periods)


def test_create_only_selected_periods_and_swap(env2):  # noqa: F811
    w = env2
    _school(w)
    code, leave = _create(w, [w.wed[0]["period_no"]])
    assert code == 201, leave
    assert leave["leave_type"] == "swap_only" and leave["leave_type_label"] == "調課(未請假)"
    assert [p["class_names"] for p in leave["affected_periods"]] == ["701"], "只展開勾選的那一節"
    assert leave["homeroom_covers"] == []
    assert "調課(未請假)" in w.db.scalars(select(AuditLog).where(
        AuditLog.action == "create_swap_request")).all()[-1].detail

    ap = leave["affected_periods"][0]
    # 只能調課
    code, body = w.assign(ap["id"], type="self_study")
    assert code == 409 and "只能選調課" in body["detail"]
    r = w.client.post(f"/api/leaves/{leave['id']}/substitutions/batch",
                      json={"handler_teacher_id": w.teachers["陳師"], "funding_source": ""})
    assert r.status_code == 409
    # 調課照常成立:陳師來上王師第一節,王師下週三補陳師第三節
    code, body = w.assign(ap["id"], type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=_find_entry(w, "陳師"), swap_date=WED2.isoformat())
    assert code == 200, body
    assert body["type_label"] == "調課"


def test_swap_only_is_not_a_leave(env2):  # noqa: F811
    """人在學校:不能被當成請假(找他代課時不會因「當天請假」被排除),也不產生代導。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("林師", ["英語"])
    w.place("王師", "國文", "701", 0)
    w.place("林師", "英語", "704", 2)    # 林師週三第三節請假,王師那節空堂
    w.publish()
    r = w.client.patch(f"/api/class-units/{w.classes['701']}", json={
        "grade": 7, "name": "701", "track": "junior_high",
        "homeroom_teacher_id": w.teachers["王師"]})
    assert r.status_code == 200, r.json()
    code, leave = _create(w, [w.wed[0]["period_no"]])
    assert code == 201 and leave["homeroom_covers"] == [], "導師沒請假,不產生代導"

    lin = w.leave("林師")[0]
    rec = w.client.get(f"/api/affected-periods/{lin['id']}/recommendations").json()
    assert "王師" in [c["teacher_name"] for c in rec["candidates"]], "王師沒請假,可以代課"


def test_not_listed_as_a_leave_type(env2):  # noqa: F811
    w = env2
    _school(w)
    assert "swap_only" not in w.client.get("/api/leave-types").json()
    r = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "swap_only",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 400
    code, leave = _create(w, [w.wed[0]["period_no"]])
    r = w.client.patch(f"/api/leaves/{leave['id']}", json={"leave_type": "official"})
    assert r.status_code == 409


def test_rejects_bad_selection(env2):  # noqa: F811
    w = env2
    _school(w)
    code, body = _create(w, [])
    assert code == 400 and "請選擇" in body["detail"]
    code, body = _create(w, [w.wed[2]["period_no"]])   # 王師第三節沒課
    assert code == 400 and "沒有這幾節課" in body["detail"]

    # 已經在別張假單裡的節次不能重複
    w.leave("王師")
    assert {p["taken_by"] for p in _day(w)} == {"病假"}
    code, body = _create(w, [w.wed[0]["period_no"]])
    assert code == 400 and "病假" in body["detail"]


def test_rejects_past_periods(env2, monkeypatch):  # noqa: F811
    w = env2
    _school(w)
    monkeypatch.setattr(clock, "school_now", lambda: AFTER)
    assert all(p["is_past"] for p in _day(w))
    code, body = _create(w, [w.wed[0]["period_no"]])
    assert code == 400 and "已經上過" in body["detail"]


def test_cancel_notifies_both_and_frees_the_period(env2):  # noqa: F811
    w = env2
    _school(w)
    code, leave = _create(w, [w.wed[0]["period_no"]])
    ap = leave["affected_periods"][0]
    w.assign(ap["id"], type="swap", handler_teacher_id=w.teachers["陳師"],
             swap_entry_id=_find_entry(w, "陳師"), swap_date=WED2.isoformat())

    r = w.client.post(f"/api/leaves/{leave['id']}/cancel")
    assert r.status_code == 200 and r.json()["notified_teachers"] == ["陳師"]
    titles = {n.teacher_id: n.title for n in w.db.scalars(
        select(Notification).order_by(Notification.id))}
    assert titles[w.teachers["陳師"]].startswith("原訂調課已取消")
    assert "取消您的調課" in titles[w.teachers["王師"]]
    assert "取消調課" in w.db.scalars(select(AuditLog).where(
        AuditLog.action == "cancel_leave")).all()[-1].detail
    # 取消後那一節又可以選
    assert {p["taken_by"] for p in _day(w)} == {""}
