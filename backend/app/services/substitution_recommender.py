"""代課推薦(M4-2,architecture.md §5.3)。

回答「這一節該找誰代」。兩段式:先**硬性過濾**(只留下那個特定日期真的能來的人),
再**排序**(同科目 > 當天已在校 > 本月代課鐘點少),每位候選附上為什麼排這個位置。

硬性過濾一律經 `availability`——那裡才知道「李師週三第二節空堂」不等於「11/11 他能代」
(他自己可能也請假、或已被指派代別班)。排序理由給人看,不是黑箱分數。
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.substitution import Substitution
from app.services.availability import Availability


@dataclass(frozen=True, slots=True)
class Candidate:
    teacher_id: int
    teacher_name: str
    same_subject: bool       # 教這個科目
    at_school_that_day: bool  # 當天本來就有課(免多跑一趟)
    sub_periods_this_month: int  # 本月已代課節數(愈少愈優先,公平)
    reasons: tuple[str, ...]  # 為什麼排這個位置(給人看)

    @property
    def sort_key(self) -> tuple:
        # 同科目最重要,其次當天在校,再者本月代課少者優先;同分以姓名穩定排序
        return (
            0 if self.same_subject else 1,
            0 if self.at_school_that_day else 1,
            self.sub_periods_this_month,
            self.teacher_name,
        )


@dataclass
class Recommendation:
    affected_period_id: int
    candidates: list[Candidate] = field(default_factory=list)
    # 全校無人可代時,給組長明確的下一步(併班/自習),而不是空清單
    no_candidate_hint: str = ""


def _subject_teacher_ids(db: Session, semester_id: int, subject_name: str) -> set[int]:
    """教這個科目的教師 id。以科目『名稱』比對(受影響節次存的是快照名稱)。"""
    if not subject_name:
        return set()
    from app.models.basedata import Subject, teacher_subjects

    rows = db.execute(
        select(teacher_subjects.c.teacher_id)
        .join(Subject, Subject.id == teacher_subjects.c.subject_id)
        .join(Teacher, Teacher.id == teacher_subjects.c.teacher_id)
        .where(Teacher.semester_id == semester_id, Subject.name == subject_name)
    ).all()
    return {r[0] for r in rows}


def _monthly_sub_counts(db: Session, semester_id: int, month_start: date) -> dict[int, int]:
    """本月各教師已計鐘點的代課節數(swap 的補課方也算一節)。"""
    counts: dict[int, int] = {}
    rows = db.execute(
        select(Substitution.handler_teacher_id, func.count())
        .join(AffectedPeriod, AffectedPeriod.id == Substitution.affected_period_id)
        .where(
            Substitution.semester_id == semester_id,
            Substitution.counts_toward_hours.is_(True),
            Substitution.handler_teacher_id.isnot(None),
            # 銷假後 substitution 列仍在、但節次已取消——不能算進公平計數的幽靈代課
            # (與 M4-5 統計的 status != cancelled 過濾同口徑)
            AffectedPeriod.status != AffectedStatus.cancelled.value,
            AffectedPeriod.date >= month_start,
            AffectedPeriod.date < _next_month(month_start),
        )
        .group_by(Substitution.handler_teacher_id)
    ).all()
    for teacher_id, n in rows:
        counts[teacher_id] = n
    return counts


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def recommend(
    db: Session,
    affected: AffectedPeriod,
    *,
    availability: Availability | None = None,
) -> Recommendation:
    """為一個受影響節次列出可代教師,已排序、附理由。"""
    semester_id = affected.semester_id
    av = availability or Availability(db, semester_id)
    slot = av.slot_of(affected)

    absent_teacher_id = affected.leave_request.teacher_id
    subject_teachers = _subject_teacher_ids(db, semester_id, affected.subject_name)
    month_counts = _monthly_sub_counts(db, semester_id, affected.date.replace(day=1))

    teachers = db.scalars(
        select(Teacher).where(Teacher.semester_id == semester_id, Teacher.is_active.is_(True))
        .order_by(Teacher.name)
    ).all()

    rec = Recommendation(affected_period_id=affected.id)
    blocked = 0
    for t in teachers:
        if t.id == absent_teacher_id:
            continue
        if av.conflict_for(t.id, affected.date, slot) is not None:
            blocked += 1
            continue

        same_subject = t.id in subject_teachers
        at_school = av.teaches_on(t.id, affected.weekday)
        month_n = month_counts.get(t.id, 0)

        reasons: list[str] = []
        reasons.append("同科目教師" if same_subject else "非本科教師")
        if at_school:
            reasons.append("當天已在校")
        reasons.append(f"本月已代 {month_n} 節")

        rec.candidates.append(Candidate(
            teacher_id=t.id, teacher_name=t.name,
            same_subject=same_subject, at_school_that_day=at_school,
            sub_periods_this_month=month_n, reasons=tuple(reasons),
        ))

    rec.candidates.sort(key=lambda c: c.sort_key)
    if not rec.candidates:
        rec.no_candidate_hint = (
            f"該時段全校 {blocked} 位教師都無法代課,建議改採「併班」或「自習」"
        )
    return rec
