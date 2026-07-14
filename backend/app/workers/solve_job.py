"""自動排課的背景任務(RQ)。

**輸入輸出流**(tasks.md M3-4 補遺):
- 以「來源草稿」為輸入:其 `locked` 格位是硬約束(H9),未鎖定的格位餵成求解提示,
  讓重排時盡量少動已排好的課。
- 結果寫成**新草稿**「{來源名} 自排結果」,來源草稿完全不動——排壞了隨時可以丟掉。
- 鎖定狀態隨結果一起複製。

**無解時**(M3-5)不只回一句「排不出來」:接著跑衝突定位,告訴教學組長是哪幾件事
湊在一起、鬆開哪一個就好了。定位本身也要送心跳,否則會被誤判成 worker 死掉。

求解跑在獨立的 worker 容器,不阻塞 Web(architecture.md §3.3)。
"""

import threading
import time
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.solver_data import load_config, load_problem
from app.solver import conflict_explainer
from app.solver import report as soft_report
from app.solver.model_builder import (
    Relaxation,
    SolveControl,
    SolveOptions,
    SolveProgress,
    SolverInputError,
    UnscheduledCourse,
    solve,
)
from app.solver.problem import Problem, SolvedEntry, SolverConfig
from app.workers.progress import (
    ControlAction,
    JobPhase,
    JobStatus,
    ProgressStore,
    RedisProgressStore,
)

RESULT_SUFFIX = "自排結果"
PARTIAL_SUFFIX = "部分排課結果"
HEARTBEAT_SECONDS = 2.0
# 衝突定位的時間預算。使用者已經等過一輪求解,不能再讓他等十分鐘才知道原因。
EXPLAIN_SECONDS = 60.0


def run_auto_schedule(
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None,
    username: str,
    allow_partial: bool = False,
    relax: Sequence[str] = (),
) -> None:
    """RQ 進入點。任何例外都必須落到 job 狀態上,否則前端只會看到永遠的轉圈。"""
    from app.core.db import SessionLocal
    from app.workers.queue import redis_conn

    store = RedisProgressStore(redis_conn)
    db = SessionLocal()
    try:
        execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username,
                allow_partial, relax)
    except Exception as exc:  # noqa: BLE001 - worker 邊界:一律轉為可見的失敗狀態
        db.rollback()
        store.update(
            job_id, status=JobStatus.failed.value,
            error=f"排課過程發生錯誤:{exc}"[:300], heartbeat=time.time(),
        )
    finally:
        db.close()


def execute(
    db: Session,
    store: ProgressStore,
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None = None,
    username: str = "system",
    allow_partial: bool = False,
    relax: Sequence[str] = (),
) -> None:
    """實際流程。與 RQ 解耦,測試可直接呼叫(記憶體版 store + 測試 session)。"""
    source = db.get(Timetable, timetable_id)
    if source is None:
        store.update(job_id, status=JobStatus.failed.value, error="找不到來源課表",
                     heartbeat=time.time())
        return

    problem = load_problem(db, source.semester_id, source)
    config = load_config(db, source.semester_id)
    relaxation = Relaxation(soft_codes=frozenset(relax)) if allow_partial else None

    store.update(job_id, status=JobStatus.running.value, partial=allow_partial,
                 phase=JobPhase.solving.value, heartbeat=time.time())

    def on_progress(p: SolveProgress) -> None:
        store.update(job_id, solutions=p.solutions, objective=p.objective,
                     elapsed=p.elapsed, heartbeat=time.time())

    def on_tick(elapsed: float) -> None:
        store.update(job_id, elapsed=elapsed, heartbeat=time.time())

    def should_stop() -> bool:
        return store.requested(job_id) is not None

    try:
        result = solve(
            problem,
            SolveOptions(max_seconds=max_seconds, workers=4, random_seed=seed),
            config=config,
            control=SolveControl(on_progress=on_progress, on_tick=on_tick,
                                 should_stop=should_stop),
            relax=relaxation,
        )
    except SolverInputError as exc:
        # 建模階段就攔下來(某門課完全沒有可排的位置)。這也是一種無解,要說得出原因。
        _fail_with_conflict(store, job_id, problem, config, str(exc))
        return

    if store.requested(job_id) == ControlAction.cancel:
        store.update(job_id, status=JobStatus.cancelled.value, heartbeat=time.time(),
                     error=None)
        return

    if not result.solved:
        # 逾時而一個解都沒有,往往其實是無解——只是帶著軟約束目標函數時,CP-SAT 很難
        # 證明這件事(實測:同一份資料純硬約束 1 秒證完,加上目標函數 60 秒證不完)。
        # 一律跑一次衝突定位:它以純硬約束求解,能分辨「不可能」與「只是慢」。
        _fail_with_conflict(store, job_id, problem, config, _failure_message(result.status))
        return

    new = write_result(db, source, result.entries, user_id, username, result.objective,
                       partial=allow_partial, unplaced=result.unplaced_periods,
                       unscheduled=result.unscheduled)
    rep = soft_report.evaluate(problem, result.entries, config)
    db.commit()

    store.update(
        job_id, status=JobStatus.finished.value, heartbeat=time.time(),
        elapsed=result.wall_time, objective=result.objective,
        result_timetable_id=new.id, result_name=new.name,
        report=_serialize_report(rep),
        unscheduled=[_serialize_unscheduled(u) for u in result.unscheduled],
    )


@contextmanager
def _heartbeat(store: ProgressStore, job_id: str) -> Generator[None]:
    """在一段沒有進度回報的長工作期間持續送心跳。

    衝突定位可能跑上一分鐘。少了心跳,API 會在 30 秒後判定 worker 已死,
    使用者就永遠看不到那份好不容易算出來的原因報告。
    """
    done = threading.Event()

    def beat() -> None:
        while not done.wait(HEARTBEAT_SECONDS):
            store.update(job_id, heartbeat=time.time())

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=HEARTBEAT_SECONDS + 1)


def _fail_with_conflict(
    store: ProgressStore, job_id: str, problem: Problem, config: SolverConfig, message: str
) -> None:
    store.update(job_id, phase=JobPhase.explaining.value, heartbeat=time.time())
    with _heartbeat(store, job_id):
        report = conflict_explainer.explain(problem, config=config,
                                            max_seconds=EXPLAIN_SECONDS)

    if report.status == "feasible":
        # 硬約束其實排得出來,是軟約束的最佳化太慢。這兩件事的處置完全不同。
        error = "排課時間內沒找到解,但這份資料確實排得出來。請延長排課時間,或降低軟約束權重。"
    else:
        error = report.headline or message

    store.update(
        job_id, status=JobStatus.failed.value, heartbeat=time.time(),
        phase=JobPhase.solving.value,
        error=error,
        conflict=_serialize_conflict(report),
    )


def _failure_message(status: str) -> str:
    if status == "infeasible":
        return "在現有條件下無解。"
    if status == "unknown":
        return "時間內找不到任何可行解。請延長排課時間,或改用部分排課。"
    return f"求解失敗({status})"


def _serialize_conflict(rep: conflict_explainer.ConflictReport) -> dict:
    return {
        "status": rep.status,
        "source": rep.source,
        "mode": rep.mode,
        "headline": rep.headline,
        "complete": rep.complete,
        "relaxable_codes": list(rep.relaxable_codes),
        "causes": [asdict(c) for c in rep.causes],
    }


def _serialize_unscheduled(u: UnscheduledCourse) -> dict:
    return {
        **asdict(u),
        "assignment_ids": list(u.assignment_ids),
        "class_names": list(u.class_names),
    }


def _serialize_report(rep: soft_report.SoftReport) -> dict:
    return {
        "total_penalty": rep.total_penalty,
        "items": [
            {**asdict(i), "satisfied": i.satisfied, "rate": i.rate, "penalty": i.penalty,
             "details": list(i.details)}
            for i in rep.items
        ],
    }


def _unique_name(db: Session, semester_id: int, base: str) -> str:
    existing = set(
        db.scalars(select(Timetable.name).where(Timetable.semester_id == semester_id))
    )
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def write_result(
    db: Session,
    source: Timetable,
    entries: tuple[SolvedEntry, ...],
    user_id: int | None,
    username: str,
    objective: float,
    *,
    partial: bool = False,
    unplaced: int = 0,
    unscheduled: tuple[UnscheduledCourse, ...] = (),
) -> Timetable:
    """把求解結果寫成新草稿。來源草稿不動。呼叫端負責 commit。

    未排清單隨草稿存進 DB(M6-3):它先前只活在 Redis 24h,草稿一旦被 force 發布,
    solver 講的「為什麼排不下」就永遠遺失。
    """
    suffix = PARTIAL_SUFFIX if partial else RESULT_SUFFIX
    name = _unique_name(db, source.semester_id, f"{source.name} {suffix}")
    new = Timetable(
        semester_id=source.semester_id, name=name, status=TimetableStatus.draft.value,
        unscheduled=[_serialize_unscheduled(u) for u in unscheduled] or None,
    )
    db.add(new)
    db.flush()
    for e in entries:
        db.add(ScheduleEntry(
            timetable_id=new.id, course_assignment_id=e.assignment_id,
            weekday=e.weekday, period_no=e.period_no, span=e.span,
            room_id=e.room_id, locked=e.locked,
        ))
    db.add(AuditLog(
        user_id=user_id, username=username, action="auto_schedule",
        target_type="timetable", target_id=new.id,
        detail=(
            f"{'部分排課' if partial else '自動排課'}由「{source.name}」產出「{name}」"
            f",共 {len(entries)} 格,軟約束目標值 {objective:.0f}"
            + (f",未排入 {unplaced} 節" if unplaced else "")
        )[:500],
    ))
    db.flush()
    return new
