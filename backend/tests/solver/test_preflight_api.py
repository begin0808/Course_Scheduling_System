"""M3-1:pre-flight 檢查報告 API(GET /api/solver/preflight)。"""

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


def _login(client, db, username="s", roles=(Role.scheduler,)):
    make_user(db, username, PW, roles=list(roles))
    client.post("/api/auth/login", json={"username": username, "password": PW})


def _setup(client, sid, *, periods):
    c = client.post(
        f"/api/class-units?semester_id={sid}",
        json={"grade": 3, "name": "301", "track": "junior_high"},
    ).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(
        f"/api/teachers?semester_id={sid}", json={"name": "王師", "base_periods": 20}
    ).json()
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": periods,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })
    return c, s, t


def test_preflight_ok(env):
    client, db = env
    _login(client, db)
    sid = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()["id"]
    _setup(client, sid, periods=20)

    r = client.get(f"/api/solver/preflight?semester_id={sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["error_count"] == 0
    assert body["class_count"] == 1 and body["teacher_count"] == 1
    assert body["assignment_count"] == 1 and body["total_periods"] == 20
    assert body["semester_label"] == "115 學年度第 1 學期"


def test_preflight_reports_class_overload(env):
    client, db = env
    _login(client, db)
    sid = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()["id"]
    _setup(client, sid, periods=40)  # 40 > 35 可排節次,且超出王師應授鐘點

    body = client.get(f"/api/solver/preflight?semester_id={sid}").json()
    assert body["ok"] is False
    codes = {i["code"] for i in body["issues"]}
    assert "class_overload" in codes
    assert "teacher_overload" in codes  # 40 節 > 35 格
    assert "teacher_over_hours" in codes
    # error 排在 warning 之前
    assert body["issues"][0]["level"] == "error"
    assert body["warning_count"] >= 1

    overload = next(i for i in body["issues"] if i["code"] == "teacher_overload")
    assert overload["detail"] == {"assigned": 40, "available": 35, "unavailable": 0}


def test_preflight_unknown_semester_404(env):
    client, db = env
    _login(client, db)
    assert client.get("/api/solver/preflight?semester_id=9999").status_code == 404


def test_preflight_requires_scheduler(env):
    client, db = env
    _login(client, db, username="t", roles=(Role.teacher,))
    sid = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).status_code
    assert sid == 403  # teacher 連建學期都不行
    assert client.get("/api/solver/preflight?semester_id=1").status_code == 403
