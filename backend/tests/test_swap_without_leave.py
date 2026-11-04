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


# ── v1.4.9:同一筆調課裡兩節互相連動(組長回報)────────────────
def _linked_school(w, extra: bool = False):
    """學校活動:701、702 兩班的第一、二節當天同時對調。

    洪師第一節 701 音樂、第二節 702 音樂;張師第一節 702 健康;李師第二節 701 數學。
    702 要洪師第一節來上(與張師對調)、701 要洪師第二節來上(與李師對調)。
    """
    w.teacher("洪師", ["音樂"])
    w.teacher("張師", ["健康"])
    w.teacher("李師", ["數學"])
    w.place("洪師", "音樂", "701", 0)
    w.place("洪師", "音樂", "702", 1)
    w.place("張師", "健康", "702", 0)
    w.place("李師", "數學", "701", 1)
    if extra:   # 林師第一節 703 英語:同一節的另一個對調對象
        w.teacher("林師", ["英語"])
        w.place("林師", "英語", "703", 0)
    w.publish()


def _options(w, ap_id: int, teacher: str) -> list[tuple[str, int]]:
    r = w.client.get(
        f"/api/affected-periods/{ap_id}/swap-options?teacher_id={w.teachers[teacher]}")
    assert r.status_code == 200, r.json()
    return [(o["date"], o["period_no"])
            for p in r.json()["partners"] for o in p["options"]]


def test_two_periods_in_one_swap_request_release_each_other(env2):  # noqa: F811
    w = env2
    _linked_school(w)
    p1, p2 = w.wed[0]["period_no"], w.wed[1]["period_no"]

    # 只選一節:另一節他還得自己上,換不了(和原本一樣)
    code, single = _create(w, [p2], "洪師")
    assert code == 201, single
    assert (WED.isoformat(), p1) not in _options(w, single["affected_periods"][0]["id"], "張師")
    w.client.post(f"/api/leaves/{single['id']}/cancel")

    # 兩節一起選:兩筆都列得出來、也都送得出去
    code, leave = _create(w, [p1, p2], "洪師")
    assert code == 201, leave
    ap = {p["period_no"]: p["id"] for p in leave["affected_periods"]}
    assert (WED.isoformat(), p1) in _options(w, ap[p2], "張師")
    assert (WED.isoformat(), p2) in _options(w, ap[p1], "李師")

    code, body = w.assign(ap[p2], type="swap", handler_teacher_id=w.teachers["張師"],
                          swap_entry_id=_find_entry(w, "張師", 0), swap_date=WED.isoformat())
    assert code == 200, body
    code, body = w.assign(ap[p1], type="swap", handler_teacher_id=w.teachers["李師"],
                          swap_entry_id=_find_entry(w, "李師", 1), swap_date=WED.isoformat())
    assert code == 200, body


def test_released_period_cannot_be_used_twice(env2):  # noqa: F811
    """放開的只是「他自己的課」;同一節不能讓他補兩次。"""
    w = env2
    _linked_school(w, extra=True)
    p1, p2 = w.wed[0]["period_no"], w.wed[1]["period_no"]
    code, leave = _create(w, [p1, p2], "洪師")
    ap = {p["period_no"]: p["id"] for p in leave["affected_periods"]}
    code, body = w.assign(ap[p2], type="swap", handler_teacher_id=w.teachers["張師"],
                          swap_entry_id=_find_entry(w, "張師", 0), swap_date=WED.isoformat())
    assert code == 200, body
    # 第一節已經要補張師的課了,不能再補林師的
    code, body = w.assign(ap[p1], type="swap", handler_teacher_id=w.teachers["林師"],
                          swap_entry_id=_find_entry(w, "林師", 0), swap_date=WED.isoformat())
    assert code == 409, body


def test_real_leave_does_not_release(env2):  # noqa: F811
    """真的請假:假單時段內本來就不能補課,放開的規則只用在沒請假的調課。"""
    w = env2
    _linked_school(w)
    p1 = w.wed[0]["period_no"]
    leave = w.leave("洪師")
    p2_ap = next(p for p in leave if p["period_no"] == w.wed[1]["period_no"])
    assert (WED.isoformat(), p1) not in _options(w, p2_ap["id"], "張師")
