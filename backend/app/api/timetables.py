"""課表 API:草稿 CRUD、格位放入/移動/刪除、鎖定、即時衝突檢查。

放入/移動時以 conflict_checker 驗證硬約束,違反則回 409 並附人話衝突清單。
跑班群組:放入/移動/刪除/鎖定皆連動同群組全部配課(H7 同時段)。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.assignment import CourseAssignment
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable
from app.models.user import Role
from app.schemas.timetable import (
    CheckRequest,
    CheckResponse,
    MoveRequest,
    PlaceRequest,
    ScheduleEntryOut,
    TimetableBrief,
    TimetableCreate,
    TimetableOut,
)
from app.services import conflict_checker as cc

router = APIRouter(tags=["timetables"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def _get_timetable(db: Session, timetable_id: int) -> Timetable:
    tt = db.get(Timetable, timetable_id)
    if tt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到課表")
    return tt


def _get_assignment(db: Session, semester_id: int, assignment_id: int) -> CourseAssignment:
    a = db.get(CourseAssignment, assignment_id)
    if a is None or a.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "配課無效或不屬於本課表學期")
    return a


def _serialize_entry(e: ScheduleEntry) -> ScheduleEntryOut:
    a = e.assignment
    su = a.scheduling_unit
    return ScheduleEntryOut(
        id=e.id, course_assignment_id=e.course_assignment_id,
        weekday=e.weekday, period_no=e.period_no, span=e.span, locked=e.locked,
        subject=a.subject.name,
        teachers=[at.teacher.name for at in a.teachers],
        classes=[m.class_unit.name for m in su.members],
        unit_type=su.unit_type, unit_name=su.name,
        room=a.room.name if a.room else None,
    )


def _conflict_409(conflicts: list[cc.Conflict]) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        detail={
            "message": "與硬約束衝突,無法排入",
            "conflicts": [{"code": c.code, "message": c.message} for c in conflicts],
        },
    )


def _slot_siblings(
    db: Session, timetable_id: int, unit_id: int, weekday: int, period_no: int
) -> list[ScheduleEntry]:
    """同一排課單位在「同一格位」的全部格位。

    跑班群組:該時段開的多門課(H7 須同進同出);單班:即該格本身。
    以格位為範圍而非整個排課單位,否則同班其他科目的格位會被誤連動。
    """
    return list(
        db.scalars(
            select(ScheduleEntry)
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .where(
                ScheduleEntry.timetable_id == timetable_id,
                CourseAssignment.scheduling_unit_id == unit_id,
                ScheduleEntry.weekday == weekday,
                ScheduleEntry.period_no == period_no,
            )
        )
    )


def _placed_periods(db: Session, timetable_id: int, assignment_id: int) -> int:
    """該配課在此課表已排入的節數(連堂以 span 計)。"""
    total = db.scalar(
        select(func.coalesce(func.sum(ScheduleEntry.span), 0)).where(
            ScheduleEntry.timetable_id == timetable_id,
            ScheduleEntry.course_assignment_id == assignment_id,
        )
    )
    return int(total or 0)


# ── 課表草稿 ──────────────────────────
@router.get("/timetables", response_model=list[TimetableBrief])
def list_timetables(
    semester_id: int = Query(...), db: Session = Depends(get_db), _: object = Depends(viewer)
):
    tts = db.scalars(
        select(Timetable).where(Timetable.semester_id == semester_id).order_by(Timetable.id)
    ).all()
    out = []
    for tt in tts:
        n = db.scalar(
            select(func.count()).select_from(ScheduleEntry).where(
                ScheduleEntry.timetable_id == tt.id
            )
        )
        out.append(TimetableBrief(
            id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status,
            entry_count=n or 0,
        ))
    return out


@router.post("/timetables", response_model=TimetableOut, status_code=status.HTTP_201_CREATED)
def create_timetable(
    body: TimetableCreate,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    tt = Timetable(semester_id=semester_id, name=body.name)
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return TimetableOut(
        id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status, entries=[]
    )


@router.get("/timetables/{timetable_id}", response_model=TimetableOut)
def get_timetable(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    tt = _get_timetable(db, timetable_id)
    rows = db.scalars(
        select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)
    ).all()
    entries = sorted(rows, key=lambda e: (e.weekday, e.period_no))
    return TimetableOut(
        id=tt.id, semester_id=tt.semester_id, name=tt.name, status=tt.status,
        entries=[_serialize_entry(e) for e in entries],
    )


@router.delete("/timetables/{timetable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_timetable(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    tt = _get_timetable(db, timetable_id)
    db.delete(tt)
    db.commit()


# ── 衝突檢查(不寫入)────────────────
@router.post("/timetables/{timetable_id}/check-conflict", response_model=CheckResponse)
def check_conflict(
    timetable_id: int,
    body: CheckRequest,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    tt = _get_timetable(db, timetable_id)
    a = _get_assignment(db, tt.semester_id, body.course_assignment_id)
    ignore_ids: set[int] = set()
    if body.ignore_entry_id is not None:
        e = db.get(ScheduleEntry, body.ignore_entry_id)
        if e is not None and e.timetable_id == tt.id:
            # 移動:忽略被搬動的那一格(群組則含同格的兄弟課)
            ignore_ids = {
                s.id for s in _slot_siblings(
                    db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no
                )
            }
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, body.span, ignore_ids
    )
    return CheckResponse(
        ok=not conflicts,
        conflicts=[{"code": c.code, "message": c.message} for c in conflicts],
    )


# ── 格位放入/移動/刪除/鎖定 ──────────
@router.post("/timetables/{timetable_id}/entries", response_model=TimetableOut,
             status_code=status.HTTP_201_CREATED)
def place_entry(
    timetable_id: int,
    body: PlaceRequest,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    tt = _get_timetable(db, timetable_id)
    a = _get_assignment(db, tt.semester_id, body.course_assignment_id)
    placements = cc.placements_for(db, a, body.weekday, body.period_no, body.span)
    # H8 守恆(放入面):不得超過該配課的每週節數
    for pl in placements:
        placed = _placed_periods(db, tt.id, pl.assignment.id)
        if placed + pl.span > pl.assignment.periods_per_week:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"「{pl.assignment.subject.name}」已排 {placed} 節,"
                f"再排 {pl.span} 節將超過每週 {pl.assignment.periods_per_week} 節",
            )
    conflicts = cc.check_conflict(db, tt, a, body.weekday, body.period_no, body.span)
    if conflicts:
        raise _conflict_409(conflicts)
    for pl in placements:
        db.add(ScheduleEntry(
            timetable_id=tt.id, course_assignment_id=pl.assignment.id,
            weekday=pl.weekday, period_no=pl.period_no, span=pl.span,
        ))
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.patch("/timetables/{timetable_id}/entries/{entry_id}", response_model=TimetableOut)
def move_entry(
    timetable_id: int, entry_id: int, body: MoveRequest,
    db: Session = Depends(get_db), _: object = Depends(editor),
):
    tt = _get_timetable(db, timetable_id)
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    if e.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "格位已鎖定,請先解鎖再移動")
    a = e.assignment
    # 同格兄弟(群組同時段的多門課)一起搬;檢查時忽略自己這幾格
    moving = _slot_siblings(db, tt.id, a.scheduling_unit_id, e.weekday, e.period_no)
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, e.span,
        ignore_entry_ids={s.id for s in moving},
    )
    if conflicts:
        raise _conflict_409(conflicts)
    for sib in moving:
        sib.weekday = body.weekday
        sib.period_no = body.period_no
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.post("/timetables/{timetable_id}/entries/{entry_id}/lock", response_model=TimetableOut)
def lock_entry(
    timetable_id: int, entry_id: int, locked: bool = Query(True),
    db: Session = Depends(get_db), _: object = Depends(editor),
):
    tt = _get_timetable(db, timetable_id)
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    for sib in _slot_siblings(db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no):
        sib.locked = locked
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.delete(
    "/timetables/{timetable_id}/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_entry(
    timetable_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> None:
    tt = _get_timetable(db, timetable_id)
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    if e.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "格位已鎖定,請先解鎖再移除")
    for sib in _slot_siblings(db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no):
        db.delete(sib)
    db.commit()
