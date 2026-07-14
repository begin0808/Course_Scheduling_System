"""今日調代課看板與調代課日誌(M4-4)。

這一層把「特定日期的受影響節次 + 其處置」攤平成一列列可讀的紀錄,供兩個出口共用:

1. **今日看板**:某一天全校的異動——誰請假、哪一節、由誰接手、教室在哪。
2. **歷史日誌**:依教師/日期/假別篩選的查詢。

資料真相仍在 `affected_period`(受影響節次快照)與 `substitution`(處置決定);這裡只做
join + 攤平 + 中文標籤,不新增任何真相。看板的「今日」以學校時區(config.tz)判定,
不是 UTC——台灣凌晨的 UTC 仍是前一天(architecture.md D6)。
"""

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import clock
from app.models.leave import (
    AFFECTED_STATUS_CN,
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.substitution import SUBSTITUTION_TYPE_CN, Substitution
from app.services import leaves

# 欄位名 date/start_time 會遮蔽同名型別,故以別名標註型別
_Date = date
_Time = time

# 歷史查詢的保護性上限(M6-5):一整年不篩選地查會是數千筆。取最新 N 筆,
# 要看更早的請縮小日期區間;完整分頁 UI 留 v1.2。
MAX_ROWS = 1000


@dataclass(frozen=True, slots=True)
class LogEntry:
    """一列調代課紀錄:一個受影響節次 + 它的處置(若已處置)。"""

    affected_period_id: int
    date: _Date
    weekday: int
    period_no: int
    period_name: str
    start_time: _Time | None
    end_time: _Time | None
    class_names: str
    subject_name: str
    room_name: str
    absent_teacher_id: int
    absent_teacher_name: str
    leave_type: str
    leave_type_label: str
    status: str
    status_label: str
    disposed: bool  # 是否已有處置(代課/調課/併班/自習/不處理)
    sub_type: str | None
    sub_type_label: str | None
    handler_teacher_id: int | None
    handler_name: str | None
    counts_toward_hours: bool | None
    swap_date: _Date | None
    swap_period_name: str
    swap_class_names: str
    swap_subject_name: str
    note: str


def school_today() -> date:
    """學校所在時區的今天(config.tz,預設 Asia/Taipei)。"""
    return clock.school_today()


def _subs_map(db: Session, affected_ids: list[int]) -> dict[int, Substitution]:
    """一次撈齊這些受影響節次的處置,免逐列 join。"""
    if not affected_ids:
        return {}
    rows = db.scalars(
        select(Substitution).where(Substitution.affected_period_id.in_(affected_ids))
    )
    return {s.affected_period_id: s for s in rows}


def _build(ap: AffectedPeriod, sub: Substitution | None) -> LogEntry:
    leave = ap.leave_request
    status = leaves.effective_status(ap.status, ap.date, ap.end_time)
    handler_id = sub.handler_teacher_id if sub else ap.handler_teacher_id
    handler_name = None
    if sub is not None and sub.handler is not None:
        handler_name = sub.handler.name
    elif ap.handler is not None:
        handler_name = ap.handler.name
    return LogEntry(
        affected_period_id=ap.id,
        date=ap.date,
        weekday=ap.weekday,
        period_no=ap.period_no,
        period_name=ap.period_name,
        start_time=ap.start_time,
        end_time=ap.end_time,
        class_names=ap.class_names,
        subject_name=ap.subject_name,
        room_name=ap.room_name,
        absent_teacher_id=leave.teacher_id,
        absent_teacher_name=leave.teacher.name if leave.teacher else "(已移除)",
        leave_type=leave.leave_type,
        leave_type_label=LEAVE_TYPE_CN.get(leave.leave_type, leave.leave_type),
        status=status,
        status_label=AFFECTED_STATUS_CN.get(status, status),
        disposed=sub is not None,
        sub_type=sub.type if sub else None,
        sub_type_label=SUBSTITUTION_TYPE_CN.get(sub.type) if sub else None,
        handler_teacher_id=handler_id,
        handler_name=handler_name,
        counts_toward_hours=sub.counts_toward_hours if sub else None,
        swap_date=sub.swap_date if sub else None,
        swap_period_name=sub.swap_period_name if sub else "",
        swap_class_names=sub.swap_class_names if sub else "",
        swap_subject_name=sub.swap_subject_name if sub else "",
        note=ap.note or (sub.note if sub else ""),
    )


def daily_board(db: Session, semester_id: int, on: date) -> list[LogEntry]:
    """某一天全校的調代課異動,依節次、班級排序。

    只看仍有效(未銷假)的假單;已因銷假取消的節次不列(那天沒有異動)。
    包含尚未處置(待處理)的節次,好讓組長一眼看出還有幾節沒排代課。
    """
    rows = db.scalars(
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(
            AffectedPeriod.semester_id == semester_id,
            AffectedPeriod.date == on,
            LeaveRequest.status == LeaveStatus.registered.value,
            AffectedPeriod.status != AffectedStatus.cancelled.value,
        )
        .order_by(AffectedPeriod.period_no, AffectedPeriod.class_names)
    ).unique().all()
    subs = _subs_map(db, [r.id for r in rows])
    return [_build(r, subs.get(r.id)) for r in rows]


def query(
    db: Session,
    semester_id: int,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    teacher_id: int | None = None,
    leave_type: str | None = None,
    limit: int = MAX_ROWS,
) -> list[LogEntry]:
    """歷史查詢:依日期區間、教師、假別篩選,最新在前。

    `teacher_id` 同時比對「請假的當事人」與「接手代課的教師」——查一位教師時,
    他缺的課與他代的課都算與他相關。

    `limit` 是保護性上限(M6-5):不篩選地查一整年,會把數千筆一次拉進記憶體再序列化。
    取最新的 N 筆(呼叫端可縮小日期區間看更早的);完整分頁 UI 留 v1.2。
    """
    stmt = (
        select(AffectedPeriod)
        .join(LeaveRequest, AffectedPeriod.leave_request_id == LeaveRequest.id)
        .where(AffectedPeriod.semester_id == semester_id)
    )
    if date_from is not None:
        stmt = stmt.where(AffectedPeriod.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(AffectedPeriod.date <= date_to)
    if leave_type is not None:
        stmt = stmt.where(LeaveRequest.leave_type == leave_type)
    if teacher_id is not None:
        stmt = stmt.where(or_(
            LeaveRequest.teacher_id == teacher_id,
            AffectedPeriod.handler_teacher_id == teacher_id,
        ))
    rows = db.scalars(
        stmt.order_by(AffectedPeriod.date.desc(), AffectedPeriod.period_no).limit(limit)
    ).unique().all()
    subs = _subs_map(db, [r.id for r in rows])
    return [_build(r, subs.get(r.id)) for r in rows]
