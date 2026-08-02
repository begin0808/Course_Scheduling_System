"""示範資料(Phase 2)測試。

重點不在「有沒有建出東西」,而在建出來的東西**排得出課表**——
示範資料若無解,比沒有示範資料更糟:使用者第一次按自動排課就看到失敗。
"""

import pytest

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Teacher
from app.models.user import Role
from app.services import assignments as assign_svc
from app.services import demo_data
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def admin_client(env):
    client, db = env
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    return client, db


# ── 規格自身的一致性 ────────────────────────────────
# 這幾支不碰資料庫,純粹檢查 demo_school.json 的數字有沒有算錯。


def test_spec_gives_every_class_the_same_weekly_periods():
    spec = demo_data.load_spec()
    per_grade = {}
    for grade in spec["classes"]["grades"]:
        per_grade[grade] = sum(
            s["periods"].get(str(grade), 0) for s in spec["subjects"]
        )
    assert set(per_grade.values()) == {33}, f"各年級節數不一致:{per_grade}"


def test_spec_capacity_covers_demand():
    """教師應授總量必須夠用,否則示範資料一載入就是一片超鐘點。"""
    spec = demo_data.load_spec()
    n = spec["classes"]["per_grade"]
    demand = sum(
        s["periods"].get(str(g), 0) * n
        for s in spec["subjects"]
        for g in spec["classes"]["grades"]
    )
    classes = demo_data._class_names(spec)
    plans = demo_data._plan_teachers(spec, [c for _, c in classes])
    # 外聘教師的應授在 generate() 時才依實際需求算出,這裡以規格值補上
    capacity = sum(p.target for p in plans if p.role != demo_data.ROLE_EXTERNAL)
    external = sum(
        s["periods"].get(str(g), 0) * n
        for s in spec["subjects"]
        for g in spec["classes"]["grades"]
        if s["dept"] == "本土語文"
    )
    assert capacity + external >= demand
    assert (capacity + external) / demand < 1.15, "教師過剩,示範資料會顯得不真實"


def test_spec_has_one_homeroom_teacher_per_class():
    spec = demo_data.load_spec()
    classes = demo_data._class_names(spec)
    homerooms = sum(d.get(demo_data.ROLE_HOMEROOM, 0) for d in spec["departments"])
    assert homerooms == len(classes)


# ── 產生結果 ────────────────────────────────────────


def test_generate_builds_a_complete_school(admin_client):
    client, db = admin_client
    r = client.post("/api/demo-data")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["classes"] == 18
    assert body["subjects"] == 24
    assert body["total_periods"] == 33 * 18
    assert body["assignments"] > 300
    # 每班一間普通教室 + 專科教室
    assert body["rooms"] >= 18


def test_every_class_has_a_homeroom_teacher(admin_client):
    client, db = admin_client
    client.post("/api/demo-data")
    for cu in db.query(ClassUnit).all():
        assert cu.homeroom_teacher_id is not None, f"{cu.name} 沒有導師"


def test_nobody_exceeds_the_overtime_limit(admin_client):
    """示範資料自己必須守 Phase 1 的規則,否則就是拿一份違規資料當範例。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    loads = assign_svc.teacher_loads(db, body["semester_id"])
    over = [row for row in loads if row["over_limit"]]
    assert not over, f"有教師超過上限:{[(r['name'], r['delta']) for r in over]}"
    assert body["max_overtime_used"] <= 8


def test_shows_both_over_and_under_hours(admin_client):
    """鐘點統計要同時看得到紅、藍兩種狀態,否則等於只示範了一半。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    loads = assign_svc.teacher_loads(db, body["semester_id"])
    assert any(r["delta"] > 0 for r in loads), "沒有任何教師超鐘點"
    assert any(r["delta"] < 0 for r in loads), "沒有任何教師鐘點不足"


def test_no_teacher_is_left_without_classes(admin_client):
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    idle = [
        r["name"] for r in assign_svc.teacher_loads(db, body["semester_id"])
        if r["assigned"] == 0
    ]
    assert not idle, f"有教師完全沒課:{idle}"


def test_tainan_base_periods_are_applied(admin_client):
    """國文科導師 11 節、其他科導師 13 節——臺南市規定的差異要真的反映出來。"""
    client, db = admin_client
    client.post("/api/demo-data")
    homerooms = {
        t.name: t.base_periods
        for t in db.query(Teacher).all()
        if db.query(ClassUnit).filter(ClassUnit.homeroom_teacher_id == t.id).first()
    }
    assert set(homerooms.values()) == {11, 13}
    assert sum(1 for v in homerooms.values() if v == 11) == 5   # 國文科導師


def test_admin_reduction_produces_the_regulated_target(admin_client):
    """兼任主任應授 6 節、組長 8 節(18-26 班),存的是 base - reduction。"""
    client, db = admin_client
    client.post("/api/demo-data")
    targets = {
        t.admin_title: t.base_periods - t.admin_reduction
        for t in db.query(Teacher).filter(Teacher.admin_title.isnot(None)).all()
    }
    assert targets, "沒有任何兼行政教師"
    for title, target in targets.items():
        expected = 6 if title.endswith("主任") else 8
        assert target == expected, f"{title} 應授 {target},應為 {expected}"


def test_subjects_are_split_not_domain_level(admin_client):
    """自然科依年級分科:國一生物、國二理化、國三理化+地科。"""
    client, db = admin_client
    body = client.post("/api/demo-data").json()
    sid = body["semester_id"]
    rows = db.query(CourseAssignment).filter(CourseAssignment.semester_id == sid).all()
    by_grade: dict[int, set[str]] = {}
    for a in rows:
        for m in a.scheduling_unit.members:
            by_grade.setdefault(m.class_unit.grade, set()).add(a.subject.name)
    assert "生物" in by_grade[7] and "理化" not in by_grade[7]
    assert "理化" in by_grade[8] and "生物" not in by_grade[8]
    assert {"理化", "地球科學"} <= by_grade[9]
    # 本土語文自 111 學年度起為七、八年級部定,九年級不排
    assert "本土語文" in by_grade[7] and "本土語文" not in by_grade[9]


# ── 安全機制 ────────────────────────────────────────


def test_refuses_when_a_semester_already_exists(admin_client):
    client, _ = admin_client
    assert client.post("/api/demo-data").status_code == 201
    again = client.post("/api/demo-data")
    assert again.status_code == 409
    assert "已有學期資料" in again.json()["detail"]


def test_status_endpoint_reflects_availability(admin_client):
    client, _ = admin_client
    assert client.get("/api/demo-data").json()["available"] is True
    client.post("/api/demo-data")
    after = client.get("/api/demo-data").json()
    assert after["available"] is False and after["reason"]


def test_non_admin_cannot_load_demo_data(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    assert client.post("/api/demo-data").status_code == 403


# ── 最重要的一支:示範資料排得出來嗎 ──────────────────
# 示範資料若無解,比沒有示範資料更糟:使用者第一次按「自動排課」就看到失敗,
# 而他還沒有能力判斷是自己弄錯還是系統不行。


def test_demo_data_is_actually_solvable(admin_client):
    """以純硬約束求解:要證明的是「有解」,軟約束只影響品質不影響可行性。

    實測本機約 10 秒得到 optimal。走完整軟約束是 anytime 求解,會用滿時間預算
    去磨品質(60 秒 objective 從 792 降到 283),放進 CI 只是浪費幾分鐘。
    """
    from app.services.solver_data import load_problem
    from app.solver import preflight
    from app.solver.model_builder import SolveOptions, solve
    from app.solver.problem import SolverConfig
    from app.solver.validator import validate

    client, db = admin_client
    sid = client.post("/api/demo-data").json()["semester_id"]

    problem = load_problem(db, sid)
    errors = preflight.run(problem).errors
    assert not errors, f"pre-flight 就擋下來了:{[(i.code, i.message) for i in errors]}"

    result = solve(
        problem, SolveOptions(max_seconds=120, workers=4), config=SolverConfig.hard_only()
    )
    assert result.status in ("optimal", "feasible"), (
        f"示範資料排不出課表(status={result.status})——"
        "這代表使用者第一次按自動排課就會失敗"
    )
    assert not validate(problem, result.entries), "解答違反硬約束"
    # H8 週節數守恆:排入的節數必須等於配課總節數
    assert len(result.entries) == 33 * 18
