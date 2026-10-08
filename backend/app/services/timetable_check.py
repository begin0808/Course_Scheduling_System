"""課表檢查:對一份既有課表重跑硬約束(v1.2.18,使用者回報 #40、#41)。

手動排入每一步都有 `conflict_checker` 把關、自動排課的結果也合規,所以正常操作排出來的
課表不會有衝堂。會出問題的是「課表排好之後,規則或資料又改了」——事後把某節設成教師
不可排、改了配課的老師或場地、調低每日上限——這時課表與規則已經矛盾,畫面上卻沒有任何
地方看得出來,發布也只檢查有沒有排完。

這裡直接沿用求解器的 `validator`(與自動排課同一套定義),再做三件事讓它適合給人看:

- **「還沒排完」不算違規**:那是 `timetable_publish.completeness` 的事,發布時本來就會列。
  節數已經排滿、但連堂的切法與設定不同,才會留下來。
- **不檢查鎖定(H9)**:那是「自動排課不可移動鎖定格位」,對一份靜態的課表沒有意義。
- **「需要場地卻未指派」不算違規**:手動排課不會替「需要某類型場地」的課挑教室,
  那只是還沒指定,不是衝突。排進了類型不符的教室才列出。
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import Teacher, TeacherRuleType
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.services.solver_data import load_config, load_problem
from app.solver.problem import AssignmentSpec, Problem, SolvedEntry
from app.solver.validator import Violation, validate

# 給畫面分組用的標題;順序即顯示順序
CODE_LABELS: dict[str, str] = {
    "H1": "班級衝堂",
    "H2": "教師衝堂",
    "H3": "場地衝堂",
    "H4": "教師不可排時段",
    "H5": "排在非上課節次",
    "H6": "連堂跨越午休",
    "H7": "跑班群組未同時段",
    "H8": "節數或連堂與配課不符",
    "H10": "超過每日上限",
    "room_type": "場地類型不符",
    "input": "資料不一致",
}

_WEEKDAYS = "一二三四五六日"


@dataclass(frozen=True, slots=True)
class CheckIssue:
    code: str
    label: str
    message: str


def _keep(v: Violation) -> bool:
    if v.code == "H9":
        return False
    if v.code == "H8":
        # 排入節數少於應排 = 還沒排完,交給完整性檢查;排滿或排超過才是這裡要講的
        placed = sum(v.detail.get("placed", []))
        expected = sum(v.detail.get("expected", []))
        return placed >= expected
    if v.code == "room_type":
        return "room_id" in v.detail  # 沒指派教室不算;排錯類型才算
    return True


def _shape(lengths: list[int]) -> str:
    """[3, 3, 1] → 「3 連堂 2 次、單節 1 節」。"""
    parts = []
    for size in sorted({n for n in lengths if n > 1}, reverse=True):
        parts.append(f"{size} 連堂 {lengths.count(size)} 次")
    singles = lengths.count(1)
    if singles:
        parts.append(f"單節 {singles} 節")
    return "、".join(parts) or "無"


def _message(problem: Problem, spec: AssignmentSpec | None, v: Violation) -> str:
    """validator 的訊息是寫給開發者看的(只有科目、節長用串列);這裡補上班級、改成人話。"""
    if spec is None:
        return v.message
    classes = "、".join(c.name for c in problem.classes_of(spec))
    who = f"{classes}「{spec.subject_name}」" if classes else f"「{spec.subject_name}」"
    if v.code == "H8":
        placed, expected = v.detail.get("placed", []), v.detail.get("expected", [])
        if sum(placed) > sum(expected):
            return f"{who}排了 {sum(placed)} 節,超過配課的每週 {sum(expected)} 節"
        return f"{who}的連堂排法與配課不同:配課是{_shape(expected)},課表是{_shape(placed)}"
    head = f"「{spec.subject_name}」"
    return who + v.message[len(head):] if v.message.startswith(head) else v.message


def check(db: Session, timetable: Timetable) -> list[CheckIssue]:
    """這份課表目前違反的硬約束;空清單表示沒有問題。未排完不在此列。"""
    problem = load_problem(db, timetable.semester_id)
    cap = load_config(db, timetable.semester_id).daily_subject_cap
    rows = db.scalars(
        select(ScheduleEntry)
        .where(ScheduleEntry.timetable_id == timetable.id)
        .order_by(ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.id)
    ).all()
    entries = [
        SolvedEntry(e.course_assignment_id, e.weekday, e.period_no, e.span, e.room_id)
        for e in rows
    ]
    order = {code: i for i, code in enumerate(CODE_LABELS)}
    issues: list[CheckIssue] = []
    seen: set[tuple[str, str]] = set()
    spec_by_id = {a.id: a for a in problem.assignments}
    for v in validate(problem, entries, daily_subject_cap=cap):
        if not _keep(v):
            continue
        message = _message(problem, spec_by_id.get(v.detail.get("assignment_id", 0)), v)
        if (v.code, message) in seen:
            continue
        seen.add((v.code, message))
        issues.append(CheckIssue(v.code, CODE_LABELS.get(v.code, v.code), message))
    issues.sort(key=lambda i: order.get(i.code, len(order)))
    return issues


@dataclass(frozen=True, slots=True)
class UnavailableHit:
    """某位教師的一節課落在他的不可排時段。"""

    timetable_id: int
    timetable_name: str
    timetable_status: str
    weekday: int
    period_no: int
    period_name: str
    subject: str
    classes: str

    @property
    def text(self) -> str:
        day = _WEEKDAYS[self.weekday - 1] if 1 <= self.weekday <= 7 else str(self.weekday)
        return f"週{day}{self.period_name} {self.classes} {self.subject}"


def unavailable_hits(db: Session, teacher: Teacher) -> list[UnavailableHit]:
    """這位教師在草稿與已發布課表中,落在「不可排」時段的課(#41)。

    儲存時段規則之後呼叫:規則常是學期初憑印象設的,課表排好後再改,兩邊就可能矛盾。
    封存的課表是歷史快照,不看。
    """
    blocked = {
        (r.weekday, r.period_no)
        for r in teacher.time_rules
        if r.rule_type == TeacherRuleType.unavailable.value
    }
    if not blocked:
        return []

    rows = db.execute(
        select(ScheduleEntry, Timetable, CourseAssignment)
        .join(Timetable, Timetable.id == ScheduleEntry.timetable_id)
        .join(CourseAssignment, CourseAssignment.id == ScheduleEntry.course_assignment_id)
        .join(AssignmentTeacher, AssignmentTeacher.course_assignment_id == CourseAssignment.id)
        .where(
            AssignmentTeacher.teacher_id == teacher.id,
            Timetable.semester_id == teacher.semester_id,
            Timetable.status.in_(
                [TimetableStatus.draft.value, TimetableStatus.published.value]
            ),
        )
        .order_by(
            # 已發布的排前面:那是老師們正在照著上課的那一份
            Timetable.status.desc(), Timetable.id,
            ScheduleEntry.weekday, ScheduleEntry.period_no, ScheduleEntry.id,
        )
    ).all()
    if not rows:
        return []

    problem = load_problem(db, teacher.semester_id)
    spec_by_id = {a.id: a for a in problem.assignments}
    hits: list[UnavailableHit] = []
    for entry, tt, assignment in rows:
        spec = spec_by_id.get(assignment.id)
        table = problem.table_of(spec) if spec else None
        classes = "、".join(c.name for c in problem.classes_of(spec)) if spec else ""
        for k in range(entry.span):
            pno = entry.period_no + k
            if (entry.weekday, pno) not in blocked:
                continue
            slot = table.slot(entry.weekday, pno) if table else None
            hits.append(UnavailableHit(
                timetable_id=tt.id, timetable_name=tt.name, timetable_status=tt.status,
                weekday=entry.weekday, period_no=pno,
                period_name=slot.name if slot else f"第 {pno} 格",
                subject=assignment.subject.name, classes=classes,
            ))
    return hits
