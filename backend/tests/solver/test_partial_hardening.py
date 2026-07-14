"""M6-3:部分排課三合一。

(a) 完全排不下的課列入未排清單並註明原因,不再讓整個部分排課失敗
(b) 未排清單隨草稿持久化(先前只活在 Redis 24h;force 發布後原因就永遠遺失)
(c) 跑班群組掉一個時段只算一節,不再乘上成員班級數
"""

from app.models.timetable import Timetable
from app.workers.progress import JobStatus
from tests.solver.test_auto_schedule import _start, sched  # noqa: F401 - 沿用 fixture


def _blocked_course(client, sid):
    """一門「完全無處可排」的課:教師整週都不可排。

    這是協同教學/兼課教師的真實情境——兩位教師的不可排時段剛好蓋滿整週。舊行為是
    `_make_lesson_vars` 直接 raise,連「其他課照排」都做不到,部分排課整鍋失敗。
    """
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "美術"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "封鎖師", "base_periods": 20}).json()
    # 整週每一格都設為「不可排」(H4 硬約束)→ 這門課完全沒有候選時段
    table = client.get(f"/api/class-units/{c['id']}/period-table").json()
    rules = [{"weekday": p["weekday"], "period_no": p["period_no"],
              "rule_type": "unavailable"} for p in table["periods"]]
    r = client.put(f"/api/teachers/{t['id']}/time-rules", json=rules)
    assert r.status_code == 200, r.text
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 2,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })
    return c, s


def _normal_course(client, sid, cls):
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()
    client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": cls["id"], "subject_id": s["id"], "periods_per_week": 4,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
    })


# ── (a) 完全排不下的課不再炸掉整鍋 ───────────────────────────
def test_a_completely_blocked_course_is_listed_not_fatal(sched):  # noqa: F811
    """部分排課的承諾是「排不下的列清單、其他照排」——完全被擋死的課不能讓它整個失敗。"""
    client, db, sid, tid, _store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    r = _start(client, tid, max_seconds=30, allow_partial=True)
    assert r.status_code == 202
    body = client.get(f"/api/solver/jobs/{r.json()['job_id']}").json()

    assert body["status"] == JobStatus.finished.value, body.get("error")
    blocked = next(u for u in body["unscheduled"] if u["subject_name"] == "美術")
    assert blocked["periods"] == 2
    assert "找不到任何可排的" in blocked["reason"], "排不下要說得出為什麼"

    # 其他課照排(這正是部分排課存在的意義)
    result = db.get(Timetable, body["result_timetable_id"])
    assert len(result.entries) == 4


def test_a_blocked_course_still_fails_loudly_in_normal_mode(sched):  # noqa: F811
    """一般模式維持原行為:完全排不下就要當場擋下,不能默默少排。

    這份資料連 pre-flight 都過不了(教師整週不可排 → 供給為零),根本輪不到 solver。
    「部分排課不再炸鍋」只放寬部分排課那條路,一般模式的把關一格都沒鬆。
    (solver 層「非部分排課仍 raise SolverInputError」的不變式由
     test_conflict_explainer.py 的「找不到任何可排」守著。)
    """
    client, _db, sid, tid, _store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    r = _start(client, tid, max_seconds=30)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["issues"], "擋下來要說得出是哪一項不對"


# ── (b) 未排清單隨草稿持久化 ─────────────────────────────────
def test_b_unscheduled_survives_redis_and_publish(sched):  # noqa: F811
    """Redis 清空(或 24h 過後)、草稿被 force 發布,原因都還在——存在 DB 裡。"""
    client, db, sid, tid, store, _calls = sched
    cls, _ = _blocked_course(client, sid)
    _normal_course(client, sid, cls)

    job_id = _start(client, tid, max_seconds=30, allow_partial=True).json()["job_id"]
    result_id = client.get(f"/api/solver/jobs/{job_id}").json()["result_timetable_id"]

    store.clear() if hasattr(store, "clear") else None  # 模擬 Redis TTL 到期
    db.expire_all()

    stored = db.get(Timetable, result_id).unscheduled
    assert stored, "未排清單必須隨草稿存進 DB,不能只活在 Redis"
    assert any("找不到任何可排的" in u["reason"] for u in stored)

    # force 發布後,版本頁的完整性報告仍講得出原因
    client.post(f"/api/timetables/{result_id}/publish?force=true")
    report = client.get(f"/api/timetables/{result_id}/completeness").json()
    art = next(u for u in report["unplaced"] if u["subject"] == "美術")
    assert art["remaining"] == 2
    assert "找不到任何可排的" in art["reason"]


def test_b_a_hand_made_draft_has_no_reason_and_that_is_fine(sched):  # noqa: F811
    """手動排的草稿沒有 solver 紀錄:未排清單照樣從 DB 算得出來,只是沒有原因。"""
    client, db, sid, tid, _store, _calls = sched
    cls = client.post(f"/api/class-units?semester_id={sid}",
                      json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    _normal_course(client, sid, cls)

    report = client.get(f"/api/timetables/{tid}/completeness").json()
    assert report["complete"] is False
    assert report["unplaced"][0]["remaining"] == 4
    assert report["unplaced"][0]["reason"] == ""
    assert db.get(Timetable, tid).unscheduled is None


# ── (c) 跑班群組不灌水 ───────────────────────────────────────
def test_c_a_group_slot_counts_once_not_per_member_class(sched):  # noqa: F811
    """跑班群組同時段開課:掉一個時段就是掉一節課,不是掉「成員班級數」節。

    舊行為對群組內每筆成員配課各記一次,3 個班的跑班少排 1 節會報成「未排 3 節」。
    """
    client, _db, sid, tid, _store, _calls = sched
    classes = [
        client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": f"30{i}", "track": "junior_high"}).json()
        for i in (1, 2, 3)
    ]
    unit = client.post(f"/api/scheduling-units?semester_id={sid}", json={
        "name": "三年級選修", "class_ids": [c["id"] for c in classes],
    }).json()
    # 跑班 = 三個班的學生同時段拆進 2 門選修。每週 12 節,但 H10 每日同科上限 2 節
    # × 5 天 = 最多排 10 節 → 必然少排 2 個「時段」。
    # 舊行為對群組內每筆配課各記一次 → 同一件事被報成 4 節。
    for name in ("選修A", "選修B"):
        s = client.post(f"/api/subjects?semester_id={sid}", json={"name": name}).json()
        t = client.post(f"/api/teachers?semester_id={sid}",
                        json={"name": f"{name}師", "base_periods": 20}).json()
        r = client.post(f"/api/assignments?semester_id={sid}", json={
            "scheduling_unit_id": unit["id"], "subject_id": s["id"],
            "periods_per_week": 12,
            "teachers": [{"teacher_id": t["id"]}], "block_rules": [],
        })
        assert r.status_code == 201, r.text

    body = client.get(f"/api/solver/jobs/"
                      f"{_start(client, tid, max_seconds=30, allow_partial=True).json()['job_id']}"
                      ).json()
    assert body["status"] == JobStatus.finished.value, body.get("error")

    unscheduled = body["unscheduled"]
    assert len(unscheduled) == 1, "一個排課單位就是一筆,不是群組內每筆配課各一筆"
    item = unscheduled[0]
    assert item["periods"] == 2, f"少排 2 個時段 = 2 節,不是 2 門×2 = 4 節(得到 {item['periods']})"
    assert sorted(item["class_names"]) == ["301", "302", "303"]
    assert len(item["assignment_ids"]) == 2  # 群組內兩門選修都留著,供前端定位
    assert item["subject_name"] == "選修A、選修B"  # 只印第一門會誤導
