"""全校教師週總表(v1.4.14):老師為欄、日期 × 節次為列,已套用調代課。"""

import io
from datetime import timedelta

import pytest
from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText

from app.models.basedata import ClassUnit, Teacher
from app.models.user import Role
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED
from tests.test_patrol_sheets import _group, _group_course, _place_group
from tests.test_substitutions import _swap_first, _World

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


def _sheets(w, day=WED, weeks=1):
    return w.client.get(
        f"/api/teacher-week-sheets{w.q}&date_from={day.isoformat()}&weeks={weeks}")


def _cell(body, teacher, day, ordinal):
    names = [t["name"] for t in body["teachers"]]
    for week in body["weeks"]:
        for row in week["rows"]:
            if row["date"] == day.isoformat() and row["ordinal"] == ordinal:
                return [(x["text"], x["kind"], x["note"])
                        for x in row["cells"][names.index(teacher)]]
    raise AssertionError(f"找不到 {day} 第 {ordinal} 節")


def test_columns_rows_and_plain_lessons(w):
    """行政職在前、再依班級排導師、其餘照建檔順序;只列有課的日子與一般課節次。"""
    for name in ("甲師", "乙師", "丙師", "丁師"):
        w.teacher(name, ["國文"])
    w.place("甲師", "國文", "701", 0)
    w.place("丙師", "國文", "702", 2, weekday=5)
    w.klass("702")
    w.publish()
    w.db.get(Teacher, w.teachers["丁師"]).admin_title = "教務主任"
    w.db.get(ClassUnit, w.classes["702"]).homeroom_teacher_id = w.teachers["丙師"]
    w.db.get(ClassUnit, w.classes["701"]).homeroom_teacher_id = w.teachers["乙師"]
    w.db.commit()

    r = _sheets(w)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert "115學年第一學期" in body["title"]
    assert [(t["name"], t["role"]) for t in body["teachers"]] == [
        ("丁師", "教務主任"), ("乙師", "701導師"), ("丙師", "702導師"), ("甲師", "")]

    [week] = body["weeks"]
    monday = WED - timedelta(days=WED.isoweekday() - 1)
    assert week["monday"] == monday.isoformat()
    days = sorted({row["date"] for row in week["rows"]})
    # 沒有課的日子(這裡是週一、二、四;實務上是週末與假日)不列
    assert days == [WED.isoformat(), (WED + timedelta(days=2)).isoformat()]
    wed_rows = [row for row in week["rows"] if row["date"] == WED.isoformat()]
    assert [row["ordinal"] for row in wed_rows] == list(range(1, len(w.wed) + 1))
    assert wed_rows[0]["period_name"] == "第一節"

    assert _cell(body, "甲師", WED, 1) == [("701 國文", "normal", "")]
    assert _cell(body, "甲師", WED, 2) == []
    fri = WED + timedelta(days=2)
    assert _cell(body, "丙師", fri, 3) == [("702 國文", "normal", "")]


def test_substitute_and_pending(w):
    """請假:自己那格劃掉並寫去向;代課老師那格藍字「代王師」。還沒安排時寫請假待處理。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")
    assert _cell(_sheets(w).json(), "王師", WED, 1) == [("701 國文", "pending", "請假待處理")]

    status, _ = w.assign(affected[0]["id"], type="substitute",
                         handler_teacher_id=w.teachers["陳師"])
    assert status == 200
    body = _sheets(w).json()
    assert _cell(body, "王師", WED, 1) == [("701 國文", "off", "陳師代")]
    assert _cell(body, "陳師", WED, 1) == [("701 國文", "cover", "代王師")]

    # 下一週照常
    nxt = WED + timedelta(days=7)
    body = _sheets(w, nxt).json()
    assert _cell(body, "王師", nxt, 1) == [("701 國文", "normal", "")]
    assert _cell(body, "陳師", nxt, 1) == []


def test_self_study_has_no_cover(w):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")
    status, _ = w.assign(affected[0]["id"], type="self_study")
    assert status == 200
    body = _sheets(w).json()
    assert _cell(body, "王師", WED, 1) == [("701 國文", "off", "自習")]
    assert _cell(body, "陳師", WED, 1) == []


def test_swap_marks_both_slots_with_codes(w):
    """調課:請假那節王師劃掉、陳師紅字;補課那節陳師劃掉、王師紅字。記號指向另一節。"""
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)                 # 週三第一節
    w.place("陳師", "數學", "701", 1, weekday=4)      # 週四第二節
    w.publish()
    affected = w.leave("王師")
    thu = WED + timedelta(days=1)
    _swap_first(w, affected[0]["id"], lambda o: o["date"] == thu.isoformat())

    body = _sheets(w).json()
    md = lambda d: f"{d.month}/{d.day}"  # noqa: E731
    assert _cell(body, "王師", WED, 1) == [("701 國文", "off", "調給陳師")]
    # 同班互調:科目跟著老師走
    assert _cell(body, "陳師", WED, 1) == [("701 數學", "swap", f"調{md(thu)}_42")]
    assert _cell(body, "陳師", thu, 2) == [("701 數學", "off", "調給王師")]
    assert _cell(body, "王師", thu, 2) == [("701 國文", "swap", f"調{md(WED)}_31")]


def test_group_lesson_shows_its_classes(w):
    w.teacher("英A師", ["英語"])
    w.teacher("英B師", ["英語"])
    unit = _group(w, "七年級英語分組", ["701", "702"])
    a = _group_course(w, unit, "英語", "英A師")
    _group_course(w, unit, "英語", "英B師")
    _place_group(w, a, 0)
    w.publish()
    body = _sheets(w).json()
    assert _cell(body, "英A師", WED, 1) == [("701、702 英語", "normal", "")]
    assert _cell(body, "英B師", WED, 1) == [("701、702 英語", "normal", "")]


def test_several_weeks_and_errors(w):
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    assert _sheets(w).status_code == 404                      # 還沒發布
    w.publish()

    body = _sheets(w, weeks=2).json()
    assert len(body["weeks"]) == 2
    assert body["weeks"][1]["monday"] == (
        WED - timedelta(days=WED.isoweekday() - 1) + timedelta(days=7)).isoformat()
    assert _sheets(w, weeks=5).status_code == 422
    far = SEM_END + timedelta(days=60)
    r = _sheets(w, far)
    assert r.status_code == 404 and "學期" in r.json()["detail"]


def test_xlsx_one_sheet_per_week_with_marks(w):
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")
    w.assign(affected[0]["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])

    r = w.client.get(
        f"/api/teacher-week-sheets.xlsx{w.q}&date_from={WED.isoformat()}&weeks=2")
    assert r.status_code == 200
    assert "filename*=UTF-8''" in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content), rich_text=True)
    assert len(wb.sheetnames) == 2
    ws = wb[wb.sheetnames[0]]
    assert "教師週總表" in ws["A1"].value
    header = [ws.cell(row=3, column=c).value for c in range(1, 5)]
    assert header == ["星期", "節次", "王師", "陳師"]
    rows = _sheets(w).json()["weeks"][0]["rows"]
    row = 4 + next(i for i, x in enumerate(rows)
                   if x["date"] == WED.isoformat() and x["ordinal"] == 1)
    assert ws.cell(row=row, column=2).value == 1
    absent, cover = ws.cell(row=row, column=3).value, ws.cell(row=row, column=4).value
    assert isinstance(absent, CellRichText) and isinstance(cover, CellRichText)
    assert str(absent) == "701 國文\n陳師代"
    assert absent[0].font.strike
    assert str(cover) == "701 國文\n代王師"
    assert ws.freeze_panes == "C4"
