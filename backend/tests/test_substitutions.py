"""M4-2:代課推薦、指派處置、調課驗證。

**推薦引擎是這張卡的星角**,測試也集中在它:排序規則(同科目 > 當天在校 > 本月代課少)
與硬性過濾(那個特定日期真的能來的人)。

硬性過濾正是 Fable 5 提醒的「週格 vs 特定日期」落差——李師週三第二節空堂,
不代表 11/11 他能代(他自己可能也請假、或已被指派代別班)。這裡逐一造出那些情境。
"""

from datetime import date, timedelta

import pytest

from app.models.leave import AffectedPeriod, AffectedStatus
from app.models.user import Role
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, THU, WED, WED2  # 日期一律由執行當日推算,不硬編

PW = "password123"


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


# ── v1.2.1:可對調節次清單(調課前端的資料來源)──────────────
def _swap_world(w):
    """王師週三第一節 701 國文請假。
    陳師也教 701(週四第二節數學),另有 702 週三第二節自然;林師只教 703。
    """
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學", "自然"])
    w.teacher("林師", ["英文"])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "數學", "701", 1, weekday=4)
    w.place("陳師", "自然", "702", 1)
    w.place("林師", "英文", "703", 2)
    w.publish()
    return w.leave("王師")[0]["id"]


def _options(w, affected_id, teacher=None):
    q = f"?teacher_id={w.teachers[teacher]}" if teacher else ""
    r = w.client.get(f"/api/affected-periods/{affected_id}/swap-options{q}")
    assert r.status_code == 200, r.json()
    return r.json()


def _notif_titles(w, teacher):
    return [n["title"] for n in w.client.get(
        f"/api/notifications{w.q}&teacher_id={w.teachers[teacher]}").json()]


def test_swap_options_list_same_class_teachers_this_and_next_week(env2):
    """預設只找也教這個班的老師;同班的節次排前面;甲請假當天的節次不列。"""
    from datetime import timedelta

    w = env2
    affected_id = _swap_world(w)
    body = _options(w, affected_id)

    assert [p["teacher_name"] for p in body["partners"]] == ["陳師"]  # 林師不教 701
    chen = body["partners"][0]
    assert chen["teaches_same_class"] is True and chen["blocked_reason"] == ""
    got = [(o["date"], o["class_names"], o["same_class"]) for o in chen["options"]]
    assert got == [
        (THU.isoformat(), "701", True),                        # 本週四,同班互調
        ((THU + timedelta(days=7)).isoformat(), "701", True),  # 下週四
        (WED2.isoformat(), "702", False),                      # 週三當天王師請假 → 只剩下週三
    ]


def test_swap_option_from_list_is_accepted_and_both_teachers_notified(env2):
    """清單上的組合送出去一定成立;乙收到代課、甲收到補課通知,撤回後兩人都收到取消。"""
    w = env2
    affected_id = _swap_world(w)
    opt = _options(w, affected_id)["partners"][0]["options"][0]

    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200, body
    assert body["swap_class_names"] == "701" and body["counts_toward_hours"] is False
    assert any(t.startswith("調課通知") for t in _notif_titles(w, "陳師"))
    assert any(t.startswith("調課補課通知") for t in _notif_titles(w, "王師"))

    assert w.client.delete(f"/api/affected-periods/{affected_id}/substitution").status_code == 200
    assert "原訂調課已取消" in _notif_titles(w, "王師")
    assert "原訂調課已取消" in _notif_titles(w, "陳師")


def test_swap_search_range_can_widen_to_four_weeks(env2):
    """預設兩週;組長可放寬到四週(本週與隔三週對調),超過四週拒絕。"""
    from datetime import timedelta

    w = env2
    affected_id = _swap_world(w)
    thursdays = lambda body: [o["date"] for o in body["partners"][0]["options"]  # noqa: E731
                              if o["class_names"] == "701"]

    two = _options(w, affected_id)
    assert two["date_to"] == (WED + timedelta(days=11)).isoformat()  # 下週日
    assert len(thursdays(two)) == 2

    r = w.client.get(f"/api/affected-periods/{affected_id}/swap-options?weeks=4")
    four = r.json()
    assert four["date_to"] == (WED + timedelta(days=25)).isoformat()  # 隔三週的週日
    assert thursdays(four)[-1] == (THU + timedelta(days=21)).isoformat()
    assert len(thursdays(four)) == 4

    assert w.client.get(
        f"/api/affected-periods/{affected_id}/swap-options?weeks=5").status_code == 422


def test_swap_options_for_a_named_teacher_outside_the_class(env2):
    """組長指定一位不教這班的老師,照樣列出他換得成的節次。"""
    w = env2
    affected_id = _swap_world(w)
    body = _options(w, affected_id, teacher="林師")
    lin = body["partners"][0]
    assert lin["teacher_name"] == "林師" and lin["teaches_same_class"] is False
    assert [o["date"] for o in lin["options"]] == [WED2.isoformat()]


def test_swap_partner_on_leave_at_absent_slot_is_blocked(env2):
    """乙在甲請假那節自己也請假:清單說明原因,送出也被拒絕(原本只驗「有沒有課」)。"""
    w = env2
    affected_id = _swap_world(w)
    w.leave("陳師")  # 陳師週三也請假

    chen = _options(w, affected_id)["partners"][0]
    assert chen["options"] == [] and "請假" in chen["blocked_reason"]

    entry_id = _find_entry(w, "陳師", period_idx=1, weekday=3)
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409 and "陳師" in body["detail"]


def test_swap_slot_where_partner_is_on_leave_is_not_offered(env2):
    """乙在補課那天自己請假:那節課本身要另外安排,不能拿來對調。"""
    w = env2
    affected_id = _swap_world(w)
    w.leave("陳師", when=WED2)

    dates = [o["date"] for o in _options(w, affected_id)["partners"][0]["options"]]
    assert WED2.isoformat() not in dates

    entry_id = _find_entry(w, "陳師", period_idx=1, weekday=3)
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=entry_id, swap_date=WED2.isoformat())
    assert code == 409 and "也請假" in body["detail"]


def test_swap_slot_already_taken_by_another_swap_is_not_offered(env2):
    """乙的同一節課不能換給兩個人補。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["數學"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "歷史", "701", 2)
    w.place("陳師", "數學", "701", 1, weekday=4)
    w.publish()
    first, second = [p["id"] for p in w.leave("王師")]

    opt = _options(w, first)["partners"][0]["options"][0]
    code, _ = w.assign(first, type="swap", handler_teacher_id=w.teachers["陳師"],
                       swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200

    remaining = [o["date"] for o in _options(w, second)["partners"][0]["options"]]
    assert opt["date"] not in remaining
    code, body = w.assign(second, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 409 and "已經和別的老師調課" in body["detail"]


def test_board_on_makeup_day_lists_the_swapped_period(env2):
    """補課那天的看板也要列出被換來的那一節:原任陳師、改由王師上,並指回請假那節。"""
    w = env2
    affected_id = _swap_world(w)
    opt = _options(w, affected_id)["partners"][0]["options"][0]  # 本週四第二節 701 數學
    code, _ = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                       swap_entry_id=opt["entry_id"], swap_date=opt["date"])
    assert code == 200

    board = w.client.get(f"/api/daily-board{w.q}&on={opt['date']}").json()
    assert len(board["entries"]) == 1
    row = board["entries"][0]
    assert row["row_kind"] == "swap_makeup"
    assert (row["class_names"], row["subject_name"]) == ("701", "數學")
    assert row["absent_teacher_name"] == "陳師" and row["handler_name"] == "王師"
    assert row["leave_type_label"] == "調課補課"
    assert row["swap_date"] == WED.isoformat() and row["swap_subject_name"] == "國文"

    # 請假那天仍是原本那一列;撤回調課後補課日的列跟著消失
    wed = w.client.get(f"/api/daily-board{w.q}&on={WED.isoformat()}").json()["entries"]
    assert [e["row_kind"] for e in wed] == ["leave"]
    w.client.delete(f"/api/affected-periods/{affected_id}/substitution")
    assert w.client.get(f"/api/daily-board{w.q}&on={opt['date']}").json()["entries"] == []


# ── v1.2.2:調課通知單(教師調課單、班級調課單)────────────────
def _slips(w, *affected_ids):
    q = "&".join(f"affected_period_ids={i}" for i in affected_ids)
    return w.client.get(f"/api/swap-slips{w.q}&{q}")


def _swap_first(w, affected_id, pick):
    opt = next(o for o in _options(w, affected_id)["partners"][0]["options"] if pick(o))
    code, body = w.assign(affected_id, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"],
                          swap_period_no=opt["period_no"])
    assert code == 200, body
    return opt


def _cells(slip):
    return [(c["date"], c["ordinal"], c["subject_name"], c["teacher_name"], c["code"])
            for week in slip["weeks"] for c in week["cells"]]


def test_swap_slips_same_class_follow_the_paper_form(env2):
    """同班互調:兩張教師單(先對調的老師)+ 一張班級單;科目跟著老師走,代碼指向對調的另一節。"""
    w = env2
    affected_id = _swap_world(w)  # 王師週三第 1 節 701 國文 ⇄ 陳師週四第 2 節 701 數學
    _swap_first(w, affected_id, lambda o: o["date"] == THU.isoformat())
    wang = [p["id"] for p in w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"]]
    assert w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"][0]["sub_type"] == "swap"

    r = _slips(w, *wang)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["title"].endswith("115學年第一學期")
    kinds = [(s["kind"], s["teacher_name"], s["class_names"]) for s in body["slips"]]
    assert kinds == [("teacher", "陳師", "701"), ("teacher", "王師", "701"), ("class", "", "701")]

    chen, wang_slip, klass = body["slips"]
    thu, wed = THU.strftime("%m-%d"), WED.strftime("%m-%d")
    assert _cells(chen) == [(WED.isoformat(), 1, "數學", "陳師", f"調{thu}_42")]
    assert _cells(wang_slip) == [(THU.isoformat(), 2, "國文", "王師", f"調{wed}_31")]
    assert len(_cells(klass)) == 2
    assert (chen["date_from"], chen["date_to"]) == (WED.isoformat(), WED.isoformat())
    assert (klass["date_from"], klass["date_to"]) == (WED.isoformat(), THU.isoformat())

    week = klass["weeks"][0]
    assert week["monday"] == (WED - timedelta(days=2)).isoformat() and len(week["days"]) == 5
    assert [r["ordinal"] for r in klass["rows"]][:2] == [1, 2]
    assert any(r["afternoon_starts"] for r in klass["rows"])  # 午休後畫粗線


def test_swap_slips_cross_class_and_cross_week(env2):
    """跨班又跨週:兩個班各一張,科目沿用那一節原本的課;每張單依週分開。"""
    w = env2
    affected_id = _swap_world(w)
    _swap_first(w, affected_id, lambda o: o["class_names"] == "702")  # 下週三 702 自然

    body = _slips(w, affected_id).json()
    kinds = [(s["kind"], s["class_names"]) for s in body["slips"]]
    assert kinds == [("teacher", "701"), ("teacher", "702"), ("class", "701"), ("class", "702")]
    chen, wang, c701, c702 = body["slips"]
    assert _cells(chen)[0][2:4] == ("國文", "陳師")   # 陳師去 701 上王師那節國文
    assert _cells(wang)[0][2:4] == ("自然", "王師")   # 王師去 702 上陳師那節自然
    assert _cells(c702)[0][0] == WED2.isoformat()
    assert [wk["monday"] for wk in c701["weeks"]] != [wk["monday"] for wk in c702["weeks"]]


def test_swap_slips_ignore_non_swap_periods(env2):
    """代課或未處置的節次不印;全都不是調課就回 404 並說明。"""
    w = env2
    affected_id = _swap_world(w)
    r = _slips(w, affected_id)
    assert r.status_code == 404 and "沒有已成立的調課" in r.json()["detail"]
    assert w.client.get(f"/api/leaves{w.q}").json()[0]["affected_periods"][0]["sub_type"] is None


def _place_block(w, teacher, subject, klass, weekday, period_idx):
    """排一堂兩節連堂。"""
    slots = [p for p in w.client.get(
        f"/api/class-units/{w.klass(klass)}/period-table").json()["periods"]
        if p["weekday"] == weekday and p["type"] == "regular"]
    a = w.client.post(f"/api/assignments{w.q}", json={
        "class_id": w.klass(klass), "subject_id": w.subject(subject),
        "periods_per_week": 2, "teachers": [{"teacher_id": w.teachers[teacher]}],
        "block_rules": [{"block_size": 2, "count_per_week": 1}],
    }).json()
    r = w.client.post(f"/api/timetables/{w.tt}/entries", json={
        "course_assignment_id": a["id"], "weekday": weekday,
        "period_no": slots[period_idx]["period_no"], "span": 2})
    assert r.status_code == 201, r.json()
    return r.json()["id"], [s["period_no"] for s in slots[period_idx:period_idx + 2]]


def test_block_lesson_can_swap_a_single_period(env2):
    """乙的連堂可以只換其中一節;換掉的那節不再列出,另一節照樣可換。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["理化"])
    w.place("王師", "國文", "701", 0)
    w.place("王師", "歷史", "701", 3)
    _, (first, second) = _place_block(w, "陳師", "理化", "701", 4, 1)  # 週四連堂
    w.publish()
    ap1, ap2 = [p["id"] for p in w.leave("王師")]

    opts = [o for o in _options(w, ap1)["partners"][0]["options"] if o["date"] == THU.isoformat()]
    assert [(o["period_no"], o["in_block"]) for o in opts] == [(first, True), (second, True)]

    code, body = w.assign(ap1, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=opts[1]["entry_id"], swap_date=THU.isoformat(),
                          swap_period_no=second)
    assert code == 200, body
    assert body["swap_period_name"] == opts[1]["period_name"]

    left = [o["period_no"] for o in _options(w, ap2)["partners"][0]["options"]
            if o["date"] == THU.isoformat()]
    assert left == [first]  # 第二節已換給第一筆調課,不能再換第二次

    code, body = w.assign(ap2, type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=opts[0]["entry_id"], swap_date=THU.isoformat(),
                          swap_period_no=first + 5)
    assert code == 409 and "不在這堂課的時段內" in body["detail"]


def _entry(w, teacher, subject, klass, period_idx):
    return w.place(teacher, subject, klass, period_idx)


def _find_entry(w, teacher: str, period_idx: int | None = None, weekday: int | None = None) -> int:
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
    if weekday is not None:
        q = q.filter(ScheduleEntry.weekday == weekday)
    return q.first().id
