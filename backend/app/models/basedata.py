"""基礎資料 model:教師、科目、場地、班級、教師時段規則。

皆隸屬於某學期(semester_id 範圍,見 D3 學期快照)。
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class RoomType(enum.StrEnum):
    normal = "normal"      # 普通教室
    special = "special"    # 專科教室
    workshop = "workshop"  # 實習工場
    outdoor = "outdoor"    # 戶外


class ClassTrack(enum.StrEnum):
    elementary = "elementary"      # 國小
    junior_high = "junior_high"    # 國中
    senior_high = "senior_high"    # 普通型高中
    comprehensive = "comprehensive"  # 綜合型高中
    vocational = "vocational"      # 技術型高中


class TeacherRuleType(enum.StrEnum):
    unavailable = "unavailable"  # 不可排(硬約束)
    avoid = "avoid"              # 盡量避開(軟約束)
    prefer = "prefer"            # 偏好(軟約束)


# ── 多對多關聯表 ──────────────────────
teacher_subjects = Table(
    "teacher_subjects",
    Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)

room_subjects = Table(
    "room_subjects",
    Base.metadata,
    Column("room_id", ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 領域/群別
    required_room_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_block_size: Mapped[int] = mapped_column(Integer, default=1)  # 預設連堂長度(1=不連堂)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(32))
    base_periods: Mapped[int] = mapped_column(Integer, default=0)  # 基本鐘點
    admin_title: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 行政職稱
    admin_reduction: Mapped[int] = mapped_column(Integer, default=0)  # 行政減課節數
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)  # 外聘/業界師資
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 在職

    subjects: Mapped[list[Subject]] = relationship(secondary=teacher_subjects, lazy="selectin")
    time_rules: Mapped[list["TeacherTimeRule"]] = relationship(
        back_populates="teacher", cascade="all, delete-orphan", lazy="selectin"
    )


class TeacherTimeRule(Base):
    __tablename__ = "teacher_time_rules"
    __table_args__ = (
        UniqueConstraint("teacher_id", "weekday", "period_no", name="uq_teacher_time_rules_cell"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("teachers.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column(Integer)
    period_no: Mapped[int] = mapped_column(Integer)
    rule_type: Mapped[str] = mapped_column(String(20))

    teacher: Mapped[Teacher] = relationship(back_populates="time_rules")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    room_type: Mapped[str] = mapped_column(String(20), default=RoomType.normal.value)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    subjects: Mapped[list[Subject]] = relationship(secondary=room_subjects, lazy="selectin")


class ClassUnit(Base):
    __tablename__ = "class_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = mapped_column(
        ForeignKey("semesters.id", ondelete="CASCADE"), index=True
    )
    grade: Mapped[int] = mapped_column(Integer)       # 年級
    name: Mapped[str] = mapped_column(String(32))     # 班名
    track: Mapped[str] = mapped_column(String(20))    # 學制標籤
    department: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 群科(技高)
    student_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 人數
    homeroom_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    homeroom_teacher: Mapped[Teacher | None] = relationship(lazy="selectin")
