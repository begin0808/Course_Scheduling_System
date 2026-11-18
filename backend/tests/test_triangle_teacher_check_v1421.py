"""三角調課指定老師(v1.4.21,組長回報「三角調課的清單裡找不到某位老師」)。

組長的情況:律動老師(這裡是丙師)只有週四有課,週四整天「調課(未請假)」;201 的換法是
「甲師(導師)來上丙師週四的律動 → 乙師(體育)上甲師週三第二節 → 丙師回來上乙師週三第四節體育」。
清單裡乙師一次都沒出現:丙師週四另一班的課已經先調好,補課就排在週三第四節,
同一個時段不能再回 201 上體育。系統是對的,但組長看不出卡在哪裡。

指定老師後:只列有這位老師的組合(不受 200 組截斷),並逐節寫出他在每個位置為什麼不行。
"""

from datetime import timedelta

from app.services.availability import Availability, Interval
from tests.dates import WED
from tests.test_timetable_week import w  # noqa: F401 - w 為 fixture

THU = WED + timedelta(days=1)
NEXT_WED = WED + timedelta(days=7)


def _md(d):
    return f"{d.month}/{d.day}"


def _school(world):
    world.teacher("甲師", ["國語"])
    world.teacher("乙師", ["體育"])
    world.teacher("丙師", ["律動"])
    world.teacher("戊師", ["數學"])
    world.place("甲師", "國語", "201", 0, weekday=3)
    world.place("甲師", "國語", "201", 1, weekday=3)
    world.place("乙師", "體育", "201", 3, weekday=3)    # 週三第四節 201 體育
    world.place("乙師", "體育", "401", 4, weekday=4)    # 週四第五節有別班:不能當 ①
    world.place("丙師", "律動", "102", 3, weekday=4)    # 丙師只有週四有課
    world.place("丙師", "律動", "201", 4, weekday=4)
    world.place("戊師", "數學", "102", 3, weekday=3)    # 102 週三第四節
    world.publish()
    day = world.client.get(
        f"/api/teachers/{world.teachers['丙師']}/day-periods{world.q}&date={THU}").json()
    r = world.client.post(f"/api/swap-requests{world.q}", json={
        "teacher_id": world.teachers["丙師"], "date": THU.isoformat(),
        "period_nos": [p["period_no"] for p in day]})
    assert r.status_code == 201, r.json()
    aps = {a["class_names"]: a["id"] for a in r.json()["affected_periods"]}
    return aps["201"], aps["102"]


def _swap_102_to_wednesday(world, ap102):
    """丙師週四 102 的課先和戊師對調:丙師週三第四節回 102 補課。"""
    opts = world.client.get(f"/api/affected-periods/{ap102}/swap-options").json()
    wu = next(p for p in opts["partners"] if p["teacher_name"] == "戊師")
    opt = next(o for o in wu["options"] if o["date"] == WED.isoformat())
    code, body = world.assign(ap102, type="swap", handler_teacher_id=world.teachers["戊師"],
                              swap_entry_id=opt["entry_id"], swap_date=opt["date"],
                              swap_period_no=opt["period_no"])
    assert code == 200, body


def _triangles(world, aid, teacher=None):
    q = f"?teacher_id={world.teachers[teacher]}" if teacher else ""
    r = world.client.get(f"/api/affected-periods/{aid}/triangle-options{q}")
    assert r.status_code == 200, r.json()
    return r.json()


def _combo(o):
    return (o["partner_name"], o["mid"]["date"], o["mid"]["period_name"], o["third_name"],
            o["makeup"]["date"], o["makeup"]["subject_name"])


def test_rotation_through_pe_is_listed_when_nothing_is_in_the_way(w):  # noqa: F811
    ap201, _ = _school(w)
    body = _triangles(w, ap201)
    assert [t["teacher_name"] for t in body["teachers"]] == ["乙師", "甲師"]
    assert body["check"] is None
    assert _combo(body["options"][0]) == (
        "甲師", WED.isoformat(), w.wed[0]["name"], "乙師", WED.isoformat(), "體育")


def test_picking_the_teacher_explains_the_blocked_makeup(w):  # noqa: F811
    ap201, ap102 = _school(w)
    _swap_102_to_wednesday(w, ap102)
    body = _triangles(w, ap201)
    # 這一週的乙師不見了(只剩下週的體育)
    assert all(o["makeup"]["date"] != WED.isoformat() for o in body["options"]
               if o["third_name"] == "乙師")

    picked = _triangles(w, ap201, "乙師")
    check = picked["check"]
    assert check["teacher_name"] == "乙師" and check["note"] == ""
    assert check["found"] == picked["total"] == len(picked["options"]) > 0
    assert all("乙師" in (o["partner_name"], o["third_name"]) for o in picked["options"])
    assert {o["makeup"]["date"] for o in picked["options"]} == {NEXT_WED.isoformat()}
    # ①:乙師週四第五節自己有課,來不了
    assert check["as_partner"] == [
        f"不能來上請假那一節 {_md(THU)}(週四) {w.wed[4]['name']}:乙師這節自己有課(401 體育)"]
    # ②:這一週的體育,丙師已經要回 102 補課
    assert check["as_third"] == [
        f"丙師回來上乙師的 {_md(WED)}(週三) {w.wed[3]['name']} 體育:"
        "丙師已被安排回 102 數學 調課補課"]


def test_a_teacher_without_lessons_in_the_class_gets_a_note(w):  # noqa: F811
    ap201, _ = _school(w)
    body = _triangles(w, ap201, "戊師")
    assert body["options"] == [] and body["total"] == 0
    assert "沒有這一班的課" in body["check"]["note"]


def test_substitute_conflicts_name_the_class(w):  # noqa: F811
    """已被安排代課時寫出是哪一班(原本只寫「已被安排代其他課」,組長不知道去哪裡找)。"""
    _school(w)
    ap = w.leave("戊師", WED)[0]["id"]               # 戊師週三請假,甲師代 102 第四節
    code, body = w.assign(ap, type="substitute", handler_teacher_id=w.teachers["甲師"])
    assert code == 200, body
    w.db.expire_all()
    av = Availability(w.db, w.sid)
    slot = Interval(3, w.wed[3]["period_no"], None, None)
    conflict = av.conflict_for(w.teachers["甲師"], WED, slot)
    assert conflict is not None and conflict.detail == "已被安排代 102 數學"
