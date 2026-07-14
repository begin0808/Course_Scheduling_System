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
from app.models.period import PeriodTable
from app.models.semester import Semester
from app.models.user import Role, User, UserRole
from app.schemas.basedata import (
    BindableAccount,
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
from app.schemas.semester import AvailableSlot, PeriodTableOut
from app.services import period_tables as pt_service

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
        is_major=body.is_major,
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
    subject.is_major = body.is_major
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


def _validate_teacher_user(
    db: Session, semester_id: int, user_id: int | None, exclude_teacher_id: int | None = None
) -> None:
    """驗證欲綁定的帳號:須存在,且同學期未被其他教師綁定(否則 409)。"""
    if user_id is None:
        return
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "欲綁定的帳號不存在")
    stmt = select(Teacher.id).where(
        Teacher.semester_id == semester_id, Teacher.user_id == user_id
    )
    if exclude_teacher_id is not None:
        stmt = stmt.where(Teacher.id != exclude_teacher_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "此帳號在本學期已綁定其他教師")


# ── 教師 ──────────────────────────────
@router.get("/teachers/bindable-accounts", response_model=list[BindableAccount])
def list_bindable_accounts(
    semester_id: int = Query(...),
    current_teacher_id: int | None = None,
    db: Session = Depends(get_db),
    _: object = Depends(viewer),
):
    """teacher 角色且在本學期尚未綁定的帳號;編輯時另納入該教師目前綁定的帳號。"""
    bound = set(
        db.scalars(
            select(Teacher.user_id).where(
                Teacher.semester_id == semester_id, Teacher.user_id.is_not(None)
            )
        )
    )
    if current_teacher_id is not None:
        cur = db.get(Teacher, current_teacher_id)
        if cur is not None and cur.user_id is not None:
            bound.discard(cur.user_id)
    teacher_user_ids = db.scalars(
        select(UserRole.user_id).where(UserRole.role == Role.teacher.value)
    )
    available = [uid for uid in set(teacher_user_ids) if uid not in bound]
    if not available:
        return []
    return db.scalars(
        select(User).where(User.id.in_(available), User.is_active.is_(True)).order_by(User.username)
    ).all()


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
    _validate_teacher_user(db, semester_id, body.user_id)
    teacher = Teacher(
        semester_id=semester_id,
        name=body.name,
        id_last4=body.id_last4,
        base_periods=body.base_periods,
        admin_title=body.admin_title,
        admin_reduction=body.admin_reduction,
        is_external=body.is_external,
        is_active=body.is_active,
        email=body.email,
        phone=body.phone,
        line_id=body.line_id,
        user_id=body.user_id,
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
    _validate_teacher_user(db, teacher.semester_id, body.user_id, exclude_teacher_id=teacher.id)
    teacher.name = body.name
    teacher.id_last4 = body.id_last4
    teacher.base_periods = body.base_periods
    teacher.admin_title = body.admin_title
    teacher.admin_reduction = body.admin_reduction
    teacher.is_external = body.is_external
    teacher.is_active = body.is_active
    teacher.email = body.email
    teacher.phone = body.phone
    teacher.line_id = body.line_id
    teacher.user_id = body.user_id
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


def _require_unique_class_name(
    db: Session, semester_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """同學期不得有兩個同名班級(M6-5)。

    衝突訊息、課表、匯出全都以班名指稱班級——同學期出現兩個「301」時,組長在畫面上
    根本分不出是哪一班。DB 有 uq 約束兜底,這裡先擋下來給人話。
    """
    stmt = select(ClassUnit).where(
        ClassUnit.semester_id == semester_id, ClassUnit.name == name
    )
    if exclude_id is not None:
        stmt = stmt.where(ClassUnit.id != exclude_id)
    if db.scalar(stmt):
        raise HTTPException(status.HTTP_409_CONFLICT, f"本學期已有班級「{name}」")


def _validate_homeroom(db: Session, semester_id: int, teacher_id: int | None) -> None:
    if teacher_id is None:
        return
    teacher = db.get(Teacher, teacher_id)
    if teacher is None or teacher.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "導師無效或不屬於本學期")


def _validate_period_table(db: Session, semester_id: int, table_id: int | None) -> None:
    if table_id is None:
        return
    table = db.get(PeriodTable, table_id)
    if table is None or table.semester_id != semester_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "節次表無效或不屬於本學期")


@router.post("/class-units", response_model=ClassUnitOut, status_code=status.HTTP_201_CREATED)
def create_class_unit(
    body: ClassUnitIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> ClassUnit:
    _require_semester(db, semester_id)
    _require_unique_class_name(db, semester_id, body.name)
    _validate_homeroom(db, semester_id, body.homeroom_teacher_id)
    _validate_period_table(db, semester_id, body.period_table_id)
    cu = ClassUnit(
        semester_id=semester_id,
        grade=body.grade,
        name=body.name,
        track=body.track.value,
        department=body.department,
        student_count=body.student_count,
        homeroom_teacher_id=body.homeroom_teacher_id,
        period_table_id=body.period_table_id,
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
    _require_unique_class_name(db, cu.semester_id, body.name, exclude_id=cu.id)
    _validate_homeroom(db, cu.semester_id, body.homeroom_teacher_id)
    _validate_period_table(db, cu.semester_id, body.period_table_id)
    cu.grade = body.grade
    cu.name = body.name
    cu.track = body.track.value
    cu.department = body.department
    cu.student_count = body.student_count
    cu.homeroom_teacher_id = body.homeroom_teacher_id
    cu.period_table_id = body.period_table_id
    db.commit()
    db.refresh(cu)
    return cu


@router.get("/class-units/{class_id}/period-table", response_model=PeriodTableOut)
def class_period_table(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> PeriodTable:
    """該班級所屬的完整節次表(含午休/早自習等非上課格位),供排課工作台渲染。

    一律經 resolve_period_table,前端不需自行處理「指定表 vs 學期預設表」。
    """
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班級")
    table = pt_service.resolve_period_table(db, cu)
    if table is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "此學期尚無任何節次表")
    return table


@router.get("/class-units/{class_id}/available-slots", response_model=list[AvailableSlot])
def class_available_slots(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> list[AvailableSlot]:
    """回傳該班級的可排課時段(依所屬節次表,空則用學期預設表)。M2 排課引擎使用。"""
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班級")
    table = pt_service.resolve_period_table(db, cu)
    if table is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "此學期尚無任何節次表")
    rows = pt_service.regular_slots(db, table.id)
    return [
        AvailableSlot(
            weekday=p.weekday, period_no=p.period_no, name=p.name,
            start_time=p.start_time, end_time=p.end_time,
        )
        for p in rows
    ]


@router.delete("/class-units/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_class_unit(
    class_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    cu = db.get(ClassUnit, class_id)
    if cu is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到班級")
    db.delete(cu)
    db.commit()
