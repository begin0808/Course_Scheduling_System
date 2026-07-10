"""M4-1:請假登記與受影響節次展開。

**這裡驗的是「週循環格 → 日曆日期」這層轉換。** M0–M3 的一切都建立在
`(weekday, period_no)` 上;請假是「王師 11/12 上午請假」。轉換錯了,M4-2 的代課推薦
(「該時段空堂、當日未請假」)整個站不住。

日期邊界是重點:週末、學期起訖外、跨週、半天、連堂。
"""

from datetime import date

import pytest

from app.models.leave import AffectedStatus, LeaveRequest, LeaveStatus
from app.models.notification import Notification, NotificationType
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"

# 115 學年度第 1 學期:2026-09-01(週二)~ 2027-01-20(週三)
SEM_START = date(2026, 9, 1)
SEM_END = date(2027, 1, 20)
# 2026-11-09 是週一,11-11 週三,11-13 週五,11-14 週六,11-15 週日
MON = date(2026, 11, 9)
WED = date(2026, 11, 11)
FRI = date(2026, 11, 13)
SAT = date(2026, 11, 14)


@pytest.fixture
def school(env):
    """已發布課表的國中:王師週三 5 節國文(701~705 班各一節)、週五 1 節。

    回傳 (client, db, semester_id, teacher_id)。
    """
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]

    subject = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    wang = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "王師", "base_periods": 20}).json()
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    classes = [
        client.post(f"/api/class-units?semester_id={sid}", json={
            "grade": 7, "name": f"70{i}", "track": "junior_high"}).json()["id"]
        for i in range(1, 6)
    ]

    # 週三的 5 個一般課節次(國中範本第一節的 period_no 是 2,不是 1)
    slots = client.get(f"/api/class-units/{classes[0]}/period-table").json()["periods"]
    wed_slots = [p["period_no"] for p in slots
                 if p["weekday"] == 3 and p["type"] == "regular"][:5]
    fri_slot = next(p["period_no"] for p in slots
                    if p["weekday"] == 5 and p["type"] == "regular")

    def assign_and_place(class_id, weekday, period_no):
        a = client.post(f"/api/assignments?semester_id={sid}", json={
            "class_id": class_id, "subject_id": subject["id"], "periods_per_week": 1,
            "teachers": [{"teacher_id": wang["id"]}], "block_rules": []}).json()
        r = client.post(f"/api/timetables/{tt['id']}/entries", json={
            "course_assignment_id": a["id"], "weekday": weekday,
            "period_no": period_no, "span": 1})
        assert r.status_code == 201, r.json()

    for cid, pno in zip(classes, wed_slots, strict=True):
        assign_and_place(cid, 3, pno)
    assign_and_place(classes[0], 5, fri_slot)  # 週五 701 班一節

    r = client.post(f"/api/timetables/{tt['id']}/publish?force=true")
    assert r.status_code == 200, r.json()
    return client, db, sid, wang["id"]


def _bind_account(client, db, teacher_id: int, username: str):
    """把登入帳號綁到教師主檔。PATCH /teachers 是整筆取代,得帶齊必填欄位。"""
    user = make_user(db, username, PW, roles=[Role.teacher])
    r = client.patch(f"/api/teachers/{teacher_id}", json={
        "name": "王師", "base_periods": 20, "user_id": user.id})
    assert r.status_code == 200, r.json()
    return user


def _leave(client, sid, teacher_id, **body):
    return client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": teacher_id, "leave_type": "sick", **body})


# ── 驗收①:整天假展開當天全部節次 ──────────────────────────
def test_full_day_leave_expands_every_period_that_day(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat())
    assert r.status_code == 201, r.json()
    body = r.json()

    assert body["affected_count"] == 5
    assert body["pending_count"] == 5
    periods = body["affected_periods"]
    assert all(p["date"] == WED.isoformat() for p in periods)
    assert all(p["weekday"] == 3 for p in periods)
    assert [p["class_names"] for p in periods] == ["701", "702", "703", "704", "705"]
    # 節次一律用節次表的名稱,不用內部 period_no(period_no 2 才是「第一節」)
    assert periods[0]["period_name"] == "第一節"
    assert periods[0]["subject_name"] == "國文"


# ── 驗收②:跨週末只展開上課日 ───────────────────────────────
def test_leave_across_a_weekend_skips_non_school_days(school):
    client, _db, sid, tid = school
    # 週三 ~ 下週一(11/11 ~ 11/16),中間夾週六日
    next_mon = date(2026, 11, 16)
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=next_mon.isoformat())
    body = r.json()

    days = sorted({p["date"] for p in body["affected_periods"]})
    assert days == [WED.isoformat(), FRI.isoformat()]  # 週四無課、週六日不上課、週一無課
    assert body["affected_count"] == 6  # 週三 5 節 + 週五 1 節


def test_a_leave_entirely_on_the_weekend_affects_nothing(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=SAT.isoformat(),
               end_date=date(2026, 11, 15).isoformat())
    assert r.status_code == 201
    assert r.json()["affected_count"] == 0  # 假單成立,只是沒有課要處理


# ── 半天假:以牆鐘時間區間判定 ───────────────────────────────
def test_morning_leave_only_expands_morning_periods(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="08:00", end_time="12:00")
    periods = r.json()["affected_periods"]

    assert 0 < len(periods) < 5, "上午請假不該把下午的課也列進來"
    assert all(p["end_time"] <= "12:00:00" for p in periods)


def test_afternoon_leave_only_expands_afternoon_periods(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="13:00", end_time="17:00")
    periods = r.json()["affected_periods"]

    assert periods, "下午應該有課"
    assert all(p["start_time"] >= "13:00:00" for p in periods)


def test_multi_day_leave_applies_times_only_to_the_boundary_days(school):
    """「週三 13:00 ~ 週五 12:00」= 週三下午 + 週四整天 + 週五上午。"""
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=FRI.isoformat(),
               start_time="13:00", end_time="12:00")
    periods = r.json()["affected_periods"]

    wed = [p for p in periods if p["date"] == WED.isoformat()]
    fri = [p for p in periods if p["date"] == FRI.isoformat()]
    assert wed and all(p["start_time"] >= "13:00:00" for p in wed)
    assert fri and all(p["end_time"] <= "12:00:00" for p in fri)


# ── 日期邊界:學期起訖外一律拒絕 ─────────────────────────────
@pytest.mark.parametrize(("start", "end", "reason"), [
    ("2026-08-31", "2026-08-31", "學期開始前"),
    ("2027-01-21", "2027-01-21", "學期結束後"),
    ("2026-11-13", "2026-11-11", "結束早於開始"),
])
def test_dates_outside_the_semester_are_rejected(school, start, end, reason):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=start, end_date=end)
    assert r.status_code == 400, reason


def test_end_time_before_start_time_on_the_same_day_is_rejected(school):
    client, _db, sid, tid = school
    r = _leave(client, sid, tid, start_date=WED.isoformat(), end_date=WED.isoformat(),
               start_time="13:00", end_time="09:00")
    assert r.status_code == 400


def test_semester_without_dates_cannot_accept_leaves(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 116, "term": 1, "template_key": "junior_high"}).json()["id"]
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()

    r = _leave(client, sid, t["id"], start_date="2026-11-11", end_date="2026-11-11")
    assert r.status_code == 400
    assert "學期尚未設定起訖日期" in r.json()["detail"]


# ── 驗收③:銷假 → 級聯取消 + 通知已指派的代課教師 ────────────
def test_cancelling_a_leave_notifies_the_assigned_substitute(school):
    client, db, sid, tid = school
    li = client.post(f"/api/teachers?semester_id={sid}",
                     json={"name": "李師", "base_periods": 20}).json()

    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]
    leave = db.get(LeaveRequest, leave_id)

    # 模擬 M4-2 已指派李師代其中 2 節、1 節已上完
    periods = sorted(leave.affected_periods, key=lambda p: p.period_no)
    for p in periods[:2]:
        p.status = AffectedStatus.resolved.value
        p.handler_teacher_id = li["id"]
    periods[4].status = AffectedStatus.completed.value
    db.commit()

    r = client.post(f"/api/leaves/{leave_id}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == LeaveStatus.cancelled.value
    assert body["revoked_count"] == 2
    assert body["notified_teachers"] == ["李師"]

    db.expire_all()
    leave = db.get(LeaveRequest, leave_id)
    states = [p.status for p in sorted(leave.affected_periods, key=lambda p: p.period_no)]
    # 已完成的那節不動——課已經上過了,事後銷假不能把歷史抹掉
    assert states == ["cancelled"] * 4 + ["completed"]

    # 李師收到一封合併通知(2 節併成一封,不是兩封)
    notes = db.query(Notification).filter_by(teacher_id=li["id"]).all()
    assert len(notes) == 1
    assert notes[0].type == NotificationType.substitution_cancelled.value
    assert "王師" in notes[0].title
    assert "2 節" in notes[0].body

    # 王師本人:代登通知 + 銷假通知
    wang_notes = db.query(Notification).filter_by(teacher_id=tid).all()
    assert [n.type for n in wang_notes] == [
        NotificationType.leave_registered.value,
        NotificationType.leave_cancelled.value,
    ]


def test_cancelling_twice_is_rejected(school):
    client, _db, sid, tid = school
    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]
    assert client.post(f"/api/leaves/{leave_id}/cancel").status_code == 200
    assert client.post(f"/api/leaves/{leave_id}/cancel").status_code == 409


# ── 快照:課表重新發布後,已展開的節次不漂移 ──────────────────
def test_affected_periods_are_a_snapshot_not_a_join(school):
    client, db, sid, tid = school
    leave_id = _leave(client, sid, tid, start_date=WED.isoformat(),
                      end_date=WED.isoformat()).json()["id"]

    before = client.get(f"/api/leaves/{leave_id}/affected").json()
    assert before[0]["subject_name"] == "國文"

    # 課表整份刪掉(等同重新發布另一份):快照仍在,溯源指標變 NULL
    assert db.get(LeaveRequest, leave_id).affected_periods[0].schedule_entry_id is not None
    published = client.get(f"/api/published/timetable?semester_id={sid}").json()
    client.patch(f"/api/timetables/{published['id']}", json={"status": "archived"})
    client.delete(f"/api/timetables/{published['id']}")

    after = client.get(f"/api/leaves/{leave_id}/affected").json()
    assert len(after) == 5
    assert after[0]["subject_name"] == "國文"
    assert after[0]["class_names"] == "701"
    assert after[0]["period_name"] == "第一節"


# ── RBAC:教師自登、只看自己 ─────────────────────────────────
def test_teacher_registers_own_leave_and_cannot_see_others(school):
    client, db, sid, tid = school
    # 王師綁定帳號 wang;另建一位陳師與其假單
    user = _bind_account(client, db, tid, "wang")
    chen = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "陳師", "base_periods": 20}).json()
    _leave(client, sid, chen["id"], start_date=WED.isoformat(), end_date=WED.isoformat())
    assert user.id

    client.post("/api/auth/login", json={"username": "wang", "password": PW})
    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "leave_type": "personal", "start_date": FRI.isoformat(), "end_date": FRI.isoformat()})
    assert r.status_code == 201
    assert r.json()["teacher_id"] == tid
    assert r.json()["affected_count"] == 1  # 王師週五只有一節

    mine = client.get(f"/api/leaves?semester_id={sid}").json()
    assert {m["teacher_name"] for m in mine} == {"王師"}  # 看不到陳師的假單


def test_teacher_cannot_register_for_someone_else(school):
    client, db, sid, tid = school
    _bind_account(client, db, tid, "wang")
    chen = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "陳師", "base_periods": 20}).json()

    client.post("/api/auth/login", json={"username": "wang", "password": PW})
    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": chen["id"], "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 403


def test_registrar_on_behalf_notifies_the_teacher(school):
    """組長代登 → 當事人要知道有人替他請了假;自登則不必通知自己。"""
    client, db, sid, tid = school
    _leave(client, sid, tid, start_date=MON.isoformat(), end_date=MON.isoformat())

    notes = db.query(Notification).filter_by(teacher_id=tid).all()
    assert len(notes) == 1
    assert notes[0].type == NotificationType.leave_registered.value
    assert "已為您登記" in notes[0].title


def test_unbound_account_gets_a_helpful_error(school):
    client, db, sid, _tid = school
    make_user(db, "nobody", PW, roles=[Role.teacher])
    client.post("/api/auth/login", json={"username": "nobody", "password": PW})

    r = client.post(f"/api/leaves?semester_id={sid}", json={
        "leave_type": "sick", "start_date": WED.isoformat(), "end_date": WED.isoformat()})
    assert r.status_code == 400
    assert "尚未綁定" in r.json()["detail"]


def test_leave_without_published_timetable_registers_with_no_periods(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 117, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat()}).json()["id"]
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()

    r = _leave(client, sid, t["id"], start_date=WED.isoformat(), end_date=WED.isoformat())
    assert r.status_code == 201
    assert r.json()["affected_count"] == 0
