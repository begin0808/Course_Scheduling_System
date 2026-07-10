"""CP-SAT 硬約束建模(architecture.md §3.2 H1–H10)。

**建模概念**

- 排課的最小單位是 *course*:單班配課各自一個;跑班群組整組一個(H7 同進同出)。
- 每個 course 依 `periods_per_week` 與 `block_rule` 拆成若干 **lesson**(節長 1 或連堂長度)。
- 每個 lesson 選一個 **起始節次候選**;候選只涵蓋「連續且皆為一般課」的區段(H5+H6),
  且已剔除任一授課教師不可排的時段(H4 以縮小定義域的方式處理,比加約束便宜)。
- `x[course, lesson, candidate]` 恰選一個 → 週節數守恆(H8)自動成立。
- `occ[course, cell]` 為該 course 是否佔用該格,連結到 x;等式(而非 ≤)同時保證
  同一 course 的兩個 lesson 不會壓在同一格。

H1/H2/H3 皆為「同一資源同時段至多一個」;跨節次表時「同時段」以牆鐘重疊判定(D7)。
場地一律互斥,容量不參與求解(D8)。
"""

from collections.abc import Callable
from dataclasses import dataclass

from ortools.sat.python import cp_model

from app.solver.problem import (
    MORNING_END_MIN,
    AssignmentSpec,
    PeriodTableSpec,
    Problem,
    Slot,
    SolvedEntry,
    SolverConfig,
    UnitSpec,
    slots_overlap,
)

Cell = tuple[int, int]  # (weekday, period_no)
# 軟約束的懲罰項:線性運算式,或常數 0(該項在此問題中無適用對象)
_Penalty = cp_model.LinearExpr | int


class SolverInputError(Exception):
    """問題描述本身不合法(通常 pre-flight 應先攔下)。"""


@dataclass(frozen=True, slots=True)
class SolveOptions:
    max_seconds: float = 600.0  # 預設 timeout 10 分鐘(architecture.md §3.3)
    workers: int = 8
    random_seed: int = 0


@dataclass(frozen=True, slots=True)
class SolveResult:
    status: str  # optimal / feasible / infeasible / unknown
    entries: tuple[SolvedEntry, ...]
    # 軟約束加權懲罰(越小越好);純硬約束模式為 0。
    # 與 report.SoftReport.total_penalty 尺度不同,見 report.py 說明。
    objective: float
    wall_time: float
    branches: int
    conflicts: int

    @property
    def solved(self) -> bool:
        return self.status in ("optimal", "feasible")


@dataclass(frozen=True, slots=True)
class _Candidate:
    weekday: int
    period_no: int
    cells: tuple[Cell, ...]


@dataclass(frozen=True, slots=True)
class _Course:
    key: tuple[str, int]
    unit: UnitSpec
    assignments: tuple[AssignmentSpec, ...]
    table: PeriodTableSpec
    lengths: tuple[int, ...]  # 每個 lesson 的節長
    teacher_ids: frozenset[int]

    @property
    def subject_ids(self) -> frozenset[int]:
        return frozenset(a.subject_id for a in self.assignments)


# ── 候選時段 ────────────────────────────────────────────────
def _runs(table: PeriodTableSpec) -> list[list[Slot]]:
    """節次表中「連續的一般課」區段。連堂只能落在同一個區段內(H6 不跨午休)。"""
    runs: list[list[Slot]] = []
    current: list[Slot] = []
    for slot in table.slots:
        if current and current[-1].weekday == slot.weekday and (
            current[-1].period_no + 1 == slot.period_no
        ):
            current.append(slot)
        else:
            if current:
                runs.append(current)
            current = [slot]
    if current:
        runs.append(current)
    return runs


def _candidates(
    table: PeriodTableSpec, length: int, forbidden: frozenset[Cell]
) -> list[_Candidate]:
    out: list[_Candidate] = []
    for run in _runs(table):
        for i in range(len(run) - length + 1):
            cells = tuple(s.key for s in run[i : i + length])
            if any(c in forbidden for c in cells):
                continue  # H4:任一授課教師不可排 → 直接不進定義域
            out.append(_Candidate(run[i].weekday, run[i].period_no, cells))
    return out


def _lengths(a: AssignmentSpec) -> tuple[int, ...]:
    out: list[int] = []
    for b in a.blocks:
        out.extend([b.size] * b.count)
    out.extend([1] * (a.periods_per_week - a.block_periods))
    return tuple(out)


def _build_courses(problem: Problem) -> list[_Course]:
    courses: list[_Course] = []
    for unit in problem.units.values():
        members = [a for a in problem.assignments if a.unit_id == unit.id]
        if not members:
            continue
        table = problem.table_of(members[0])
        if table is None:
            raise SolverInputError(f"排課單位「{unit.name}」的班級沒有節次表")

        if unit.is_group:
            shapes = {(a.periods_per_week, a.blocks) for a in members}
            if len(shapes) > 1:
                raise SolverInputError(
                    f"跑班群組「{unit.name}」的各門課節數/連堂結構不一致,無法同時段開課"
                )
            courses.append(_Course(
                key=("unit", unit.id), unit=unit, assignments=tuple(members), table=table,
                lengths=_lengths(members[0]),
                teacher_ids=frozenset(t for a in members for t in a.teacher_ids),
            ))
        else:
            for a in members:
                courses.append(_Course(
                    key=("assignment", a.id), unit=unit, assignments=(a,), table=table,
                    lengths=_lengths(a), teacher_ids=frozenset(a.teacher_ids),
                ))
    return courses


def _candidate_rooms(problem: Problem, a: AssignmentSpec) -> list[int]:
    return [
        r.id
        for r in problem.rooms.values()
        if r.room_type == a.required_room_type
        and (not r.subject_ids or a.subject_id in r.subject_ids)
    ]


class _Model:
    def __init__(self, problem: Problem, config: SolverConfig) -> None:
        self.problem = problem
        self.config = config
        self.cap = config.daily_subject_cap
        self.m = cp_model.CpModel()
        self.courses = _build_courses(problem)

        self.cands: dict[tuple[int, int], list[_Candidate]] = {}  # (ci, li) → 候選
        self.x: dict[tuple[int, int], list[cp_model.IntVar]] = {}
        self.occ: dict[tuple[int, Cell], cp_model.IntVar] = {}
        self.y: dict[tuple[int, int], cp_model.IntVar] = {}  # (assignment_id, room_id)
        # 教師是否在某節次上課;依星期分組並按牆鐘時間排序(算連續授課與空堂用)
        self.teacher_day: dict[int, dict[int, list[tuple[Slot, cp_model.IntVar]]]] = {}
        self.has_objective = False

        self._make_lesson_vars()
        self._make_room_vars()
        self._h1_class()
        self._h2_teacher()
        self._h3_room()
        self._h10_daily_cap()
        self._h9_locked()

        self._make_teacher_busy()
        self._objective()

    # ── 變數 ────────────────────────────
    def _forbidden(self, course: _Course) -> frozenset[Cell]:
        cells: set[Cell] = set()
        for tid in course.teacher_ids:
            teacher = self.problem.teachers.get(tid)
            if teacher:
                cells |= set(teacher.unavailable)
        return frozenset(cells)

    def _make_lesson_vars(self) -> None:
        for ci, course in enumerate(self.courses):
            forbidden = self._forbidden(course)
            covering: dict[Cell, list[cp_model.IntVar]] = {}
            pos_by_length: dict[int, list[cp_model.IntVar]] = {}

            for li, length in enumerate(course.lengths):
                cands = _candidates(course.table, length, forbidden)
                if not cands:
                    raise SolverInputError(
                        f"「{course.assignments[0].subject_name}」找不到任何可排的 "
                        f"{length} 連堂時段(節次表或教師不可排時段過於嚴格)"
                    )
                xs = [self.m.new_bool_var(f"x{ci}_{li}_{k}") for k in range(len(cands))]
                self.m.add_exactly_one(xs)  # H8:每個 lesson 恰排一次
                self.cands[(ci, li)] = cands
                self.x[(ci, li)] = xs
                for xv, cand in zip(xs, cands, strict=True):
                    for cell in cand.cells:
                        covering.setdefault(cell, []).append(xv)

                pos = self.m.new_int_var(0, len(cands) - 1, f"p{ci}_{li}")
                self.m.add(pos == sum(k * xs[k] for k in range(len(cands))))
                pos_by_length.setdefault(length, []).append(pos)

            # 同長度的 lesson 可互換 → 強制遞增以消除對稱性(候選依時間排序)
            for positions in pos_by_length.values():
                for a, b in zip(positions, positions[1:], strict=False):
                    self.m.add(a < b)

            for slot in course.table.slots:
                o = self.m.new_bool_var(f"o{ci}_{slot.weekday}_{slot.period_no}")
                # 等式:同一 course 的兩個 lesson 不得壓在同一格(sum=2 直接不可行)
                self.m.add(o == sum(covering.get(slot.key, [])))
                self.occ[(ci, slot.key)] = o

    def _make_room_vars(self) -> None:
        for course in self.courses:
            for a in course.assignments:
                if a.room_id is not None or not a.required_room_type:
                    continue
                rooms = _candidate_rooms(self.problem, a)
                if not rooms:
                    raise SolverInputError(
                        f"「{a.subject_name}」需要 {a.required_room_type} 類型場地,但學期內沒有"
                    )
                ys = [self.m.new_bool_var(f"y{a.id}_{rid}") for rid in rooms]
                self.m.add_exactly_one(ys)  # 一門課整學期固定一間教室
                for rid, yv in zip(rooms, ys, strict=True):
                    self.y[(a.id, rid)] = yv

    # ── 硬約束 ──────────────────────────
    def _courses_of_class(self, class_id: int) -> list[int]:
        return [
            ci for ci, c in enumerate(self.courses) if class_id in c.unit.class_ids
        ]

    def _h1_class(self) -> None:
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            if len(cis) < 2:
                continue
            table = self.problem.tables[cls.period_table_id]
            for slot in table.slots:
                self.m.add_at_most_one(self.occ[(ci, slot.key)] for ci in cis)

    def _resource_at_most_one(
        self, entries: list[tuple[int, Slot, cp_model.IntVar]]
    ) -> None:
        """同一資源(教師/場地)在同時段至多一個佔用。

        entries 為 (table_id, slot, literal)。同表同節次 → 直接互斥;
        跨表則兩兩比對牆鐘重疊(D7)。單一節次表的學校完全走前者,零額外成本。
        """
        by_key: dict[tuple[int, int, int], list[cp_model.IntVar]] = {}
        slot_of: dict[tuple[int, int, int], tuple[int, Slot]] = {}
        for table_id, slot, lit in entries:
            key = (table_id, slot.weekday, slot.period_no)
            by_key.setdefault(key, []).append(lit)
            slot_of[key] = (table_id, slot)

        for lits in by_key.values():
            if len(lits) > 1:
                self.m.add_at_most_one(lits)

        keys = list(by_key)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                ta, sa = slot_of[keys[i]]
                tb, sb = slot_of[keys[j]]
                if ta == tb:
                    continue
                if slots_overlap(sa, sb, same_table=False):
                    self.m.add_at_most_one(by_key[keys[i]] + by_key[keys[j]])

    def _h2_teacher(self) -> None:
        for teacher_id in self.problem.teachers:
            entries: list[tuple[int, Slot, cp_model.IntVar]] = []
            for ci, course in enumerate(self.courses):
                if teacher_id not in course.teacher_ids:
                    continue
                for slot in course.table.slots:
                    entries.append((course.table.id, slot, self.occ[(ci, slot.key)]))
            if entries:
                self._resource_at_most_one(entries)

    def _h3_room(self) -> None:
        """場地互斥(D8:容量不參與求解)。未綁定場地者由引擎在候選教室中挑一間。"""
        rooms_of_assignment: dict[int, list[int]] = {}
        for a_id, rid in self.y:
            rooms_of_assignment.setdefault(a_id, []).append(rid)

        by_room: dict[int, list[tuple[int, Slot, cp_model.IntVar]]] = {}
        for ci, course in enumerate(self.courses):
            for a in course.assignments:
                for slot in course.table.slots:
                    o = self.occ[(ci, slot.key)]
                    if a.room_id is not None:
                        by_room.setdefault(a.room_id, []).append((course.table.id, slot, o))
                        continue
                    for rid in rooms_of_assignment.get(a.id, []):
                        yv = self.y[(a.id, rid)]
                        # z = o AND y:這一格是否真的用到這間教室
                        z = self.m.new_bool_var(f"z{a.id}_{rid}_{slot.weekday}_{slot.period_no}")
                        self.m.add(z <= o)
                        self.m.add(z <= yv)
                        self.m.add(z >= o + yv - 1)
                        by_room.setdefault(rid, []).append((course.table.id, slot, z))

        for entries in by_room.values():
            self._resource_at_most_one(entries)

    def _h10_daily_cap(self) -> None:
        """同班同科目每日單節數上限;連堂是一次上完的整塊,不計入。"""
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            subjects = {sid for ci in cis for sid in self.courses[ci].subject_ids}
            for subject_id in subjects:
                for weekday in range(1, self.problem.tables[cls.period_table_id].num_weekdays + 1):
                    lits: list[cp_model.IntVar] = []
                    for ci in cis:
                        course = self.courses[ci]
                        if subject_id not in course.subject_ids:
                            continue
                        for li, length in enumerate(course.lengths):
                            if length != 1:
                                continue
                            for xv, cand in zip(
                                self.x[(ci, li)], self.cands[(ci, li)], strict=True
                            ):
                                if cand.weekday == weekday:
                                    lits.append(xv)
                    if len(lits) > self.cap:
                        self.m.add(sum(lits) <= self.cap)

    def _h9_locked(self) -> None:
        """鎖定的格位必須維持原位。

        不指定「哪一個 lesson」佔住該格(同長度的 lesson 可互換,綁死會與對稱性
        約束打架),只要求「該長度的 lesson 中恰有一個排在這裡」。
        """
        course_of: dict[int, int] = {}
        for ci, course in enumerate(self.courses):
            for a in course.assignments:
                course_of[a.id] = ci

        pinned: set[tuple[int, int, int, int]] = set()
        for f in self.problem.fixed_entries:
            if not f.locked or f.assignment_id not in course_of:
                continue
            ci = course_of[f.assignment_id]
            key = (ci, f.weekday, f.period_no, f.span)
            if key in pinned:
                continue  # 跑班群組:多筆兄弟格位對應同一個 course
            pinned.add(key)

            lits: list[cp_model.IntVar] = []
            for li, length in enumerate(self.courses[ci].lengths):
                if length != f.span:
                    continue
                for xv, cand in zip(self.x[(ci, li)], self.cands[(ci, li)], strict=True):
                    if (cand.weekday, cand.period_no) == (f.weekday, f.period_no):
                        lits.append(xv)
            if not lits:
                raise SolverInputError(
                    f"鎖定的格位(配課 {f.assignment_id} 週{f.weekday} 第 {f.period_no} 格,"
                    f"{f.span} 節)不是合法的排課位置"
                )
            self.m.add(sum(lits) == 1)

            if f.room_id is not None and (f.assignment_id, f.room_id) in self.y:
                self.m.add(self.y[(f.assignment_id, f.room_id)] == 1)

    # ── 軟約束(architecture.md §3.2 S1–S8)────────────────
    def _make_teacher_busy(self) -> None:
        """teacher_day[t][weekday] = [(節次, 該教師是否在此上課), …],依牆鐘時間排序。"""
        for tid in self.problem.teachers:
            per_cell: dict[tuple[int, int, int], tuple[Slot, list[cp_model.IntVar]]] = {}
            for ci, course in enumerate(self.courses):
                if tid not in course.teacher_ids:
                    continue
                for slot in course.table.slots:
                    key = (course.table.id, slot.weekday, slot.period_no)
                    per_cell.setdefault(key, (slot, []))[1].append(self.occ[(ci, slot.key)])

            by_day: dict[int, list[tuple[Slot, cp_model.IntVar]]] = {}
            for (_table_id, weekday, period_no), (slot, lits) in per_cell.items():
                if len(lits) == 1:
                    busy = lits[0]  # 只教一門課的那一格,占用變數本身就是「是否上課」
                else:
                    busy = self.m.new_bool_var(f"b{tid}_{weekday}_{period_no}")
                    self.m.add(busy == sum(lits))  # H2 已保證至多一個為 1
                by_day.setdefault(weekday, []).append((slot, busy))

            for day in by_day.values():
                day.sort(key=lambda p: (p[0].start_min or 0, p[0].period_no))
            self.teacher_day[tid] = by_day

    def _objective(self) -> None:
        cfg = self.config
        terms: list[_Penalty] = []

        def add(code: str, expr: _Penalty) -> None:
            weight = cfg.weight(code)
            if weight:
                terms.append(weight * expr)

        s1_avoid, s1_prefer, unmet_by_teacher = self._s1_preferences()
        add("S1", s1_avoid)
        if cfg.enabled("S1") and s1_prefer is not None:
            terms.append(-cfg.weight("S1") * s1_prefer)  # 偏好達成 = 負懲罰

        add("S2", self._s2_spread())
        add("S3", self._s3_daily_load())
        add("S4", self._s4_gaps())
        add("S5", self._s5_major_in_morning())
        add("S6", self._s6_consecutive())
        add("S7", self._s7_homeroom_first_period())
        add("S8", self._s8_fairness(unmet_by_teacher))

        if terms:
            self.m.minimize(sum(terms))
            self.has_objective = True

    def _s1_preferences(self) -> tuple[_Penalty, _Penalty | None, dict[int, list[cp_model.IntVar]]]:
        """avoid 節次扣分、prefer 節次加分;順帶回傳每位教師的未達成數供 S8 使用。"""
        avoid_terms: list[cp_model.IntVar] = []
        prefer_terms: list[cp_model.IntVar] = []
        unmet: dict[int, list[cp_model.IntVar]] = {}
        for tid, by_day in self.teacher_day.items():
            teacher = self.problem.teachers[tid]
            if not teacher.has_preferences:
                continue
            for day in by_day.values():
                for slot, busy in day:
                    if slot.key in teacher.avoid:
                        avoid_terms.append(busy)
                        unmet.setdefault(tid, []).append(busy)
                    elif slot.key in teacher.prefer:
                        prefer_terms.append(busy)
        return (
            sum(avoid_terms) if avoid_terms else 0,
            sum(prefer_terms) if prefer_terms else None,
            unmet,
        )

    def _s2_spread(self) -> _Penalty:
        """同班同科目同日超過 1 節的部分計為懲罰(連堂不計,本來就是同一天上完)。"""
        extras: list[cp_model.IntVar] = []
        for cls in self.problem.classes.values():
            cis = self._courses_of_class(cls.id)
            table = self.problem.tables[cls.period_table_id]
            subjects = {sid for ci in cis for sid in self.courses[ci].subject_ids}
            for subject_id in subjects:
                for weekday in range(1, table.num_weekdays + 1):
                    lits = self._single_lesson_lits(cis, subject_id, weekday)
                    if len(lits) < 2:
                        continue
                    extra = self.m.new_int_var(
                        0, len(lits) - 1, f"s2_{cls.id}_{subject_id}_{weekday}"
                    )
                    self.m.add(extra >= sum(lits) - 1)
                    extras.append(extra)
        return sum(extras) if extras else 0

    def _single_lesson_lits(
        self, cis: list[int], subject_id: int, weekday: int
    ) -> list[cp_model.IntVar]:
        lits: list[cp_model.IntVar] = []
        for ci in cis:
            course = self.courses[ci]
            if subject_id not in course.subject_ids:
                continue
            for li, length in enumerate(course.lengths):
                if length != 1:
                    continue
                for xv, cand in zip(self.x[(ci, li)], self.cands[(ci, li)], strict=True):
                    if cand.weekday == weekday:
                        lits.append(xv)
        return lits

    def _s3_daily_load(self) -> _Penalty:
        overs: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                over = self.m.new_int_var(0, len(day), f"s3_{tid}_{weekday}")
                self.m.add(over >= sum(b for _s, b in day) - self.config.teacher_daily_max)
                overs.append(over)
        return sum(overs) if overs else 0

    def _s4_gaps(self) -> _Penalty:
        """零碎空堂 = (最後一節 − 第一節 + 1) − 當日節數。目標函數會把 first/last 壓緊。"""
        gaps: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                n = len(day)
                if n < 3:  # 少於 3 格不可能出現中間的空堂
                    continue
                first = self.m.new_int_var(0, n - 1, f"f{tid}_{weekday}")
                last = self.m.new_int_var(0, n - 1, f"l{tid}_{weekday}")
                for i, (_slot, busy) in enumerate(day):
                    self.m.add(first <= i).only_enforce_if(busy)
                    self.m.add(last >= i).only_enforce_if(busy)
                gap = self.m.new_int_var(0, n, f"s4_{tid}_{weekday}")
                self.m.add(gap >= last - first + 1 - sum(b for _s, b in day))
                gaps.append(gap)
        return sum(gaps) if gaps else 0

    def _s5_major_in_morning(self) -> _Penalty:
        afternoon: list[cp_model.IntVar] = []
        for ci, course in enumerate(self.courses):
            if not any(a.subject_is_major for a in course.assignments):
                continue
            for slot in course.table.slots:
                if slot.start_min is not None and slot.start_min >= MORNING_END_MIN:
                    afternoon.append(self.occ[(ci, slot.key)])
        return sum(afternoon) if afternoon else 0

    def _s6_consecutive(self) -> _Penalty:
        """任何 (上限+1) 節的連續視窗中,上課節數不得超過上限;超出部分計為懲罰。"""
        window = self.config.teacher_consecutive_max + 1
        excesses: list[cp_model.IntVar] = []
        for tid, by_day in self.teacher_day.items():
            for weekday, day in by_day.items():
                for i in range(len(day) - window + 1):
                    chunk = [b for _s, b in day[i : i + window]]
                    excess = self.m.new_int_var(0, 1, f"s6_{tid}_{weekday}_{i}")
                    self.m.add(excess >= sum(chunk) - self.config.teacher_consecutive_max)
                    excesses.append(excess)
        return sum(excesses) if excesses else 0

    def _s7_homeroom_first_period(self) -> _Penalty:
        misses: list[cp_model.IntVar] = []
        for cls in self.problem.classes.values():
            tid = cls.homeroom_teacher_id
            if tid is None:
                continue
            table = self.problem.tables[cls.period_table_id]
            cis = [
                ci for ci in self._courses_of_class(cls.id)
                if tid in self.courses[ci].teacher_ids
            ]
            if not cis:
                continue  # 導師沒教這個班 → 這條軟約束無從滿足,不列入懲罰
            for weekday in range(1, table.num_weekdays + 1):
                day = table.slots_on(weekday)
                if not day:
                    continue
                lits = [self.occ[(ci, day[0].key)] for ci in cis]
                miss = self.m.new_bool_var(f"s7_{cls.id}_{weekday}")
                self.m.add(miss == 1 - sum(lits))
                misses.append(miss)
        return sum(misses) if misses else 0

    def _s8_fairness(self, unmet: dict[int, list[cp_model.IntVar]]) -> _Penalty:
        """最差者優先:壓低「偏好未達成最多的那位教師」的未達成節數。"""
        if not unmet:
            return 0
        worst = self.m.new_int_var(0, max(len(v) for v in unmet.values()), "s8_worst")
        for lits in unmet.values():
            self.m.add(worst >= sum(lits))
        return worst

    # ── 取解 ────────────────────────────
    def extract(self, solver: cp_model.CpSolver) -> tuple[SolvedEntry, ...]:
        locked = {
            (f.assignment_id, f.weekday, f.period_no, f.span)
            for f in self.problem.fixed_entries
            if f.locked
        }
        rooms_of: dict[int, int] = {}
        for (a_id, rid), yv in self.y.items():
            if solver.value(yv):
                rooms_of[a_id] = rid

        out: list[SolvedEntry] = []
        for ci, course in enumerate(self.courses):
            for li in range(len(course.lengths)):
                cands = self.cands[(ci, li)]
                xs = self.x[(ci, li)]
                chosen = next(c for c, xv in zip(cands, xs, strict=True) if solver.value(xv))
                span = len(chosen.cells)
                for a in course.assignments:
                    room_id = a.room_id if a.room_id is not None else rooms_of.get(a.id)
                    key = (a.id, chosen.weekday, chosen.period_no, span)
                    out.append(SolvedEntry(
                        assignment_id=a.id, weekday=chosen.weekday,
                        period_no=chosen.period_no, span=span, room_id=room_id,
                        locked=key in locked,
                    ))
        out.sort(key=lambda e: (e.weekday, e.period_no, e.assignment_id))
        return tuple(out)


_STATUS = {
    cp_model.OPTIMAL: "optimal",
    cp_model.FEASIBLE: "feasible",
    cp_model.INFEASIBLE: "infeasible",
    cp_model.MODEL_INVALID: "invalid",
    cp_model.UNKNOWN: "unknown",
}


def solve(
    problem: Problem,
    options: SolveOptions | None = None,
    *,
    config: SolverConfig | None = None,
    on_progress: Callable[[int, float], None] | None = None,
) -> SolveResult:
    """求解一份完整課表:硬約束必須全滿足,軟約束以加權目標最小化。

    CP-SAT 是 anytime solver——逾時仍會回傳當下最佳解(status=feasible)。
    config 給 `SolverConfig.hard_only()` 即退化為純可行性問題(最快)。
    on_progress 供 worker 回報進度(M3-4),參數為 (已找到的解數, 經過秒數)。
    """
    options = options or SolveOptions()
    config = config or SolverConfig()
    built = _Model(problem, config)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_seconds
    solver.parameters.num_workers = options.workers
    solver.parameters.random_seed = options.random_seed

    callback = _ProgressCallback(on_progress) if on_progress else None
    status = solver.solve(built.m, callback) if callback else solver.solve(built.m)

    entries: tuple[SolvedEntry, ...] = ()
    objective = 0.0
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        entries = built.extract(solver)
        objective = solver.objective_value if built.has_objective else 0.0

    return SolveResult(
        status=_STATUS.get(status, "unknown"),
        entries=entries,
        objective=objective,
        wall_time=solver.wall_time,
        branches=solver.num_branches,
        conflicts=solver.num_conflicts,
    )


class _ProgressCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, on_progress: Callable[[int, float], None]) -> None:
        super().__init__()
        self._on_progress = on_progress
        self._count = 0

    def on_solution_callback(self) -> None:
        self._count += 1
        self._on_progress(self._count, self.WallTime())
