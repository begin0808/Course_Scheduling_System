"""跨節次表教師的「顯示」:國中小(國中 45 分、國小 40 分)同一位老師兩部都有課。

衝堂判定本來就以牆鐘時間為準(D7,見 test_timetables);這裡驗的是使用者看到的東西——
教師課表與通知單的格線只能照一套節次表畫,另一套的課必須標出實際時間,
衝堂訊息也要寫出對方那一節真正的時間。
"""

import io

import pytest
from openpyxl import load_workbook

from app.models.user import Role
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED
from tests.test_substitutions import _World

PW = "password123"


@pytest.fixture
def k9(env):
    """國中小:預設國中節次表 + 國小節次表;林師在 701(國中)與 601(國小)都有英語。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    w = _World(client, db, sid)
    table = client.post(f"/api/semesters/{sid}/period-tables",
                        json={"name": "國小節次表", "template_key": "elementary"}).json()
    w.classes["601"] = client.post(f"/api/class-units{w.q}", json={
        "grade": 6, "name": "601", "track": "elementary", "period_table_id": table["id"],
    }).json()["id"]
    w.teacher("林師", ["英語"])
    w.teacher("陳師", ["英語"])
    w.place("林師", "英語", "701", 0)   # 國中第一節 08:20–09:05
    w.place("林師", "英語", "601", 3)   # 國小第四節 11:10–11:50(國中第四節是 11:15–12:00)
    return w


def test_conflict_message_gives_the_other_lessons_real_time(k9):
    """國小第一節 08:30 撞到國中第一節 08:20–09:05:訊息要寫出那堂課實際的時間。"""
    w = k9
    slots = [p for p in w.client.get(
        f"/api/class-units/{w.classes['601']}/period-table").json()["periods"]
        if p["weekday"] == 3 and p["type"] == "regular"]
    a = w.client.post(f"/api/assignments{w.q}", json={
        "class_id": w.classes["601"], "subject_id": w.subject("英語"), "periods_per_week": 1,
        "teachers": [{"teacher_id": w.teachers["林師"]}], "block_rules": [],
    }).json()
    r = w.client.post(f"/api/timetables/{w.tt}/entries", json={
        "course_assignment_id": a["id"], "weekday": 3,
        "period_no": slots[0]["period_no"], "span": 1})
    assert r.status_code == 409
    messages = [c["message"] for c in r.json()["detail"]["conflicts"]]
    assert any("701 班英語(08:20–09:05)" in m for m in messages), messages


def test_teacher_timetable_marks_the_real_time_of_other_table_lessons(k9):
    w = k9
    w.publish()
    r = w.client.get(
        f"/api/export/timetable{w.q}&view=teacher&target_id={w.teachers['林師']}&fmt=xlsx")
    assert r.status_code == 200, r.text
    cells = [str(v) for row in load_workbook(io.BytesIO(r.content)).active.iter_rows(
        values_only=True) for v in row if v]
    c601 = next(c for c in cells if "601" in c)
    c701 = next(c for c in cells if "701" in c)
    assert "11:10–11:50" in c601          # 國小的課:標出實際時間
    assert "–" not in c701                # 國中的課就在自己的格線上,不必標


def test_class_timetable_needs_no_note(k9):
    """班級課表照該班自己的節次表畫,時間本來就對。"""
    w = k9
    w.publish()
    r = w.client.get(
        f"/api/export/timetable{w.q}&view=class&target_id={w.classes['601']}&fmt=xlsx")
    cells = [str(v) for row in load_workbook(io.BytesIO(r.content)).active.iter_rows(
        values_only=True) for v in row if v]
    assert "–" not in next(c for c in cells if "林師" in c)


def test_substitute_slip_marks_the_real_time_of_other_table_lessons(k9):
    """陳師同一張代課單上有國中與國小的課:格線照第一節(國中)畫,國小那格要標時間。"""
    w = k9
    w.publish()
    affected = w.leave("林師")
    for ap in affected:
        status, _ = w.assign(ap["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
        assert status == 200
    q = "&".join(f"affected_period_ids={ap['id']}" for ap in affected)
    body = w.client.get(f"/api/substitute-slips{w.q}&{q}").json()

    teacher = next(s for s in body["slips"] if s["kind"] == "teacher")
    notes = {c["actor"]: c["time_note"] for c in teacher["weeks"][0]["cells"]}
    assert notes == {"701[代]": "", "601[代]": "11:10–11:50"}
    assert WED.isoformat() == teacher["weeks"][0]["cells"][0]["date"]

    for slip in (s for s in body["slips"] if s["kind"] == "class"):
        assert all(c["time_note"] == "" for c in slip["weeks"][0]["cells"])   # 班級單照自己的格線
