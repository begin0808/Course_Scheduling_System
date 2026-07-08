"""基礎資料 API:教師、科目、場地、班級。

權限:讀取 = 教學組長/教務主任;寫入 = 教學組長(admin 一律通過)。
所有資源以 semester_id 為範圍。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.basedata import (
    ClassUnit,
    Room,
    Subject,
    Teacher,
    TeacherTimeRule,
    room_subjects,
    teacher_subjects,
)
from app.models.semester import Semester
from app.models.user import Role
from app.schemas.basedata import (
    ClassUnitIn,
    ClassUnitOut,
    RoomIn,
    RoomOut,
    SubjectIn,
    SubjectOut,
    TeacherIn,
    TeacherOut,
    TeacherTimeRuleIn,
    TeacherTimeRuleOut,
)

router = APIRouter(tags=["basedata"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def _require_semester(db: Session, semester_id: int) -> None:
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")


def _resolve_subjects(db: Session, semester_id: int, ids: list[int]) -> list[Subject]:
    if not ids:
        return []
    subjects = db.scalars(
        select(Subject).where(Subject.id.in_(ids), Subject.semester_id == semester_id)
    ).all()
    if len(subjects) != len(set(ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "科目清單含無效或跨學期的科目")
    return list(subjects)


# ── 科目 ──────────────────────────────
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Subject).where(Subject.semester_id == semester_id)
    if q:
        stmt = stmt.where(Subject.name.contains(q))
    return db.scalars(stmt.order_by(Subject.name)).all()


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED)
def create_subject(
    body: SubjectIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Subject:
    _require_semester(db, semester_id)
    subject = Subject(
        semester_id=semester_id,
        name=body.name,
        domain=body.domain,
        required_room_type=body.required_room_type.value if body.required_room_type else None,
        default_block_size=body.default_block_size,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return subject


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int, body: SubjectIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    subject.name = body.name
    subject.domain = body.domain
    subject.required_room_type = body.required_room_type.value if body.required_room_type else None
    subject.default_block_size = body.default_block_size
    db.commit()
    db.refresh(subject)
    return subject


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subject(
    subject_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到科目")
    t_count = db.scalar(
        select(func.count()).select_from(teacher_subjects).where(
            teacher_subjects.c.subject_id == subject_id
        )
    )
    r_count = db.scalar(
        select(func.count()).select_from(room_subjects).where(
            room_subjects.c.subject_id == subject_id
        )
    )
    if t_count or r_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"此科目已被 {t_count} 位教師、{r_count} 間場地引用,請先解除關聯再刪除",
        )
    db.delete(subject)
    db.commit()


# ── 教師 ──────────────────────────────
@router.get("/teachers", response_model=list[TeacherOut])
def list_teachers(
    semester_id: int = Query(...),
    q: str | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Teacher).where(Teacher.semester_id == semester_id)
    if q:
        stmt = stmt.where(Teacher.name.contains(q))
    if active_only:
        stmt = stmt.where(Teacher.is_active.is_(True))
    return db.scalars(stmt.order_by(Teacher.name)).all()


@router.post("/teachers", response_model=TeacherOut, status_code=status.HTTP_201_CREATED)
def create_teacher(
    body: TeacherIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Teacher:
    _require_semester(db, semester_id)
    teacher = Teacher(
        semester_id=semester_id,
        name=body.name,
        base_periods=body.base_periods,
        admin_title=body.admin_title,
        admin_reduction=body.admin_reduction,
        is_external=body.is_external,
        is_active=body.is_active,
        subjects=_resolve_subjects(db, semester_id, body.subject_ids),
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.get("/teachers/{teacher_id}", response_model=TeacherOut)
def get_teacher(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
    return teacher


@router.patch("/teachers/{teacher_id}", response_model=TeacherOut)
def update_teacher(
    teacher_id: int, body: TeacherIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Teacher:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
    teacher.name = body.name
    teacher.base_periods = body.base_periods
    teacher.admin_title = body.admin_title
    teacher.admin_reduction = body.admin_reduction
    teacher.is_external = body.is_external
    teacher.is_active = body.is_active
    teacher.subjects = _resolve_subjects(db, teacher.semester_id, body.subject_ids)
    db.commit()
    db.refresh(teacher)
    return teacher


@router.delete("/teachers/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_teacher(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
    homeroom_count = db.scalar(
        select(func.count()).select_from(ClassUnit).where(
            ClassUnit.homeroom_teacher_id == teacher_id
        )
    )
    if homeroom_count:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"此教師為 {homeroom_count} 個班級的導師,無法刪除;請先更換導師,或將教師設為離職",
        )
    db.delete(teacher)
    db.commit()


@router.get("/teachers/{teacher_id}/time-rules", response_model=list[TeacherTimeRuleOut])
def get_time_rules(
    teacher_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
    return teacher.time_rules


@router.put("/teachers/{teacher_id}/time-rules", response_model=list[TeacherTimeRuleOut])
def replace_time_rules(
    teacher_id: int,
    rules: list[TeacherTimeRuleIn],
    db: Session = Depends(get_db),
    _: object = Depends(editor),
):
    teacher = db.get(Teacher, teacher_id)
    if teacher is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到教師")
    seen: set[tuple[int, int]] = set()
    for r in rules:
        key = (r.weekday, r.period_no)
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "同一格位不可重複設定規則")
        seen.add(key)
    teacher.time_rules.clear()
    db.flush()
    for r in rules:
        teacher.time_rules.append(
            TeacherTimeRule(weekday=r.weekday, period_no=r.period_no, rule_type=r.rule_type.value)
        )
    db.commit()
    db.refresh(teacher)
    return teacher.time_rules


# ── 場地 ──────────────────────────────
@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(Room).where(Room.semester_id == semester_id)
    if q:
        stmt = stmt.where(Room.name.contains(q))
    return db.scalars(stmt.order_by(Room.name)).all()


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    body: RoomIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Room:
    _require_semester(db, semester_id)
    room = Room(
        semester_id=semester_id,
        name=body.name,
        room_type=body.room_type.value,
        capacity=body.capacity,
        subjects=_resolve_subjects(db, semester_id, body.subject_ids),
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.patch("/rooms/{room_id}", response_model=RoomOut)
def update_room(
    room_id: int, body: RoomIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Room:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到場地")
    room.name = body.name
    room.room_type = body.room_type.value
    room.capacity = body.capacity
    room.subjects = _resolve_subjects(db, room.semester_id, body.subject_ids)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(room_id: int, db: Session = Depends(get_db), _: object = Depends(editor)) -> None:
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到場地")
    db.delete(room)
    db.commit()


# ── 班級 ──────────────────────────────
@router.get("/class-units", response_model=list[ClassUnitOut])
def list_class_units(
    semester_id: int = Query(...),
    q: str | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    stmt = select(ClassUnit).where(ClassUnit.semester_id == semester_id)
    if q:
        stmt = stmt.where(ClassUnit.name.contains(q))
    return db.scalars(stmt.order_by(ClassUnit.grade, ClassUnit.name)).all()


def _validate_homeroom(db: Session, semester_id: int, teacher_id: int | None) -> None:
    if teacher_id is None:
        return
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "導師無效或不屬於本學期")


@router.post("/class-units", response_model=ClassUnitOut, status_code=status.HTTP_201_CREATED)
def create_class_unit(
    body: ClassUnitIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> ClassUnit:
    _require_semester(db, semester_id)
    _validate_homeroom(db, semester_id, body.homeroom_teacher_id)
    cu = ClassUnit(
        semester_id=semester_id,
        grade=body.grade,
        name=body.name,
        track=body.track.value,
        department=body.department,
        student_count=body.student_count,
        homeroom_teacher_id=body.homeroom_teacher_id,
    )
    db.add(cu)
    db.commit()
    db.refresh(cu)
    return cu


@router.patch("/class-units/{class_id}", response_model=ClassUnitOut)
def update_class_unit(
    class_id: int, body: ClassUnitIn, db: Session = Depends(get_db), _: object = Depends(editor)
) -> ClassUnit:
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班級")
    _validate_homeroom(db, cu.semester_id, body.homeroom_teacher_id)
    cu.grade = body.grade
    cu.name = body.name
    cu.track = body.track.value
    cu.department = body.department
    cu.student_count = body.student_count
    cu.homeroom_teacher_id = body.homeroom_teacher_id
    db.commit()
    db.refresh(cu)
    return cu


@router.delete("/class-units/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class_unit(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班級")
    db.delete(cu)
    db.commit()
