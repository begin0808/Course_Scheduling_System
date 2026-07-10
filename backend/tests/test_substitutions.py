"""M4-2:代課推薦、指派處置、調課驗證。

**推薦引擎是這張卡的星角**,測試也集中在它:排序規則(同科目 > 當天在校 > 本月代課少)
與硬性過濾(那個特定日期真的能來的人)。

硬性過濾正是 Fable 5 提醒的「週格 vs 特定日期」落差——李師週三第二節空堂,
不代表 11/11 他能代(他自己可能也請假、或已被指派代別班)。這裡逐一造出那些情境。
"""

from datetime import date

import pytest

from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"

# 115 學年度第 1 學期
SEM_START = date(2026, 9, 1)
SEM_END = date(2027, 1, 20)
WED = date(2026, 11, 11)  # 週三
WED2 = date(2026, 11, 18)


@pytest.fixture
def env2(env):
    """已發布課表的國中。回傳 helper 物件,測試逐步疊教師/配課/請假。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return _World(client, db, sid)


class _World:
    def __init__(self, client, db, sid):
        self.client, self.db, self.sid = client, db, sid
        self.q = f"?semester_id={sid}"
        self.subjects: dict[str, int] = {
            s["name"]: s["id"]
            for s in client.get(f"/api/subjects{self.q}").json()
        }
        self.teachers: dict[str, int] = {}
        self.classes: dict[str, int] = {}
        self.tt = client.post(f"/api/timetables{self.q}", json={"name": "草稿A"}).json()["id"]
        self._published = False
        # 週三節次
        c = self.klass("900")  # 佔位班,取節次表
        self.wed = [p for p in client.get(f"/api/class-units/{c}/period-table").json()["periods"]
                    if p["weekday"] == 3 and p["type"] == "regular"]

    def subject(self, name: str) -> int:
        if name not in self.subjects:
            self.subjects[name] = self.client.post(
                f"/api/subjects{self.q}", json={"name": name}).json()["id"]
        return self.subjects[name]

    def teacher(self, name: str, subjects: list[str] | None = None) -> int:
        tid = self.client.post(f"/api/teachers{self.q}", json={
            "name": name, "base_periods": 20,
            "subject_ids": [self.subject(s) for s in (subjects or [])],
        }).json()["id"]
        self.teachers[name] = tid
        return tid

    def klass(self, name: str) -> int:
        if name not in self.classes:
            self.classes[name] = self.client.post(f"/api/class-units{self.q}", json={
                "grade": 7, "name": name, "track": "junior_high"}).json()["id"]
        return self.classes[name]

    def place(self, teacher: str, subject: str, klass: str, period_idx: int, weekday: int = 3):
        """把 teacher 的 subject 課排到 (weekday, 第 period_idx 個一般課節次)、上 klass 班。"""
        slots = [p for p in self.client.get(
            f"/api/class-units/{self.klass(klass)}/period-table").json()["periods"]
            if p["weekday"] == weekday and p["type"] == "regular"]
        a = self.client.post(f"/api/assignments{self.q}", json={
            "class_id": self.klass(klass), "subject_id": self.subject(subject),
            "periods_per_week": 1, "teachers": [{"teacher_id": self.teachers[teacher]}],
            "block_rules": [],
        }).json()
        r = self.client.post(f"/api/timetables/{self.tt}/entries", json={
            "course_assignment_id": a["id"], "weekday": weekday,
            "period_no": slots[period_idx]["period_no"], "span": 1})
        assert r.status_code == 201, r.json()
        return a["id"], slots[period_idx]["period_no"]

    def publish(self):
        r = self.client.post(f"/api/timetables/{self.tt}/publish?force=true")
        assert r.status_code == 200, r.json()
        self._published = True

    def leave(self, teacher: str, when: date = WED) -> list[dict]:
        r = self.client.post(f"/api/leaves{self.q}", json={
            "teacher_id": self.teachers[teacher], "leave_type": "sick",
            "start_date": when.isoformat(), "end_date": when.isoformat()})
        assert r.status_code == 201, r.json()
        return r.json()["affected_periods"]

    def recommend(self, affected_id: int) -> dict:
        return self.client.get(
            f"/api/affected-periods/{affected_id}/recommendations").json()

    def assign(self, affected_id: int, **body) -> "tuple[int, dict]":
        r = self.client.put(f"/api/affected-periods/{affected_id}/substitution", json=body)
        return r.status_code, r.json()


# ── 驗收①:第一名必為空堂 + 同科;已滿檔者靠後 ──────────────
def test_recommendation_ranks_same_subject_first(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])   # 同科,當天沒課
    w.teacher("林師", ["數學"])   # 非本科
    # 王師週三第一節上 701 國文;陳師與林師該節空堂
    a_id, _ = w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")

    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"]]
    assert names[0] == "陳師", names   # 同科優先
    top = rec["candidates"][0]
    assert top["same_subject"] is True
    assert "同科目教師" in top["reasons"]


def test_at_school_that_day_beats_a_teacher_not_coming_in(env2):
    """同為非本科,當天已在校者優先(免多跑一趟)。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["體育"])  # 非本科,當天週三另有課 → 已在校
    w.teacher("林師", ["體育"])  # 非本科,週三完全沒課
    w.place("王師", "國文", "701", 0)  # 王師週三第一節(被請假)
    w.place("陳師", "體育", "702", 2)  # 陳師週三第三節有課 → 當天在校,但第一節空
    w.publish()
    affected = w.leave("王師")

    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"]]
    assert names.index("陳師") < names.index("林師"), names
    chen = next(c for c in rec["candidates"] if c["teacher_name"] == "陳師")
    assert chen["at_school_that_day"] is True
    assert "當天已在校" in chen["reasons"]


def test_fewer_monthly_sub_periods_ranks_higher(env2):
    """同科同條件時,本月代課少者優先(公平)。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.teacher("林師", ["國文"])
    w.place("王師", "國文", "701", 0)
    # 林師本月已代一節(11/18):先幫另一個請假的老師代
    w.teacher("周師", ["國文"])
    w.place("周師", "國文", "702", 0, weekday=3)
    w.publish()

    other = w.client.post(f"/api/leaves{w.q}", json={
        "teacher_id": w.teachers["周師"], "leave_type": "sick",
        "start_date": WED2.isoformat(), "end_date": WED2.isoformat()}).json()
    code, _ = w.assign(other["affected_periods"][0]["id"],
                       type="substitute", handler_teacher_id=w.teachers["林師"])
    assert code == 200

    affected = w.leave("王師")  # 11/11
    rec = w.recommend(affected[0]["id"])
    names = [c["teacher_name"] for c in rec["candidates"] if c["teacher_name"] in ("陳師", "林師")]
    assert names[0] == "陳師", names  # 陳師本月 0 節,林師 1 節
    lin = next(c for c in rec["candidates"] if c["teacher_name"] == "林師")
    assert lin["sub_periods_this_month"] == 1
    assert "本月已代 1 節" in lin["reasons"]


# ── 硬性過濾:週格 vs 特定日期(Fable 5 的落差)──────────────
def test_a_teacher_busy_that_period_is_filtered_out(env2):
    """週格層:陳師該節有自己的課 → 不可代。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)  # 王師週三第一節
    w.place("陳師", "國文", "702", 0)  # 陳師同一節也有課
    w.publish()
    affected = w.leave("王師")

    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "陳師" not in names


def test_a_teacher_on_leave_that_day_is_filtered_out(env2):
    """日期層:陳師該節空堂,但『那一天』他自己也請假 → 不可代。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)   # 王師週三第一節(被請假)
    w.place("陳師", "國文", "703", 2)   # 陳師週三第三節有課;第一節空堂
    w.publish()
    w.leave("陳師")                     # 陳師也請整天假(含第一節)
    affected = w.leave("王師")

    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "陳師" not in names, "當天請假的人不該出現在可代清單"


def test_a_teacher_already_covering_that_slot_is_filtered_out(env2):
    """日期層:陳師該節空堂、當天沒請假,但已被指派代別班 → 不可代。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("周師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)  # 王師週三第一節
    w.place("周師", "國文", "702", 0)  # 周師同一節也有課(也會被請假)
    w.publish()

    a_wang = w.leave("王師")[0]["id"]
    a_zhou = w.leave("周師")[0]["id"]
    # 陳師先被指派去代周師那一節(週三第一節)
    code, _ = w.assign(a_zhou, type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 200

    names = [c["teacher_name"] for c in w.recommend(a_wang)["candidates"]]
    assert "陳師" not in names, "同一時段已被指派代課的人不該再被推薦"


def test_the_absent_teacher_is_never_a_candidate(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected = w.leave("王師")
    names = [c["teacher_name"] for c in w.recommend(affected[0]["id"])["candidates"]]
    assert "王師" not in names


# ── 驗收③:全校無人可代 → 提示併班/自習 ────────────────────
def test_no_available_teacher_hints_merge_or_self_study(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)  # 王師週三第一節
    w.place("陳師", "國文", "702", 0)  # 唯一其他教師同一節也有課
    w.publish()
    affected = w.leave("王師")

    rec = w.recommend(affected[0]["id"])
    assert rec["candidates"] == []
    assert "併班" in rec["no_candidate_hint"] and "自習" in rec["no_candidate_hint"]


# ── 指派處置 ─────────────────────────────────────────────────
def test_assigning_a_substitute_marks_resolved_and_notifies(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]

    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 200
    assert body["type_label"] == "代課"
    assert body["handler_name"] == "陳師"
    assert body["counts_toward_hours"] is True

    ap = w.db.get(AffectedPeriod, affected_id)
    assert ap.status == AffectedStatus.resolved.value
    assert ap.handler_teacher_id == w.teachers["陳師"]

    # 陳師收到代課通知
    notes = w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers['陳師']}").json()
    assert notes and notes[0]["type"] == "substitution_assigned"


def test_self_study_and_merge_hours_policy(env2):
    """自習不計鐘點且無處理教師;併班計不計由預設(不計)。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    ids = [p["id"] for p in w.leave("王師")]

    _, self_study = w.assign(ids[0], type="self_study")
    assert self_study["handler_name"] is None
    assert self_study["counts_toward_hours"] is False


def test_cannot_assign_absent_teacher_to_cover_self(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]
    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["王師"])
    assert code == 409
    assert "代自己" in body["detail"]


def test_assigning_a_busy_teacher_is_rejected_with_reason(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "國文", "702", 0)  # 陳師同一節有課
    w.publish()
    affected_id = w.leave("王師")[0]["id"]
    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 409
    assert "有自己的課" in body["detail"]


def test_clearing_a_substitution_returns_to_pending(env2):
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]
    w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陳師"])

    r = w.client.delete(f"/api/affected-periods/{affected_id}/substitution")
    assert r.status_code == 200
    assert r.json()["status"] == AffectedStatus.pending.value
    assert w.db.get(AffectedPeriod, affected_id).handler_teacher_id is None
    # 陳師收到取消通知
    types = [n["type"] for n in w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers['陳師']}").json()]
    assert "substitution_cancelled" in types


# ── 驗收②:調課(swap)驗證 ─────────────────────────────────
def test_swap_succeeds_when_both_sides_are_free(env2):
    """乙代甲週三第一節;甲於下週三補乙原本週三第二節的課。兩邊都空 → 成立。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)              # 甲:週三第一節(被請假)
    _, swap_entry = _entry(w, "陳師", "數學", "702", 1)  # 乙:週三第二節
    w.publish()
    affected_id = w.leave("王師")[0]["id"]

    entry_id = _find_entry(w, "陳師")
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())  # 下週三補
    assert code == 200, body
    assert body["type_label"] == "調課"
    assert body["swap_subject_name"] == "數學"
    assert body["swap_date"] == WED2.isoformat()


def test_swap_rejected_when_partner_busy_at_absent_slot(env2):
    """乙在甲請假那節本來就有課 → 無法來代,拒絕並指名。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)   # 甲週三第一節
    w.place("陳師", "數學", "702", 0)   # 乙週三第一節也有課
    _entry(w, "陳師", "數學", "703", 1)  # 乙另有週三第二節(用來當 swap 目標)
    w.publish()
    affected_id = w.leave("王師")[0]["id"]

    entry_id = _find_entry(w, "陳師", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409
    assert "陳師" in body["detail"] and "有自己的課" in body["detail"]


def test_swap_rejected_when_absent_teacher_busy_at_makeup_slot(env2):
    """甲在補課那節本來就有別的課 → 補不了,拒絕並指名。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)   # 甲週三第一節(被請假)
    w.place("王師", "國文", "705", 1)   # 甲週三第二節另有課(補課會撞)
    _entry(w, "陳師", "數學", "702", 1)  # 乙週三第二節 → swap 目標
    w.publish()
    affected_id = [p for p in w.leave("王師") if p["period_name"] == w.wed[0]["name"]][0]["id"]

    entry_id = _find_entry(w, "陳師", period_idx=1)
    code, body = w.assign(
        affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
        swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409
    assert "王師" in body["detail"]


def _entry(w, teacher, subject, klass, period_idx):
    return w.place(teacher, subject, klass, period_idx)


def _find_entry(w, teacher: str, period_idx: int | None = None) -> int:
    """取某教師某節的 schedule_entry id(供 swap 目標)。"""
    from app.models.assignment import AssignmentTeacher, CourseAssignment
    from app.models.timetable import ScheduleEntry
    q = (w.db.query(ScheduleEntry)
         .join(CourseAssignment, ScheduleEntry.course_assignment_id == CourseAssignment.id)
         .join(AssignmentTeacher,
               AssignmentTeacher.course_assignment_id == CourseAssignment.id)
         .filter(AssignmentTeacher.teacher_id == w.teachers[teacher],
                 ScheduleEntry.timetable_id == w.tt))
    if period_idx is not None:
        q = q.filter(ScheduleEntry.period_no == w.wed[period_idx]["period_no"])
    return q.first().id
