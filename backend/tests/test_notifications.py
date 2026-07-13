"""M4-3:通知寄送、確認收到、組長看板、SMTP 設定。

站內通知永遠送達;Email 走 RQ,SMTP 未設定時整個流程照常(僅站內)。
Email 部分以「假佇列」攔截 enqueue,驗「該不該寄、寄什麼」,不真的連 SMTP。
"""


import pytest

from app.models.user import Role
from app.services import notifications as notif_service
from app.services import settings as app_settings
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START, WED  # 日期一律由執行當日推算,不硬編

PW = "password123"


@pytest.fixture
def outbox(monkeypatch):
    """攔截 Email enqueue:記錄 (to, subject, body),不連 Redis/SMTP。"""
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "app.workers.queue.enqueue_email",
        lambda to, subject, body: sent.append((to, subject, body)),
    )
    return sent


@pytest.fixture
def school(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    return client, db, sid


def _publish_wang(client, sid, *, email: str | None = None):
    """王師週三第一節國文,課表已發布。回傳 (王師id, 陳師id)。"""
    guo = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()["id"]
    wang = client.post(f"/api/teachers?semester_id={sid}",
                       json={"name": "王師", "base_periods": 20}).json()["id"]
    chen_body = {"name": "陳師", "base_periods": 20, "subject_ids": [guo]}
    if email:
        chen_body["email"] = email
    chen = client.post(f"/api/teachers?semester_id={sid}", json=chen_body).json()["id"]
    c701 = client.post(f"/api/class-units?semester_id={sid}",
                       json={"grade": 7, "name": "701", "track": "junior_high"}).json()["id"]
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()["id"]
    wed = [p for p in client.get(f"/api/class-units/{c701}/period-table").json()["periods"]
           if p["weekday"] == 3 and p["type"] == "regular"]
    a = client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c701, "subject_id": guo, "periods_per_week": 1,
        "teachers": [{"teacher_id": wang}], "block_rules": []}).json()
    client.post(f"/api/timetables/{tt}/entries", json={
        "course_assignment_id": a["id"], "weekday": 3, "period_no": wed[0]["period_no"], "span": 1})
    client.post(f"/api/timetables/{tt}/publish?force=true")
    return wang, chen


def _leave_and_assign(client, sid, wang, chen):
    affected = client.post(f"/api/leaves?semester_id={sid}", json={
        "teacher_id": wang, "leave_type": "sick",
        "start_date": WED.isoformat(), "end_date": WED.isoformat()}).json()["affected_periods"][0]
    client.put(f"/api/affected-periods/{affected['id']}/substitution",
               json={"type": "substitute", "handler_teacher_id": chen})
    return affected


# ── 驗收①:指派後站內通知;有 Email 則排入寄送 ────────────────
def test_assignment_creates_in_app_notification(school, outbox):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid)   # 陳師無 email
    _leave_and_assign(client, sid, wang, chen)

    # 站內:陳師登入看得到自己的通知
    _bind_login(client, db, chen, "chen")
    body = client.get(f"/api/notifications/mine?semester_id={sid}").json()
    assert body["unread"] == 1
    assert body["items"][0]["type"] == "substitution_assigned"
    assert body["items"][0]["link"] == ""
    # 陳師沒填 email → 不排入寄送
    assert outbox == []


def test_assignment_emails_when_teacher_has_address(school, outbox):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid, email="chen@example.com")
    # 需設定 SMTP,否則 email 管道不會放進寄件匣?——不,寄件匣只看有沒有信箱;
    # 是否真的寄由 email_job 依 SMTP 設定決定。這裡驗「有信箱 → 有排入」。
    _leave_and_assign(client, sid, wang, chen)

    assert len(outbox) == 1
    to, subject, _body = outbox[0]
    assert to == "chen@example.com"
    assert "代課通知" in subject


# ── 驗收①:確認收到 ─────────────────────────────────────────
def test_teacher_acknowledges_a_notification(school):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid)
    _leave_and_assign(client, sid, wang, chen)

    _bind_login(client, db, chen, "chen")
    nid = client.get(f"/api/notifications/mine?semester_id={sid}").json()["items"][0]["id"]

    r = client.post(f"/api/notifications/{nid}/acknowledge")
    assert r.status_code == 200
    assert r.json()["acknowledged_at"] is not None
    assert r.json()["read_at"] is not None  # 確認即已讀

    # 未讀數歸零
    count = client.get(f"/api/notifications/mine/unread-count?semester_id={sid}").json()
    assert count["unread"] == 0


def test_cannot_acknowledge_someone_elses_notification(school):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid)
    _leave_and_assign(client, sid, wang, chen)
    nid = client.get(f"/api/notifications?semester_id={sid}&teacher_id={chen}").json()[0]["id"]

    # 王師(別人)不能確認陳師的通知
    _bind_login(client, db, wang, "wang")
    assert client.post(f"/api/notifications/{nid}/acknowledge").status_code == 403


# ── 驗收②:組長看板 + 再次提醒 ──────────────────────────────
def test_board_shows_acknowledgement_status(school):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid)
    _leave_and_assign(client, sid, wang, chen)

    board = client.get(f"/api/notifications?semester_id={sid}").json()
    assigned = next(n for n in board if n["type"] == "substitution_assigned")
    assert assigned["teacher_name"] == "陳師"
    assert assigned["acknowledged_at"] is None

    # 只看未確認
    unack = client.get(
        f"/api/notifications?semester_id={sid}&unacknowledged_only=true").json()
    assert all(n["acknowledged_at"] is None for n in unack)


def test_remind_resends_and_is_blocked_after_acknowledgement(school, outbox):
    client, db, sid = school
    wang, chen = _publish_wang(client, sid, email="chen@example.com")
    _leave_and_assign(client, sid, wang, chen)
    outbox.clear()

    nid = client.get(f"/api/notifications?semester_id={sid}&teacher_id={chen}").json()[0]["id"]
    r = client.post(f"/api/notifications/{nid}/remind")
    assert r.status_code == 200
    assert "再次提醒" in r.json()["title"]
    assert len(outbox) == 1  # 重發也走 Email

    # 陳師確認後,再提醒被擋
    _bind_login(client, db, chen, "chen")
    my = client.get(f"/api/notifications/mine?semester_id={sid}").json()["items"]
    reminder = next(n for n in my if "再次提醒" in n["title"])
    client.post(f"/api/notifications/{reminder['id']}/acknowledge")

    _login(client, "s")
    assert client.post(f"/api/notifications/{reminder['id']}/remind").status_code == 409


# ── 驗收③:SMTP 未設定時系統正常運作 ───────────────────────
def test_works_without_smtp_configured(school, outbox):
    """沒設 SMTP:站內通知照常;email_job 之後會 no-op(此處驗 send 回 False)。"""
    client, db, sid = school
    wang, chen = _publish_wang(client, sid, email="chen@example.com")
    _leave_and_assign(client, sid, wang, chen)

    # 通知仍建立(站內)
    assert client.get(
        f"/api/notifications?semester_id={sid}&teacher_id={chen}").json()

    # SMTP 未設定 → email service 回 False,不拋錯
    from app.services import email as email_service
    assert app_settings.smtp_config(db).configured is False
    assert email_service.send(db, to="x@example.com", subject="t", body="b") is False


def test_smtp_settings_roundtrip_hides_password(env):
    client, db = env
    make_user(db, "admin2", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin2", "password": PW})

    r = client.put("/api/settings/smtp", json={
        "host": "mailhog", "port": 1025, "user": "", "password": "secret",
        "sender": "noreply@school.edu.tw", "use_tls": False})
    assert r.status_code == 200
    out = r.json()
    assert out["configured"] is True
    assert out["has_password"] is True
    assert "password" not in out  # 密碼不回傳

    # 再存一次、密碼留空 = 不變更
    client.put("/api/settings/smtp", json={
        "host": "mailhog", "port": 1025, "user": "", "password": "",
        "sender": "noreply@school.edu.tw", "use_tls": False})
    assert app_settings.smtp_config(db).password == "secret"


def test_smtp_settings_require_admin(school):
    client, _db, _sid = school  # 已登入教學組長
    assert client.get("/api/settings/smtp").status_code == 403


# ── outbox 交易語意:回滾不寄信 ─────────────────────────────
def test_email_outbox_is_discarded_on_rollback(env, outbox):
    """通知寫入的交易若回滾,不該寄出對應的信。"""
    client, db = env
    sid = _prep_teacher_with_email(client, db)

    from app.models.notification import NotificationType
    tid = db.query(_Teacher()).filter_by(semester_id=sid).first().id
    notif_service.notify(db, semester_id=sid, teacher_id=tid,
                         type=NotificationType.leave_registered, title="x", body="y")
    db.rollback()
    assert outbox == []  # 回滾 → 不寄

    notif_service.notify(db, semester_id=sid, teacher_id=tid,
                         type=NotificationType.leave_registered, title="x", body="y")
    db.commit()
    assert len(outbox) == 1  # commit → 寄


def _Teacher():
    from app.models.basedata import Teacher
    return Teacher


def _prep_teacher_with_email(client, db) -> int:
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 116, "term": 1, "template_key": "junior_high"}).json()["id"]
    client.post(f"/api/teachers?semester_id={sid}",
                json={"name": "王師", "base_periods": 20, "email": "wang@example.com"})
    return sid


# ── helpers ──────────────────────────────────────────────────
def _login(client, username):
    client.post("/api/auth/login", json={"username": username, "password": PW})


def _bind_login(client, db, teacher_id, username):
    """把登入帳號綁到教師主檔。PATCH 是整筆取代,得帶回原名以免把老師改名。"""
    from app.models.basedata import Teacher
    teacher = db.get(Teacher, teacher_id)
    user = make_user(db, username, PW, roles=[Role.teacher])
    r = client.patch(f"/api/teachers/{teacher_id}", json={
        "name": teacher.name, "base_periods": teacher.base_periods,
        "subject_ids": [s.id for s in teacher.subjects], "user_id": user.id})
    assert r.status_code == 200, r.json()
    _login(client, username)
