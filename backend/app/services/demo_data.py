"""示範資料產生器:一鍵建出一所完整的示範國中。

為什麼需要這個:裝好系統之後,使用者面對的是一個空系統——要看到「自動排課」
做了什麼,得先手 key 十幾個班級、四十幾位教師、幾百筆配課。連本專案作者
自己想完整走一遍都卡在「手邊沒有資料」,遑論素未謀面的評估者。

規格在 app/data/demo_school.json,這裡只負責把規格算成實際資料:
教師名冊、應授節數、以及「哪位老師教哪一班的哪一科」都是推算出來的,
改 JSON 裡的人數,配課會自動重新平衡。

只在空學期上執行(呼叫端負責擋)。
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.assignment import AssignmentTeacher, CourseAssignment
from app.models.basedata import ClassTrack, ClassUnit, Room, Subject, Teacher
from app.models.semester import Semester
from app.services import templates as template_service
from app.services.assignments import get_or_create_single_unit

_SPEC_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_school.json"

# 教師身分。順序即配課的優先序:導師要先拿到自己班的課(軟約束 S7 才有東西可排),
# 行政人員應授少、最後才補,免得把他們塞爆。
ROLE_HOMEROOM = "導師"
ROLE_FULLTIME = "專任"
ROLE_EXTERNAL = "外聘"
ROLE_ORDER = [ROLE_HOMEROOM, ROLE_FULLTIME, "組長", "主任", "專任輔導教師", ROLE_EXTERNAL]


@lru_cache
def load_spec() -> dict:
    with open(_SPEC_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class _TeacherPlan:
    """建表前的教師規劃:先算好應授節數,再決定配課。"""

    name: str
    dept: str
    role: str
    base_periods: int
    admin_reduction: int = 0
    admin_title: str | None = None
    is_external: bool = False
    homeroom_of: str | None = None          # 導師帶的班名
    assigned: int = 0                        # 累計配課節數
    model: Teacher | None = field(default=None, repr=False)

    @property
    def target(self) -> int:
        return max(self.base_periods - self.admin_reduction, 0)

    @property
    def headroom(self) -> int:
        """離應授還差幾節。負數代表已超鐘點。"""
        return self.target - self.assigned


@dataclass
class DemoSummary:
    """產生結果,供 API 回報與測試斷言。"""

    semester_id: int
    school_name: str
    classes: int
    teachers: int
    subjects: int
    rooms: int
    assignments: int
    total_periods: int
    max_overtime_used: int   # 全校最大超鐘點節數
    under_target: int        # 未達應授的教師數


def _base_for(spec: dict, dept: str, role: str) -> int:
    """該科該身分的基本鐘點。行政職以『專任』為基準,再靠減課降到規定的應授。"""
    table = spec["base_periods"].get(dept, spec["base_periods"]["_default"])
    if role == ROLE_HOMEROOM:
        return table[ROLE_HOMEROOM]
    return table[ROLE_FULLTIME]


def _plan_teachers(spec: dict, class_names: list[str]) -> list[_TeacherPlan]:
    """依編制表產生教師名冊(含應授節數),導師依序綁定班級。"""
    surnames, givens = spec["surnames"], spec["given_names"]
    titles = {k: list(v) for k, v in spec["admin_titles"].items()}
    homeroom_queue = list(class_names)
    plans: list[_TeacherPlan] = []

    for dept in spec["departments"]:
        dept_name = dept["name"]
        for role in ROLE_ORDER:
            for _ in range(dept.get(role, 0)):
                idx = len(plans)
                # 姓名以索引錯開組合,49 個姓 × 49 個名足以避免重複
                name = surnames[idx % len(surnames)] + givens[(idx * 7 + 3) % len(givens)]
                plan = _TeacherPlan(
                    name=name,
                    dept=dept_name,
                    role=role,
                    base_periods=_base_for(spec, dept_name, role),
                    is_external=(role == ROLE_EXTERNAL),
                )
                if role in titles and titles[role]:
                    plan.admin_title = titles[role].pop(0)
                if role in spec["admin_targets"]:
                    # 主任/組長/專輔:規定寫的是「應授幾節」,換算成減課存進資料庫
                    plan.admin_reduction = max(
                        plan.base_periods - spec["admin_targets"][role], 0
                    )
                if role == ROLE_HOMEROOM and homeroom_queue:
                    plan.homeroom_of = homeroom_queue.pop(0)
                if role == ROLE_EXTERNAL:
                    # 外聘兼任:沒有專任基鐘,以實際需求節數為應授
                    plan.base_periods = 0
                plans.append(plan)
    return plans


def _class_names(spec: dict) -> list[tuple[int, str]]:
    """班名。十二年國教後多數國中改用年級+序號(701~706),不再用忠孝仁愛。"""
    cfg = spec["classes"]
    fmt = cfg.get("name_format", "{grade}{index:02d}")
    return [
        (grade, fmt.format(grade=grade, index=i))
        for grade in cfg["grades"]
        for i in range(1, cfg["per_grade"] + 1)
    ]


def _demand(spec: dict, classes: list[tuple[int, str]]) -> list[tuple[str, str, int]]:
    """展開成 (班名, 科目名, 每週節數);沒有該年級節數的科目自動跳過。"""
    rows: list[tuple[str, str, int]] = []
    for grade, cname in classes:
        for subj in spec["subjects"]:
            periods = subj["periods"].get(str(grade))
            if periods:
                rows.append((cname, subj["name"], periods))
    return rows


def _pick_teacher(pool: list[_TeacherPlan]) -> _TeacherPlan:
    """挑「剩餘容量最多」的老師。

    這樣自然會把課平均分散,而不是把前幾位塞滿、後幾位沒課。
    全科都滿了就給最不滿的那位,超出的部分成為超鐘點——真實學校也是這樣。
    """
    return max(pool, key=lambda p: (p.headroom, -p.assigned))


def generate(db: Session, spec: dict | None = None) -> DemoSummary:
    """建立整所示範學校。呼叫端負責確認學期是空的,並負責 commit。"""
    spec = spec or load_spec()
    classes = _class_names(spec)
    class_names = [name for _, name in classes]

    # ── 學期與節次表(沿用既有的學制範本,示範資料不另造一套)──
    semester = template_service.create_semester_from_template(
        db,
        academic_year=spec["academic_year"],
        term=spec["term"],
        template_key=spec["template_key"],
    )
    sid = semester.id

    # 範本會帶入領域層級的科目名稱;示範資料要分科,先清掉再建自己的
    for row in db.query(Subject).filter(Subject.semester_id == sid).all():
        db.delete(row)
    db.flush()

    subjects: dict[str, Subject] = {}
    for item in spec["subjects"]:
        s = Subject(
            semester_id=sid,
            name=item["name"],
            domain=item["domain"],
            is_major=item.get("major", False),
            required_room_type=item.get("room"),
        )
        db.add(s)
        subjects[item["name"]] = s

    # ── 場地 ──
    rooms: dict[str, list[Room]] = {}
    room_count = 0
    for spec_room in spec["rooms"]:
        for i in range(spec_room["count"]):
            suffix = f"{i + 1}" if spec_room["count"] > 1 else ""
            r = Room(
                semester_id=sid,
                name=f"{spec_room['name']}{suffix}",
                room_type=spec_room["type"],
            )
            db.add(r)
            for sub_name in spec_room["subjects"]:
                rooms.setdefault(sub_name, []).append(r)
            room_count += 1
    # 每班一間普通教室
    for _, cname in classes:
        db.add(Room(semester_id=sid, name=cname, room_type="normal"))
        room_count += 1
    db.flush()

    # ── 教師 ──
    plans = _plan_teachers(spec, class_names)
    by_name: dict[str, _TeacherPlan] = {}
    for plan in plans:
        t = Teacher(
            semester_id=sid,
            name=plan.name,
            base_periods=plan.base_periods,
            admin_reduction=plan.admin_reduction,
            admin_title=plan.admin_title,
            is_external=plan.is_external,
        )
        db.add(t)
        plan.model = t
        by_name[plan.name] = plan
    db.flush()

    # 外聘教師的應授 = 他實際要教的節數(如本土語文 12 節),避免顯示成「超鐘點 12 節」
    demand = _demand(spec, classes)
    dept_of = {s["name"]: s["dept"] for s in spec["subjects"]}
    for plan in plans:
        if plan.role != ROLE_EXTERNAL:
            continue
        total = sum(p for _, sname, p in demand if dept_of[sname] == plan.dept)
        plan.base_periods = total
        assert plan.model is not None
        plan.model.base_periods = total

    # ── 班級(綁導師)──
    homeroom_by_class = {p.homeroom_of: p for p in plans if p.homeroom_of}
    class_models: dict[str, ClassUnit] = {}
    for grade, cname in classes:
        hr = homeroom_by_class.get(cname)
        assert hr is None or hr.model is not None
        cu = ClassUnit(
            semester_id=sid,
            grade=grade,
            name=cname,
            track=ClassTrack.junior_high.value,
            student_count=spec["classes"]["student_count"],
            homeroom_teacher_id=hr.model.id if hr and hr.model else None,
        )
        db.add(cu)
        class_models[cname] = cu
    db.flush()

    # ── 配課 ──
    pools: dict[str, list[_TeacherPlan]] = {}
    for plan in plans:
        pools.setdefault(plan.dept, []).append(plan)

    # 導師優先拿自己班、自己科的課:S7(導師的課優先排自己班第一節)才示範得出來
    def sort_key(row: tuple[str, str, int]) -> tuple[int, str, str]:
        cname, sname, _ = row
        hr = homeroom_by_class.get(cname)
        own = 0 if hr and dept_of[sname] == hr.dept else 1
        return (own, cname, sname)

    assignment_count = 0
    total_periods = 0
    for cname, sname, periods in sorted(demand, key=sort_key):
        pool = pools[dept_of[sname]]
        hr = homeroom_by_class.get(cname)
        if hr is not None and hr.dept == dept_of[sname] and hr.headroom >= periods:
            teacher = hr
        else:
            teacher = _pick_teacher(pool)

        assert teacher.model is not None
        unit = get_or_create_single_unit(db, class_models[cname])
        assignment = CourseAssignment(
            semester_id=sid,
            scheduling_unit_id=unit.id,
            subject_id=subjects[sname].id,
            periods_per_week=periods,
            required_room_type=subjects[sname].required_room_type,
        )
        db.add(assignment)
        db.flush()
        assignment.teachers.append(
            AssignmentTeacher(teacher_id=teacher.model.id, is_lead=True)
        )
        teacher.assigned += periods
        assignment_count += 1
        total_periods += periods
    db.flush()

    overs = [-p.headroom for p in plans if p.headroom < 0]
    return DemoSummary(
        semester_id=sid,
        school_name=spec["school_name"],
        classes=len(classes),
        teachers=len(plans),
        subjects=len(subjects),
        rooms=room_count,
        assignments=assignment_count,
        total_periods=total_periods,
        max_overtime_used=max(overs, default=0),
        under_target=sum(1 for p in plans if p.headroom > 0),
    )


def semester_is_empty(db: Session, semester_id: int) -> bool:
    """學期是否還沒有任何班級或教師——示範資料只能建在空學期上。"""
    has_class = db.query(ClassUnit).filter(ClassUnit.semester_id == semester_id).first()
    has_teacher = db.query(Teacher).filter(Teacher.semester_id == semester_id).first()
    return has_class is None and has_teacher is None


def any_semester_exists(db: Session) -> bool:
    return db.query(Semester).first() is not None
