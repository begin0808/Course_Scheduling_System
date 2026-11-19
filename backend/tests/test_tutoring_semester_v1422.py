"""v1.4.22 寒暑假輔導:學期多兩種類型(term 3 寒假輔導、4 暑期輔導)。

規則(使用者 2026-11-19 定案):起訖日期必填、不能和其他學期重疊;清單照日期由新到舊;
不管基本鐘點與超鐘點(上幾節給幾節);其餘排課、請假、代課全部沿用一般學期。
"""

from app.models.basedata import ClassTrack
from app.services import settings as settings_service
from app.services.assignments import assert_within_overtime_limit, teacher_loads
from app.services.slip_layout import school_title
from app.services.solver_data import load_problem
from app.solver import preflight
from tests.fixtures import Builder
from tests.test_semesters import login

FIRST = {"academic_year": 115, "term": 1, "start_date": "2026-08-31", "end_date": "2027-01-20"}
SECOND = {"academic_year": 115, "term": 2, "start_date": "2027-02-11", "end_date": "2027-06-30"}
WINTER = {"academic_year": 115, "term": 3, "start_date": "2027-01-25", "end_date": "2027-02-05"}
SUMMER = {"academic_year": 115, "term": 4, "start_date": "2027-07-05", "end_date": "2027-07-30"}


def _post(client, body):
    return client.post("/api/semesters", json=body)


def test_labels_and_list_sorted_by_date(env):
    client, db = env
    login(client, db)
    for body in (FIRST, SUMMER, WINTER, SECOND):
        assert _post(client, body).status_code == 201, body
    # 沒填日期的舊學期,照學年度推估排在後面
    assert _post(client, {"academic_year": 114, "term": 2}).status_code == 201
    assert _post(client, {"academic_year": 114, "term": 1}).status_code == 201

    items = client.get("/api/semesters").json()
    assert [s["label"] for s in items] == [
        "115 學年度暑期輔導", "115 學年度第 2 學期", "115 學年度寒假輔導",
        "115 學年度第 1 學期", "114 學年度第 2 學期", "114 學年度第 1 學期",
    ]
    assert [s["is_tutoring"] for s in items[:4]] == [True, False, True, False]


def test_tutoring_needs_dates(env):
    client, db = env
    login(client, db)
    r = _post(client, {"academic_year": 115, "term": 4})
    assert r.status_code == 400
    assert "寒暑假輔導要填開始日與結束日" in r.json()["detail"]
    sid = _post(client, SUMMER).json()["id"]
    r = client.patch(f"/api/semesters/{sid}", json={"end_date": None})
    assert r.status_code == 400


def test_tutoring_cannot_overlap_other_semesters(env):
    client, db = env
    login(client, db)
    assert _post(client, FIRST).status_code == 201
    second_id = _post(client, SECOND).json()["id"]

    r = _post(client, {**WINTER, "start_date": "2027-01-15"})
    assert r.status_code == 409
    assert "115 學年度第 1 學期" in r.json()["detail"]
    assert "不能和其他學期重疊" in r.json()["detail"]

    assert _post(client, WINTER).status_code == 201
    # 一般學期改日期,撞到輔導學期也要擋
    r = client.patch(f"/api/semesters/{second_id}", json={"start_date": "2027-02-01"})
    assert r.status_code == 409
    assert "115 學年度寒假輔導" in r.json()["detail"]
    # 一般學期之間照舊不擋(既有資料可能本來就重疊)
    assert _post(client, {"academic_year": 116, "term": 1,
                          "start_date": "2027-06-01", "end_date": "2027-06-20"}).status_code == 201


def test_copy_to_tutoring_semester(env):
    client, db = env
    login(client, db)
    src = _post(client, {**SECOND, "template_key": "junior_high"}).json()["id"]
    r = client.post(f"/api/semesters/{src}/copy", json={
        "academic_year": 115, "term": 4, "grade_promotion": False,
        "start_date": SUMMER["start_date"], "end_date": SUMMER["end_date"]})
    assert r.status_code == 201
    assert r.json()["label"] == "115 學年度暑期輔導"
    assert r.json()["is_tutoring"] is True
    # 複製也要檢查重疊
    r = client.post(f"/api/semesters/{src}/copy", json={
        "academic_year": 115, "term": 3, "start_date": "2027-06-20", "end_date": "2027-07-10"})
    assert r.status_code == 409


def _overworked(db, term):
    """王師基本鐘點 4 節,配了 10 節(超鐘點上限 2 節)。"""
    settings_service.save_max_overtime(db, 2)
    b = Builder(db, 120, term, "junior_high")
    b.teacher("王師", base_periods=4)
    b.klass("901", grade=9, track=ClassTrack.junior_high.value)
    b.subject("數學")
    b.assign(subject="數學", teachers=["王師"], periods=10, classes=["901"])
    fx = b.build()
    return b, fx.semester_id


def test_regular_semester_still_checks_overtime(db):
    b, sid = _overworked(db, 1)
    row = next(r for r in teacher_loads(db, sid) if r["name"] == "王師")
    assert row["over_limit"] and not row["tutoring"]
    codes = {i.code for i in preflight.run(load_problem(db, sid)).issues}
    assert "teacher_over_hours" in codes


def test_tutoring_ignores_base_hours_and_overtime(db):
    b, sid = _overworked(db, 4)
    row = next(r for r in teacher_loads(db, sid) if r["name"] == "王師")
    assert row["tutoring"] and not row["over_limit"]
    assert row["assigned"] == 10
    # 配課與匯入共用的上限檢核不擋
    assert_within_overtime_limit(db, sid, {b.teachers["王師"].id})
    problem = load_problem(db, sid)
    assert problem.is_tutoring
    codes = {i.code for i in preflight.run(problem).issues}
    assert "teacher_over_hours" not in codes


def test_slip_title_for_tutoring(db):
    b, sid = _overworked(db, 4)
    assert school_title(db, sid).endswith("120學年暑期輔導")
    b1, sid1 = _overworked(db, 1)
    assert school_title(db, sid1).endswith("120學年第一學期")
