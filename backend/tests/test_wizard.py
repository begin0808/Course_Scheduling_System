"""設定精靈與資料摘要測試。對應 M1-4 驗收標準。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def scheduler(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    return client


def test_initial_state_is_step0_incomplete(scheduler):
    """全新系統:精靈在第 0 步、未完成、無學期。"""
    r = scheduler.get("/api/wizard/state")
    assert r.status_code == 200
    body = r.json()
    assert body["current_step"] == 0
    assert body["completed"] is False
    assert body["has_semesters"] is False
    assert body["total_steps"] == 5


def test_progress_persists(scheduler):
    """驗收②:更新步驟後再讀,狀態保留(模擬關瀏覽器後續作)。"""
    sem = scheduler.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    scheduler.patch("/api/wizard/state", json={"current_step": 3, "semester_id": sem["id"]})
    body = scheduler.get("/api/wizard/state").json()
    assert body["current_step"] == 3
    assert body["semester_id"] == sem["id"]
    assert body["has_semesters"] is True


def test_complete_and_reset(scheduler):
    scheduler.patch("/api/wizard/state", json={"completed": True, "current_step": 4})
    assert scheduler.get("/api/wizard/state").json()["completed"] is True
    # 重新啟動精靈
    r = scheduler.post("/api/wizard/reset")
    body = r.json()
    assert body["completed"] is False
    assert body["current_step"] == 0
    assert body["semester_id"] is None


def test_step_clamped_to_valid_range(scheduler):
    scheduler.patch("/api/wizard/state", json={"current_step": 99})
    assert scheduler.get("/api/wizard/state").json()["current_step"] == 4  # TOTAL_STEPS-1


def test_semester_summary_counts(scheduler):
    """驗收①:摘要顯示教師/班級等數量。"""
    # 用空白學期(不帶範本)使計數可預期
    sem = scheduler.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    sid = sem["id"]
    scheduler.post(f"/api/subjects?semester_id={sid}", json={"name": "數學"})
    scheduler.post(f"/api/teachers?semester_id={sid}", json={"name": "王老師"})
    scheduler.post(f"/api/teachers?semester_id={sid}", json={"name": "李老師"})
    scheduler.post(
        f"/api/class-units?semester_id={sid}",
        json={"grade": 1, "name": "甲", "track": "junior_high"},
    )
    summary = scheduler.get(f"/api/semesters/{sid}/summary").json()
    assert summary == {"subjects": 1, "teachers": 2, "classes": 1, "rooms": 0}


def test_teacher_cannot_write_wizard(env):
    client, db = env
    make_user(db, "t", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert client.patch("/api/wizard/state", json={"current_step": 2}).status_code == 403
