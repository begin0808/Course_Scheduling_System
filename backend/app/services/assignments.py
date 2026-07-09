"""配課領域服務:排課單位解析、跑班群組驗證、鐘點/負載統計、序列化。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.basedata import ClassUnit, Teacher
from app.services import period_tables as pt_service


class DomainError(Exception):
    """商業規則違反(由 API 層轉為對應 HTTP 狀態)。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def get_or_create_single_unit(db: Session, class_unit: ClassUnit) -> SchedulingUnit:
    """取得(或建立)某班級的單班排課單位。單班的所有配課共用同一 single unit。"""
    existing = db.scalar(
        select(SchedulingUnit)
        .join(SchedulingUnitMember, SchedulingUnitMember.scheduling_unit_id == SchedulingUnit.id)
        .where(
            SchedulingUnit.semester_id == class_unit.semester_id,
            SchedulingUnit.unit_type == SchedulingUnitType.single.value,
            SchedulingUnitMember.class_unit_id == class_unit.id,
        )
    )
    if existing is not None:
        return existing
    unit = SchedulingUnit(
        semester_id=class_unit.semester_id,
        unit_type=SchedulingUnitType.single.value,
        name=class_unit.name,
    )
    unit.members.append(SchedulingUnitMember(class_unit_id=class_unit.id))
    db.add(unit)
    db.flush()
    return unit


def create_group(
    db: Session, semester_id: int, name: str, class_ids: list[int]
) -> SchedulingUnit:
    """建立跑班群組。驗證班級同屬本學期,且成員節次表一致(architecture.md D7 #4)。"""
    classes = list(
        db.scalars(
            select(ClassUnit).where(
                ClassUnit.id.in_(class_ids), ClassUnit.semester_id == semester_id
            )
        )
    )
    if len(classes) != len(set(class_ids)):
        raise DomainError("班級清單含無效或跨學期的班級")
    _require_same_period_table(db, classes)
    unit = SchedulingUnit(
        semester_id=semester_id, unit_type=SchedulingUnitType.group.value, name=name
    )
    for cid in class_ids:
        unit.members.append(SchedulingUnitMember(class_unit_id=cid))
    db.add(unit)
    db.flush()
    return unit


def _require_same_period_table(db: Session, classes: list[ClassUnit]) -> None:
    table_ids = set()
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        table_ids.add(table.id if table is not None else None)
    if len(table_ids) > 1:
        raise DomainError(
            "跑班群組的成員班級必須使用同一套節次表(否則無法同時段開課)", status_code=409
        )


def teacher_loads(db: Session, semester_id: int) -> list[dict]:
    """每位教師的鐘點統計:應授(base-減課)vs 已配課,delta 正為超鐘點。"""
    rows = db.execute(
        select(
            AssignmentTeacher.teacher_id,
            func.sum(CourseAssignment.periods_per_week),
        )
        .join(CourseAssignment, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .where(CourseAssignment.semester_id == semester_id)
        .group_by(AssignmentTeacher.teacher_id)
    ).all()
    assigned_by = {tid: int(total or 0) for tid, total in rows}
    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.name)
    )
    out: list[dict] = []
    for t in teachers:
        target = max(t.base_periods - t.admin_reduction, 0)
        assigned = assigned_by.get(t.id, 0)
        out.append({
            "teacher_id": t.id, "name": t.name,
            "base_periods": t.base_periods, "admin_reduction": t.admin_reduction,
            "target": target, "assigned": assigned, "delta": assigned - target,
        })
    return out


def class_loads(db: Session, semester_id: int) -> list[dict]:
    """每班每週配課總節數 vs 可排節次數(超出即警告,對應驗收④)。"""
    rows = db.execute(
        select(
            SchedulingUnitMember.class_unit_id,
            func.sum(CourseAssignment.periods_per_week),
        )
        .join(
            CourseAssignment,
            CourseAssignment.scheduling_unit_id == SchedulingUnitMember.scheduling_unit_id,
        )
        .join(SchedulingUnit, SchedulingUnit.id == SchedulingUnitMember.scheduling_unit_id)
        .where(SchedulingUnit.semester_id == semester_id)
        .group_by(SchedulingUnitMember.class_unit_id)
    ).all()
    assigned_by = {cid: int(total or 0) for cid, total in rows}
    classes = db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)
    )
    out: list[dict] = []
    for c in classes:
        table = pt_service.resolve_period_table(db, c)
        capacity = len(pt_service.regular_slots(db, table.id)) if table is not None else 0
        assigned = assigned_by.get(c.id, 0)
        out.append({
            "class_id": c.id, "name": c.name, "grade": c.grade,
            "assigned": assigned, "capacity": capacity,
            "over_capacity": assigned > capacity,
        })
    return out


# ── 序列化 ────────────────────────────
def serialize_unit(u: SchedulingUnit) -> dict:
    return {
        "id": u.id, "semester_id": u.semester_id,
        "unit_type": u.unit_type, "name": u.name,
        "classes": [
            {"id": m.class_unit.id, "name": m.class_unit.name, "grade": m.class_unit.grade}
            for m in u.members
        ],
    }


def serialize_assignment(a: CourseAssignment) -> dict:
    return {
        "id": a.id, "semester_id": a.semester_id,
        "scheduling_unit": serialize_unit(a.scheduling_unit),
        "subject": {"id": a.subject.id, "name": a.subject.name},
        "periods_per_week": a.periods_per_week,
        "required_room_type": a.required_room_type,
        "room_id": a.room_id, "lock_room": a.lock_room,
        "teachers": [
            {"teacher_id": t.teacher_id, "is_lead": t.is_lead, "name": t.teacher.name}
            for t in sorted(a.teachers, key=lambda x: (not x.is_lead, x.teacher_id))
        ],
        "block_rules": [
            {"id": b.id, "block_size": b.block_size, "count_per_week": b.count_per_week}
            for b in a.block_rules
        ],
    }
