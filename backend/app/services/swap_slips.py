"""調課通知單(教師調課單、班級調課單)的資料組裝(v1.2.2)。

版面照使用學校現行的紙本:一張週課表,只在「有異動的格子」寫上
「日期 / 科目 / 實際上課的老師 / [調月/日_星期節次]」,中括號指向對調的另一節
(例如 [調10/30_56] = 10/30 星期五第 6 節;v1.3.5 起日期寫成 10/30,原本是 10-30)。
格線與跨週分頁等共用部分見 `slip_layout`。

**一筆調課 = 兩個異動格。** 甲請假那節改由乙上;乙原本那節改由甲上。
三角調課(v1.4.20)是三格:甲那節由乙上、乙那節由丙上、丙那節由甲上;
記號指向「來上的老師自己空出來的那一節」。

- 教師調課單:每位老師一張,只列他「要去上」的那一格(空出來的那一格不列——
  他那節不用去,紙本上也沒有)。
- 班級調課單:每個班一張,列該班所有異動格。

**科目怎麼寫。** 同班互調時,科目跟著老師走(學生只是兩科前後對換):乙在甲那節上乙自己的科目。
跨班對調時乙去的是甲的班、上的是甲那一節的課,科目沿用該節原本的科目。

本模組只讀,不寫資料庫;資料全部來自已成立調課的快照欄位與節次表。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.leave import AffectedPeriod, AffectedStatus, LeaveRequest, LeaveStatus
from app.models.substitution import Substitution, SubstitutionType
from app.models.timetable import ScheduleEntry
from app.services import swap_legs
from app.services.slip_layout import Move, SlipError, Slips, Tables, assemble, school_title


def _md(d: date) -> str:
    """記號裡的日期照習慣寫成 10/30(不補零)。"""
    return f"{d.month}/{d.day}"


def _moves(db: Session, tables: Tables, ap: AffectedPeriod, sub: Substitution) -> list[Move]:
    """這筆調課換人上的每一格(互調兩格、三角調課三格,見 `swap_legs`)。"""
    legs = swap_legs.legs(ap, sub)
    if (sub.handler is None or len(legs) < 2
            or (sub.is_triangle and (sub.tri_teacher is None or len(legs) < 3))):
        raise SlipError("這筆調課資料不完整(對調教師或補課節次已被刪除),無法列印")

    def table(leg_entry: int | None, assignment: int | None) -> int | None:
        if assignment is None and leg_entry is not None:
            entry = db.get(ScheduleEntry, leg_entry)
            assignment = entry.course_assignment_id if entry else ap.course_assignment_id
        return tables.of_assignment(assignment or ap.course_assignment_id)

    out: list[Move] = []
    for leg in legs:
        assert leg.teacher_id is not None and leg.back_date is not None
        assert leg.back_period_no is not None
        back_wd = leg.back_date.isoweekday()
        back_ord = tables.ordinal(table(leg.back_entry_id, leg.back_assignment_id),
                                  back_wd, leg.back_period_no)
        out.append(Move(
            date=leg.date, period_no=leg.period_no, class_names=leg.class_names,
            subject_name=leg.subject_taught, teacher_id=leg.teacher_id,
            teacher_name=leg.teacher_name, table_id=table(leg.entry_id, leg.assignment_id),
            code=f"調{_md(leg.back_date)}_{back_wd}{back_ord}",
        ))
    return out


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
