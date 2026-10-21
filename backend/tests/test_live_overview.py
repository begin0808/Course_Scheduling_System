"""儀表板即時概況(v1.3.3,Issue #50):現在這一節各班實際在上什麼課、誰在上。

國中節次表(範本):早自習 07:50–08:20、第一節 08:20–09:05、第二節 09:15–10:00、
第三節 10:20–11:05、第四節 11:15–12:00、午休 12:00–13:10、第五節 13:10–13:55 …
第七節 15:10–15:55。
"""

from datetime import datetime, time

import pytest

from app.models.period import Period
from app.models.user import Role
from tests.conftest import make_user
from tests.dates import AFTER_SEM, SAT, SEM_END, SEM_START, WED
from tests.test_patrol_sheets import _group, _group_course, _place_group
from tests.test_substitutions import _World

PW = "password123"


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


def _live(w, hhmm: str, day=WED):
    at = datetime.combine(day, time.fromisoformat(hhmm)).isoformat()
    r = w.client.get(f"/api/live-overview{w.q}&at={at}")
    assert r.status_code == 200, r.json()
    return r.json()


def _only(body):
    assert body["message"] == ""
    assert len(body["sections"]) == 1
    return body["sections"][0]


def _cell(section, klass):
    return next(c for c in section["cells"] if c["class_name"] == klass)


@pytest.fixture
def school(w):
    """701 第一節國文(王師)、第二節數學(李師);702 第一節沒有課。"""
    w.teacher("王師", ["國文"])
    w.teacher("李師", ["數學"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("李師", "數學", "701", 1)
    w.klass("702")
    w.publish()
    return w


def test_in_class_shows_what_each_class_is_having_now(school):
    s = _only(_live(school, "08:30"))
    assert (s["state"], s["period_name"], s["start"], s["end"]) == (
        "in_class", "第一節", "08:20", "09:05")
    assert s["table_name"] == ""          # 全校一套節次表,不必寫是哪一套
    assert _cell(s, "701") == {
        "class_name": "701", "subject": "國文", "teacher": "王師", "room": "", "note": ""}
    assert _cell(s, "702")["subject"] == ""   # 這一節沒課,仍列出班級
    names = [c["class_name"] for c in s["cells"]]
    assert names.index("701") < names.index("702")   # 依年級、班名排序


def test_time_with_offset_is_read_in_school_time(school):
    """瀏覽器若送 UTC 時刻,換算成學校時區(台北 08:30 = UTC 00:30)。"""
    at = f"{WED.isoformat()}T00:30:00Z"
    s = _only(school.client.get(f"/api/live-overview{school.q}&at={at}").json())
    assert (s["state"], s["period_name"]) == ("in_class", "第一節")


@pytest.mark.parametrize(("hhmm", "label", "period"), [
    ("09:10", "下課", "第二節"),
    ("08:00", "早自習", "第一節"),
    ("12:30", "午休", "第五節"),
])
def test_between_lessons_shows_the_next_period(school, hhmm, label, period):
    """下課、早自習、午休:列出下一節,讓組長先確認有沒有缺人(使用者定案)。"""
    s = _only(_live(school, hhmm))
    assert (s["state"], s["now_label"], s["period_name"]) == ("upcoming", label, period)
    if period == "第二節":
        assert _cell(s, "701")["subject"] == "數學"


def test_lesson_boundaries(school):
    """09:05 第一節剛結束 → 下課;10:00 整點第二節結束。"""
    assert _only(_live(school, "09:04"))["period_name"] == "第一節"
    s = _only(_live(school, "09:05"))
    assert (s["state"], s["period_name"]) == ("upcoming", "第二節")
    assert _only(_live(school, "09:15"))["state"] == "in_class"


@pytest.mark.parametrize(("hhmm", "day", "state", "text"), [
    ("07:00", WED, "before_school", "第一節 08:20 開始"),
    ("16:30", WED, "after_school", "今天的課已結束"),
    ("10:30", SAT, "no_class", "今天沒有課"),
])
def test_outside_school_hours_is_a_single_line(school, hhmm, day, state, text):
    s = _only(_live(school, hhmm, day))
    assert s["state"] == state and text in s["message"]
    assert s["cells"] == []


def test_today_substitution_is_applied(school):
    w = school
    affected = w.leave("王師")
    cell = _cell(_only(_live(w, "08:30")), "701")
    assert (cell["teacher"], cell["note"]) == ("王師", "請假待處理")

    status, _ = w.assign(
        affected[0]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert status == 200
    cell = _cell(_only(_live(w, "08:30")), "701")
    assert (cell["subject"], cell["teacher"], cell["note"]) == ("國文", "陳師", "代課")


def test_big_group_is_summarised(w):
    """社團這類大型跑班一格塞不下,只寫群組名稱與組數(同巡堂表)。"""
    unit = _group(w, "社團", ["701", "702"])
    ids = []
    for i, club in enumerate(["羽球社", "桌球社", "棒球社", "漫畫社"]):
        w.teacher(f"師{i}", [club])
        ids.append(_group_course(w, unit, club, f"師{i}"))
    _place_group(w, ids[0], 5)          # 第六節 14:05–14:50
    w.publish()
    cell = _cell(_only(_live(w, "14:10")), "702")
    assert (cell["subject"], cell["teacher"], cell["note"]) == ("社團", "共 4 組", "")


def test_two_period_tables_are_judged_separately(w):
    """國中小:11:10 國中第三節已下課(下一節第四節 11:15),國小第四節(11:10–11:50)正在上。"""
    table = w.client.post(f"/api/semesters/{w.sid}/period-tables",
                          json={"name": "國小節次表", "template_key": "elementary"}).json()
    w.classes["601"] = w.client.post(f"/api/class-units{w.q}", json={
        "grade": 6, "name": "601", "track": "elementary", "period_table_id": table["id"],
    }).json()["id"]
    w.teacher("林師", ["英語"])
    w.place("林師", "英語", "701", 0)
    w.place("林師", "英語", "601", 3)
    w.publish()

    body = _live(w, "11:10")
    by_table = {s["table_name"]: s for s in body["sections"]}
    assert set(by_table) == {"國中節次表", "國小節次表"}
    jh, el = by_table["國中節次表"], by_table["國小節次表"]
    assert (jh["state"], jh["period_name"]) == ("upcoming", "第四節")
    assert "701" in [c["class_name"] for c in jh["cells"]]
    assert [c["class_name"] for c in el["cells"]] == ["601"]
    assert (el["state"], el["period_name"], el["start"]) == ("in_class", "第四節", "11:10")
    assert _cell(el, "601")["teacher"] == "林師"


def test_missing_period_times_ask_for_them(school):
    w = school
    for p in w.db.query(Period).all():
        p.start_time = p.end_time = None
    w.db.commit()
    s = _only(_live(w, "08:30"))
    assert s["state"] == "no_times" and "學期與節次表" in s["message"]


def test_nothing_published_or_outside_the_semester(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    assert _live(w, "08:30")["message"] == "這個學期還沒有發布課表"
    w.publish()
    body = _live(w, "08:30", AFTER_SEM)
    assert body["message"] == "今天不在這個學期的起訖日期內" and body["sections"] == []


def test_teachers_cannot_see_it(env):
    client, db = env
    make_user(db, "t", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert client.get("/api/live-overview?semester_id=1").status_code == 403
