"""無解衝突定位(architecture.md §3.4)。

市售排課系統無解時只回一句「排不出來」,教學組長只能靠經驗猜。本模組回答的是
「**是哪幾件事湊在一起才排不出來,鬆開哪一個就好了**」,並附上具體數字。

兩條路徑,先廉價後昂貴:

1. **pre-flight**:必要條件不成立(某位教師配課 30 節但只有 21 格可排)。
   這已經是證明,而且數字現成,不必啟動 solver。
2. **逐項驗證**:必要條件全數通過卻仍然無解——代表是幾條約束**交互作用**的結果,
   單看任何一條都很合理。此時把每個「教學組長轉得動的旋鈕」逐一關掉重解,
   看哪一個關掉之後就排得出來。

第 2 條路徑正是差異化所在。例:兩位音樂老師各教 15 節、各自都有充裕的可排時段,
音樂教室一週也有 35 格——每一項單獨看都寬鬆。但兩人都不排週五,音樂教室週五就
沒人能用,實際只有 28 格要塞 30 節課。這種「數字都對、湊起來就是不行」的情形,
任何逐項檢查都抓不到。

**為什麼不用 CP-SAT 的 assumption / unsat core?**
原本的設計(architecture.md §3.4)是每類硬約束掛 assumption literal,無解時取
unsat core。實測不可行:掛上 enforcement literal 之後,presolve 認不出「30 節課
塞進 28 格」的鴿籠結構,同一個問題從 **0.8 秒證完變成 60 秒證不完**。
改用「關掉一組約束 → 重新求解」的刪除法後,每次求解都是完整 presolve 過的乾淨模型,
上例整套定位約 3 秒。附帶的好處是每一條結論都被一次真實的求解驗證過:
報告說「放寬音樂師1 的不可排時段就排得出來」,是因為真的排出來了。

本模組屬於 `app.solver`,不得 import `app.models` / SQLAlchemy(見 problem.py)。
"""

import time
from dataclasses import dataclass, field

from app.solver import preflight
from app.solver.model_builder import (
    RELAXABLE_CODES,
    RELAXABLE_NAMES,
    ConstraintTag,
    check_feasibility,
)
from app.solver.problem import (
    AssignmentSpec,
    ClassSpec,
    Problem,
    RoomSpec,
    Slot,
    SolverConfig,
    TeacherSpec,
    max_non_overlapping,
)

# 衝突定位的預設時間預算。求解本身可能跑十分鐘,但「為什麼排不出來」要儘快回答;
# 拖太久的話,教學組長會直接關掉視窗。
DEFAULT_MAX_SECONDS = 60.0
# 單次試解的上限。試解要嘛很快找到解(該項是成因),要嘛很快證明仍然無解;
# 卡住的那種對定位沒有幫助,不值得等。
STEP_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class Cause:
    """一條「造成無解」的原因。message 說發生什麼事,suggestion 說可以怎麼辦。"""

    code: str  # H3 / H4 / H9 / H10 / structural,或 pre-flight 的檢查代碼
    scope_type: str  # class / teacher / room / assignment / semester
    scope_id: int
    scope_name: str
    message: str
    suggestion: str
    relaxable: bool = False  # 可在「部分排課」中勾選放寬
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConflictReport:
    status: str  # infeasible / feasible / unknown
    source: str  # preflight / analysis / none
    causes: tuple[Cause, ...] = ()
    # each:放寬任一項即可解決。joint:必須一起處理。structural:旋鈕轉到底仍無解。
    mode: str = ""
    wall_time: float = 0.0
    complete: bool = True  # 是否把所有可調項目都試過(時間用完時為 False)

    @property
    def explained(self) -> bool:
        return bool(self.causes)

    @property
    def headline(self) -> str:
        if not self.causes:
            return ""
        if self.source == "preflight":
            return "資料本身就排不出來,以下每一項都必須修正"
        if self.mode == "each":
            return f"以下 {len(self.causes)} 項各自都是瓶頸,放寬其中任何一項即可排出課表"
        if self.mode == "joint":
            return "以下項目必須一起處理,只鬆開其中一項仍然排不出來"
        return "即使放寬所有可調整的項目仍然無解,問題出在配課總量"

    @property
    def relaxable_codes(self) -> tuple[str, ...]:
        """可放寬的約束代碼,依原因出現順序。UI 用來預先勾選「部分排課」選項。"""
        seen: list[str] = []
        for c in self.causes:
            if c.relaxable and c.code not in seen:
                seen.append(c.code)
        return tuple(seen)


def explain(
    problem: Problem,
    *,
    config: SolverConfig | None = None,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> ConflictReport:
    """為什麼排不出來。"""
    config = config or SolverConfig()

    report = preflight.run(problem)
    if not report.ok:
        return ConflictReport(
            status="infeasible",
            source="preflight",
            causes=tuple(_from_issue(problem, i) for i in report.errors),
        )

    started = time.monotonic()
    deadline = started + max_seconds

    base = check_feasibility(problem, config=config, max_seconds=_step(deadline))
    if base != "infeasible":
        status = "feasible" if base == "feasible" else "unknown"
        return ConflictReport(status, "none", wall_time=time.monotonic() - started)

    knobs = _knobs(problem, config)
    tags, mode, complete = _locate(problem, config, knobs, deadline)
    causes = tuple(_describe(problem, tag, config) for tag in tags)
    if mode == "structural":
        causes = _structural_causes(problem)

    return ConflictReport(
        status="infeasible", source="analysis", causes=causes, mode=mode,
        wall_time=time.monotonic() - started, complete=complete,
    )


def _step(deadline: float) -> float:
    return max(1.0, min(STEP_SECONDS, deadline - time.monotonic()))


# ── 定位 ───────────────────────────────────────────────────
def _locate(
    problem: Problem,
    config: SolverConfig,
    knobs: list[ConstraintTag],
    deadline: float,
) -> tuple[list[ConstraintTag], str, bool]:
    """逐一關掉每個旋鈕重解,看誰是瓶頸。"""
    critical: list[ConstraintTag] = []
    complete = True
    for tag in knobs:
        if time.monotonic() >= deadline:
            complete = False
            break
        if _feasible_without(problem, config, {tag}, deadline):
            critical.append(tag)  # 只鬆開這一項就排得出來 → 它就是瓶頸

    if critical:
        return critical, "each", complete

    # 沒有單一項目能解決:要嘛需要同時鬆開多項,要嘛連全部鬆開都不夠
    if not knobs or not _feasible_without(problem, config, set(knobs), deadline):
        return [], "structural", complete
    return _joint(problem, config, knobs, deadline), "joint", complete


def _feasible_without(
    problem: Problem, config: SolverConfig, disabled: set[ConstraintTag], deadline: float
) -> bool:
    status = check_feasibility(
        problem, config=config, disabled=frozenset(disabled), max_seconds=_step(deadline)
    )
    return status == "feasible"  # unknown 一律當作「沒能證明可行」,不亂下結論


def _joint(
    problem: Problem, config: SolverConfig, knobs: list[ConstraintTag], deadline: float
) -> list[ConstraintTag]:
    """需要同時鬆開多項時,找一組夠小的組合:先累加到可行,再逐一試著拿掉。"""
    disabled: set[ConstraintTag] = set()
    for tag in knobs:
        disabled.add(tag)
        if _feasible_without(problem, config, disabled, deadline):
            break
        if time.monotonic() >= deadline:
            break

    for tag in list(disabled):
        if time.monotonic() >= deadline:
            break
        if _feasible_without(problem, config, disabled - {tag}, deadline):
            disabled.discard(tag)  # 少了它照樣可行 → 它不是必要的
    return [t for t in knobs if t in disabled]


def _knobs(problem: Problem, config: SolverConfig) -> list[ConstraintTag]:
    """教學組長轉得動的旋鈕,依「有多緊」由緊到鬆排序。

    H1(班級同時段一門課)與 H2(教師同時段一門課)不在此列:它們沒有旋鈕可轉,
    而且真正的成因(某位教師配課超過可排格數)pre-flight 已經算得出來。
    """
    scored: list[tuple[float, ConstraintTag]] = []

    for room in problem.rooms.values():
        if not _room_users(problem, room):
            continue
        demand, _supply, usable = _room_numbers(problem, room)
        scored.append((demand / max(usable, 1), ConstraintTag("H3", "room", room.id)))

    for teacher in problem.teachers.values():
        if not teacher.unavailable or not problem.assignments_of_teacher(teacher.id):
            continue
        if _blocked_slots(problem, teacher) == 0:
            continue  # 不可排時段全落在午休之類的非上課格位,擋不住任何課
        assigned, available = _teacher_numbers(problem, teacher)
        scored.append((assigned / max(available, 1), ConstraintTag("H4", "teacher", teacher.id)))

    tightest = max(
        (_cap_ratio(problem, cls, sid, config)
         for cls in problem.classes.values()
         for sid in _subject_ids_of(problem, cls)),
        default=0.0,
    )
    if tightest > 0:
        scored.append((tightest, ConstraintTag("H10", "semester", problem.semester_id)))

    if any(f.locked for f in problem.fixed_entries):
        scored.append((1.0, ConstraintTag("H9", "semester", problem.semester_id)))

    scored.sort(key=lambda p: -p[0])
    return [tag for _score, tag in scored]


# ── pre-flight 錯誤 → 原因 ─────────────────────────────────
_PREFLIGHT_SUGGESTIONS = {
    "teacher_overload": "減少該教師的配課節數,或放寬其不可排時段",
    "class_overload": "減少該班配課節數,或在節次表增加一般課節次",
    "room_supply": "增設同類型場地,或把部分課移到其他場地",
    "room_type_supply": "增設該類型的場地,或減少需要此類型場地的課",
    "block_infeasible": "縮短連堂長度,或調整節次表讓連續的一般課更長",
    "block_exceeds_periods": "調整連堂設定,使連堂節數不超過每週節數",
    "group_shape_mismatch": "讓跑班群組內各門課的每週節數與連堂結構一致",
    "no_period_table": "為該班級指派節次表",
    "assignment_without_class": "為該配課指定班級或跑班群組",
}


def _from_issue(problem: Problem, issue: preflight.Issue) -> Cause:
    return Cause(
        code=issue.code,
        scope_type=issue.subject_type,
        scope_id=issue.subject_id,
        scope_name=_scope_name(problem, issue.subject_type, issue.subject_id),
        message=issue.message,
        suggestion=_PREFLIGHT_SUGGESTIONS.get(issue.code, "請修正上述資料"),
        detail=dict(issue.detail),
    )


def _scope_name(problem: Problem, scope_type: str, scope_id: int) -> str:
    if scope_type == "teacher" and scope_id in problem.teachers:
        return problem.teachers[scope_id].name
    if scope_type == "class" and scope_id in problem.classes:
        return problem.classes[scope_id].name
    if scope_type == "room" and scope_id in problem.rooms:
        return problem.rooms[scope_id].name
    if scope_type == "assignment":
        a = next((a for a in problem.assignments if a.id == scope_id), None)
        if a is not None:
            return a.subject_name
    return problem.semester_label


# ── 旋鈕 → 人話 ────────────────────────────────────────────
def _describe(problem: Problem, tag: ConstraintTag, config: SolverConfig) -> Cause:
    builders = {
        "H3": _room_cause,
        "H4": _unavailable_cause,
        "H9": _locked_cause,
        "H10": _daily_cap_cause,
    }
    build = builders[tag.code]
    return build(problem, tag, config)


def _room_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    room = problem.rooms[tag.scope_id]
    demand, supply, usable = _room_numbers(problem, room)

    if usable < supply:
        message = (
            f"場地「{room.name}」需求 {demand} 節,但扣除相關教師的不可排時段後"
            f"只剩 {usable} 節可用(該場地一週共 {supply} 節)"
        )
    else:
        message = f"場地「{room.name}」需求 {demand} 節,可用 {usable} 節,同時段只能容納一班"

    return Cause(
        "H3", "room", room.id, room.name, message,
        "增設同類型場地、把部分課移到其他場地,或放寬使用該場地之教師的不可排時段",
        _relaxable("H3"),
        {"demand": demand, "supply": supply, "usable": usable},
    )


def _unavailable_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    teacher = problem.teachers[tag.scope_id]
    assigned, available = _teacher_numbers(problem, teacher)
    blocked = _blocked_slots(problem, teacher)
    return Cause(
        "H4", "teacher", teacher.id, teacher.name,
        f"教師{teacher.name} 有 {blocked} 格不可排時段,扣除後只剩 {available} 格"
        f"可安排 {assigned} 節課,擋住了排課",
        f"放寬 {teacher.name} 的不可排時段(或在部分排課中勾選放寬此項)",
        _relaxable("H4"),
        {"assigned": assigned, "available": available, "unavailable": blocked},
    )


def _locked_cause(problem: Problem, tag: ConstraintTag, _config: SolverConfig) -> Cause:
    locked = [f for f in problem.fixed_entries if f.locked]
    by_id = {a.id: a for a in problem.assignments}
    sample = "、".join(
        f"「{by_id[f.assignment_id].subject_name}」"
        f"{_cell_label(problem, by_id[f.assignment_id], f.weekday, f.period_no)}"
        for f in locked[:3]
        if f.assignment_id in by_id
    )
    tail = f"(共 {len(locked)} 格)" if len(locked) > 3 else ""
    return Cause(
        # 全校性的旋鈕沒有「某位教師」「某間場地」可指,scope_name 用旋鈕本身的名字,
        # 學期名稱對讀報告的人毫無資訊。
        "H9", "semester", tag.scope_id, RELAXABLE_NAMES["H9"],
        f"來源草稿中被鎖定的格位與其他限制衝突:{sample}{tail}",
        "解除這些格位的鎖定,或改動與它們衝突的其他課",
        _relaxable("H9"),
        {"locked": len(locked)},
    )


def _daily_cap_cause(problem: Problem, tag: ConstraintTag, config: SolverConfig) -> Cause:
    cap = config.daily_subject_cap
    over = _over_cap_pairs(problem, config)
    if over:
        cls, subject_name, singles, ceiling, days = over[0]
        extra = f",另有 {len(over) - 1} 組同樣超量" if len(over) > 1 else ""
        message = (
            f"班級 {cls.name}「{subject_name}」有 {singles} 節單節課,"
            f"但每日上限 {cap} 節 × {days} 天最多只能排 {ceiling} 節{extra}"
        )
        detail = {"cap": cap, "singles": singles, "ceiling": ceiling, "over_pairs": len(over)}
    else:
        message = (
            f"「同班同科目每日至多 {cap} 節」的限制與其他條件一起造成無解"
            f"(單看任何一個班級都沒有超量)"
        )
        detail = {"cap": cap, "over_pairs": 0}

    return Cause(
        "H10", "semester", tag.scope_id, RELAXABLE_NAMES["H10"], message,
        "提高「同班同科目每日節數上限」,或把部分節數改為連堂"
        "(連堂是一次上完的整塊,不計入每日上限)",
        _relaxable("H10"),
        detail,
    )


def _structural_causes(problem: Problem) -> tuple[Cause, ...]:
    """所有旋鈕都轉到底仍然無解:問題出在配課總量與可排格數的硬碰硬。

    列出最吃緊的班級與教師——pre-flight 沒報錯只代表沒有單一項目超量,
    但湊在一起就是塞不下。
    """
    rows: list[tuple[float, Cause]] = []
    for cls in problem.classes.values():
        used, capacity = _class_numbers(problem, cls)
        if capacity:
            rows.append((used / capacity, Cause(
                "structural", "class", cls.id, cls.name,
                f"班級 {cls.name} 每週配課 {used} 節,可排節次 {capacity} 格",
                "減少該班配課節數,或在節次表增加一般課節次",
                detail={"assigned": used, "capacity": capacity},
            )))
    for teacher in problem.teachers.values():
        assigned, available = _teacher_numbers(problem, teacher)
        if assigned and available:
            rows.append((assigned / available, Cause(
                "structural", "teacher", teacher.id, teacher.name,
                f"教師{teacher.name} 配課 {assigned} 節,可排時段 {available} 格",
                f"減少 {teacher.name} 的配課,或改由其他教師分擔",
                detail={"assigned": assigned, "available": available},
            )))
    rows.sort(key=lambda r: -r[0])
    return tuple(c for _score, c in rows[:5])


def _relaxable(code: str) -> bool:
    return code in RELAXABLE_CODES


# ── 數字 ───────────────────────────────────────────────────
def _class_numbers(problem: Problem, cls: ClassSpec) -> tuple[int, int]:
    used = sum(
        problem.unit_slot_consumption(u.id)
        for u in problem.units.values()
        if cls.id in u.class_ids
    )
    table = problem.tables.get(cls.period_table_id)
    return used, len(table.slots) if table else 0


def _teacher_numbers(problem: Problem, teacher: TeacherSpec) -> tuple[int, int]:
    assigned = sum(a.periods_per_week for a in problem.assignments_of_teacher(teacher.id))
    return assigned, preflight.teacher_available_slots(problem, teacher)


def _blocked_slots(problem: Problem, teacher: TeacherSpec) -> int:
    """不可排時段中,真正落在一般課節次上的格數(設在午休上的規則不擋住任何課)。"""
    cells = {s.key for table in problem.tables_of_teacher(teacher.id) for s in table.slots}
    return len(cells & teacher.unavailable)


def _room_users(problem: Problem, room: RoomSpec) -> list[AssignmentSpec]:
    bound = [a for a in problem.assignments if a.room_id == room.id]
    if bound:
        return bound
    # 未綁定場地、由引擎在候選中挑選的配課
    return [
        a for a in problem.assignments
        if a.room_id is None
        and a.required_room_type == room.room_type
        and (not room.subject_ids or a.subject_id in room.subject_ids)
    ]


def _room_numbers(problem: Problem, room: RoomSpec) -> tuple[int, int, int]:
    """(需求節數, 該場地一週的節次數, 扣掉相關教師不可排時段後真正可用的節次數)。"""
    users = _room_users(problem, room)
    demand = sum(a.periods_per_week for a in users)

    all_slots: dict[tuple[int, int, int], Slot] = {}
    free_slots: dict[tuple[int, int, int], Slot] = {}
    for a in users:
        table = problem.table_of(a)
        if table is None:
            continue
        forbidden = {
            cell
            for tid in a.teacher_ids
            if tid in problem.teachers
            for cell in problem.teachers[tid].unavailable
        }
        for s in table.slots:
            all_slots[(table.id, *s.key)] = s
            if s.key not in forbidden:
                free_slots[(table.id, *s.key)] = s

    supply = max_non_overlapping(list(all_slots.values()))
    usable = max_non_overlapping(list(free_slots.values()))
    return demand, supply, usable


def _subject_ids_of(problem: Problem, cls: ClassSpec) -> set[int]:
    return {
        a.subject_id
        for a in problem.assignments
        if cls.id in problem.units[a.unit_id].class_ids
    }


def _subject_singles(problem: Problem, cls: ClassSpec, subject_id: int) -> tuple[int, str]:
    """該班該科目的「單節」總數(連堂不計入每日上限)與科目名稱。"""
    singles = 0
    name = str(subject_id)
    for a in problem.assignments:
        if a.subject_id != subject_id or cls.id not in problem.units[a.unit_id].class_ids:
            continue
        name = a.subject_name
        singles += a.periods_per_week - a.block_periods
    return singles, name


def _cap_ratio(problem: Problem, cls: ClassSpec, subject_id: int, config: SolverConfig) -> float:
    singles, _name = _subject_singles(problem, cls, subject_id)
    table = problem.tables.get(cls.period_table_id)
    ceiling = config.daily_subject_cap * (table.num_weekdays if table else 0)
    return singles / ceiling if ceiling else 0.0


def _over_cap_pairs(
    problem: Problem, config: SolverConfig
) -> list[tuple[ClassSpec, str, int, int, int]]:
    """(班級, 科目, 單節數, 每週上限, 天數),依超量程度排序。"""
    out = []
    for cls in problem.classes.values():
        table = problem.tables.get(cls.period_table_id)
        days = table.num_weekdays if table else 0
        ceiling = config.daily_subject_cap * days
        for sid in _subject_ids_of(problem, cls):
            singles, name = _subject_singles(problem, cls, sid)
            if ceiling and singles > ceiling:
                out.append((cls, name, singles, ceiling, days))
    out.sort(key=lambda r: r[3] - r[2])
    return out


def _cell_label(problem: Problem, a: AssignmentSpec, weekday: int, period_no: int) -> str:
    """「週二第三節」——一律用節次表裡的名稱,不用內部的節次編號。"""
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    day = names[weekday - 1] if 1 <= weekday <= 7 else f"星期{weekday}"
    table = problem.table_of(a)
    slot = table.slot(weekday, period_no) if table else None
    return f"{day}{slot.name}" if slot else f"{day}第 {period_no} 格"


__all__ = [
    "DEFAULT_MAX_SECONDS",
    "RELAXABLE_CODES",
    "RELAXABLE_NAMES",
    "Cause",
    "ConflictReport",
    "explain",
]
