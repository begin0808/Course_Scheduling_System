"""停課日(v1.4.19,組長回報:「停課日在哪邊可以設定?」)。

全校、年級或指定班級,整天或第幾節到第幾節不上課。停課的課:
請假時不列為受影響節次、整天停課不必代導、不能拿來調課補課;
巡堂表、週課表、教師週總表標「停課」,全校整天停課的日子巡堂表略過。
"""

from datetime import timedelta

from app.models.user import Role
from app.services import suspensions as suspension_service
from tests.conftest import make_user
from tests.creds import PW
from tests.dates import WED
from tests.test_homeroom_cover import _homeroom
from tests.test_substitutions import _options, _World, env2  # noqa: F401 - env2 為 fixture

THU = WED + timedelta(days=1)


def _suspend(w: _World, day=WED, end=None, *, classes=None, lo=None, hi=None, reason="校慶補假"):
    body = {
        "start_date": day.isoformat(), "end_date": (end or day).isoformat(),
        "whole_school": classes is None,
        "class_ids": [w.classes[c] for c in (classes or [])],
        "all_day": lo is None, "from_ordinal": lo, "to_ordinal": hi, "reason": reason,
    }
    r = w.client.post(f"/api/suspensions{w.q}", json=body)
    assert r.status_code == 201, r.json()
    return r.json()


def _week(w, view, target, day=WED):
    r = w.client.get(f"/api/published/week{w.q}&view={view}&target_id={target}"
                     f"&on={day.isoformat()}")
    assert r.status_code == 200, r.json()
    return r.json()


def _at(body, day, ordinal):
    return [(c["subject"], c["teacher"], c["kind"], c["note"]) for c in body["cells"]
            if c["date"] == day.isoformat() and c["ordinal"] == ordinal]


def test_settings_describe_target_and_periods(env2):  # noqa: F811
    w = env2
    w.klass("701")
    w.klass("702")
    w.classes["801"] = w.client.post(f"/api/class-units{w.q}", json={
        "grade": 8, "name": "801", "track": "junior_high"}).json()["id"]
    school = _suspend(w)["item"]
    assert (school["target_text"], school["period_text"]) == ("全校", "整天")
    grade = _suspend(w, classes=["701", "702", "900"], lo=5, hi=7, reason="探索活動")["item"]
    assert (grade["target_text"], grade["period_text"]) == ("七年級", "第 5~7 節")
    some = _suspend(w, classes=["701", "801"], lo=3)["item"]
    # 八年級只有 801 一班:勾了就是整個八年級
    assert (some["target_text"], some["period_text"]) == ("701、八年級", "第 3 節")

    listed = w.client.get(f"/api/suspensions{w.q}").json()
    assert [x["id"] for x in listed] == [school["id"], grade["id"], some["id"]]

    r = w.client.put(f"/api/suspensions/{some['id']}", json={
        "start_date": THU.isoformat(), "end_date": THU.isoformat(), "whole_school": False,
        "class_ids": [w.classes["801"]], "all_day": True, "reason": "戶外教學"})
    assert r.status_code == 200, r.json()
    assert r.json()["item"]["target_text"] == "八年級"
    assert w.client.delete(f"/api/suspensions/{some['id']}").status_code == 204
    assert len(w.client.get(f"/api/suspensions{w.q}").json()) == 2


def test_invalid_settings_are_explained(env2):  # noqa: F811
    w = env2
    w.klass("701")

    def post(**over):
        body = {"start_date": WED.isoformat(), "end_date": WED.isoformat(),
                "whole_school": True, "class_ids": [], "all_day": True, "reason": ""}
        body.update(over)
        return w.client.post(f"/api/suspensions{w.q}", json=body)

    assert "早於" in post(end_date=(WED - timedelta(days=1)).isoformat()).json()["detail"]
    assert "班級" in post(whole_school=False).json()["detail"]
    assert "學期期間" in post(end_date=(WED + timedelta(days=170)).isoformat()).json()["detail"]
    assert "第幾節" in post(all_day=False).json()["detail"]
    assert "節次" in post(all_day=False, from_ordinal=5, to_ordinal=3).json()["detail"]

    # 老師看得到停課,不能設定
    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert w.client.get(f"/api/suspensions{w.q}").status_code == 200
    assert post().status_code == 403


def test_leave_on_suspended_periods_needs_no_substitute(env2):  # noqa: F811
    w = env2
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)      # 第 1 節
    w.place("王師", "國文", "701", 4)      # 第 5 節
    w.place("王師", "國文", "702", 5)      # 第 6 節,702 照常上課
    w.publish()
    _suspend(w, classes=["701"], lo=5, hi=7, reason="探索活動")

    r = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert [(p["class_names"], p["period_name"]) for p in body["affected_periods"]] == [
        ("701", "第一節"), ("702", "第六節")]
    assert [(s["period_name"], s["taken_by"]) for s in body["skipped"]] == [
        ("第五節", "停課(探索活動)")]


def test_whole_day_suspension_needs_no_homeroom_cover(env2):  # noqa: F811
    w = env2
    w.teacher("王師", ["國文"])
    _homeroom(w, "701", "王師")
    w.place("王師", "國文", "701", 0)
    w.publish()
    _suspend(w, classes=["701"])                       # 701 週三整天停課
    _suspend(w, THU, classes=["701"], lo=1, hi=2)       # 週四只停兩節:還是要代導
    r = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "personal",
        "start_date": WED.isoformat(), "end_date": THU.isoformat()})
    assert r.status_code == 201, r.json()
    assert [c["date"] for c in r.json()["homeroom_covers"]] == [THU.isoformat()]


def test_group_lesson_still_runs_when_only_one_class_is_off(env2):  # noqa: F811
    """合班、跑班:還有一個班要上課,老師就要去——每一個班都停課才算停課。"""
    w = env2
    w.klass("701")
    w.klass("702")
    _suspend(w, classes=["701"])
    cal = suspension_service.Calendar(w.db, w.sid, WED, WED)
    assert cal.for_classes([w.classes["701"]], WED, 1) is not None
    assert cal.for_classes([w.classes["701"], w.classes["702"]], WED, 1) is None
    _suspend(w, classes=["702"])
    cal = suspension_service.Calendar(w.db, w.sid, WED, WED)
    assert cal.for_classes([w.classes["701"], w.classes["702"]], WED, 1) is not None
    assert cal.for_classes([], WED, 1) is None


def test_suspended_period_cannot_be_used_for_a_swap(env2):  # noqa: F811
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "數學", "701", 1, weekday=4)   # 週四第 2 節
    w.publish()
    affected = w.leave("王師")
    _suspend(w, THU, classes=["701"], lo=2, reason="戶外教學")

    partner = _options(w, affected[0]["id"], "陳師")["partners"][0]
    thu = [o for o in partner["options"] + partner["blocked"] if o["date"] == THU.isoformat()]
    assert len(thu) == 1 and thu[0] in partner["blocked"]
    assert "停課(戶外教學)" in thu[0]["blocked_reason"]
    code, body = w.assign(affected[0]["id"], type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=thu[0]["entry_id"], swap_date=thu[0]["date"],
                          swap_period_no=thu[0]["period_no"])
    assert code in (400, 409), body
    assert "停課" in str(body)


def test_week_views_and_sheets_mark_suspended_lessons(env2):  # noqa: F811
    w = env2
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "國文", "702", 1)
    w.publish()
    _suspend(w, classes=["701"], reason="探索活動")

    cls = _week(w, "class", w.classes["701"])
    assert _at(cls, WED, 1) == [("國文", "王師", "off", "停課(探索活動)")]
    teacher = _week(w, "teacher", w.teachers["王師"])
    assert _at(teacher, WED, 1) == [("701 國文", "", "off", "停課(探索活動)")]
    assert _at(teacher, WED, 2) == [("702 國文", "", "normal", "")]

    patrol = w.client.get(f"/api/patrol-sheets{w.q}&date_from={WED.isoformat()}").json()
    morning = next(p for p in patrol["pages"] if "701" in p["classes"])
    first = morning["rows"][0]["cells"]
    assert first[morning["classes"].index("701")]["note"] == "停課"


def test_whole_school_day_off_is_left_out_of_the_sheets(env2):  # noqa: F811
    w = env2
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "國文", "701", 0, weekday=4)
    w.publish()
    _suspend(w)

    patrol = w.client.get(
        f"/api/patrol-sheets{w.q}&date_from={WED.isoformat()}&date_to={THU.isoformat()}").json()
    assert {p["date"] for p in patrol["pages"]} == {THU.isoformat()}
    only_wed = w.client.get(f"/api/patrol-sheets{w.q}&date_from={WED.isoformat()}")
    assert only_wed.status_code in (400, 404) and "停課" in only_wed.json()["detail"]

    sheets = w.client.get(
        f"/api/teacher-week-sheets{w.q}&date_from={WED.isoformat()}&weeks=1").json()
    assert WED.isoformat() not in {r["date"] for wk in sheets["weeks"] for r in wk["rows"]}
    assert THU.isoformat() in {r["date"] for wk in sheets["weeks"] for r in wk["rows"]}


def test_existing_arrangements_are_listed_when_suspending(env2):  # noqa: F811
    """停課是事後才設的:之前排好的不自動改(可能已經通知老師),列出來讓組長處理。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")
    w.assign(affected[0]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])

    saved = _suspend(w, classes=["701"])
    md = f"{WED.month}/{WED.day}"
    assert saved["conflicts"] == [f"{md} 第一節 701 國文:王師 病假"]
    # 畫面上以停課為準
    assert _at(_week(w, "class", w.classes["701"]), WED, 1) == [
        ("國文", "王師", "off", "停課(校慶補假)")]
    # 別班停課不相干
    w.klass("702")
    assert _suspend(w, classes=["702"])["conflicts"] == []
