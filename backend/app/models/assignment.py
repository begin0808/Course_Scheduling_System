"""配課領域 model:排課單位、配課、配課教師、連堂規則。

排課單位(scheduling_unit)是支撐五學制的核心抽象(architecture.md D1):
- `single`:單一班級的課(國小包班=導師在自己班的大量 single 配課)
- `group`:跑班群組(多班聯排,群組內配課由求解器強制排在同一時段)

配課(course_assignment)掛在排課單位上,而非直接掛班級,故單班與跑班共用一套 schema。
"""

import enum

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.basedata import ClassUnit, Room, Subject, Teacher


class SchedulingUnitType(enum.StrEnum):
    single = "single"  # 單一班級
    group = "group"    # 跑班群組(多班聯排)


class SchedulingUnit(Base):
    __tablename__ = "scheduling_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    unit_type: Mapped[str] = mapped_column(String(10), default=SchedulingUnitType.single.value)
    name: Mapped[str] = mapped_column(String(64))  # single=班名;group=群組名(如「高二多元選修」)

    members: Mapped[list["SchedulingUnitMember"]] = relationship(
        back_populates="scheduling_unit", cascade="all, delete-orphan", lazy="selectin"
    )
    assignments: Mapped[list["CourseAssignment"]] = relationship(
        back_populates="scheduling_unit", cascade="all, delete-orphan", lazy="selectin"
    )


class SchedulingUnitMember(Base):
    __tablename__ = "scheduling_unit_members"
    __table_args__ = (
        UniqueConstraint(
            "scheduling_unit_id", "class_unit_id", name="uq_scheduling_unit_members_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scheduling_unit_id: Mapped[int] = mapped_column(
        ForeignKey("scheduling_units.id", ondelete="CASCADE"), index=True
    )
    class_unit_id: Mapped[int] = mapped_column(
        ForeignKey("class_units.id", ondelete="CASCADE"), index=True
    )

    scheduling_unit: Mapped[SchedulingUnit] = relationship(back_populates="members")
    class_unit: Mapped[ClassUnit] = relationship(lazy="selectin")


class CourseAssignment(Base):
    __tablename__ = "course_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # semester_id 為去正規化欄位,方便以學期為範圍查詢(隨排課單位同屬一學期)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    scheduling_unit_id: Mapped[int] = mapped_column(
        ForeignKey("scheduling_units.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    periods_per_week: Mapped[int] = mapped_column(Integer)  # 每週節數
    # 場地需求:類型(普通/專科/實習工場/戶外)或指定場地;lock_room 表是否綁死該場地
    required_room_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lock_room: Mapped[bool] = mapped_column(Boolean, default=False)

    scheduling_unit: Mapped[SchedulingUnit] = relationship(back_populates="assignments")
    subject: Mapped[Subject] = relationship(lazy="selectin")
    room: Mapped[Room | None] = relationship(lazy="selectin")
    teachers: Mapped[list["AssignmentTeacher"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", lazy="selectin"
    )
    block_rules: Mapped[list["BlockRule"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan", lazy="selectin"
    )


class AssignmentTeacher(Base):
    __tablename__ = "assignment_teachers"
    __table_args__ = (
        UniqueConstraint(
            "course_assignment_id", "teacher_id", name="uq_assignment_teachers_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    is_lead: Mapped[bool] = mapped_column(Boolean, default=True)  # 主教(False=協同)

    assignment: Mapped[CourseAssignment] = relationship(back_populates="teachers")
    teacher: Mapped[Teacher] = relationship(lazy="selectin")


class BlockRule(Base):
    __tablename__ = "block_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("course_assignments.id", ondelete="CASCADE"), index=True
    )
    block_size: Mapped[int] = mapped_column(Integer)      # 連堂長度(2-4)
    count_per_week: Mapped[int] = mapped_column(Integer)  # 每週次數

    assignment: Mapped[CourseAssignment] = relationship(back_populates="block_rules")
