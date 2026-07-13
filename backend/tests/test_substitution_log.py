"""M4-4:今日調代課看板與調代課日誌。

看板/日誌不新增真相,只把「受影響節次 + 處置」攤平成可讀紀錄。測試集中在:
- 看板只列當天、且排除已銷假的節次;含待處理讓組長看出還有幾節沒排。
- 歷史查詢依教師(缺課或代課皆算)、日期區間、假別篩選。
- 攤平後的欄位正確(處置類型/代課教師/教室/是否已處置)。
- RBAC:純教師不得存取行政看板。
"""


import pytest

from app.models.user import Role
from app.services import substitution_log as log_service
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED, WED2  # 日期一律由執行當日推算,不硬編
from tests.test_substitutions import _World

PW = "password123"


@pytest.fixture
def w(env):
    """已發布課表的國中,登入教學組長。回傳 _World。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


def _board(w, on=WED):
    return w.client.get(f"/api/daily-board{w.q}&on={on.isoformat()}").json()


def _log(w, **params):
    qs = "".join(f"&{k}={v}" for k, v in params.items() if v is not None)
    return w.client.get(f"/api/substitution-log{w.q}{qs}").json()


# ── 驗收①:看板反映當日處置;無異動則空 ──────────────────────
def test_board_empty_when_no_leave_that_day(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    board = _board(w)
    assert board["entries"] == []
    assert board["date"] == WED.isoformat()
    assert board["weekday"] == 3
    assert board["school_name"]           # 表頭校名(供列印通知單)
    assert board["semester_label"] == "115 學年度第 1 學期"


def test_board_lists_todays_changes_with_disposition(w):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]
    w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陳師"])

    board = _board(w)
    assert len(board["entries"]) == 1
    e = board["entries"][0]
    assert e["absent_teacher_name"] == "王師"
    assert e["disposed"] is True
    assert e["sub_type_label"] == "代課"
    assert e["handler_name"] == "陳師"
    assert e["class_names"] == "701"
    assert e["subject_name"] == "國文"
    assert e["leave_type_label"] == "病假"


def test_board_includes_pending_periods(w):
    """待處理節次也上看板,好讓組長看出還有幾節沒排代課。"""
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    w.leave("王師")  # 不指派

    board = _board(w)
    assert len(board["entries"]) == 1
    e = board["entries"][0]
    assert e["disposed"] is False
    assert e["status_label"] == "待處理"
    assert e["handler_name"] is None


def test_board_ordered_by_period(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 2)  # 第三節
    w.place("王師", "國文", "701", 0)  # 第一節
    w.publish()
    w.leave("王師")

    board = _board(w)
    nos = [e["period_no"] for e in board["entries"]]
    assert nos == sorted(nos)


def test_board_excludes_cancelled_leave(w):
    """銷假後,那天不再有異動——看板不列。"""
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    leave = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()
    assert _board(w)["entries"], "銷假前應有一節"
    w.client.post(f"/api/leaves/{leave['id']}/cancel")
    assert _board(w)["entries"] == [], "銷假後不該再列"


def test_board_only_that_day(w):
    """另一天的請假不會出現在今天的看板。"""
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})
    assert _board(w, on=WED)["entries"] == []
    assert _board(w, on=WED2)["entries"]


def test_board_defaults_to_school_today(w, monkeypatch):
    """未帶 on 時以學校時區的今天為準。"""
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    w.leave("王師")  # WED
    monkeypatch.setattr(log_service, "school_today", lambda: WED)
    board = w.client.get(f"/api/daily-board{w.q}").json()
    assert board["date"] == WED.isoformat()
    assert board["entries"]


# ── 歷史查詢 ─────────────────────────────────────────────────
def test_log_filters_by_date_range(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    w.leave("王師", when=WED)
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})

    only_first = _log(w, date_from=WED.isoformat(), date_to=WED.isoformat())
    dates = {e["date"] for e in only_first}
    assert dates == {WED.isoformat()}


def test_log_filters_by_leave_type(w):
    w.teacher("王師", ["國文"])
    w.teacher("李師", ["數學"])
    w.place("王師", "國文", "701", 0)
    w.place("李師", "數學", "702", 1)
    w.publish()
    w.leave("王師", when=WED)  # sick
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["李師"], "leave_type": "official",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})

    sick = _log(w, leave_type="sick")
    assert {e["absent_teacher_name"] for e in sick} == {"王師"}
    official = _log(w, leave_type="official")
    assert {e["absent_teacher_name"] for e in official} == {"李師"}


def test_log_by_teacher_matches_absent_and_handler(w):
    """查一位教師:他缺的課與他代的課都算與他相關。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)  # 王師第一節(被請假)
    w.publish()
    a_wang = w.leave("王師")[0]["id"]
    w.assign(a_wang, type="substitute", handler_teacher_id=w.teachers["陳師"])

    # 以陳師查詢:他沒請假,但代了王師的課 → 應命中
    chen = _log(w, teacher_id=w.teachers["陳師"])
    assert len(chen) == 1
    assert chen[0]["absent_teacher_name"] == "王師"
    assert chen[0]["handler_name"] == "陳師"

    # 以王師查詢:他是缺課的當事人 → 應命中
    wang = _log(w, teacher_id=w.teachers["王師"])
    assert len(wang) == 1


def test_log_newest_first(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    w.leave("王師", when=WED)
    w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["王師"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()})
    dates = [e["date"] for e in _log(w)]
    assert dates == sorted(dates, reverse=True)


# ── RBAC ─────────────────────────────────────────────────────
def test_teacher_cannot_view_board(w):
    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/logout")
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    r = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}")
    assert r.status_code == 403
    r2 = w.client.get(f"/api/substitution-log{w.q}")
    assert r2.status_code == 403


def test_board_unknown_semester_404(w):
    r = w.client.get(f"/api/daily-board?semester_id=999999&on={WED.isoformat()}")
    assert r.status_code == 404
