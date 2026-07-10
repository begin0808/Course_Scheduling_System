"""M3-4:自動排課任務、進度回報、提前結束/取消、worker 失聯。

以「假佇列」取代 RQ:enqueue 時直接同步執行 `solve_job.execute`,測試不需要
Redis 也不需要 worker 容器。真實的 RQ 派送在 docker compose 上另行實測。
"""

import time

import pytest

from app.api import solver as solver_api
from app.models.timetable import ScheduleEntry, Timetable
from app.models.user import Role
from app.services.solver_data import load_problem
from app.solver.model_builder import SolveControl, SolveOptions, SolveProgress, solve
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from app.workers import queue as job_queue
from app.workers import solve_job
from app.workers.progress import (
    ControlAction,
    InMemoryProgressStore,
    JobState,
    JobStatus,
)
from tests.conftest import make_user
from tests.fixtures import build_junior_high_mid

PW = "password123"


@pytest.fixture
def sched(env, monkeypatch):
    """已登入教學組長 + 國中範本學期 + 一份草稿 + 記憶體版進度儲存 + 假佇列。

    回傳 (client, db, sid, timetable_id, store, calls)。
    """
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    store = InMemoryProgressStore()
    client.app.dependency_overrides[solver_api.get_progress_store] = lambda: store

    calls: list[tuple] = []

    def fake_enqueue(job_id, timetable_id, max_seconds, seed, user_id, username,
                     allow_partial=False, relax=()):
        calls.append((job_id, timetable_id, max_seconds, seed))
        solve_job.execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username,
                          allow_partial, relax)

    monkeypatch.setattr(job_queue, "enqueue_solve", fake_enqueue)

    sid = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()["id"]
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    return client, db, sid, tt["id"], store, calls


def _seed_courses(client, sid, *, periods=4):
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    out = []
    for subject, teacher in (("國文", "王師"), ("數學", "李師")):
        s = client.post(f"/api/subjects?semester_id={sid}", json={"name": subject}).json()
        t = client.post(f"/api/teachers?semester_id={sid}",
                        json={"name": teacher, "base_periods": 20}).json()
        a = client.post(f"/api/assignments?semester_id={sid}", json={
            "class_id": c["id"], "subject_id": s["id"], "periods_per_week": periods,
            "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        }).json()
        out.append(a)
    return c, out


def _start(client, tid, **body):
    return client.post(f"/api/timetables/{tid}/auto-schedule",
                       json={"max_seconds": 20, "seed": 1, **body})


# ── 驗收①(後端面):啟動 → 進度 → 結果草稿 ────────────────────
def test_auto_schedule_writes_result_draft(sched):
    client, db, sid, tid, store, calls = sched
    _seed_courses(client, sid, periods=4)

    r = _start(client, tid)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert calls and calls[0][1] == tid

    body = client.get(f"/api/solver/jobs/{job_id}").json()
    assert body["status"] == JobStatus.finished.value
    assert body["error"] is None
    assert body["result_timetable_id"] is not None
    assert body["result_name"] == "草稿A 自排結果"
    assert body["solutions"] >= 1
    assert body["report"]["items"][0]["code"] == "S1"

    # 結果草稿排滿 8 節;來源草稿完全不動
    result_id = body["result_timetable_id"]
    entries = db.query(ScheduleEntry).filter_by(timetable_id=result_id).all()
    assert sum(e.span for e in entries) == 8
    assert db.query(ScheduleEntry).filter_by(timetable_id=tid).count() == 0
    assert db.get(Timetable, result_id).status == "draft"


def test_result_name_is_unique(sched):
    client, db, sid, tid, store, _calls = sched
    _seed_courses(client, sid, periods=2)
    first = client.get(
        f"/api/solver/jobs/{_start(client, tid).json()['job_id']}").json()["result_name"]
    second = client.get(
        f"/api/solver/jobs/{_start(client, tid).json()['job_id']}").json()["result_name"]
    assert first == "草稿A 自排結果"
    assert second == "草稿A 自排結果 2"


def test_locked_entries_are_pinned_and_copied(sched):
    client, db, sid, tid, store, _calls = sched
    _seed_courses(client, sid, periods=4)
    a = client.get(f"/api/assignments?semester_id={sid}").json()[0]

    # 在來源草稿鎖定一格(國中範本:週三第一節 = period_no 2)
    client.post(f"/api/timetables/{tid}/entries",
                json={"course_assignment_id": a["id"], "weekday": 3, "period_no": 2, "span": 1})
    entry_id = client.get(f"/api/timetables/{tid}").json()["entries"][0]["id"]
    client.post(f"/api/timetables/{tid}/entries/{entry_id}/lock?locked=true")

    job_id = _start(client, tid).json()["job_id"]
    result_id = client.get(f"/api/solver/jobs/{job_id}").json()["result_timetable_id"]

    entries = db.query(ScheduleEntry).filter_by(timetable_id=result_id).all()
    pinned = [e for e in entries if e.locked]
    assert len(pinned) == 1
    assert (pinned[0].weekday, pinned[0].period_no) == (3, 2)
    assert pinned[0].course_assignment_id == a["id"]


# ── 驗收①:提前結束取當前最佳解 ─────────────────────────────
def test_solver_stop_returns_best_solution_so_far(db):
    """在真正需要時間收斂的問題上(12 班國中),提前結束要拿得到「當下最佳解」。

    這裡才驗得出 stop 的語意:solver 尚未證明最佳(status=feasible),但解已完整且
    零硬約束違反——不是丟棄,也不是半張課表。
    """
    fx = build_junior_high_mid(db)
    problem = load_problem(db, fx.semester_id)

    seen: list[SolveProgress] = []
    result = solve(
        problem,
        SolveOptions(max_seconds=120.0, workers=4, random_seed=1),
        control=SolveControl(
            on_progress=seen.append,
            should_stop=lambda: len(seen) >= 1,  # 找到第一個解就喊停
        ),
    )

    assert seen, "至少要找到一個解才談得上提前結束"
    assert result.status == "feasible", "提前結束 → 未證明最佳,但有解"
    assert result.entries and not validate(problem, result.entries)
    assert result.wall_time < 60, f"應在找到第一個解後很快停止,實得 {result.wall_time:.1f}s"


def test_stop_keeps_best_solution(sched, monkeypatch):
    client, db, sid, tid, store, _calls = sched
    _seed_courses(client, sid, periods=4)

    # 求解一開始就要求提前結束 → 第一個解出現即停,仍寫出結果草稿
    def enqueue_then_stop(job_id, timetable_id, max_seconds, seed, user_id, username,
                          allow_partial=False, relax=()):
        store.request(job_id, ControlAction.stop)
        solve_job.execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username)

    monkeypatch.setattr(job_queue, "enqueue_solve", enqueue_then_stop)

    job_id = _start(client, tid).json()["job_id"]
    body = client.get(f"/api/solver/jobs/{job_id}").json()
    assert body["status"] == JobStatus.finished.value
    assert body["result_timetable_id"] is not None
    assert body["solutions"] >= 1


def test_cancel_discards_result(sched, monkeypatch):
    client, db, sid, tid, store, _calls = sched
    _seed_courses(client, sid, periods=4)

    def enqueue_then_cancel(job_id, timetable_id, max_seconds, seed, user_id, username,
                            allow_partial=False, relax=()):
        store.request(job_id, ControlAction.cancel)
        solve_job.execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username)

    monkeypatch.setattr(job_queue, "enqueue_solve", enqueue_then_cancel)

    job_id = _start(client, tid).json()["job_id"]
    body = client.get(f"/api/solver/jobs/{job_id}").json()
    assert body["status"] == JobStatus.cancelled.value
    assert body["result_timetable_id"] is None
    assert db.query(Timetable).filter_by(semester_id=sid).count() == 1  # 只有來源草稿


def test_stop_endpoint_marks_request(sched):
    client, db, sid, tid, store, _calls = sched
    state = JobState(job_id="j1", status=JobStatus.running.value, semester_id=sid,
                     source_timetable_id=tid, source_name="草稿A", max_seconds=60)
    store.create(state)

    assert client.post("/api/solver/jobs/j1/stop").status_code == 200
    assert store.requested("j1") == ControlAction.stop

    assert client.post("/api/solver/jobs/j1/cancel").status_code == 200
    assert store.requested("j1") == ControlAction.cancel


def test_control_on_finished_job_is_noop(sched):
    client, db, sid, tid, store, _calls = sched
    store.create(JobState(job_id="j2", status=JobStatus.finished.value, semester_id=sid,
                          source_timetable_id=tid, source_name="草稿A", max_seconds=60))
    client.post("/api/solver/jobs/j2/cancel")
    assert store.requested("j2") is None


# ── 驗收③:worker 被 kill → 明確錯誤,而非永遠轉圈 ────────────
def test_stale_running_job_is_reported_as_failed(sched):
    client, db, sid, tid, store, _calls = sched
    store.create(JobState(
        job_id="dead", status=JobStatus.running.value, semester_id=sid,
        source_timetable_id=tid, source_name="草稿A", max_seconds=600,
        heartbeat=time.time() - 120,  # 心跳停了兩分鐘
    ))

    body = client.get("/api/solver/jobs/dead").json()
    assert body["status"] == JobStatus.failed.value
    assert "工作程序中斷" in body["error"]
    assert store.get("dead").status == JobStatus.failed.value  # 狀態已落盤,不會反覆判定


def test_queued_job_waiting_in_line_is_not_stale(sched):
    client, db, sid, tid, store, _calls = sched
    store.create(JobState(
        job_id="waiting", status=JobStatus.queued.value, semester_id=sid,
        source_timetable_id=tid, source_name="草稿A", max_seconds=600,
        heartbeat=time.time() - 120,  # 排在別的排課後面,還沒輪到
    ))
    assert client.get("/api/solver/jobs/waiting").json()["status"] == JobStatus.queued.value


def test_unknown_job_404(sched):
    client, *_ = sched
    assert client.get("/api/solver/jobs/nope").status_code == 404


# ── 啟動前的守衛 ────────────────────────────────────────────
def test_preflight_errors_block_start(sched):
    client, db, sid, tid, store, calls = sched
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()
    client.post(f"/api/assignments?semester_id={sid}", json={  # 40 節 > 35 可排節次
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 40,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })

    r = _start(client, tid)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "class_overload" in {i["code"] for i in detail["issues"]}
    assert not calls, "pre-flight 不過就不該浪費 worker 的時間"


def test_published_timetable_cannot_be_source(sched):
    client, db, sid, tid, store, _calls = sched
    _seed_courses(client, sid, periods=1)
    tt = db.get(Timetable, tid)
    tt.status = "published"
    db.commit()

    r = _start(client, tid)
    assert r.status_code == 409
    assert "草稿" in r.json()["detail"]


def test_missing_timetable_404(sched):
    client, *_ = sched
    assert _start(client, 9999).status_code == 404


# ── 訊息 ────────────────────────────────────────────────────
def test_failure_messages_are_actionable():
    assert "無解" in solve_job._failure_message("infeasible")
    assert "延長排課時間" in solve_job._failure_message("unknown")


# ── M3-5:無解時的衝突定位與部分排課 ─────────────────────────
def _seed_infeasible(client, sid):
    """301 班國文 12 節單節;每日上限 2 節 × 5 天 = 10 節 → 無解,但 pre-flight 看不出來。"""
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "陳師", "base_periods": 40}).json()
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 12,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })


def test_infeasible_job_carries_a_conflict_report(sched):
    """無解不是句點:任務狀態要帶著「是哪一件事、鬆開它就好了」。"""
    client, _db, sid, tid, _store, _calls = sched
    _seed_infeasible(client, sid)

    assert client.get(f"/api/solver/preflight?semester_id={sid}").json()["ok"]
    r = _start(client, tid, max_seconds=30)
    assert r.status_code == 202

    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()
    assert body["status"] == JobStatus.failed.value
    assert body["phase"] == "solving"  # 定位跑完要把 phase 收回來

    conflict = body["conflict"]
    assert conflict["source"] == "analysis"
    assert conflict["mode"] == "each"
    assert conflict["relaxable_codes"] == ["H10"]
    cause = conflict["causes"][0]
    assert cause["code"] == "H10"
    assert "12" in cause["message"] and "10" in cause["message"]
    assert cause["relaxable"]
    # 錯誤訊息本身就是人話,不是「求解失敗(infeasible)」
    assert "放寬其中任何一項" in body["error"]


def test_partial_mode_places_most_and_lists_the_rest(sched):
    client, db, sid, tid, store, _calls = sched
    _seed_infeasible(client, sid)

    r = _start(client, tid, max_seconds=30, allow_partial=True)
    assert r.status_code == 202
    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()

    assert body["status"] == JobStatus.finished.value
    assert body["partial"] is True
    assert body["result_name"] == "草稿A 部分排課結果"

    unscheduled = body["unscheduled"]
    assert len(unscheduled) == 1
    assert unscheduled[0]["subject_name"] == "國文"
    assert unscheduled[0]["periods"] == 2  # 12 節只排得下 10 節
    assert unscheduled[0]["class_names"] == ["301"]

    result = db.get(Timetable, body["result_timetable_id"])
    assert len(result.entries) == 10


def test_partial_mode_can_relax_the_daily_cap(sched):
    """勾選放寬「每日科目上限」→ 12 節全排入,不再有未排清單。"""
    client, db, sid, tid, _store, _calls = sched
    _seed_infeasible(client, sid)

    r = _start(client, tid, max_seconds=30, allow_partial=True, relax=["H10"])
    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()
    assert body["status"] == JobStatus.finished.value
    assert body["unscheduled"] == []
    assert len(db.get(Timetable, body["result_timetable_id"]).entries) == 12


def test_partial_mode_survives_preflight_overload(sched):
    """班級配課 40 節 > 35 格:一般模式擋下,部分排課放行(少排 5 節)。"""
    client, _db, sid, tid, _store, _calls = sched
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "陳師", "base_periods": 40}).json()
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 40,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })

    blocked = _start(client, tid, max_seconds=20)
    assert blocked.status_code == 409
    assert "class_overload" in str(blocked.json()["detail"]["issues"])

    r = _start(client, tid, max_seconds=30, allow_partial=True, relax=["H10"])
    assert r.status_code == 202
    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()
    assert body["status"] == JobStatus.finished.value
    assert body["unscheduled"][0]["periods"] == 5  # 40 節 − 35 格


def test_structural_preflight_errors_still_block_partial_mode(sched):
    """需要專科教室,但學期裡一間都沒有:少排幾節課也救不了,連模型都建不起來。"""
    client, _db, sid, tid, _store, _calls = sched
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "音樂"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "陳師", "base_periods": 40}).json()
    created = client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 2,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        "required_room_type": "special",
    })
    assert created.status_code == 201, created.json()

    r = _start(client, tid, max_seconds=20, allow_partial=True)
    assert r.status_code == 409
    assert "room_type_supply" in str(r.json()["detail"]["issues"])


def test_relaxable_options_exclude_physical_constraints(sched):
    client, _db, _sid, _tid, _store, _calls = sched
    codes = [o["code"] for o in client.get("/api/solver/relaxable").json()]
    assert codes == ["H4", "H9", "H10"]
    assert not {"H1", "H2", "H3"} & set(codes)


def test_relax_requires_partial_mode(sched):
    client, _db, sid, tid, _store, _calls = sched
    _seed_courses(client, sid, periods=4)

    assert _start(client, tid, relax=["H10"]).status_code == 400
    assert _start(client, tid, allow_partial=True, relax=["H2"]).status_code == 400


def test_timeout_on_a_solvable_problem_says_so(sched):
    """逾時而無解 ≠ 無解。硬約束其實排得出來時,建議必須是「延長時間」而不是「放寬約束」。

    帶著軟約束目標函數時 CP-SAT 常常證不出 INFEASIBLE(實測 60 秒還在跑),
    所以 worker 一律跑一次純硬約束的衝突定位來分辨這兩件事。
    """
    client, db, sid, _tid, store, _calls = sched
    _seed_courses(client, sid, periods=4)

    state = JobState(job_id="j1", status=JobStatus.running.value, semester_id=sid,
                     source_timetable_id=0, source_name="草稿A", max_seconds=10)
    store.create(state)
    problem = load_problem(db, sid)
    solve_job._fail_with_conflict(store, "j1", problem, SolverConfig(), "時間內找不到任何可行解。")

    got = store.get("j1")
    assert got.status == JobStatus.failed.value
    assert "確實排得出來" in got.error
    assert got.conflict["status"] == "feasible"
    assert got.conflict["causes"] == []
