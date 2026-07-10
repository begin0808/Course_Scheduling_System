"""DB → 排課引擎問題描述的轉換層。

刻意放在 `app.services` 而非 `app.solver`:loader 必須 import models 與 SQLAlchemy,
而 solver 套件的架構規則是「不碰 ORM」(見 app/solver/__init__.py)。
這裡是兩者唯一的交界。
"""

from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
)
from app.models.basedata import ClassUnit, Room, Teacher, TeacherRuleType
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable
from app.services import period_tables as pt_service
from app.solver.problem import (
    AssignmentSpec,
    BlockSpec,
    ClassSpec,
    FixedEntry,
    PeriodTableSpec,
    Problem,
    RoomSpec,
    Slot,
    TeacherSpec,
    UnitSpec,
)


def _minutes(value: time | None) -> int | None:
    return value.hour * 60 + value.minute if value is not None else None


def _load_tables(db: Session, semester_id: int) -> dict[int, PeriodTableSpec]:
    tables = db.scalars(
        select(PeriodTable).where(PeriodTable.semester_id == semester_id)
    ).all()
    out: dict[int, PeriodTableSpec] = {}
    for t in tables:
        periods = db.scalars(
            select(Period)
            .where(
                Period.period_table_id == t.id,
                Period.type == PeriodType.regular.value,  # 只有一般課參與排課(H5)
            )
            .order_by(Period.weekday, Period.period_no)
        ).all()
        out[t.id] = PeriodTableSpec(
            id=t.id,
            name=t.name,
            num_weekdays=t.num_weekdays,
            slots=tuple(
                Slot(
                    weekday=p.weekday,
                    period_no=p.period_no,
                    name=p.name,
                    start_min=_minutes(p.start_time),
                    end_min=_minutes(p.end_time),
                )
                for p in periods
            ),
        )
    return out


def load_problem(
    db: Session, semester_id: int, timetable: Timetable | None = None
) -> Problem:
    """把一個學期的排課資料讀成純 dataclass 的問題描述。

    timetable 給定時,其格位一併帶入 fixed_entries:locked 者為 H9 硬約束,
    其餘供求解器作為起點提示(M3-4)。
    """
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise ValueError(f"找不到學期 {semester_id}")

    tables = _load_tables(db, semester_id)
    default_table = pt_service.semester_default_table(db, semester_id)
    default_table_id = default_table.id if default_table else None

    classes: dict[int, ClassSpec] = {}
    for c in db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id).order_by(ClassUnit.id)
    ):
        # 在此一次解析節次表(指定表 → 學期預設表),solver 不需再回退
        table_id = c.period_table_id if c.period_table_id in tables else default_table_id
        if table_id is None:
            continue
        classes[c.id] = ClassSpec(
            id=c.id, name=c.name, grade=c.grade,
            period_table_id=table_id, student_count=c.student_count,
        )

    teachers: dict[int, TeacherSpec] = {}
    for t in db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id).order_by(Teacher.id)
    ):
        unavailable = frozenset(
            (r.weekday, r.period_no)
            for r in t.time_rules
            if r.rule_type == TeacherRuleType.unavailable.value
        )
        teachers[t.id] = TeacherSpec(
            id=t.id, name=t.name, base_periods=t.base_periods,
            admin_reduction=t.admin_reduction, is_external=t.is_external,
            unavailable=unavailable,
        )

    rooms = {
        r.id: RoomSpec(id=r.id, name=r.name, room_type=r.room_type, capacity=r.capacity)
        for r in db.scalars(
            select(Room).where(Room.semester_id == semester_id).order_by(Room.id)
        )
    }

    members: dict[int, list[int]] = {}
    for unit_id, class_id in db.execute(
        select(SchedulingUnitMember.scheduling_unit_id, SchedulingUnitMember.class_unit_id)
        .join(SchedulingUnit, SchedulingUnit.id == SchedulingUnitMember.scheduling_unit_id)
        .where(SchedulingUnit.semester_id == semester_id)
        .order_by(SchedulingUnitMember.id)
    ):
        members.setdefault(unit_id, []).append(class_id)

    units = {
        u.id: UnitSpec(
            id=u.id, unit_type=u.unit_type, name=u.name,
            class_ids=tuple(cid for cid in members.get(u.id, []) if cid in classes),
        )
        for u in db.scalars(
            select(SchedulingUnit).where(SchedulingUnit.semester_id == semester_id)
        )
    }

    teachers_by_a: dict[int, list[int]] = {}
    for a_id, t_id in db.execute(
        select(AssignmentTeacher.course_assignment_id, AssignmentTeacher.teacher_id)
        .join(CourseAssignment, CourseAssignment.id == AssignmentTeacher.course_assignment_id)
        .where(CourseAssignment.semester_id == semester_id)
        .order_by(AssignmentTeacher.id)
    ):
        teachers_by_a.setdefault(a_id, []).append(t_id)

    blocks_by_a: dict[int, list[BlockSpec]] = {}
    for a_id, size, count in db.execute(
        select(BlockRule.course_assignment_id, BlockRule.block_size, BlockRule.count_per_week)
        .join(CourseAssignment, CourseAssignment.id == BlockRule.course_assignment_id)
        .where(CourseAssignment.semester_id == semester_id)
    ):
        blocks_by_a.setdefault(a_id, []).append(BlockSpec(size=size, count=count))

    assignments = tuple(
        AssignmentSpec(
            id=a.id, unit_id=a.scheduling_unit_id,
            subject_id=a.subject_id, subject_name=a.subject.name,
            periods_per_week=a.periods_per_week,
            teacher_ids=tuple(teachers_by_a.get(a.id, [])),
            room_id=a.room_id, required_room_type=a.required_room_type,
            lock_room=a.lock_room,
            blocks=tuple(blocks_by_a.get(a.id, [])),
        )
        for a in db.scalars(
            select(CourseAssignment)
            .where(CourseAssignment.semester_id == semester_id)
            .order_by(CourseAssignment.id)
        )
    )

    fixed: tuple[FixedEntry, ...] = ()
    if timetable is not None:
        fixed = tuple(
            FixedEntry(
                assignment_id=e.course_assignment_id, weekday=e.weekday,
                period_no=e.period_no, span=e.span,
                room_id=e.room_id, locked=e.locked,
            )
            for e in db.scalars(
                select(ScheduleEntry)
                .where(ScheduleEntry.timetable_id == timetable.id)
                .order_by(ScheduleEntry.id)
            )
        )

    return Problem(
        semester_id=semester_id,
        semester_label=semester.label,
        tables=tables,
        classes=classes,
        teachers=teachers,
        rooms=rooms,
        units=units,
        assignments=assignments,
        fixed_entries=fixed,
    )
