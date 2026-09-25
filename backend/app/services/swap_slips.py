"""調課通知單(教師調課單、班級調課單)的資料組裝(v1.2.2)。

版面照使用學校現行的紙本:一張週課表,只在「有異動的格子」寫上
「日期 / 科目 / 實際上課的老師 / [調MM-DD_星期節次]」,中括號指向對調的另一節。
格線與跨週分頁等共用部分見 `slip_layout`。

**一筆調課 = 兩個異動格。** 甲請假那節改由乙上;乙原本那節改由甲上。

- 教師調課單:每位老師一張,只列他「要去上」的那一格(空出來的那一格不列——
  他那節不用去,紙本上也沒有)。
- 班級調課單:每個班一張,列該班所有異動格。

**科目怎麼寫。** 同班互調時,科目跟著老師走(學生只是兩科前後對換):乙在甲那節上乙自己的科目。
跨班對調時乙去的是甲的班、上的是甲那一節的課,科目沿用該節原本的科目。

本模組只讀,不寫資料庫;資料全部來自已成立調課的快照欄位與節次表。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services.slip_layout import Move, SlipError, Slips, Tables, assemble, school_title


def _moves(db: Session, tables: Tables, ap: AffectedPeriod, sub: Substitution) -> list[Move]:
    absent = ap.leave_request.teacher
    partner = sub.handler
    if partner is None or sub.swap_date is None or sub.swap_period_no is None:
        raise SlipError("這筆調課資料不完整(對調教師或補課節次已被刪除),無法列印")
    same_class = ap.class_names == sub.swap_class_names
    leave_table = tables.of_assignment(ap.course_assignment_id)
    entry = db.get(ScheduleEntry, sub.swap_entry_id) if sub.swap_entry_id else None
    swap_table = tables.of_assignment(entry.course_assignment_id) if entry else leave_table
    swap_wd, leave_wd = sub.swap_date.isoweekday(), ap.date.isoweekday()
    swap_ord = tables.ordinal(swap_table, swap_wd, sub.swap_period_no)
    leave_ord = tables.ordinal(leave_table, leave_wd, ap.period_no)
    return [
        Move(  # 請假那節:改由乙上
            date=ap.date, period_no=ap.period_no, class_names=ap.class_names,
            subject_name=sub.swap_subject_name if same_class else ap.subject_name,
            teacher_id=partner.id, teacher_name=partner.name, table_id=leave_table,
            code=f"調{sub.swap_date:%m-%d}_{swap_wd}{swap_ord}",
        ),
        Move(  # 乙原本那節:改由甲上
            date=sub.swap_date, period_no=sub.swap_period_no, class_names=sub.swap_class_names,
            subject_name=ap.subject_name if same_class else sub.swap_subject_name,
            teacher_id=absent.id, teacher_name=absent.name, table_id=swap_table,
            code=f"調{ap.date:%m-%d}_{leave_wd}{leave_ord}",
        ),
    ]


def build(db: Session, semester_id: int, affected_ids: list[int]) -> Slips:
    """把指定的調課組成通知單:先每位老師一張(依出場順序),再每個班一張。

    非調課、已撤回或已銷假的節次略過;一筆有效的調課都沒有時拋 `SlipError`。
    """
    rows = db.execute(
        select(AffectedPeriod, Substitution)
        .join(Substitution, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.id.in_(affected_ids),
            AffectedPeriod.semester_id == semester_id,
            Substitution.type == SubstitutionType.swap.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        )
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ).all()
    if not rows:
        raise SlipError("選取的節次中沒有已成立的調課")

    tables = Tables(db)
    moves: list[Move] = []
    for ap, sub in rows:
        moves.extend(_moves(db, tables, ap, sub))

    by_teacher: dict[int, list[Move]] = {}
    by_class: dict[str, list[Move]] = {}
    for m in moves:
        by_teacher.setdefault(m.teacher_id, []).append(m)
        by_class.setdefault(m.class_names, []).append(m)

    result = Slips(title=school_title(db, semester_id), kind="swap")
    for ms in by_teacher.values():
        result.slips.append(assemble(tables, "teacher", ms[0].teacher_name, ms, _actor))
    for ms in by_class.values():
        result.slips.append(assemble(tables, "class", "", ms, _actor))
    return result


def _actor(m: Move) -> str:
    """調課單的第三行:實際上課的老師(教師單與班級單相同)。"""
    return m.teacher_name
