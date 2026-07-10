"""軟約束達成度報告(architecture.md §3.2 S1–S8)。

與 `validator.py` 一樣**從課表本身重新推導**,不讀 CP-SAT 的目標值——建模的懲罰項
寫錯時,solver 回報的目標值只會忠實反映錯誤的模型。報告要說人話:
不是「S1 得分 0.82」,而是「教師王師 週四第七節 被排課(該時段標記為盡量避開)」。

滿分 = 機會數(可以被滿足的次數),得分 = 實際滿足數。

**`total_penalty` 不等於 `SolveResult.objective`**,兩者刻意用不同尺度:
目標函數以「超出的節數」計價(S3 超 2 節就罰 2 份),讓 solver 有梯度可下降;
報告以「未達成的次數」計價(S3 那天沒排好就是 1 次),讓教學組長知道要修幾個地方。
比較兩份課表的優劣時看 objective,看報告是為了知道**哪裡**還不夠好。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.solver.problem import (
    MORNING_END_MIN,
    SOFT_NAMES,
    AssignmentSpec,
    ClassSpec,
    Problem,
    Slot,
    SolvedEntry,
    SolverConfig,
)

MAX_DETAILS = 20  # 每項軟約束最多列出的明細筆數(其餘以總數表示)


def _wd(weekday: int) -> str:
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


@dataclass(frozen=True, slots=True)
class SoftScore:
    code: str
    name: str
    weight: int
    opportunities: int  # 滿分
    violations: int
    details: tuple[str, ...] = field(default_factory=tuple)

    @property
    def satisfied(self) -> int:
        return max(self.opportunities - self.violations, 0)

    @property
    def rate(self) -> float:
        return self.satisfied / self.opportunities if self.opportunities else 1.0

    @property
    def penalty(self) -> int:
        return self.weight * self.violations


@dataclass(frozen=True, slots=True)
class SoftReport:
    items: tuple[SoftScore, ...]

    @property
    def total_penalty(self) -> int:
        return sum(i.penalty for i in self.items)

    def get(self, code: str) -> SoftScore:
        return next(i for i in self.items if i.code == code)


@dataclass(frozen=True, slots=True)
class _Busy:
    """教師在某一節次上課。position 是該教師當日可排節次序列中的位置(用來算連續/空堂)。"""

    weekday: int
    position: int
    slot: Slot


def evaluate(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    config: SolverConfig | None = None,
) -> SoftReport:
    config = config or SolverConfig()
    by_id = {a.id: a for a in problem.assignments}
    busy = _teacher_busy(problem, entries, by_id)

    return SoftReport((
        _s1_preferences(problem, busy, config),
        _s2_spread(problem, entries, by_id, config),
        _s3_daily_load(problem, busy, config),
        _s4_gaps(problem, busy, config),
        _s5_major_in_morning(problem, entries, by_id, config),
        _s6_consecutive(problem, busy, config),
        _s7_homeroom_first_period(problem, entries, by_id, config),
        _s8_fairness(problem, busy, config),
    ))


def _teacher_day_slots(problem: Problem, teacher_id: int) -> dict[int, list[Slot]]:
    """該教師可能上課的節次,依星期分組並按牆鐘時間排序(跨節次表也有一致的順序)。"""
    slots: list[Slot] = []
    for table in problem.tables_of_teacher(teacher_id):
        slots.extend(table.slots)
    by_day: dict[int, list[Slot]] = {}
    for s in slots:
        by_day.setdefault(s.weekday, []).append(s)
    for day in by_day.values():
        day.sort(key=lambda s: (s.start_min if s.start_min is not None else 0, s.period_no))
    return by_day


def _teacher_busy(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec]
) -> dict[int, list[_Busy]]:
    day_slots = {tid: _teacher_day_slots(problem, tid) for tid in problem.teachers}
    positions: dict[int, dict[tuple[int, int], int]] = {}
    for tid, by_day in day_slots.items():
        positions[tid] = {
            (s.weekday, s.period_no): i for day in by_day.values() for i, s in enumerate(day)
        }

    out: dict[int, list[_Busy]] = {tid: [] for tid in problem.teachers}
    for e in entries:
        a = by_id[e.assignment_id]
        table = problem.table_of(a)
        if table is None:
            continue
        for k in range(e.span):
            slot = table.slot(e.weekday, e.period_no + k)
            if slot is None:
                continue
            for tid in a.teacher_ids:
                pos = positions.get(tid, {}).get((slot.weekday, slot.period_no))
                if pos is not None:
                    out[tid].append(_Busy(slot.weekday, pos, slot))
    return out


# ── S1 教師偏好時段 ──────────────────────────────────────────
def _s1_preferences(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        if not t.has_preferences:
            continue
        mine = busy.get(t.id, [])
        opportunities += len(mine)
        for b in mine:
            if b.slot.key in t.avoid:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教師{t.name} {_wd(b.weekday)}{b.slot.name} 被排課"
                        f"(該時段標記為盡量避開)"
                    )
    return SoftScore("S1", SOFT_NAMES["S1"], c.weight("S1"), opportunities, violations,
                     tuple(details))


# ── S2 同班同科目分散於不同日 ────────────────────────────────
def _s2_spread(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    counts: dict[tuple[int, int, int], int] = {}
    for e in entries:
        if e.span != 1:
            continue  # 連堂本來就是同一天上完
        a = by_id[e.assignment_id]
        for cls in problem.classes_of(a):
            key = (cls.id, a.subject_id, e.weekday)
            counts[key] = counts.get(key, 0) + 1

    opportunities = sum(counts.values())
    violations = 0
    details: list[str] = []
    for (class_id, subject_id, weekday), n in sorted(counts.items()):
        if n > 1:
            violations += n - 1
            if len(details) < MAX_DETAILS:
                subject = next(a.subject_name for a in problem.assignments
                               if a.subject_id == subject_id)
                details.append(
                    f"班級 {problem.classes[class_id].name} {_wd(weekday)} "
                    f"排了 {n} 節「{subject}」"
                )
    return SoftScore("S2", SOFT_NAMES["S2"], c.weight("S2"), opportunities, violations,
                     tuple(details))


# ── S3 教師每日授課節數上限 ──────────────────────────────────
def _s3_daily_load(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, int] = {}
        for b in busy.get(t.id, []):
            by_day[b.weekday] = by_day.get(b.weekday, 0) + 1
        for weekday, load in sorted(by_day.items()):
            opportunities += 1
            if load > c.teacher_daily_max:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教師{t.name} {_wd(weekday)} 排了 {load} 節,"
                        f"超過每日上限 {c.teacher_daily_max} 節"
                    )
    return SoftScore("S3", SOFT_NAMES["S3"], c.weight("S3"), opportunities, violations,
                     tuple(details))


# ── S4 教師空堂集中 ──────────────────────────────────────────
def _s4_gaps(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, list[int]] = {}
        for b in busy.get(t.id, []):
            by_day.setdefault(b.weekday, []).append(b.position)
        for weekday, positions in sorted(by_day.items()):
            opportunities += 1
            gaps = (max(positions) - min(positions) + 1) - len(positions)
            if gaps > 0:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(f"教師{t.name} {_wd(weekday)} 有 {gaps} 節零碎空堂")
    return SoftScore("S4", SOFT_NAMES["S4"], c.weight("S4"), opportunities, violations,
                     tuple(details))


# ── S5 主科優先排上午 ────────────────────────────────────────
def _s5_major_in_morning(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for e in entries:
        a = by_id[e.assignment_id]
        if not a.subject_is_major:
            continue
        table = problem.table_of(a)
        if table is None:
            continue
        for k in range(e.span):
            slot = table.slot(e.weekday, e.period_no + k)
            if slot is None or slot.start_min is None:
                continue
            opportunities += 1
            if slot.start_min >= MORNING_END_MIN:
                violations += 1
                if len(details) < MAX_DETAILS:
                    names = "、".join(cls.name for cls in problem.classes_of(a))
                    details.append(
                        f"{names} 的「{a.subject_name}」排在 {_wd(e.weekday)}{slot.name}(下午)"
                    )
    return SoftScore("S5", SOFT_NAMES["S5"], c.weight("S5"), opportunities, violations,
                     tuple(details))


# ── S6 教師連續授課節數上限 ──────────────────────────────────
def _s6_consecutive(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for t in problem.teachers.values():
        by_day: dict[int, list[int]] = {}
        for b in busy.get(t.id, []):
            by_day.setdefault(b.weekday, []).append(b.position)
        for weekday, positions in sorted(by_day.items()):
            opportunities += 1
            longest = _longest_run(sorted(positions))
            if longest > c.teacher_consecutive_max:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"教師{t.name} {_wd(weekday)} 連續授課 {longest} 節,"
                        f"超過上限 {c.teacher_consecutive_max} 節"
                    )
    return SoftScore("S6", SOFT_NAMES["S6"], c.weight("S6"), opportunities, violations,
                     tuple(details))


def _longest_run(sorted_positions: list[int]) -> int:
    best = run = 0
    prev: int | None = None
    for p in sorted_positions:
        run = run + 1 if prev is not None and p == prev + 1 else 1
        prev = p
        best = max(best, run)
    return best


# ── S7 導師的課排在自己班第一節 ──────────────────────────────
def _homeroom_classes(problem: Problem) -> list[tuple[ClassSpec, int]]:
    """有導師、且導師確實任教該班的班級(否則這條軟約束無從滿足)。"""
    out: list[tuple[ClassSpec, int]] = []
    for cls in problem.classes.values():
        tid = cls.homeroom_teacher_id
        if tid is None:
            continue
        teaches = any(
            tid in a.teacher_ids and cls.id in problem.units[a.unit_id].class_ids
            for a in problem.assignments
        )
        if teaches:
            out.append((cls, tid))
    return out


def _s7_homeroom_first_period(
    problem: Problem, entries: Sequence[SolvedEntry], by_id: dict[int, AssignmentSpec],
    c: SolverConfig,
) -> SoftScore:
    opportunities = 0
    violations = 0
    details: list[str] = []
    for cls, tid in _homeroom_classes(problem):
        table = problem.tables[cls.period_table_id]
        for weekday in range(1, table.num_weekdays + 1):
            day = table.slots_on(weekday)
            if not day:
                continue
            first = day[0]
            opportunities += 1
            taken_by_homeroom = any(
                e.weekday == weekday and e.period_no == first.period_no
                and tid in by_id[e.assignment_id].teacher_ids
                and cls.id in problem.units[by_id[e.assignment_id].unit_id].class_ids
                for e in entries
            )
            if not taken_by_homeroom:
                violations += 1
                if len(details) < MAX_DETAILS:
                    details.append(
                        f"班級 {cls.name} {_wd(weekday)}{first.name} 不是導師"
                        f"{problem.teachers[tid].name}的課"
                    )
    return SoftScore("S7", SOFT_NAMES["S7"], c.weight("S7"), opportunities, violations,
                     tuple(details))


# ── S8 教師偏好達成率的公平性 ────────────────────────────────
def _s8_fairness(problem: Problem, busy: dict[int, list[_Busy]], c: SolverConfig) -> SoftScore:
    unmet: dict[int, int] = {}
    for t in problem.teachers.values():
        if not t.has_preferences:
            continue
        unmet[t.id] = sum(1 for b in busy.get(t.id, []) if b.slot.key in t.avoid)

    opportunities = len(unmet)
    violations = sum(1 for n in unmet.values() if n > 0)
    details: list[str] = []
    if unmet:
        worst_id = max(unmet, key=lambda tid: unmet[tid])
        if unmet[worst_id] > 0:
            details.append(
                f"偏好未達成最多的是教師{problem.teachers[worst_id].name}"
                f"({unmet[worst_id]} 節);共 {violations}/{opportunities} 位教師的偏好未完全達成"
            )
    return SoftScore("S8", SOFT_NAMES["S8"], c.weight("S8"), opportunities, violations,
                     tuple(details))
