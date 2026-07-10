"""排課前置檢查(architecture.md §3.4)。

在丟給 CP-SAT 之前先跑一輪廉價的**必要條件**檢查,攔掉多數資料錯誤:
教師配課數 ≤ 可排格數、班級週節數 ≤ 可排節次、場地需求 ≤ 供給、連堂放得進連續節次。
必要條件通過不代表一定有解(那要靠 solver),但不通過就一定無解——不必浪費求解時間。

錯誤(error)會擋下自動排課;警告(warning)只提醒,不擋。
訊息一律用教務語言與具體數字,不是「排不出來」。
"""

from dataclasses import dataclass, field
from typing import Literal

from app.solver.problem import Problem, Slot, TeacherSpec, max_non_overlapping

Level = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Issue:
    level: Level
    code: str
    message: str  # 人話,含具體數字
    subject_type: str  # teacher / class / room / assignment / semester
    subject_id: int
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PreflightReport:
    issues: tuple[Issue, ...]

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "error")

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.level == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def teacher_available_slots(problem: Problem, teacher: TeacherSpec) -> int:
    """教師可排格數:其任教班級的節次表中,扣除不可排時段後互不重疊的節次數。

    單一節次表(絕大多數學校)= 一般課格數 − 落在一般課上的 unavailable 格數。
    跨節次表任教(完全中學)則以牆鐘區間去重,見 problem.max_non_overlapping。
    """
    usable: list[Slot] = []
    for table in problem.tables_of_teacher(teacher.id):
        usable.extend(s for s in table.slots if s.key not in teacher.unavailable)
    return max_non_overlapping(usable)


def _room_supply(problem: Problem, room_id: int) -> int:
    """該場地可用的節次數:使用它的班級所屬節次表的節次聯集(去重疊)。"""
    tables = {}
    for a in problem.assignments:
        if a.room_id != room_id:
            continue
        table = problem.table_of(a)
        if table is not None:
            tables[table.id] = table
    if not tables:
        return 0
    slots: list[Slot] = []
    for table in tables.values():
        slots.extend(table.slots)
    return max_non_overlapping(slots)


def run(problem: Problem) -> PreflightReport:
    issues: list[Issue] = []

    _check_period_tables(problem, issues)
    _check_teachers(problem, issues)
    _check_classes(problem, issues)
    _check_rooms(problem, issues)
    _check_blocks(problem, issues)

    order = {"error": 0, "warning": 1}
    return PreflightReport(tuple(sorted(issues, key=lambda i: (order[i.level], i.code))))


def _check_period_tables(problem: Problem, issues: list[Issue]) -> None:
    for a in problem.assignments:
        if not problem.classes_of(a):
            issues.append(Issue(
                "error", "assignment_without_class",
                f"配課「{a.subject_name}」沒有任何班級,無法排課",
                "assignment", a.id,
            ))
        elif problem.table_of(a) is None:
            issues.append(Issue(
                "error", "no_period_table",
                f"配課「{a.subject_name}」的班級尚未指派節次表,無法決定可排時段",
                "assignment", a.id,
            ))


def _check_teachers(problem: Problem, issues: list[Issue]) -> None:
    for teacher in problem.teachers.values():
        assigned = sum(a.periods_per_week for a in problem.assignments_of_teacher(teacher.id))
        if assigned == 0:
            continue
        available = teacher_available_slots(problem, teacher)
        if assigned > available:
            blocked = len(teacher.unavailable)
            suffix = f"(已扣除 {blocked} 格不可排時段)" if blocked else ""
            issues.append(Issue(
                "error", "teacher_overload",
                f"教師{teacher.name} 配課 {assigned} 節,但可排時段僅 {available} 格{suffix}",
                "teacher", teacher.id,
                {"assigned": assigned, "available": available, "unavailable": blocked},
            ))
        if assigned > teacher.target_periods:
            issues.append(Issue(
                "warning", "teacher_over_hours",
                f"教師{teacher.name} 配課 {assigned} 節,超出應授鐘點 "
                f"{teacher.target_periods} 節 {assigned - teacher.target_periods} 節",
                "teacher", teacher.id,
                {"assigned": assigned, "target": teacher.target_periods},
            ))


def _check_classes(problem: Problem, issues: list[Issue]) -> None:
    consumption: dict[int, int] = {}
    for unit in problem.units.values():
        used = problem.unit_slot_consumption(unit.id)
        for cid in unit.class_ids:
            consumption[cid] = consumption.get(cid, 0) + used

    for cid, used in consumption.items():
        cls = problem.classes[cid]
        table = problem.tables.get(cls.period_table_id)
        capacity = len(table.slots) if table else 0
        if used > capacity:
            issues.append(Issue(
                "error", "class_overload",
                f"班級 {cls.name} 每週配課 {used} 節,超過可排節次 {capacity} 節",
                "class", cid,
                {"assigned": used, "capacity": capacity},
            ))


def _check_rooms(problem: Problem, issues: list[Issue]) -> None:
    # 1) 已綁定場地:逐間比對需求與可用節次
    demand_by_room: dict[int, int] = {}
    for a in problem.assignments:
        if a.room_id is not None:
            demand_by_room[a.room_id] = demand_by_room.get(a.room_id, 0) + a.periods_per_week

    for room_id, demand in demand_by_room.items():
        room = problem.rooms.get(room_id)
        if room is None:
            continue
        supply = _room_supply(problem, room_id)
        if demand > supply:
            issues.append(Issue(
                "error", "room_supply",
                f"場地 {room.name} 需求 {demand} 節,超過可用節次 {supply} 節",
                "room", room_id,
                {"demand": demand, "supply": supply},
            ))

    # 2) 場地類型的總量檢查(§3.4「音樂教室需求 35 節 > 供給 30 節」)。
    #    供給以「該類型場地數 × 單表節次數」估算——這是上界,故只在明顯不足時報錯。
    demand_by_type: dict[str, int] = {}
    for a in problem.assignments:
        if a.required_room_type:
            demand_by_type[a.required_room_type] = (
                demand_by_type.get(a.required_room_type, 0) + a.periods_per_week
            )
    slots_per_room = max((len(t.slots) for t in problem.tables.values()), default=0)
    for room_type, demand in demand_by_type.items():
        rooms = [r for r in problem.rooms.values() if r.room_type == room_type]
        supply = len(rooms) * slots_per_room
        if demand > supply:
            names = "、".join(r.name for r in rooms) or "(無)"
            issues.append(Issue(
                "error", "room_type_supply",
                f"需要「{_ROOM_TYPE_CN.get(room_type, room_type)}」的課共 {demand} 節,"
                f"但這類場地({names})合計只能提供 {supply} 節",
                "semester", problem.semester_id,
                {"room_type": room_type, "demand": demand, "supply": supply},
            ))

    # 3) D8:場地容量僅作警告,不參與求解(同一場地同時段仍是至多一門課)
    for a in problem.assignments:
        if a.room_id is None:
            continue
        room = problem.rooms.get(a.room_id)
        unit = problem.units[a.unit_id]
        if room is None or room.capacity is None or unit.is_group:
            continue  # 跑班群組的學生分流到多門課,人數不可直接相加
        students = sum(c.student_count or 0 for c in problem.classes_of(a))
        if students > room.capacity:
            issues.append(Issue(
                "warning", "room_capacity",
                f"「{a.subject_name}」使用 {room.name}(容量 {room.capacity} 人),"
                f"但上課人數 {students} 人",
                "assignment", a.id,
                {"students": students, "capacity": room.capacity},
            ))


def _check_blocks(problem: Problem, issues: list[Issue]) -> None:
    for a in problem.assignments:
        if not a.blocks:
            continue
        table = problem.table_of(a)
        if table is None:
            continue
        longest = table.longest_run()
        for block in a.blocks:
            if block.size > longest:
                issues.append(Issue(
                    "error", "block_infeasible",
                    f"「{a.subject_name}」要求 {block.size} 連堂,"
                    f"但節次表最長只有 {longest} 節連續的一般課(連堂不可跨午休)",
                    "assignment", a.id,
                    {"block_size": block.size, "longest_run": longest},
                ))
        if a.block_periods > a.periods_per_week:
            issues.append(Issue(
                "error", "block_exceeds_periods",
                f"「{a.subject_name}」連堂共 {a.block_periods} 節,"
                f"超過每週 {a.periods_per_week} 節",
                "assignment", a.id,
                {"block_periods": a.block_periods, "periods_per_week": a.periods_per_week},
            ))


_ROOM_TYPE_CN = {
    "normal": "普通教室",
    "special": "專科教室",
    "workshop": "實習工場",
    "outdoor": "戶外場地",
}
