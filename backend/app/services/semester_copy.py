"""開新學期:從既有學期複製資料。

依 FK 依賴逐層複製並建立 舊id→新id 對照,確保新學期資料完全獨立(見 D3 學期快照)。
可勾選複製項目;班級可選年級進位(超過該學制最高年級者視為畢業,不複製)。
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import (
    ClassTrack,
    ClassUnit,
    Room,
    Subject,
    Teacher,
    TeacherTimeRule,
)
from app.models.constraint import ConstraintConfig
from app.models.period import Period, PeriodTable
from app.models.semester import Semester

# 各學制最高年級(進位後超過即畢業)
TRACK_MAX_GRADE = {
    ClassTrack.elementary.value: 6,
    ClassTrack.junior_high.value: 3,
    ClassTrack.senior_high.value: 3,
    ClassTrack.comprehensive.value: 3,
    ClassTrack.vocational.value: 3,
}


@dataclass
class CopyOptions:
    period_tables: bool = True
    subjects: bool = True
    teachers: bool = True
    rooms: bool = True
    classes: bool = True
    grade_promotion: bool = True
    # 軟約束權重(constraint_configs)。不帶的話新學期會悄悄回到預設值,
    # 上學期調好的偏好設定就白調了(M6-4)。
    constraint_config: bool = True


def copy_semester(
    db: Session,
    source: Semester,
    academic_year: int,
    term: int,
    opts: CopyOptions,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Semester:
    """複製 source 到新學期。呼叫端負責檢查目標學年學期未重複、並 commit。

    起訖日必須明確給:它不能沿用來源學期(那是上學期的日期),但少了它,請假展開、
    今日看板、代課的「已上過」判定全部失準——而且畫面上看不出哪裡不對(M6-4)。
    """
    new = Semester(
        academic_year=academic_year, term=term,
        start_date=start_date, end_date=end_date,
    )
    db.add(new)
    db.flush()

    if opts.constraint_config:
        for cc in db.scalars(
            select(ConstraintConfig).where(ConstraintConfig.semester_id == source.id)
        ):
            db.add(ConstraintConfig(semester_id=new.id, key=cc.key, value=cc.value))

    table_map: dict[int, int] = {}
    if opts.period_tables:
        for pt in source.period_tables:
            npt = PeriodTable(
                semester_id=new.id, name=pt.name,
                num_weekdays=pt.num_weekdays, is_default=pt.is_default,
            )
            for p in pt.periods:
                npt.periods.append(
                    Period(
                        weekday=p.weekday, period_no=p.period_no, name=p.name,
                        start_time=p.start_time, end_time=p.end_time, type=p.type,
                    )
                )
            db.add(npt)
            db.flush()
            table_map[pt.id] = npt.id

    subject_map: dict[int, Subject] = {}  # 舊 subject id → 新 Subject
    if opts.subjects:
        for s in db.scalars(select(Subject).where(Subject.semester_id == source.id)):
            ns = Subject(
                semester_id=new.id, name=s.name, domain=s.domain,
                required_room_type=s.required_room_type, default_block_size=s.default_block_size,
                is_major=s.is_major,
            )
            db.add(ns)
            db.flush()
            subject_map[s.id] = ns

    teacher_map: dict[int, int] = {}
    if opts.teachers:
        for t in db.scalars(select(Teacher).where(Teacher.semester_id == source.id)):
            nt = Teacher(
                semester_id=new.id, name=t.name, id_last4=t.id_last4,
                base_periods=t.base_periods, admin_title=t.admin_title,
                admin_reduction=t.admin_reduction, is_external=t.is_external,
                is_active=t.is_active,
                # 帳號綁定與聯絡資訊跨學期延續(user_id 唯一性以 semester 為範圍,不衝突)
                email=t.email, phone=t.phone, line_id=t.line_id, user_id=t.user_id,
            )
            # 任教科目(僅在科目也複製時對應)
            nt.subjects = [subject_map[s.id] for s in t.subjects if s.id in subject_map]
            for r in t.time_rules:
                nt.time_rules.append(
                    TeacherTimeRule(weekday=r.weekday, period_no=r.period_no, rule_type=r.rule_type)
                )
            db.add(nt)
            db.flush()
            teacher_map[t.id] = nt.id

    if opts.rooms:
        for room in db.scalars(select(Room).where(Room.semester_id == source.id)):
            nr = Room(
                semester_id=new.id, name=room.name, room_type=room.room_type,
                capacity=room.capacity,
            )
            nr.subjects = [subject_map[s.id] for s in room.subjects if s.id in subject_map]
            db.add(nr)

    if opts.classes:
        for c in db.scalars(select(ClassUnit).where(ClassUnit.semester_id == source.id)):
            grade = c.grade
            if opts.grade_promotion:
                grade += 1
                if grade > TRACK_MAX_GRADE.get(c.track, 12):
                    continue  # 畢業年級,不複製
            db.add(
                ClassUnit(
                    semester_id=new.id, grade=grade, name=c.name, track=c.track,
                    department=c.department, student_count=c.student_count,
                    homeroom_teacher_id=teacher_map.get(c.homeroom_teacher_id or -1),
                    period_table_id=table_map.get(c.period_table_id or -1),
                )
            )

    db.flush()
    return new
