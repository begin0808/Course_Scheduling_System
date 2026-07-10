"""課表硬約束驗證器(architecture.md §3.2 H1–H10)。

**刻意與 `model_builder` 完全不共用程式碼。** 測試策略總則第 2 點:排課引擎的解一律以
本驗證器逐項檢查,絕不以 solver 自身回報的狀態為準——建模寫錯時 solver 會很有信心地
交出一個違反硬約束的「可行解」。

同一支驗證器日後也用於「匯入外部課表 → 檢查衝突」。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.solver.problem import (
    AssignmentSpec,
    Problem,
    Slot,
    SolvedEntry,
    slots_overlap,
)

DEFAULT_DAILY_SUBJECT_CAP = 2  # H10 同班同科目每日單節上限(連堂不計)


@dataclass(frozen=True, slots=True)
class Violation:
    code: str  # H1..H10 / room_type
    message: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Occurrence:
    """一筆格位在某一節次上的佔用。"""

    entry: SolvedEntry
    assignment: AssignmentSpec
    table_id: int
    slot: Slot


def _wd(weekday: int) -> str:
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"


def _effective_room(problem: Problem, entry: SolvedEntry, a: AssignmentSpec) -> int | None:
    return entry.room_id if entry.room_id is not None else a.room_id


def validate(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    *,
    daily_subject_cap: int = DEFAULT_DAILY_SUBJECT_CAP,
) -> tuple[Violation, ...]:
    """回傳所有硬約束違反;空 tuple 表示這份課表完全合法。"""
    v: list[Violation] = []
    by_id = {a.id: a for a in problem.assignments}

    unknown = [e for e in entries if e.assignment_id not in by_id]
    if unknown:
        return (Violation("input", f"有 {len(unknown)} 筆格位指向不存在的配課"),)

    occurrences = _expand(problem, entries, by_id, v)
    _h1_class(problem, occurrences, v)
    _h2_teacher(problem, occurrences, v)
    _h3_room(problem, occurrences, v)
    _h4_unavailable(problem, occurrences, v)
    _h7_group_sync(problem, entries, by_id, v)
    _h8_weekly_periods(problem, entries, by_id, v)
    _h9_locked(problem, entries, v)
    _h10_daily_cap(problem, entries, by_id, daily_subject_cap, v)
    _room_type(problem, entries, by_id, v)
    return tuple(v)


def _expand(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    by_id: dict[int, AssignmentSpec],
    v: list[Violation],
) -> list[_Occurrence]:
    """展開每筆格位涵蓋的節次,順帶驗 H5(節次有效)與 H6(連堂連續不跨午休)。"""
    out: list[_Occurrence] = []
    for e in entries:
        a = by_id[e.assignment_id]
        table = problem.table_of(a)
        if table is None:
            v.append(Violation("H5", f"配課「{a.subject_name}」無節次表", {"assignment_id": a.id}))
            continue
        for k in range(e.span):
            slot = table.slot(e.weekday, e.period_no + k)
            if slot is None:
                code = "H6" if e.span > 1 else "H5"
                reason = (
                    f"{e.span} 連堂涵蓋的第 {k + 1} 節不是連續的一般課(跨越午休或不存在)"
                    if e.span > 1
                    else "不是一般上課節次"
                )
                v.append(Violation(
                    code,
                    f"「{a.subject_name}」{_wd(e.weekday)}第 {e.period_no + k} 格{reason}",
                    {"assignment_id": a.id, "weekday": e.weekday, "period_no": e.period_no + k},
                ))
                continue
            out.append(_Occurrence(e, a, table.id, slot))
    return out


def _h1_class(problem: Problem, occ: list[_Occurrence], v: list[Violation]) -> None:
    """班級同時段至多一門課。跑班群組同進同出,整組只佔班級一格。"""
    seen: dict[tuple[int, int, int], set[tuple[str, int]]] = {}
    for o in occ:
        key_course = problem.course_key(o.assignment)
        for cls in problem.classes_of(o.assignment):
            key = (cls.id, o.slot.weekday, o.slot.period_no)
            courses = seen.setdefault(key, set())
            courses.add(key_course)
            if len(courses) > 1:
                v.append(Violation(
                    "H1",
                    f"班級 {cls.name} {_wd(o.slot.weekday)}{o.slot.name} 同時有多門課",
                    {"class_id": cls.id, "weekday": o.slot.weekday,
                     "period_no": o.slot.period_no},
                ))


def _pairwise_resource_clash(
    problem: Problem,
    occ: list[_Occurrence],
    resource_of,
    label: str,
    code: str,
    name_of,
    v: list[Violation],
) -> None:
    """教師/場地是跨班級共用的資源:同一資源的兩筆佔用在牆鐘上重疊即衝突(D7)。"""
    buckets: dict[int, list[_Occurrence]] = {}
    for o in occ:
        for rid in resource_of(o):
            buckets.setdefault(rid, []).append(o)

    for rid, items in buckets.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a.entry is b.entry:
                    continue
                if not slots_overlap(a.slot, b.slot, same_table=a.table_id == b.table_id):
                    continue
                v.append(Violation(
                    code,
                    f"{label} {name_of(rid)} {_wd(a.slot.weekday)}{a.slot.name} 同時有"
                    f"「{a.assignment.subject_name}」與「{b.assignment.subject_name}」",
                    {"resource_id": rid, "weekday": a.slot.weekday},
                ))


def _h2_teacher(problem: Problem, occ: list[_Occurrence], v: list[Violation]) -> None:
    _pairwise_resource_clash(
        problem, occ,
        resource_of=lambda o: o.assignment.teacher_ids,
        label="教師", code="H2",
        name_of=lambda tid: problem.teachers[tid].name,
        v=v,
    )


def _h3_room(problem: Problem, occ: list[_Occurrence], v: list[Violation]) -> None:
    def rooms(o: _Occurrence) -> tuple[int, ...]:
        rid = _effective_room(problem, o.entry, o.assignment)
        return (rid,) if rid is not None else ()

    _pairwise_resource_clash(
        problem, occ,
        resource_of=rooms, label="場地", code="H3",
        name_of=lambda rid: problem.rooms[rid].name if rid in problem.rooms else str(rid),
        v=v,
    )


def _h4_unavailable(problem: Problem, occ: list[_Occurrence], v: list[Violation]) -> None:
    for o in occ:
        for tid in o.assignment.teacher_ids:
            teacher = problem.teachers.get(tid)
            if teacher and o.slot.key in teacher.unavailable:
                v.append(Violation(
                    "H4",
                    f"教師{teacher.name} {_wd(o.slot.weekday)}{o.slot.name} 為不可排時段",
                    {"teacher_id": tid, "weekday": o.slot.weekday,
                     "period_no": o.slot.period_no},
                ))


def _h7_group_sync(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    by_id: dict[int, AssignmentSpec],
    v: list[Violation],
) -> None:
    """跑班群組內的所有配課必須排在完全相同的時段。"""
    by_assignment: dict[int, set[tuple[int, int, int]]] = {}
    for e in entries:
        by_assignment.setdefault(e.assignment_id, set()).add((e.weekday, e.period_no, e.span))

    for unit in problem.units.values():
        if not unit.is_group:
            continue
        members = [a for a in problem.assignments if a.unit_id == unit.id]
        slots = {frozenset(by_assignment.get(a.id, set())) for a in members}
        if len(slots) > 1:
            v.append(Violation(
                "H7",
                f"跑班群組「{unit.name}」的各門課未排在相同時段",
                {"unit_id": unit.id},
            ))


def _h8_weekly_periods(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    by_id: dict[int, AssignmentSpec],
    v: list[Violation],
) -> None:
    """每筆配課排入的節數 = 設定的每週節數,且連堂結構符合 block_rule。"""
    spans: dict[int, list[int]] = {}
    for e in entries:
        spans.setdefault(e.assignment_id, []).append(e.span)

    for a in problem.assignments:
        got = sorted(spans.get(a.id, []), reverse=True)
        expected: list[int] = []
        for b in a.blocks:
            expected.extend([b.size] * b.count)
        expected.extend([1] * (a.periods_per_week - a.block_periods))
        expected.sort(reverse=True)
        if got != expected:
            v.append(Violation(
                "H8",
                f"「{a.subject_name}」排入 {sum(got)} 節(節長 {got or '無'}),"
                f"應為 {a.periods_per_week} 節(節長 {expected})",
                {"assignment_id": a.id, "placed": got, "expected": expected},
            ))


def _h9_locked(problem: Problem, entries: Sequence[SolvedEntry], v: list[Violation]) -> None:
    placed = {(e.assignment_id, e.weekday, e.period_no, e.span) for e in entries}
    for f in problem.fixed_entries:
        if not f.locked:
            continue
        if (f.assignment_id, f.weekday, f.period_no, f.span) not in placed:
            v.append(Violation(
                "H9",
                f"鎖定的格位(配課 {f.assignment_id} {_wd(f.weekday)}第 {f.period_no} 格)被移動了",
                {"assignment_id": f.assignment_id, "weekday": f.weekday,
                 "period_no": f.period_no},
            ))


def _h10_daily_cap(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    by_id: dict[int, AssignmentSpec],
    cap: int,
    v: list[Violation],
) -> None:
    """同班同科目每日至多 N 節。連堂本來就是一次上完,不計入。"""
    counts: dict[tuple[int, int, int], int] = {}
    for e in entries:
        if e.span != 1:
            continue
        a = by_id[e.assignment_id]
        for cls in problem.classes_of(a):
            key = (cls.id, e.weekday, a.subject_id)
            counts[key] = counts.get(key, 0) + 1

    for (class_id, weekday, _subject_id), n in counts.items():
        if n > cap:
            cls = problem.classes[class_id]
            v.append(Violation(
                "H10",
                f"班級 {cls.name} {_wd(weekday)} 同一科目排了 {n} 節,超過每日上限 {cap} 節",
                {"class_id": class_id, "weekday": weekday, "count": n},
            ))


def _room_type(
    problem: Problem,
    entries: Sequence[SolvedEntry],
    by_id: dict[int, AssignmentSpec],
    v: list[Violation],
) -> None:
    for e in entries:
        a = by_id[e.assignment_id]
        if not a.required_room_type:
            continue
        rid = _effective_room(problem, e, a)
        room = problem.rooms.get(rid) if rid is not None else None
        if room is None:
            v.append(Violation(
                "room_type", f"「{a.subject_name}」需要場地,卻未指派",
                {"assignment_id": a.id},
            ))
        elif room.room_type != a.required_room_type:
            v.append(Violation(
                "room_type",
                f"「{a.subject_name}」需要 {a.required_room_type} 類型場地,"
                f"卻排在 {room.name}({room.room_type})",
                {"assignment_id": a.id, "room_id": room.id},
            ))
