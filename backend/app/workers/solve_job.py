"""自動排課的背景任務(RQ)。

**輸入輸出流**(tasks.md M3-4 補遺):
- 以「來源草稿」為輸入:其 `locked` 格位是硬約束(H9),未鎖定的格位餵成求解提示,
  讓重排時盡量少動已排好的課。
- 結果寫成**新草稿**「{來源名} 自排結果」,來源草稿完全不動——排壞了隨時可以丟掉。
- 鎖定狀態隨結果一起複製。

求解跑在獨立的 worker 容器,不阻塞 Web(architecture.md §3.3)。
"""

import time
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.solver_data import load_config, load_problem
from app.solver import report as soft_report
from app.solver.model_builder import SolveControl, SolveOptions, SolveProgress, solve
from app.solver.problem import SolvedEntry
from app.workers.progress import (
    ControlAction,
    JobStatus,
    ProgressStore,
    RedisProgressStore,
)

RESULT_SUFFIX = "自排結果"


def run_auto_schedule(
    job_id: str,
    timetable_id: int,
    max_seconds: float,
    seed: int,
    user_id: int | None,
    username: str,
) -> None:
    """RQ 進入點。任何例外都必須落到 job 狀態上,否則前端只會看到永遠的轉圈。"""
    from app.core.db import SessionLocal
    from app.workers.queue import redis_conn

    store = RedisProgressStore(redis_conn)
    db = SessionLocal()
    try:
        execute(db, store, job_id, timetable_id, max_seconds, seed, user_id, username)
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
) -> None:
    """實際流程。與 RQ 解耦,測試可直接呼叫(記憶體版 store + 測試 session)。"""
    source = db.get(Timetable, timetable_id)
    if source is None:
        store.update(job_id, status=JobStatus.failed.value, error="找不到來源課表",
                     heartbeat=time.time())
        return

    problem = load_problem(db, source.semester_id, source)
    config = load_config(db, source.semester_id)

    store.update(job_id, status=JobStatus.running.value, heartbeat=time.time())

    def on_progress(p: SolveProgress) -> None:
        store.update(job_id, solutions=p.solutions, objective=p.objective,
                     elapsed=p.elapsed, heartbeat=time.time())

    def on_tick(elapsed: float) -> None:
        store.update(job_id, elapsed=elapsed, heartbeat=time.time())

    def should_stop() -> bool:
        return store.requested(job_id) is not None

    result = solve(
        problem,
        SolveOptions(max_seconds=max_seconds, workers=4, random_seed=seed),
        config=config,
        control=SolveControl(on_progress=on_progress, on_tick=on_tick, should_stop=should_stop),
    )

    if store.requested(job_id) == ControlAction.cancel:
        store.update(job_id, status=JobStatus.cancelled.value, heartbeat=time.time(),
                     error=None)
        return

    if not result.solved:
        store.update(
            job_id, status=JobStatus.failed.value, heartbeat=time.time(),
            error=_failure_message(result.status),
        )
        return

    new = write_result(db, source, result.entries, user_id, username, result.objective)
    rep = soft_report.evaluate(problem, result.entries, config)
    db.commit()

    store.update(
        job_id, status=JobStatus.finished.value, heartbeat=time.time(),
        elapsed=result.wall_time, objective=result.objective,
        result_timetable_id=new.id, result_name=new.name,
        report=_serialize_report(rep),
    )


def _failure_message(status: str) -> str:
    if status == "infeasible":
        return "在現有條件下無解。請先看 pre-flight 檢查報告,或放寬教師不可排時段。"
    if status == "unknown":
        return "時間內找不到任何可行解。請延長排課時間,或先修正 pre-flight 的警告。"
    return f"求解失敗({status})"


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
) -> Timetable:
    """把求解結果寫成新草稿。來源草稿不動。呼叫端負責 commit。"""
    name = _unique_name(db, source.semester_id, f"{source.name} {RESULT_SUFFIX}")
    new = Timetable(
        semester_id=source.semester_id, name=name, status=TimetableStatus.draft.value
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
            f"自動排課由「{source.name}」產出「{name}」"
            f",共 {len(entries)} 格,軟約束目標值 {objective:.0f}"
        )[:500],
    ))
    db.flush()
    return new
