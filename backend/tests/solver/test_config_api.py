"""M3-3:軟約束權重設定(GET/PUT /api/solver/config)。"""

from app.models.user import Role
from app.services.solver_data import load_config
from app.solver.problem import DEFAULT_WEIGHTS
from tests.conftest import make_user

PW = "password123"


def _login(client, db, username="s", roles=(Role.scheduler,)):
    make_user(db, username, PW, roles=list(roles))
    client.post("/api/auth/login", json={"username": username, "password": PW})


def _semester(client):
    return client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()["id"]


def test_get_returns_defaults_for_untouched_semester(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    body = client.get(f"/api/solver/config?semester_id={sid}").json()
    assert body["weights"] == DEFAULT_WEIGHTS
    assert body["daily_subject_cap"] == 2
    assert body["teacher_daily_max"] == 6
    assert body["teacher_consecutive_max"] == 3
    assert body["weight_names"]["S2"] == "同班同科目分散於不同日"


def test_put_persists_and_zero_weight_disables(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    r = client.put(f"/api/solver/config?semester_id={sid}", json={
        "daily_subject_cap": 3, "teacher_daily_max": 5, "teacher_consecutive_max": 2,
        "weights": {"S2": 0, "S5": 10},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["weights"]["S2"] == 0 and body["weights"]["S5"] == 10
    assert body["weights"]["S1"] == DEFAULT_WEIGHTS["S1"]  # 未指定者維持預設

    again = client.get(f"/api/solver/config?semester_id={sid}").json()
    assert again["daily_subject_cap"] == 3
    assert again["teacher_daily_max"] == 5
    assert again["weights"]["S2"] == 0

    config = load_config(db, sid)
    assert config.enabled("S2") is False
    assert config.weight("S5") == 10
    assert config.daily_subject_cap == 3


def test_put_is_idempotent(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)
    payload = {"daily_subject_cap": 2, "teacher_daily_max": 6,
               "teacher_consecutive_max": 3, "weights": {"S4": 0}}
    first = client.put(f"/api/solver/config?semester_id={sid}", json=payload).json()
    second = client.put(f"/api/solver/config?semester_id={sid}", json=payload).json()
    assert first == second


def test_put_rejects_unknown_code_and_negative_weight(env):
    client, db = env
    _login(client, db)
    sid = _semester(client)

    r = client.put(f"/api/solver/config?semester_id={sid}", json={"weights": {"S9": 1}})
    assert r.status_code == 400 and "S9" in r.json()["detail"]

    r = client.put(f"/api/solver/config?semester_id={sid}", json={"weights": {"S1": -1}})
    assert r.status_code == 400


def test_config_requires_scheduler_to_write(env):
    client, db = env
    _login(client, db, username="d", roles=(Role.director,))
    # director 不能建學期,借用 admin 建好的?此處僅驗權限:director 可讀不可寫
    assert client.get("/api/solver/config?semester_id=1").status_code in (403, 404)
    assert client.put("/api/solver/config?semester_id=1", json={"weights": {}}).status_code == 403


def test_unknown_semester_404(env):
    client, db = env
    _login(client, db)
    assert client.get("/api/solver/config?semester_id=9999").status_code == 404
    assert client.put("/api/solver/config?semester_id=9999",
                      json={"weights": {}}).status_code == 404
