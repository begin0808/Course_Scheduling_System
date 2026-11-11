"""課表查詢的「某一週實際課表」(v1.4.15):已套用調代課,有異動的格子標出種類。"""

from datetime import timedelta

import pytest

from app.models.user import Role
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED
from tests.test_substitutions import _options, _swap_first, _World

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


def _week(w, view, target, day=WED):
    return w.client.get(f"/api/published/week{w.q}&view={view}&target_id={target}"
                        f"&on={day.isoformat()}")


def _at(body, day, ordinal):
    got = [c for c in body["cells"] if c["date"] == day.isoformat() and c["ordinal"] == ordinal]
    return [(c["subject"], c["teacher"], c["kind"], c["note"]) for c in got]


def test_class_week_shows_substitute_with_original_teacher(w):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    body = _week(w, "class", w.classes["701"]).json()
    monday = WED - timedelta(days=WED.isoweekday() - 1)
    assert body["monday"] == monday.isoformat() and len(body["dates"]) == 7
    assert _at(body, WED, 1) == [("國文", "王師", "normal", "")]
    assert _at(body, WED, 1)[0] and body["cells"][0]["period_no"] == w.wed[0]["period_no"]

    affected = w.leave("王師")
    assert _at(_week(w, "class", w.classes["701"]).json(), WED, 1) == [
        ("國文", "王師", "pending", "請假待處理")]
    w.assign(affected[0]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert _at(_week(w, "class", w.classes["701"]).json(), WED, 1) == [
        ("國文", "陳師", "cover", "代課(原:王師)")]
    # 下一週照常
    nxt = WED + timedelta(days=7)
    assert _at(_week(w, "class", w.classes["701"], nxt).json(), nxt, 1) == [
        ("國文", "王師", "normal", "")]


def test_teacher_week_matches_the_master_sheet(w):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "數學", "701", 1, weekday=4)
    w.publish()
    affected = w.leave("王師")
    thu = WED + timedelta(days=1)
    _swap_first(w, affected[0]["id"], lambda o: o["date"] == thu.isoformat())
    md = lambda d: f"{d.month}/{d.day}"  # noqa: E731

    wang = _week(w, "teacher", w.teachers["王師"]).json()
    assert _at(wang, WED, 1) == [("701 國文", "", "off", "調給陳師")]
    assert _at(wang, thu, 2) == [("701 國文", "", "swap", f"調{md(WED)}_31")]
    assert all(c["period_no"] is None for c in wang["cells"])
    chen = _week(w, "teacher", w.teachers["陳師"]).json()
    assert _at(chen, WED, 1) == [("701 數學", "", "swap", f"調{md(thu)}_42")]
    assert _at(chen, thu, 2) == [("701 數學", "", "off", "調給王師")]

    # 班級課表兩格都寫出對調的另一節(v1.4.17)
    cls = _week(w, "class", w.classes["701"]).json()
    assert _at(cls, WED, 1) == [("數學", "陳師", "swap", f"調課(原:王師,與 {md(thu)} 第二節對調)")]
    assert _at(cls, thu, 2) == [("國文", "王師", "swap", f"調課(原:陳師,與 {md(WED)} 第一節對調)")]


def test_class_week_swap_into_another_week(w):
    """組長回報(v1.4.17):週四請假的課和隔週的課對調,這週的週課表只有一格變色,
    看起來像「只有一個人被調」。變色那格要寫出另一半在哪一天哪一節。"""
    w.teacher("王師", ["國文"])
    w.teacher("林師", ["輔導"])
    thu = WED + timedelta(days=1)
    w.place("王師", "國文", "701", 4, weekday=4)
    w.place("林師", "輔導", "701", 5, weekday=3)
    w.publish()
    affected = w.leave("王師", thu)
    nxt = WED + timedelta(days=7)
    opt = next(o for o in _options(w, affected[0]["id"], "林師")["partners"][0]["options"]
               if o["date"] == nxt.isoformat())
    code, body = w.assign(affected[0]["id"], type="swap", handler_teacher_id=w.teachers["林師"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"],
                          swap_period_no=opt["period_no"])
    assert code == 200, body
    md = lambda d: f"{d.month}/{d.day}"  # noqa: E731

    this_week = _week(w, "class", w.classes["701"]).json()
    assert _at(this_week, thu, 5) == [
        ("輔導", "林師", "swap", f"調課(原:王師,與 {md(nxt)} 第六節對調)")]
    assert _at(this_week, WED, 6) == [("輔導", "林師", "normal", "")], "這週的週三照常"
    next_week = _week(w, "class", w.classes["701"], nxt).json()
    assert _at(next_week, nxt, 6) == [
        ("國文", "王師", "swap", f"調課(原:林師,與 {md(thu)} 第五節對調)")]


def test_week_errors_and_teacher_can_view(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    assert _week(w, "class", w.classes["701"]).status_code == 404     # 還沒發布
    w.publish()
    assert _week(w, "room", 1).status_code == 422
    assert _week(w, "class", 99999).status_code == 404
    far = SEM_END + timedelta(days=30)
    assert _week(w, "class", w.classes["701"], far).json()["cells"] == []

    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert _week(w, "teacher", w.teachers["王師"]).status_code == 200
