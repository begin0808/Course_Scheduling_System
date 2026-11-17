"""三角調課(v1.4.20,組長拿別家系統的畫面來問:「會出三角調課嗎?」)。

同一班三位老師輪流換課:王師週三第一節請假,林師來上;林師週四第二節由陳師上;
陳師週五第三節由王師回來上。兩人互調湊不出來(王師週四第二節有別班的課、
陳師週三第一節有別班的課)時,只有三個人一起換才換得成。

規則(使用者 2026-11-17 同意):只限同一個班、請假老師發起、範圍與互調相同、
鐘點不計、三位老師各一張調課單(只列自己要去上的那格)與班級一張、撤回三格一起撤、
三角調的節次不能再調。
"""

from datetime import timedelta

from app.models.substitution import Substitution
from app.services.availability import Availability, Interval
from tests.dates import WED
from tests.test_substitutions import _notif_titles, _options, _slips
from tests.test_teacher_week_sheets import _cell, _sheets
from tests.test_timetable_week import _at, _week, w  # noqa: F401 - w 為 fixture

THU = WED + timedelta(days=1)
FRI = WED + timedelta(days=2)


def _md(d):
    return f"{d.month}/{d.day}"


def _world(world):
    """701:王師週三第一節國文、林師週四第二節數學、陳師週五第三節英語。"""
    world.teacher("王師", ["國文"])
    world.teacher("林師", ["數學"])
    world.teacher("陳師", ["英語"])
    world.place("王師", "國文", "701", 0, weekday=3)
    world.place("林師", "數學", "701", 1, weekday=4)
    world.place("陳師", "英語", "701", 2, weekday=5)
    world.place("王師", "國文", "702", 1, weekday=4)   # 王師週四第二節有 702 的課:不能和林師互調
    world.place("陳師", "英語", "703", 0, weekday=3)   # 陳師週三第一節有 703 的課:不能來代
    world.publish()
    return world.leave("王師")[0]["id"]


def _triangles(world, aid, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    r = world.client.get(f"/api/affected-periods/{aid}/triangle-options?{qs}")
    assert r.status_code == 200, r.json()
    return r.json()


def _assign(world, aid, opt):
    return world.assign(
        aid, type="swap", handler_teacher_id=opt["partner_id"],
        tri_teacher_id=opt["third_id"], tri_entry_id=opt["mid"]["entry_id"],
        tri_date=opt["mid"]["date"], tri_period_no=opt["mid"]["period_no"],
        swap_entry_id=opt["makeup"]["entry_id"], swap_date=opt["makeup"]["date"],
        swap_period_no=opt["makeup"]["period_no"])


def _first(world, aid):
    opt = _triangles(world, aid)["options"][0]
    code, body = _assign(world, aid, opt)
    assert code == 200, body
    return body


def test_two_way_swaps_fail_but_the_rotation_is_listed(w):  # noqa: F811
    aid = _world(w)
    partners = {p["teacher_name"]: p for p in _options(w, aid)["partners"]}
    assert partners["林師"]["options"] == []          # 王師週四第二節自己有課
    assert partners["陳師"]["blocked_reason"]          # 陳師週三第一節自己有課

    body = _triangles(w, aid)
    assert body["unavailable"] == ""
    got = [(o["partner_name"], o["mid"]["date"], o["mid"]["subject_name"], o["third_name"],
            o["makeup"]["date"], o["makeup"]["subject_name"]) for o in body["options"]]
    nxt = timedelta(days=7)
    # 範圍與互調相同(預設兩週);兩節都早的排前面
    assert got[0] == ("林師", THU.isoformat(), "數學", "陳師", FRI.isoformat(), "英語")
    assert body["total"] == 4 and set(got) == {
        ("林師", THU.isoformat(), "數學", "陳師", FRI.isoformat(), "英語"),
        ("林師", THU.isoformat(), "數學", "陳師", (FRI + nxt).isoformat(), "英語"),
        ("林師", (THU + nxt).isoformat(), "數學", "陳師", FRI.isoformat(), "英語"),
        ("林師", (THU + nxt).isoformat(), "數學", "陳師", (FRI + nxt).isoformat(), "英語"),
    }


def test_rotation_is_recorded_and_all_three_are_notified(w):  # noqa: F811
    aid = _world(w)
    body = _first(w, aid)
    assert (body["handler_name"], body["tri_teacher_name"]) == ("林師", "陳師")
    assert (body["tri_date"], body["tri_subject_name"]) == (THU.isoformat(), "數學")
    assert (body["swap_date"], body["swap_subject_name"]) == (FRI.isoformat(), "英語")
    assert body["counts_toward_hours"] is False                     # 鐘點都不計

    assert any(t.startswith("三角調課通知") for t in _notif_titles(w, "林師"))
    assert any(t.startswith("三角調課通知") for t in _notif_titles(w, "陳師"))
    assert any(t.startswith("三角調課補課通知") for t in _notif_titles(w, "王師"))

    listed = w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"][0]
    assert (listed["tri_teacher_name"], listed["tri_date"]) == ("陳師", THU.isoformat())

    # 陳師週四第二節已經有安排:找人代別的課時他不是空的
    w.db.expire_all()
    av = Availability(w.db, w.sid)
    slot = Interval(4, w.wed[1]["period_no"], None, None)
    assert av.conflict_for(w.teachers["陳師"], THU, slot) is not None


def test_week_views_and_master_sheet_show_three_cells(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    cls = _week(w, "class", w.classes["701"]).json()
    assert _at(cls, WED, 1) == [("數學", "林師", "swap",
                                 f"三角調課(原:王師,另兩節 {_md(THU)} 第二節、{_md(FRI)} 第三節)")]
    assert _at(cls, THU, 2)[0][:3] == ("英語", "陳師", "swap")
    assert _at(cls, FRI, 3)[0][:3] == ("國文", "王師", "swap")
    chen = _week(w, "teacher", w.teachers["陳師"]).json()
    assert _at(chen, THU, 2)[0][2] == "swap"           # 老師本人的週課表看得到要去上的那一節

    sheet = _sheets(w).json()
    assert _cell(sheet, "林師", WED, 1) == [("701 數學", "swap", f"調{_md(THU)}_42")]
    assert _cell(sheet, "林師", THU, 2) == [("701 數學", "off", "調給陳師")]
    assert _cell(sheet, "陳師", THU, 2) == [("701 英語", "swap", f"調{_md(FRI)}_53")]
    assert _cell(sheet, "陳師", FRI, 3) == [("701 英語", "off", "調給王師")]
    assert _cell(sheet, "王師", FRI, 3) == [("701 國文", "swap", f"調{_md(WED)}_31")]

    patrol = w.client.get(f"/api/patrol-sheets{w.q}&date_from={THU.isoformat()}").json()
    page = next(p for p in patrol["pages"] if "701" in p["classes"])
    cell = page["rows"][1]["cells"][page["classes"].index("701")]
    assert (cell["subject"], cell["teacher"], cell["note"]) == ("英語", "陳師", "三角調課")


def test_slips_one_per_teacher_and_one_for_the_class(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    body = _slips(w, aid).json()
    kinds = [(s["kind"], s["teacher_name"]) for s in body["slips"]]
    assert kinds == [("teacher", "林師"), ("teacher", "陳師"), ("teacher", "王師"),
                     ("class", "")]

    def cells(slip):
        return [(c["date"], c["ordinal"], c["subject_name"], c["actor"], c["code"])
                for week in slip["weeks"] for c in week["cells"]]

    lin, chen, wang, klass = body["slips"]
    assert cells(lin) == [(WED.isoformat(), 1, "數學", "林師", f"調{_md(THU)}_42")]
    assert cells(chen) == [(THU.isoformat(), 2, "英語", "陳師", f"調{_md(FRI)}_53")]
    assert cells(wang) == [(FRI.isoformat(), 3, "國文", "王師", f"調{_md(WED)}_31")]
    assert len(cells(klass)) == 3


def test_board_and_log_list_every_cell(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    wed = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}").json()["entries"]
    assert [(e["row_kind"], e["handler_name"], e["is_triangle"], e["tri_teacher_name"])
            for e in wed] == [("leave", "林師", True, "陳師")]
    thu = w.client.get(f"/api/daily-board{w.q}&on={THU.isoformat()}").json()["entries"]
    assert [(e["row_kind"], e["absent_teacher_name"], e["handler_name"], e["swap_date"],
             e["leave_type_label"]) for e in thu] == [
        ("swap_makeup", "林師", "陳師", FRI.isoformat(), "三角調課")]
    fri = w.client.get(f"/api/daily-board{w.q}&on={FRI.isoformat()}").json()["entries"]
    assert [(e["absent_teacher_name"], e["handler_name"], e["swap_date"]) for e in fri] == [
        ("陳師", "王師", WED.isoformat())]

    # 查陳師的紀錄也查得到(他換了課)
    log = w.client.get(f"/api/substitution-log{w.q}&teacher_id={w.teachers['陳師']}").json()
    assert [e["absent_teacher_name"] for e in log] == ["王師"]


def test_withdrawing_undoes_all_three_cells(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    assert w.client.delete(f"/api/affected-periods/{aid}/substitution").status_code == 200
    assert "原訂三角調課已取消" in _notif_titles(w, "陳師")
    assert "原訂調課已取消" in _notif_titles(w, "林師")
    assert "原訂調課已取消" in _notif_titles(w, "王師")
    cls = _week(w, "class", w.classes["701"]).json()
    assert _at(cls, THU, 2) == [("數學", "林師", "normal", "")]
    assert _at(cls, FRI, 3) == [("英語", "陳師", "normal", "")]


def test_cancelling_the_leave_tells_the_third_teacher(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    leave = w.client.get(f"/api/leaves{w.q}").json()[0]
    assert w.client.post(f"/api/leaves/{leave['id']}/cancel").status_code == 200
    assert any(t.startswith("原訂三角調課已取消") for t in _notif_titles(w, "陳師"))
    assert _at(_week(w, "class", w.classes["701"]).json(), THU, 2)[0][2] == "normal"


def test_rotated_periods_cannot_be_swapped_again(w):  # noqa: F811
    """三角調的節次不能再調:黃師週三第二節請假,林師週四第二節、陳師週五第三節都不能再拿來換。"""
    aid = _world(w)
    _first(w, aid)
    w.teacher("黃師", ["自然"])
    new = w.client.post(f"/api/timetables/{w.tt}/duplicate", json={"name": "草稿B"}).json()
    w.tt = new["id"]
    w.place("黃師", "自然", "701", 1, weekday=3)
    w.publish()
    other = w.leave("黃師")[0]["id"]
    for who, day in (("林師", THU), ("陳師", FRI)):
        p = _options(w, other, who)["partners"][0]
        blocked = [o for o in p["blocked"] if o["date"] == day.isoformat()]
        assert blocked and "已經和別的老師調課了" in blocked[0]["blocked_reason"], (who, p)
    tri = _triangles(w, other)
    assert all((o["mid"]["date"], o["mid"]["teacher_name"]) != (THU.isoformat(), "林師")
               for o in tri["options"])


def test_invalid_rotations_are_explained(w):  # noqa: F811
    aid = _world(w)
    opt = _triangles(w, aid)["options"][0]

    def bad(**over):
        body = dict(opt)
        merged = {**body, **over}
        code, out = _assign(w, aid, merged)
        assert code == 409, out
        return out["detail"]

    assert "三位不同" in bad(third_id=w.teachers["林師"])
    assert "不是 陳師" in bad(makeup={**opt["makeup"], "entry_id": opt["mid"]["entry_id"],
                                       "date": opt["mid"]["date"]})
    # 陳師週四第二節另有安排(臨時排了 703 的課)→ 不能來上林師那節
    new = w.client.post(f"/api/timetables/{w.tt}/duplicate", json={"name": "草稿B"}).json()
    w.tt = new["id"]
    w.place("陳師", "英語", "703", 1, weekday=4)
    w.publish()
    opt2 = {**opt, "mid": {**opt["mid"], "entry_id": _entry(w, "林師", 4)},
            "makeup": {**opt["makeup"], "entry_id": _entry(w, "陳師", 5)}}
    code, out = _assign(w, aid, opt2)
    assert code == 409 and "陳師這節自己有課" in out["detail"], out
    assert w.db.query(Substitution).count() == 0


def _entry(world, teacher, weekday):
    tt = world.client.get(f"/api/timetables/{world.tt}").json()
    a_ids = {a["id"] for a in world.client.get(f"/api/assignments{world.q}").json()
             if any(t["teacher_id"] == world.teachers[teacher] for t in a["teachers"])
             and a["scheduling_unit"]["name"] == "701"}
    return next(e["id"] for e in tt["entries"]
                if e["course_assignment_id"] in a_ids and e["weekday"] == weekday)


def test_group_lessons_are_not_offered(w):  # noqa: F811
    """跑班、協同教學的課不能三角調課(那一節不只一門課或一位老師)。"""
    w.teacher("王師", ["國文"])
    w.teacher("林師", ["國文"])
    a = w.client.post(f"/api/assignments{w.q}", json={
        "class_id": w.klass("701"), "subject_id": w.subject("國文"), "periods_per_week": 1,
        "teachers": [{"teacher_id": w.teachers["王師"], "is_lead": True},
                     {"teacher_id": w.teachers["林師"], "is_lead": False}],
        "block_rules": []}).json()
    r = w.client.post(f"/api/timetables/{w.tt}/entries", json={
        "course_assignment_id": a["id"], "weekday": 3, "period_no": w.wed[0]["period_no"],
        "span": 1})
    assert r.status_code == 201, r.json()
    w.publish()
    aid = w.leave("王師")[0]["id"]
    assert "協同教學" in _triangles(w, aid)["unavailable"]


def test_republish_keeps_both_rotated_cells(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    new = w.client.post(f"/api/timetables/{w.tt}/duplicate", json={"name": "草稿B"}).json()
    r = w.client.post(f"/api/timetables/{new['id']}/publish?force=true")
    assert r.status_code == 200 and r.json()["swap_unlinked"] == 0, r.json()
    w.tt = new["id"]
    cls = _week(w, "class", w.classes["701"]).json()
    assert _at(cls, THU, 2)[0][:3] == ("英語", "陳師", "swap")
    assert _at(cls, FRI, 3)[0][:3] == ("國文", "王師", "swap")


def test_suspension_lists_the_third_teacher(w):  # noqa: F811
    aid = _world(w)
    _first(w, aid)
    r = w.client.post(f"/api/suspensions{w.q}", json={
        "start_date": THU.isoformat(), "end_date": THU.isoformat(), "whole_school": False,
        "class_ids": [w.classes["701"]], "all_day": True, "reason": "戶外教學"})
    assert r.status_code == 201, r.json()
    assert r.json()["conflicts"] == [f"{_md(THU)} 第二節 701:陳師 三角調課來上課"]
