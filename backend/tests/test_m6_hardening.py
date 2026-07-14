"""M6-5:小型加固批次的回歸測試。

① 同學期班名唯一(API 409、匯入擋下、遷移對既有重複資料先去重)
② /api/docs 正式環境預設關閉
④ 衝突定位期間可取消
⑥ 清單查詢的伺服器端保護性上限
(③ 主色對比由 e2e 的 a11y.spec 驗;⑤ 已於 M6-3 完成)
"""

import pytest

from app.models.user import Role
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED, WED2

PW = "password123"


@pytest.fixture
def school(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
    }).json()["id"]
    return client, db, sid


def _class(client, sid, name, grade=3):
    return client.post(f"/api/class-units?semester_id={sid}",
                       json={"grade": grade, "name": name, "track": "junior_high"})


# ── ① 同學期班名唯一 ────────────────────────────────────────
def test_duplicate_class_name_in_the_same_semester_is_rejected(school):
    """衝突訊息、課表、匯出都以班名指稱班級——兩個「301」會讓組長分不出是哪一班。"""
    client, _db, sid = school
    assert _class(client, sid, "301").status_code == 201
    r = _class(client, sid, "301")
    assert r.status_code == 409
    assert "301" in r.json()["detail"]


def test_the_same_class_name_in_another_semester_is_fine(school):
    """唯一性只在學期內:每年都會有 301。"""
    client, _db, sid = school
    assert _class(client, sid, "301").status_code == 201
    other = client.post("/api/semesters", json={"academic_year": 116, "term": 1}).json()["id"]
    assert _class(client, other, "301").status_code == 201


def test_renaming_a_class_onto_an_existing_name_is_rejected(school):
    client, _db, sid = school
    a = _class(client, sid, "301").json()
    _class(client, sid, "302")
    r = client.patch(f"/api/class-units/{a['id']}",
                     json={"grade": 3, "name": "302", "track": "junior_high"})
    assert r.status_code == 409


def test_renaming_a_class_to_its_own_name_is_fine(school):
    """改別的欄位時班名沒變,不該被自己擋下來。"""
    client, _db, sid = school
    a = _class(client, sid, "301").json()
    r = client.patch(f"/api/class-units/{a['id']}",
                     json={"grade": 3, "name": "301", "track": "junior_high",
                           "student_count": 30})
    assert r.status_code == 200
    assert r.json()["student_count"] == 30


# ── ② /api/docs 預設關閉 ────────────────────────────────────
def test_api_docs_are_off_by_default(env):
    """端點都有權限守著,公開它不是漏洞,但沒必要把整套內部 API 攤在網路上。"""
    client, _db = env
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_api_docs_can_be_switched_on():
    """需要串接 API 時可用 .env 打開(開發用 compose 預設帶開)。"""
    from app.core.config import Settings

    assert Settings().api_docs_enabled is False
    assert Settings(api_docs_enabled=True).api_docs_enabled is True


# ── ④ 衝突定位期間可取消 ────────────────────────────────────
def test_explain_raises_cancelled_when_asked_to_stop(db):
    """定位最長跑一分鐘。先前完全不看取消旗標,使用者按了取消只能乾等,
    最後還收到一份他已經不想要的 failed 報告。"""
    from app.services.solver_data import load_problem
    from app.solver import conflict_explainer as ce
    from tests.fixtures import build_junior_high_mid

    problem = load_problem(db, build_junior_high_mid(db).semester_id)

    with pytest.raises(ce.Cancelled):
        ce.explain(problem, max_seconds=30, should_stop=lambda: True)


def test_explain_without_a_stop_signal_runs_to_completion(db):
    from app.services.solver_data import load_problem
    from app.solver import conflict_explainer as ce
    from tests.fixtures import build_junior_high_mid

    problem = load_problem(db, build_junior_high_mid(db).semester_id)
    report = ce.explain(problem, max_seconds=30)
    assert report.status in ("feasible", "infeasible", "unknown")


# ── ⑥ 清單查詢的保護性上限 ──────────────────────────────────
def test_substitution_log_query_applies_the_limit_in_sql(env):
    """不篩選地查一整年會是數千筆;不設限就整包拉進記憶體再序列化。

    以 limit=1 驗證上限真的下到 SQL(而不只是個沒人用的參數)。
    """
    from app.services import substitution_log as log_service
    from tests.test_substitutions import _World

    client, db = env
    make_user(db, "s2", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s2", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 117, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    w = _World(client, db, sid)
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "國文", "702", 1)
    w.publish()
    w.leave("王師")  # 同一天兩節受影響

    assert len(log_service.query(db, sid)) == 2               # 預設上限之內,全拿
    assert len(log_service.query(db, sid, limit=1)) == 1      # 上限確實下到 SQL
    assert log_service.MAX_ROWS == 1000


def test_leaves_list_applies_the_limit(school, monkeypatch):
    from app.api import leaves as leaves_api

    client, _db, sid = school
    assert leaves_api.MAX_LEAVE_ROWS == 1000
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()
    client.patch(f"/api/semesters/{sid}",
                 json={"start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat()})
    for day in (WED, WED2):
        client.post(f"/api/leaves?semester_id={sid}", json={
            "teacher_id": t["id"], "leave_type": "sick",
            "start_date": day.isoformat(), "end_date": day.isoformat()})
    assert len(client.get(f"/api/leaves?semester_id={sid}").json()) == 2

    monkeypatch.setattr(leaves_api, "MAX_LEAVE_ROWS", 1)
    assert len(client.get(f"/api/leaves?semester_id={sid}").json()) == 1
