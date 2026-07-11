"""課表 API:草稿 CRUD、格位放入/移動/刪除、鎖定、即時衝突檢查。

放入/移動時以 conflict_checker 驗證硬約束,違反則回 409 並附人話衝突清單。
跑班群組:放入/移動/刪除/鎖定皆連動同群組全部配課(H7 同時段)。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Room, Teacher
from app.models.period import PeriodTable
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role, User
from app.schemas.timetable import (
    CheckRequest,
    CheckResponse,
    CompletenessOut,
    MoveRequest,
    NamedBrief,
    PlaceRequest,
    PublicClass,
    PublicPeriodTable,
    PublicSemester,
    PublishedTimetableOut,
    ScheduleEntryOut,
    TimetableBrief,
    TimetableCreate,
    TimetableOut,
    TimetableRename,
)
from app.services import conflict_checker as cc
from app.services import timetable_publish as pub
from app.services.teachers import current_teacher

router = APIRouter(tags=["timetables"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def _get_timetable(db: Session, timetable_id: int) -> Timetable:
    tt = db.get(Timetable, timetable_id)
    if tt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到課表")
    return tt


def _require_draft(tt: Timetable) -> Timetable:
    """已發布/已封存的課表是快照,不得再改格位(architecture.md D4)。"""
    if tt.status != TimetableStatus.draft.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "此課表已發布或已封存,不可編輯;請複製為新草稿後修改",
        )
    return tt


def _get_assignment(db: Session, semester_id: int, assignment_id: int) -> CourseAssignment:
    a = db.get(CourseAssignment, assignment_id)
    if a is None or a.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "配課無效或不屬於本課表學期")
    return a


def _serialize_entry(e: ScheduleEntry) -> ScheduleEntryOut:
    a = e.assignment
    su = a.scheduling_unit
    # 格位場地優先於配課場地(引擎逐格指派、調代課教室異動皆寫在格位上)
    room = e.room if e.room is not None else a.room
    return ScheduleEntryOut(
        id=e.id, course_assignment_id=e.course_assignment_id,
        weekday=e.weekday, period_no=e.period_no, span=e.span, locked=e.locked,
        subject=a.subject.name,
        teachers=[at.teacher.name for at in a.teachers],
        classes=[m.class_unit.name for m in su.members],
        unit_type=su.unit_type, unit_name=su.name,
        room=room.name if room else None,
        teacher_ids=[at.teacher_id for at in a.teachers],
        class_ids=[m.class_unit_id for m in su.members],
        room_id=e.effective_room_id,
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


@router.patch("/timetables/{timetable_id}", response_model=TimetableOut)
def rename_timetable(
    timetable_id: int,
    body: TimetableRename,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    tt = _get_timetable(db, timetable_id)
    tt.name = body.name
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.post(
    "/timetables/{timetable_id}/duplicate",
    response_model=TimetableOut,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_timetable(
    timetable_id: int,
    body: TimetableRename,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    """複製為新草稿(含全部格位);兩份草稿互不影響。"""
    src = _get_timetable(db, timetable_id)
    new = pub.duplicate(db, src, body.name)
    db.commit()
    return get_timetable(new.id, db, None)


@router.get("/timetables/{timetable_id}/completeness", response_model=CompletenessOut)
def timetable_completeness(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    """發布前完整性檢查:列出尚未排完的課務。"""
    tt = _get_timetable(db, timetable_id)
    return pub.completeness(db, tt)


@router.post("/timetables/{timetable_id}/publish", response_model=TimetableOut)
def publish_timetable(
    timetable_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    """draft → published;同學期原 published 轉 archived。未排完時需 force=true 才可發布。"""
    tt = _require_draft(_get_timetable(db, timetable_id))
    report = pub.completeness(db, tt)
    if not report["complete"] and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"message": "尚有課務未排完,確認後可強制發布", "completeness": report},
        )
    pub.publish(db, tt, user, forced=not report["complete"])
    db.commit()
    # 條件 D:重新發布後,提醒仍有多少「今日之後」的調代課是依舊課表展開的
    out = get_timetable(timetable_id, db, None)
    out.stale_affected = pub.stale_future_affected_count(db, tt.semester_id)
    return out


@router.delete("/timetables/{timetable_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_timetable(
    timetable_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    tt = _get_timetable(db, timetable_id)
    db.delete(tt)
    db.commit()


# ── 全員唯讀課表查詢(含 teacher 角色)────
@router.get("/published/semesters", response_model=list[PublicSemester])
def published_semesters(db: Session = Depends(get_db), _: User = Depends(get_active_user)):
    """有已發布課表的學期。"""
    rows = db.scalars(
        select(Semester)
        .join(Timetable, Timetable.semester_id == Semester.id)
        .where(Timetable.status == TimetableStatus.published.value)
        .order_by(Semester.academic_year.desc(), Semester.term.desc())
    ).all()
    return [PublicSemester(id=s.id, label=s.label) for s in rows]


@router.get("/published/my-teacher", response_model=NamedBrief | None)
def published_my_teacher(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_active_user),
):
    """登入者在該學期綁定的教師主檔(無綁定回 null),供教師端預設顯示本人課表。"""
    t = current_teacher(db, user, semester_id)
    return NamedBrief(id=t.id, name=t.name) if t else None


@router.get("/published/timetable", response_model=PublishedTimetableOut | None)
def published_timetable(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """該學期的已發布課表 + 查詢頁所需選項與節次表(教師端只需這一支)。"""
    tt = db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )
    if tt is None:
        return None
    sem = db.get(Semester, semester_id)
    rows = db.scalars(select(ScheduleEntry).where(ScheduleEntry.timetable_id == tt.id)).all()
    classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    ).all()
    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.name)
    ).all()
    rooms = db.scalars(
        select(Room).where(Room.semester_id == semester_id).order_by(Room.name)
    ).all()
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id)
    ).all()
    return PublishedTimetableOut(
        id=tt.id, semester_id=semester_id, semester_label=sem.label if sem else "",
        name=tt.name, status=tt.status,
        entries=[_serialize_entry(e) for e in sorted(rows, key=lambda x: (x.weekday, x.period_no))],
        classes=[
            PublicClass(id=c.id, name=c.name, grade=c.grade, period_table_id=c.period_table_id)
            for c in classes
        ],
        teachers=[NamedBrief(id=t.id, name=t.name) for t in teachers],
        rooms=[NamedBrief(id=r.id, name=r.name) for r in rooms],
        period_tables=[
            PublicPeriodTable(
                id=p.id, name=p.name, num_weekdays=p.num_weekdays, is_default=p.is_default,
                periods=list(p.periods),
            )
            for p in tables
        ],
    )


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
        db, tt, a, body.weekday, body.period_no, body.span, ignore_ids, body.room_id
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
    tt = _require_draft(_get_timetable(db, timetable_id))
    a = _get_assignment(db, tt.semester_id, body.course_assignment_id)
    if body.room_id is not None:
        room = db.get(Room, body.room_id)
        if room is None or room.semester_id != tt.semester_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "場地無效或不屬於本課表學期")
    placements = cc.placements_for(db, a, body.weekday, body.period_no, body.span, body.room_id)
    # H8 守恆(放入面):不得超過該配課的每週節數
    for pl in placements:
        placed = _placed_periods(db, tt.id, pl.assignment.id)
        if placed + pl.span > pl.assignment.periods_per_week:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"「{pl.assignment.subject.name}」已排 {placed} 節,"
                f"再排 {pl.span} 節將超過每週 {pl.assignment.periods_per_week} 節",
            )
    conflicts = cc.check_conflict(
        db, tt, a, body.weekday, body.period_no, body.span, room_id=body.room_id
    )
    if conflicts:
        raise _conflict_409(conflicts)
    for pl in placements:
        db.add(ScheduleEntry(
            timetable_id=tt.id, course_assignment_id=pl.assignment.id,
            weekday=pl.weekday, period_no=pl.period_no, span=pl.span,
            room_id=pl.room_id,
        ))
    db.commit()
    return get_timetable(timetable_id, db, None)


@router.patch("/timetables/{timetable_id}/entries/{entry_id}", response_model=TimetableOut)
def move_entry(
    timetable_id: int, entry_id: int, body: MoveRequest,
    db: Session = Depends(get_db), _: object = Depends(editor),
):
    tt = _require_draft(_get_timetable(db, timetable_id))
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
        room_id=e.room_id,  # 搬動時沿用格位既有的場地
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
    tt = _require_draft(_get_timetable(db, timetable_id))
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
    tt = _require_draft(_get_timetable(db, timetable_id))
    e = db.get(ScheduleEntry, entry_id)
    if e is None or e.timetable_id != tt.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到格位")
    if e.locked:
        raise HTTPException(status.HTTP_409_CONFLICT, "格位已鎖定,請先解鎖再移除")
    for sib in _slot_siblings(db, tt.id, e.assignment.scheduling_unit_id, e.weekday, e.period_no):
        db.delete(sib)
    db.commit()
