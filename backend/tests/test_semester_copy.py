"""開新學期複製測試。對應 M1-5 驗收標準。"""

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def populated(env):
    """已登入教學組長 + 一個含完整基礎資料的來源學期。回傳 (client, source_id)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()
    sid = sem["id"]
    # 科目已由範本帶入;再加教師(含科目+時段規則)、場地、班級
    subs = client.get(f"/api/subjects?semester_id={sid}").json()
    t = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "王老師", "base_periods": 20, "subject_ids": [subs[0]["id"]]},
    ).json()
    client.put(
        f"/api/teachers/{t['id']}/time-rules",
        json=[{"weekday": 1, "period_no": 2, "rule_type": "unavailable"}],
    )
    client.post(f"/api/rooms?semester_id={sid}", json={"name": "理化教室", "room_type": "special"})
    for grade in (1, 2, 3):
        client.post(
            f"/api/class-units?semester_id={sid}",
            json={"grade": grade, "name": f"{grade}年甲", "track": "junior_high",
                  "homeroom_teacher_id": t["id"]},
        )
    return client, sid


def _copy(client, sid, **kwargs):
    body = {"academic_year": 116, "term": 1, **kwargs}
    return client.post(f"/api/semesters/{sid}/copy", json=body)


def test_copy_all_and_counts(populated):
    client, sid = populated
    r = _copy(client, sid, grade_promotion=False)
    assert r.status_code == 201
    new = r.json()
    nid = new["id"]
    assert new["label"] == "116 學年度第 1 學期"
    # 各實體數量一致
    assert len(client.get(f"/api/subjects?semester_id={nid}").json()) == \
        len(client.get(f"/api/subjects?semester_id={sid}").json())
    assert len(client.get(f"/api/teachers?semester_id={nid}").json()) == 1
    assert len(client.get(f"/api/rooms?semester_id={nid}").json()) == 1
    assert len(client.get(f"/api/class-units?semester_id={nid}").json()) == 3
    assert len(new["period_tables"]) == 1


def test_copy_is_independent(populated):
    """驗收:改來源學期教師不影響新學期。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    src_teacher = client.get(f"/api/teachers?semester_id={sid}").json()[0]
    # 改來源教師姓名
    client.patch(f"/api/teachers/{src_teacher['id']}", json={"name": "改名了"})
    # 新學期教師不受影響
    new_teacher = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert new_teacher["name"] == "王老師"
    assert new_teacher["id"] != src_teacher["id"]


def test_grade_promotion_and_graduation(populated):
    """驗收:年級進位正確,畢業年級(國中三年級)移除。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=True).json()["id"]
    classes = client.get(f"/api/class-units?semester_id={nid}").json()
    grades = sorted(c["grade"] for c in classes)
    # 原 1,2,3 → 進位 2,3,(4 畢業移除)
    assert grades == [2, 3]


def test_no_promotion_keeps_grades(populated):
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    grades = sorted(c["grade"] for c in client.get(f"/api/class-units?semester_id={nid}").json())
    assert grades == [1, 2, 3]


def test_teacher_subjects_and_rules_copied(populated):
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    nt = client.get(f"/api/teachers?semester_id={nid}").json()[0]
    assert len(nt["subjects"]) == 1
    rules = client.get(f"/api/teachers/{nt['id']}/time-rules").json()
    assert len(rules) == 1 and rules[0]["rule_type"] == "unavailable"


def test_class_relations_remapped_to_new_semester(populated):
    """複製後班級的導師/節次表指向新學期的實體,非來源學期。"""
    client, sid = populated
    nid = _copy(client, sid, grade_promotion=False).json()["id"]
    new_teacher_ids = {t["id"] for t in client.get(f"/api/teachers?semester_id={nid}").json()}
    for c in client.get(f"/api/class-units?semester_id={nid}").json():
        assert c["homeroom_teacher_id"] in new_teacher_ids


def test_selective_copy_subjects_only(populated):
    client, sid = populated
    r = _copy(client, sid, subjects=True, teachers=False, rooms=False, classes=False,
              period_tables=False, grade_promotion=False)
    nid = r.json()["id"]
    assert len(client.get(f"/api/subjects?semester_id={nid}").json()) > 0
    assert client.get(f"/api/teachers?semester_id={nid}").json() == []
    assert client.get(f"/api/class-units?semester_id={nid}").json() == []


def test_copy_to_existing_target_409(populated):
    client, sid = populated
    assert _copy(client, sid, grade_promotion=False).status_code == 201
    assert _copy(client, sid, grade_promotion=False).status_code == 409  # 116/1 已存在
