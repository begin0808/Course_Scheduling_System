"""排課問題的純資料描述。

**此模組(及整個 `app.solver` 套件)不得 import `app.models` / `app.api` / SQLAlchemy。**
排課引擎只認得這裡的 dataclass;DB → Problem 的轉換放在 `app.services.solver_data`。
如此引擎可獨立測試、獨立跑在 worker 容器,也不會被 ORM 的 lazy loading 拖垮效能。

時間一律以「當日分鐘數」(minutes since midnight)表示,避免 solver 依賴 datetime。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# (period_table_id, weekday, period_no)
SlotKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Slot:
    """節次表中的一個「一般課」格位(非一般課不進 Problem)。"""

    weekday: int
    period_no: int
    name: str  # 顯示名稱(第一節/第五節);人話訊息一律用此欄,不用 period_no
    start_min: int | None
    end_min: int | None

    @property
    def key(self) -> tuple[int, int]:
        return (self.weekday, self.period_no)

    @property
    def has_time(self) -> bool:
        return self.start_min is not None and self.end_min is not None


@dataclass(frozen=True, slots=True)
class PeriodTableSpec:
    id: int
    name: str
    num_weekdays: int
    slots: tuple[Slot, ...]  # 僅 regular,依 (weekday, period_no) 排序

    def slot(self, weekday: int, period_no: int) -> Slot | None:
        return next(
            (s for s in self.slots if s.weekday == weekday and s.period_no == period_no), None
        )

    def slots_on(self, weekday: int) -> tuple[Slot, ...]:
        return tuple(s for s in self.slots if s.weekday == weekday)

    def longest_run(self) -> int:
        """全表最長的「連續一般課」段長度(連堂上限,H6 不跨午休)。"""
        best = 0
        for weekday in range(1, self.num_weekdays + 1):
            run = 0
            prev: int | None = None
            for s in self.slots_on(weekday):
                run = run + 1 if prev is not None and s.period_no == prev + 1 else 1
                prev = s.period_no
                best = max(best, run)
        return best


@dataclass(frozen=True, slots=True)
class TeacherSpec:
    id: int
    name: str
    base_periods: int
    admin_reduction: int
    is_external: bool
    # 不可排時段(H4)。(weekday, period_no) 以其任教班級的節次表解讀
    # ——多套節次表的學校語意會浮動,見 tasks.md Backlog。
    unavailable: frozenset[tuple[int, int]]

    @property
    def target_periods(self) -> int:
        return max(self.base_periods - self.admin_reduction, 0)


@dataclass(frozen=True, slots=True)
class RoomSpec:
    id: int
    name: str
    room_type: str
    capacity: int | None


@dataclass(frozen=True, slots=True)
class ClassSpec:
    id: int
    name: str
    grade: int
    period_table_id: int  # 已解析(指定表 → 學期預設表),solver 不需再回退
    student_count: int | None


@dataclass(frozen=True, slots=True)
class BlockSpec:
    size: int
    count: int


@dataclass(frozen=True, slots=True)
class UnitSpec:
    id: int
    unit_type: str  # single / group
    name: str
    class_ids: tuple[int, ...]

    @property
    def is_group(self) -> bool:
        return self.unit_type == "group"


@dataclass(frozen=True, slots=True)
class AssignmentSpec:
    id: int
    unit_id: int
    subject_id: int
    subject_name: str
    periods_per_week: int
    teacher_ids: tuple[int, ...]
    room_id: int | None
    required_room_type: str | None
    lock_room: bool
    blocks: tuple[BlockSpec, ...]

    @property
    def block_periods(self) -> int:
        return sum(b.size * b.count for b in self.blocks)


@dataclass(frozen=True, slots=True)
class FixedEntry:
    """既有課表的格位。locked=True 者為 H9 硬約束,其餘可作為求解起點提示。"""

    assignment_id: int
    weekday: int
    period_no: int
    span: int
    room_id: int | None
    locked: bool


@dataclass(frozen=True, slots=True)
class Problem:
    semester_id: int
    semester_label: str
    tables: Mapping[int, PeriodTableSpec]
    classes: Mapping[int, ClassSpec]
    teachers: Mapping[int, TeacherSpec]
    rooms: Mapping[int, RoomSpec]
    units: Mapping[int, UnitSpec]
    assignments: tuple[AssignmentSpec, ...]
    fixed_entries: tuple[FixedEntry, ...] = ()

    # ── 導覽 ────────────────────────
    def classes_of(self, a: AssignmentSpec) -> tuple[ClassSpec, ...]:
        return tuple(self.classes[cid] for cid in self.units[a.unit_id].class_ids)

    def table_of(self, a: AssignmentSpec) -> PeriodTableSpec | None:
        """配課所屬節次表。跑班群組成員保證同表(D7#4),故取第一個班級即可。"""
        members = self.classes_of(a)
        if not members:
            return None
        return self.tables.get(members[0].period_table_id)

    def assignments_of_teacher(self, teacher_id: int) -> tuple[AssignmentSpec, ...]:
        return tuple(a for a in self.assignments if teacher_id in a.teacher_ids)

    def tables_of_teacher(self, teacher_id: int) -> tuple[PeriodTableSpec, ...]:
        seen: dict[int, PeriodTableSpec] = {}
        for a in self.assignments_of_teacher(teacher_id):
            table = self.table_of(a)
            if table is not None:
                seen[table.id] = table
        return tuple(seen.values())

    def unit_slot_consumption(self, unit_id: int) -> int:
        """該排課單位佔用成員班級的節數。

        single:單位內各配課節數總和;group:群組內配課同時段開課(H7),
        班級只被佔掉最長的那一筆。
        """
        periods = [a.periods_per_week for a in self.assignments if a.unit_id == unit_id]
        if not periods:
            return 0
        return max(periods) if self.units[unit_id].is_group else sum(periods)


# ── 時段重疊(architecture.md D7)────────────────────────────
def slots_overlap(a: Slot, b: Slot, *, same_table: bool) -> bool:
    """兩個節次是否「同時段」。

    同一節次表退化為節次號相等(常見情形,零額外成本);
    跨表則以牆鐘時間區間重疊判定——節次號相同不代表時間相同。
    """
    if a.weekday != b.weekday:
        return False
    if same_table:
        return a.period_no == b.period_no
    if not (a.has_time and b.has_time):
        return False
    assert a.start_min is not None and a.end_min is not None
    assert b.start_min is not None and b.end_min is not None
    return a.start_min < b.end_min and b.start_min < a.end_min


def max_non_overlapping(slots: Sequence[Slot]) -> int:
    """一組節次中,互不重疊的最大數量(每星期各自計算後加總)。

    這是「一位教師最多能上幾節課」的正確上限:同表的節次天然不重疊,
    數量即節次數;跨表(完全中學同時任教國中部/高中部)則因牆鐘時間交錯,
    可上的節數少於兩表節次之和。以區間排程的貪婪法(取最早結束者)求解。
    """
    total = 0
    by_weekday: dict[int, list[Slot]] = {}
    for s in slots:
        by_weekday.setdefault(s.weekday, []).append(s)

    for day_slots in by_weekday.values():
        timed = [s for s in day_slots if s.has_time]
        if len(timed) != len(day_slots):
            # 節次表缺起訖時間:無法判定重疊,退化為節次數(單表學校的正確值)
            total += len({(s.period_no) for s in day_slots})
            continue
        last_end = -1
        for s in sorted(timed, key=lambda x: (x.end_min, x.start_min)):
            assert s.start_min is not None and s.end_min is not None
            if s.start_min >= last_end:
                total += 1
                last_end = s.end_min
    return total
