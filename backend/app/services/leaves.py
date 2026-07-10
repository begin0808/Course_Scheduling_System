"""請假登記與受影響節次展開(M4-1,architecture.md §5.3)。

**把週循環格展開成日曆日期。** 課表說「王師週三第三節上 301 班國文」;
請假說「王師 11/12 上午請假」。這裡負責把兩者對起來:

1. 走訪請假期間的每一天;
2. 跳過該班節次表沒有的星期(週末,或六日制學校的週六以外);
3. 取出**已發布課表**中該教師當天的每一節課(連堂展開成每一節);
4. 半天假以牆鐘時間區間重疊判定,整天假則全部列入;
5. 寫成 `affected_period` 快照。

只看**已發布**課表:草稿隨時會變,拿草稿去找代課老師沒有意義。
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Room, Subject, Teacher
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
)
from app.models.notification import NotificationType
from app.models.period import Period, PeriodType
from app.models.semester import Semester
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services import notifications
from app.services import period_tables as pt_service

MAX_LEAVE_DAYS = 180  # 產假上限約 8 週;180 天足夠,同時擋住手殘輸入的 2099 年


class LeaveError(Exception):
    """請假單本身不合法(呼叫端轉為 400)。"""


def school_dates(start: date, end: date) -> Iterator[date]:
    """請假期間的每一天(含頭尾)。是否為上課日由節次表決定,不在這裡判斷。"""
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _leave_window(leave: LeaveRequest, day: date) -> tuple[time | None, time | None]:
    """該日的請假時間區間。回傳 (from, to),None 表示該端點沒有限制(整天)。

    只有第一天受 start_time 限制、最後一天受 end_time 限制;中間的日子一律整天。
    「11/12 13:00 ~ 11/14 12:00」= 12 日下午 + 13 日整天 + 14 日上午。
    """
    begin = leave.start_time if day == leave.start_date else None
    finish = leave.end_time if day == leave.end_date else None
    return begin, finish


def _overlaps(period: Period, window: tuple[time | None, time | None]) -> bool:
    """節次是否落在該日的請假區間內。"""
    begin, finish = window
    if begin is None and finish is None:
        return True  # 整天假
    if period.start_time is None or period.end_time is None:
        # 節次表沒填起訖時間就無法判定半天假。寧可多列一節讓組長刪掉,
        # 也不要漏掉一節沒人代課——漏掉的那節會直接變成沒有老師的教室。
        return True
    if finish is not None and period.start_time >= finish:
        return False
    if begin is not None and period.end_time <= begin:
        return False
    return True


def _published_timetable(db: Session, semester_id: int) -> Timetable | None:
    return db.scalar(
        select(Timetable).where(
            Timetable.semester_id == semester_id,
            Timetable.status == TimetableStatus.published.value,
        )
    )


def _teacher_entries(db: Session, timetable_id: int, teacher_id: int) -> list[ScheduleEntry]:
    return list(
        db.scalars(
            select(ScheduleEntry)
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
            .where(
                ScheduleEntry.timetable_id == timetable_id,
                AssignmentTeacher.teacher_id == teacher_id,
            )
            .order_by(ScheduleEntry.weekday, ScheduleEntry.period_no)
        ).unique()
    )


class _Expander:
    """一次展開所需的節次表/班級/科目/場地查詢,全部先撈好再組裝。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._periods: dict[int, dict[tuple[int, int], Period]] = {}
        self._num_weekdays: dict[int, int] = {}

    def table_of(self, assignment: CourseAssignment) -> int | None:
        members = assignment.scheduling_unit.members
        if not members:
            return None
        table = pt_service.resolve_period_table(self.db, members[0].class_unit)
        return table.id if table else None

    def _load_table(self, table_id: int) -> dict[tuple[int, int], Period]:
        if table_id not in self._periods:
            rows = list(self.db.scalars(select(Period).where(Period.period_table_id == table_id)))
            self._periods[table_id] = {(p.weekday, p.period_no): p for p in rows}
            self._num_weekdays[table_id] = max((p.weekday for p in rows), default=0)
        return self._periods[table_id]

    def is_school_day(self, table_id: int, day: date) -> bool:
        """節次表沒有這個星期 = 不上課(週末;六日制學校則週六有課)。"""
        self._load_table(table_id)
        return day.isoweekday() <= self._num_weekdays[table_id]

    def period(self, table_id: int, weekday: int, period_no: int) -> Period | None:
        return self._load_table(table_id).get((weekday, period_no))

    def describe(self, a: CourseAssignment, entry: ScheduleEntry) -> tuple[str, str, str]:
        subject = self.db.get(Subject, a.subject_id)
        classes = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
        room_id = entry.room_id if entry.room_id is not None else a.room_id
        room = self.db.get(Room, room_id) if room_id else None
        return (subject.name if subject else ""), classes, (room.name if room else "")


def expand(db: Session, leave: LeaveRequest) -> list[AffectedPeriod]:
    """依已發布課表展開受影響節次。呼叫端負責 commit。

    課表尚未發布時回傳空清單——假單照樣成立,只是沒有課要處理。
    """
    timetable = _published_timetable(db, leave.semester_id)
    if timetable is None:
        return []

    entries = _teacher_entries(db, timetable.id, leave.teacher_id)
    if not entries:
        return []

    exp = _Expander(db)
    out: list[AffectedPeriod] = []
    seen: set[tuple[date, int, str]] = set()

    for day in school_dates(leave.start_date, leave.end_date):
        window = _leave_window(leave, day)
        weekday = day.isoweekday()
        for entry in entries:
            if entry.weekday != weekday:
                continue
            a = entry.assignment
            table_id = exp.table_of(a)
            if table_id is None or not exp.is_school_day(table_id, day):
                continue

            subject_name, class_names, room_name = exp.describe(a, entry)
            # 連堂佔用連續數節,逐節展開:代課是逐節找人的
            for k in range(entry.span):
                period = exp.period(table_id, weekday, entry.period_no + k)
                if period is None or period.type != PeriodType.regular.value:
                    continue
                if not _overlaps(period, window):
                    continue
                key = (day, period.period_no, class_names)
                if key in seen:
                    continue
                seen.add(key)
                out.append(AffectedPeriod(
                    leave_request_id=leave.id, semester_id=leave.semester_id,
                    date=day, weekday=weekday, period_no=period.period_no,
                    period_name=period.name, start_time=period.start_time,
                    end_time=period.end_time,
                    subject_name=subject_name, class_names=class_names, room_name=room_name,
                    schedule_entry_id=entry.id, course_assignment_id=a.id,
                    status=AffectedStatus.pending.value,
                ))

    out.sort(key=lambda p: (p.date, p.period_no))
    return out


def validate(semester: Semester, start: date, end: date) -> None:
    if end < start:
        raise LeaveError("結束日期不可早於開始日期")
    if (end - start).days + 1 > MAX_LEAVE_DAYS:
        raise LeaveError(f"單張假單最長 {MAX_LEAVE_DAYS} 天")
    if semester.start_date is None or semester.end_date is None:
        raise LeaveError("學期尚未設定起訖日期,無法登記請假")
    if start < semester.start_date or end > semester.end_date:
        raise LeaveError(
            f"請假日期須落在學期範圍內({semester.start_date} ~ {semester.end_date})"
        )


def create(
    db: Session,
    semester: Semester,
    teacher: Teacher,
    *,
    leave_type: str,
    start_date: date,
    start_time: time | None,
    end_date: date,
    end_time: time | None,
    reason: str,
    created_by_user_id: int | None,
    created_by_name: str,
    notify_teacher: bool,
) -> LeaveRequest:
    """登記請假並展開受影響節次。呼叫端負責 commit。"""
    validate(semester, start_date, end_date)
    if start_date == end_date and start_time and end_time and end_time <= start_time:
        raise LeaveError("結束時間不可早於開始時間")

    leave = LeaveRequest(
        semester_id=semester.id, teacher_id=teacher.id, leave_type=leave_type,
        start_date=start_date, start_time=start_time,
        end_date=end_date, end_time=end_time,
        reason=reason, created_by_user_id=created_by_user_id, created_by_name=created_by_name,
    )
    db.add(leave)
    db.flush()

    for period in expand(db, leave):
        db.add(period)
    db.flush()

    if notify_teacher:
        # 組長代登:當事人要知道有人替他請了假
        notifications.notify(
            db, semester_id=semester.id, teacher_id=teacher.id,
            type=NotificationType.leave_registered,
            title=f"{created_by_name} 已為您登記{LEAVE_TYPE_CN[leave.leave_type]}",
            body=f"{range_text(leave)},共 {len(leave.affected_periods)} 節課受影響",
        )
    return leave


def cancel(db: Session, leave: LeaveRequest, *, actor_name: str) -> list[AffectedPeriod]:
    """銷假:級聯取消所有受影響節次,並通知已被指派的代課教師。

    回傳「原本已指派、現在被取消」的節次。已完成的節次不動——那堂課已經上過了,
    事後銷假不能把歷史抹掉(鐘點統計要照算)。
    """
    if leave.status == LeaveStatus.cancelled.value:
        raise LeaveError("此假單已銷假")

    leave.status = LeaveStatus.cancelled.value
    leave.cancelled_at = datetime.now().astimezone()

    revoked: list[AffectedPeriod] = []
    for period in leave.affected_periods:
        if period.status == AffectedStatus.completed.value:
            continue
        if period.status == AffectedStatus.resolved.value:
            revoked.append(period)
        period.status = AffectedStatus.cancelled.value

    # 一位代課老師可能被取消好幾節,合併成一封通知
    by_handler: dict[int, list[AffectedPeriod]] = {}
    for period in revoked:
        if period.handler_teacher_id:
            by_handler.setdefault(period.handler_teacher_id, []).append(period)

    for handler_id, periods in by_handler.items():
        detail = "、".join(f"{p.date} {p.period_name}({p.class_names}{p.subject_name})"
                           for p in periods)
        notifications.notify(
            db, semester_id=leave.semester_id, teacher_id=handler_id,
            type=NotificationType.substitution_cancelled,
            title=f"原訂代課已取消({leave.teacher.name} 銷假)",
            body=f"以下 {len(periods)} 節課不需要您代課了:{detail}",
        )

    notifications.notify(
        db, semester_id=leave.semester_id, teacher_id=leave.teacher_id,
        type=NotificationType.leave_cancelled,
        title=f"{actor_name} 已為您銷假" if actor_name != leave.teacher.name else "銷假完成",
        body=f"{range_text(leave)} 的{LEAVE_TYPE_CN[leave.leave_type]}已銷假",
    )
    db.flush()
    return revoked


def range_text(leave: LeaveRequest) -> str:
    if leave.start_date == leave.end_date:
        if leave.is_half_day:
            begin = leave.start_time.strftime("%H:%M") if leave.start_time else "上課起"
            finish = leave.end_time.strftime("%H:%M") if leave.end_time else "放學"
            return f"{leave.start_date} {begin}~{finish}"
        return f"{leave.start_date} 整天"
    return f"{leave.start_date} ~ {leave.end_date}"


def find_teacher(db: Session, semester_id: int, teacher_id: int) -> Teacher | None:
    return db.scalar(
        select(Teacher).where(Teacher.id == teacher_id, Teacher.semester_id == semester_id)
    )
