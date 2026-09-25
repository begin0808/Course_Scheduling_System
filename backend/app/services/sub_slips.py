"""代課通知單(教師代課單、班級代課單)的資料組裝(v1.2.5)。

版面照使用學校現行的紙本:一張週課表,只在「有代課的格子」寫上
「日期 / 科目 / 班級[代]」(教師單)或「日期 / 科目 / 代課老師[代]」(班級單)。
表頭寫代課教師(或代課班級)、請假教師、請假起訖、假別與計費方式。

**一筆代課 = 一個異動格**(不像調課要動兩格):請假那節改由代課老師上。
併班比照辦理,標記寫「[併]」。

- 教師代課單:同一張假單裡,每位代課老師一張。
- 班級代課單:同一張假單裡,每個班一張。
- 跨週的假單一週一頁(共用 `slip_layout`)。

表頭的請假資訊逐張假單不同,故分組時把假單一起當 key;跨假單批次列印時
會各自成張,不會把兩位請假教師混在同一張紙上。

本模組只讀,不寫資料庫。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.substitution import Substitution, SubstitutionType
from app.services.slip_layout import Move, Slip, SlipError, Slips, Tables, assemble, school_title

# 代課單印得出來的處置:找人代(代課)與併入他班(併班),兩者都有「接手的老師」
_PRINTABLE = (SubstitutionType.substitute.value, SubstitutionType.merge.value)
_MARK = {SubstitutionType.substitute.value: "[代]", SubstitutionType.merge.value: "[併]"}


def _teacher_actor(m: Move) -> str:
    """教師代課單的第三行:去哪一班代課。"""
    return f"{m.class_names}{m.mark}"


def _class_actor(m: Move) -> str:
    """班級代課單的第三行:這一節改由誰上。"""
    return f"{m.teacher_name}{m.mark}"


def _header(slip: Slip, leave: LeaveRequest, funding: str) -> Slip:
    """表頭改寫成紙本的樣子:日期用請假起訖(不是只有被代的那幾天)。"""
    slip.absent_teacher_name = leave.teacher.name
    slip.leave_type_name = LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type)
    slip.funding_label = funding
    slip.date_from = leave.start_date
    slip.date_to = leave.end_date
    return slip


def build(db: Session, semester_id: int, affected_ids: list[int]) -> Slips:
    """把指定的代課/併班組成通知單:先每位代課老師一張,再每個班一張。

    非代課/併班、沒有指定教師、已撤回或已銷假的節次略過;一筆都沒有時拋 `SlipError`。
    """
    rows = db.execute(
        select(AffectedPeriod, Substitution)
        .join(Substitution, Substitution.affected_period_id == AffectedPeriod.id)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.id.in_(affected_ids),
            AffectedPeriod.semester_id == semester_id,
            Substitution.type.in_(_PRINTABLE),
            Substitution.handler_teacher_id.is_not(None),
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            LeaveRequest.status == LeaveStatus.registered.value,
        )
        .order_by(AffectedPeriod.date, AffectedPeriod.period_no)
    ).all()
    if not rows:
        raise SlipError("選取的節次中沒有已指派的代課")

    tables = Tables(db)
    leaves: dict[int, LeaveRequest] = {}
    fundings: dict[int, str] = {}                     # 假單 → 計費方式(取第一個有填的)
    by_teacher: dict[tuple[int, int], list[Move]] = {}
    by_class: dict[tuple[int, str], list[Move]] = {}
    for ap, sub in rows:
        handler = sub.handler
        if handler is None:                           # 指派後教師被刪:略過,不讓整批印不出來
            continue
        leave = ap.leave_request
        leaves.setdefault(leave.id, leave)
        if sub.funding_source and not fundings.get(leave.id):
            fundings[leave.id] = sub.funding_source
        move = Move(
            date=ap.date, period_no=ap.period_no, class_names=ap.class_names,
            subject_name=ap.subject_name, teacher_id=handler.id, teacher_name=handler.name,
            table_id=tables.of_assignment(ap.course_assignment_id),
            mark=_MARK.get(sub.type, ""),
        )
        by_teacher.setdefault((leave.id, handler.id), []).append(move)
        by_class.setdefault((leave.id, ap.class_names), []).append(move)
    if not by_teacher:
        raise SlipError("選取的節次中沒有已指派的代課")

    result = Slips(title=school_title(db), kind="substitute")
    for (leave_id, _), ms in by_teacher.items():
        slip = assemble(tables, "teacher", ms[0].teacher_name, ms, _teacher_actor)
        result.slips.append(_header(slip, leaves[leave_id], fundings.get(leave_id, "")))
    for (leave_id, _), ms in by_class.items():
        slip = assemble(tables, "class", "", ms, _class_actor)
        result.slips.append(_header(slip, leaves[leave_id], fundings.get(leave_id, "")))
    return result
