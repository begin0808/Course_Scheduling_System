"""混合學制(班級 ↔ 節次表指派)測試。對應 M1-6 驗收標準。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user
from tests.test_import import upload

PW = "password123"


@pytest.fixture
def env2(env):
    """已登入教學組長 + 一個以國中範本建立的學期(預設=國中節次表)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()
    return client, sem


def _add_table(client, sid, name, template_key):
    return client.post(
        f"/api/semesters/{sid}/period-tables",
        json={"name": name, "template_key": template_key},
    ).json()


def _make_class(client, sid, name, table_id=None):
    body = {"grade": 1, "name": name, "track": "junior_high"}
    if table_id is not None:
        body["period_table_id"] = table_id
    return client.post(f"/api/class-units?semester_id={sid}", json=body).json()


def test_complete_high_school_each_class_own_slots(env2):
    """驗收①:完全中學 — 國中部/高中部班級各用各的節次表,可排時段不同。"""
    client, sem = env2
    sid = sem["id"]
    junior_table = sem["period_tables"][0]["id"]  # 國中(45 分,每日 7 節可排)
    senior_table = _add_table(client, sid, "高中部節次表", "senior_high")["id"]  # 8 節可排

    ca = _make_class(client, sid, "國中301", junior_table)
    cb = _make_class(client, sid, "高中501", senior_table)

    slots_a = client.get(f"/api/class-units/{ca['id']}/available-slots").json()
    slots_b = client.get(f"/api/class-units/{cb['id']}/available-slots").json()
    assert len(slots_a) == 7 * 5   # 國中每日 7 節 regular × 5 天
    assert len(slots_b) == 8 * 5   # 高中每日 8 節 regular × 5 天
    assert len(slots_a) != len(slots_b)


def test_unassigned_class_falls_back_to_default(env2):
    """驗收②:未指派節次表的班級回退學期預設表。"""
    client, sem = env2
    sid = sem["id"]
    cc = _make_class(client, sid, "無指定班")  # period_table_id 空
    slots = client.get(f"/api/class-units/{cc['id']}/available-slots").json()
    assert len(slots) == 7 * 5  # 預設(國中)表


def test_delete_period_table_referenced_by_class_blocked(env2):
    """驗收③:被班級指定的節次表刪除時回 409。"""
    client, sem = env2
    sid = sem["id"]
    senior_table = _add_table(client, sid, "高中部節次表", "senior_high")["id"]
    _make_class(client, sid, "高中501", senior_table)
    r = client.delete(f"/api/period-tables/{senior_table}")
    assert r.status_code == 409
    assert "班級" in r.json()["detail"]


def test_assign_cross_semester_table_rejected(env2):
    client, sem = env2
    sid = sem["id"]
    other = client.post("/api/semesters", json={"academic_year": 115, "term": 2}).json()
    foreign = _add_table(client, other["id"], "外部表", "senior_high")["id"]
    r = client.post(
        f"/api/class-units?semester_id={sid}",
        json={"grade": 1, "name": "X", "track": "junior_high", "period_table_id": foreign},
    )
    assert r.status_code == 400


def test_import_class_with_period_table_name(env2):
    """驗收④:Excel 匯入班級可指定節次表名稱;不存在時報列號錯誤。"""
    client, sem = env2
    sid = sem["id"]
    _add_table(client, sid, "高中部節次表", "senior_high")

    # 合法:指定「高中部節次表」
    ok_rows = [["1", "高中501", "普通型高中", "", "", 35, "高中部節次表"]]
    r = upload(client, "classes", sid, ok_rows, ncols=7)
    assert r.json()["imported"] == 1
    cu = client.get(f"/api/class-units?semester_id={sid}").json()[0]
    assert cu["period_table_id"] is not None

    # 錯誤:節次表名稱不存在 → 報列號
    bad_rows = [["1", "甲", "國中", "", "", "", "查無此表"]]
    body = upload(client, "classes", sid, bad_rows, ncols=7).json()
    assert body["imported"] == 0
    assert any("節次表" in e and "第 4 列" in e for e in body["errors"])
