"""手動排課的硬約束單格檢查(architecture.md §3.2 H1–H10 的單格版)。

放入/移動一筆配課到某格位時,檢查是否違反硬約束並回傳人話衝突清單。
跨節次表的教師(H2)/場地(H3)衝突以「同星期 + 牆鐘時間區間重疊」判定
(architecture.md D7);同節次表則退化為 period_no 相等(常見情形,零額外成本)。
跑班群組:同群組多筆配課同時排在同一格(H7),批次一起檢查;群組成員班級由
多門課共用(不互相視為 H1 衝突),但彼此的教師/場地仍不可重複。
"""

from dataclasses import dataclass
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assignment import (
    AssignmentTeacher,
    CourseAssignment,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.basedata import ClassUnit, Room, Subject
from app.models.period import Period, PeriodType
from app.models.timetable import ScheduleEntry, Timetable
from app.services import period_tables as pt_service

WEEKDAY_CN = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
DEFAULT_DAILY_SUBJECT_CAP = 2  # H10 同班同科目每日上限(連堂除外)


@dataclass
class Conflict:
    code: str  # H1..H10
    message: str


@dataclass
class Placement:
    assignment: CourseAssignment
    weekday: int
    period_no: int
    span: int = 1
    # 本格位實際使用的場地(空=沿用配課場地);手動改教室或引擎逐格指派時帶入
    room_id: int | None = None

    @property
    def effective_room_id(self) -> int | None:
        return self.room_id if self.room_id is not None else self.assignment.room_id


@dataclass
class _Occ:
    weekday: int
    table_id: int
    period_no: int
    start: time | None
    end: time | None
    desc: str


def _wd(w: int) -> str:
    return WEEKDAY_CN[w - 1] if 1 <= w <= len(WEEKDAY_CN) else f"星期{w}"


class _Checker:
    def __init__(self, db: Session, timetable: Timetable) -> None:
        self.db = db
        self.timetable = timetable
        self._pmap_cache: dict[int, dict[tuple[int, int], Period]] = {}
        self._table_cache: dict[int, int | None] = {}
        self._class_table_cache: dict[int, int | None] = {}
        self._default_table_cache: dict[int, int | None] = {}
        self._room_name_cache: dict[int, str] = {}

    def _room_name(self, room_id: int) -> str:
        if room_id not in self._room_name_cache:
            room = self.db.get(Room, room_id)
            self._room_name_cache[room_id] = room.name if room else str(room_id)
        return self._room_name_cache[room_id]

    def _period_map(self, table_id: int) -> dict[tuple[int, int], Period]:
        if table_id not in self._pmap_cache:
            rows = self.db.scalars(select(Period).where(Period.period_table_id == table_id))
            self._pmap_cache[table_id] = {(p.weekday, p.period_no): p for p in rows}
        return self._pmap_cache[table_id]

    def _default_table_id(self, semester_id: int) -> int | None:
        if semester_id not in self._default_table_cache:
            t = pt_service.semester_default_table(self.db, semester_id)
            self._default_table_cache[semester_id] = t.id if t else None
        return self._default_table_cache[semester_id]

    def _table_for_class(self, class_id: int, semester_id: int, table_id: int | None) -> int | None:
        """等同 resolve_period_table(指定表 → 回退學期預設表),但於單次檢查內快取,
        避免每筆配課都重查一次學期預設表(check-conflict 需 <100ms)。"""
        if class_id not in self._class_table_cache:
            self._class_table_cache[class_id] = (
                table_id if table_id is not None else self._default_table_id(semester_id)
            )
        return self._class_table_cache[class_id]

    def _class_table_id(self, cls: ClassUnit) -> int | None:
        return self._table_for_class(cls.id, cls.semester_id, cls.period_table_id)

    def _table_id(self, a: CourseAssignment) -> int | None:
        if a.id not in self._table_cache:
            members = a.scheduling_unit.members
            cls = members[0].class_unit if members else None
            self._table_cache[a.id] = self._class_table_id(cls) if cls else None
        return self._table_cache[a.id]

    def _classes(self, a: CourseAssignment):
        return [m.class_unit for m in a.scheduling_unit.members]

    def _desc(self, a: CourseAssignment) -> str:
        names = "、".join(m.class_unit.name for m in a.scheduling_unit.members)
        return f"{names} 班{a.subject.name}"

    def _slot(self, pmap: dict[tuple[int, int], Period], weekday: int, pno: int) -> str:
        """人話時段標籤:用節次表裡的名稱(早自習/午休/第一節),而非內部 period_no。

        period_no 是含早自習/午休的內部索引(國中範本第一節的 period_no 是 2),
        直接顯示會與教學組長的認知不符。
        """
        p = pmap.get((weekday, pno))
        return f"{_wd(weekday)}{p.name}" if p else f"{_wd(weekday)}第{pno}節"

    def _overlap(
        self, occ: _Occ, weekday: int, table_id: int, pno: int, start: time | None, end: time | None
    ) -> bool:
        if occ.weekday != weekday:
            return False
        if occ.table_id == table_id:
            return occ.period_no == pno  # 同表:節次號相等
        # 跨節次表:牆鐘時間區間重疊(D7)
        if occ.start and occ.end and start and end:
            return start < occ.end and occ.start < end
        return False

    def _build_occupancy(self, ignore_entry_ids: set[int]):
        """以欄位查詢(非 ORM 實體)建立既有格位的佔用索引。

        check-conflict 是拖曳時的熱路徑(目標 p95 <100ms),逐格 hydrate ORM 物件
        在 60 班規模下代價過高,故此處只取需要的欄位並在 Python 端組裝。
        """
        class_occ: dict[tuple[int, int, int], str] = {}
        teacher_occ: dict[int, list[_Occ]] = {}
        room_occ: dict[int, list[_Occ]] = {}
        subj_count: dict[tuple[int, int, int], int] = {}

        rows = self.db.execute(
            select(
                ScheduleEntry.id, ScheduleEntry.weekday, ScheduleEntry.period_no,
                ScheduleEntry.span, CourseAssignment.id, CourseAssignment.subject_id,
                # 格位場地優先,未指定才沿用配課場地
                func.coalesce(ScheduleEntry.room_id, CourseAssignment.room_id),
                CourseAssignment.scheduling_unit_id, Subject.name,
            )
            .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
            .join(Subject, Subject.id == CourseAssignment.subject_id)
            .where(ScheduleEntry.timetable_id == self.timetable.id)
        ).all()
        rows = [r for r in rows if r[0] not in ignore_entry_ids]
        if not rows:
            return class_occ, teacher_occ, room_occ, subj_count

        unit_ids = {r[7] for r in rows}
        a_ids = {r[4] for r in rows}

        # 排課單位 → 成員班級(id, 班名, 節次表)
        classes_by_unit: dict[int, list[tuple[int, str, int | None]]] = {}
        for uid, cid, cname, c_sem, c_table in self.db.execute(
            select(
                SchedulingUnitMember.scheduling_unit_id, ClassUnit.id, ClassUnit.name,
                ClassUnit.semester_id, ClassUnit.period_table_id,
            )
            .join(ClassUnit, ClassUnit.id == SchedulingUnitMember.class_unit_id)
            .where(SchedulingUnitMember.scheduling_unit_id.in_(unit_ids))
        ).all():
            classes_by_unit.setdefault(uid, []).append(
                (cid, cname, self._table_for_class(cid, c_sem, c_table))
            )

        # 配課 → 教師
        teachers_by_a: dict[int, list[int]] = {}
        for aid, tid in self.db.execute(
            select(AssignmentTeacher.course_assignment_id, AssignmentTeacher.teacher_id)
            .where(AssignmentTeacher.course_assignment_id.in_(a_ids))
        ).all():
            teachers_by_a.setdefault(aid, []).append(tid)

        for _e_id, wd, pno0, span, a_id, subject_id, room_id, unit_id, subj_name in rows:
            classes = classes_by_unit.get(unit_id, [])
            if not classes:
                continue
            table_id = classes[0][2]
            if table_id is None:
                continue
            pmap = self._period_map(table_id)
            desc = f"{'、'.join(c[1] for c in classes)} 班{subj_name}"
            t_ids = teachers_by_a.get(a_id, [])
            for k in range(span):
                pno = pno0 + k
                p = pmap.get((wd, pno))
                start = p.start_time if p else None
                end = p.end_time if p else None
                occ = _Occ(wd, table_id, pno, start, end, desc)
                for cid, _cname, _ct in classes:
                    class_occ[(cid, wd, pno)] = desc
                for t_id in t_ids:
                    teacher_occ.setdefault(t_id, []).append(occ)
                if room_id:
                    room_occ.setdefault(room_id, []).append(occ)
            for cid, _cname, _ct in classes:
                key = (cid, wd, subject_id)
                subj_count[key] = subj_count.get(key, 0) + span
        return class_occ, teacher_occ, room_occ, subj_count

    def check(self, placements: list[Placement], ignore_entry_ids: set[int]) -> list[Conflict]:
        class_occ, teacher_occ, room_occ, subj_count = self._build_occupancy(ignore_entry_ids)
        conflicts: list[Conflict] = []
        batch_teacher: dict[int, list[_Occ]] = {}
        batch_room: dict[int, list[_Occ]] = {}

        for pl in placements:
            a = pl.assignment
            wd = pl.weekday
            table_id = self._table_id(a)
            if table_id is None:
                conflicts.append(Conflict("H5", f"{self._desc(a)} 尚無可用節次表"))
                continue
            pmap = self._period_map(table_id)

            # H5/H6:區塊涵蓋的節次須存在且皆為一般課
            covered: list[tuple[int, time | None, time | None]] = []
            block_ok = True
            for k in range(pl.span):
                pno = pl.period_no + k
                p = pmap.get((wd, pno))
                if p is None or p.type != PeriodType.regular.value:
                    block_ok = False
                    break
                covered.append((pno, p.start_time, p.end_time))
            if not block_ok:
                if pl.span > 1:
                    conflicts.append(Conflict(
                        "H6",
                        f"連堂課排在 {self._slot(pmap, wd, pl.period_no)} 會跨越午休或非上課時段"
                        f"(需連續 {pl.span} 節一般課)",
                    ))
                else:
                    conflicts.append(Conflict(
                        "H5",
                        f"{self._slot(pmap, wd, pl.period_no)} 非一般上課節次,不可排課"))
                continue

            # H1:班級不衝堂(僅比對既有格位;同群組成員班級共用不算衝突)
            for c in self._classes(a):
                for pno, _s, _e in covered:
                    d = class_occ.get((c.id, wd, pno))
                    if d:
                        conflicts.append(Conflict(
                            "H1", f"班級 {c.name} {self._slot(pmap, wd, pno)} 已有 {d}"))

            # H4 教師不可排時段 + H2 教師不衝堂(含跨表時間重疊、同群組其他門課)
            for at in a.teachers:
                t = at.teacher
                for pno, s, e in covered:
                    label = self._slot(pmap, wd, pno)
                    for rule in t.time_rules:
                        if (rule.rule_type == "unavailable"
                                and rule.weekday == wd and rule.period_no == pno):
                            conflicts.append(Conflict(
                                "H4", f"教師{t.name} {label} 為不可排時段"))
                    for occ in teacher_occ.get(at.teacher_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e):
                            conflicts.append(Conflict(
                                "H2", f"教師{t.name} {label} 已有 {occ.desc}"))
                    for occ in batch_teacher.get(at.teacher_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e):
                            conflicts.append(Conflict(
                                "H2", f"教師{t.name} {label} 與同群組另一門課撞課"))

            # H3 場地不衝堂(以格位實際場地判定,非配課上的預設場地)
            room_id = pl.effective_room_id
            if room_id:
                for pno, s, e in covered:
                    for occ in room_occ.get(room_id, []) + batch_room.get(room_id, []):
                        if self._overlap(occ, wd, table_id, pno, s, e):
                            conflicts.append(Conflict(
                                "H3",
                                f"場地 {self._room_name(room_id)} "
                                f"{self._slot(pmap, wd, pno)} 已有 {occ.desc}"))

            # H10 同班同科目每日上限(連堂除外)
            if pl.span == 1 and not a.block_rules:
                for c in self._classes(a):
                    existing = subj_count.get((c.id, wd, a.subject_id), 0)
                    if existing + 1 > DEFAULT_DAILY_SUBJECT_CAP:
                        conflicts.append(Conflict(
                            "H10",
                            f"班級 {c.name} {_wd(wd)} 已排「{a.subject.name}」{existing} 節,"
                            f"達每日上限 {DEFAULT_DAILY_SUBJECT_CAP} 節",
                        ))

            # 累積批次教師/場地佔用(同群組其他門課據此互檢)
            desc = self._desc(a)
            for at in a.teachers:
                for pno, s, e in covered:
                    batch_teacher.setdefault(at.teacher_id, []).append(
                        _Occ(wd, table_id, pno, s, e, desc))
            if room_id:
                for pno, s, e in covered:
                    batch_room.setdefault(room_id, []).append(_Occ(wd, table_id, pno, s, e, desc))

        return conflicts


def placements_for(
    db: Session,
    assignment: CourseAssignment,
    weekday: int,
    period_no: int,
    span: int,
    room_id: int | None = None,
) -> list[Placement]:
    """展開實際要放入的配課:跑班群組 → 群組內全部配課同格(span=1);單班 → 該配課。

    room_id 為「本次放入的場地」,只套用在被拖曳的那一筆配課上;
    群組內的其他門課各自使用自己的場地(跑班的每組本來就在不同教室)。
    """
    su = assignment.scheduling_unit
    if su.unit_type == SchedulingUnitType.group.value:
        sibs = list(
            db.scalars(
                select(CourseAssignment).where(CourseAssignment.scheduling_unit_id == su.id)
            )
        )
        return [
            Placement(s, weekday, period_no, 1, room_id if s.id == assignment.id else None)
            for s in sibs
        ]
    return [Placement(assignment, weekday, period_no, span, room_id)]


def check_conflict(
    db: Session,
    timetable: Timetable,
    assignment: CourseAssignment,
    weekday: int,
    period_no: int,
    span: int = 1,
    ignore_entry_ids: set[int] | None = None,
    room_id: int | None = None,
) -> list[Conflict]:
    """檢查將 assignment 放到 (weekday, period_no) 是否違反硬約束。

    移動既有格位時傳 ignore_entry_ids(被搬動的那幾格),使其不與自己相衝。
    room_id 為格位指定場地(空=沿用配課場地)。回傳空清單表示可放。
    """
    checker = _Checker(db, timetable)
    placements = placements_for(db, assignment, weekday, period_no, span, room_id)
    return checker.check(placements, ignore_entry_ids or set())
