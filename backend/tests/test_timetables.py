"""手動排課與衝突檢查(M2-3)測試。

覆蓋 architecture.md §3.2 硬約束 H1–H10 的單格檢查版(每項過/不過各至少 2 案例)、
D7 跨節次表牆鐘時間重疊、跑班群組同進同出,以及 check-conflict 效能。
"""

import time as _time

import pytest

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"

# 主節次表:p1-p3 一般課、p4 午休、p5-p6 一般課(50 分/節)
MAIN_SLOTS = [
    (1, "第一節", "08:00", "08:50", "regular"),
    (2, "第二節", "09:00", "09:50", "regular"),
    (3, "第三節", "10:00", "10:50", "regular"),
    (4, "午休", "12:00", "13:00", "lunch"),
    (5, "第四節", "13:00", "13:50", "regular"),
    (6, "第五節", "14:00", "14:50", "regular"),
]


def _periods(slots, weekdays=5):
    out = []
    for w in range(1, weekdays + 1):
        for pno, name, s, e, typ in slots:
            out.append({
                "weekday": w, "period_no": pno, "name": name,
                "start_time": f"{s}:00", "end_time": f"{e}:00", "type": typ,
            })
    return out


@pytest.fixture
def env2(env):
    """已登入教學組長 + 空白學期 + 主節次表(預設)+ 一份課表草稿。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    sid = sem["id"]
    pt = client.post(
        f"/api/semesters/{sid}/period-tables", json={"name": "主表", "is_default": True}
    ).json()
    client.put(f"/api/period-tables/{pt['id']}/periods", json=_periods(MAIN_SLOTS))
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()
    return client, sid, tt["id"], pt["id"]


# ── 建立資料的小工具 ──────────────────
def _subject(client, sid, name):
    return client.post(f"/api/subjects?semester_id={sid}", json={"name": name}).json()


def _teacher(client, sid, name):
    return client.post(f"/api/teachers?semester_id={sid}", json={"name": name}).json()


def _room(client, sid, name):
    return client.post(f"/api/rooms?semester_id={sid}", json={"name": name}).json()


def _class(client, sid, grade, name, period_table_id=None):
    body = {"grade": grade, "name": name, "track": "junior_high"}
    if period_table_id:
        body["period_table_id"] = period_table_id
    return client.post(f"/api/class-units?semester_id={sid}", json=body).json()


def _assign(client, sid, *, class_id=None, unit_id=None, subject_id, teacher_ids,
            periods=5, room_id=None, blocks=None):
    body = {
        "subject_id": subject_id, "periods_per_week": periods,
        "teachers": [{"teacher_id": t, "is_lead": i == 0} for i, t in enumerate(teacher_ids)],
        "block_rules": blocks or [],
    }
    if class_id:
        body["class_id"] = class_id
    else:
        body["scheduling_unit_id"] = unit_id
    if room_id:
        body["room_id"] = room_id
    r = client.post(f"/api/assignments?semester_id={sid}", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _place(client, tid, aid, weekday, period_no, span=1, room_id=None):
    body = {"course_assignment_id": aid, "weekday": weekday,
            "period_no": period_no, "span": span}
    if room_id:
        body["room_id"] = room_id
    return client.post(f"/api/timetables/{tid}/entries", json=body)


def _check(client, tid, aid, weekday, period_no, span=1, ignore_entry_id=None, room_id=None):
    body = {"course_assignment_id": aid, "weekday": weekday, "period_no": period_no, "span": span}
    if ignore_entry_id:
        body["ignore_entry_id"] = ignore_entry_id
    if room_id:
        body["room_id"] = room_id
    return client.post(f"/api/timetables/{tid}/check-conflict", json=body).json()


def _codes(resp_json) -> set[str]:
    return {c["code"] for c in resp_json["conflicts"]}


def _entries(client, tid):
    return client.get(f"/api/timetables/{tid}").json()["entries"]


# ── 班級所屬節次表(工作台渲染用)────
def test_class_period_table_endpoint(env2):
    """回傳完整節次表(含午休等非上課格位),且經 resolve_period_table 回退學期預設表。"""
    client, sid, _tid, ptid = env2
    c = _class(client, sid, 1, "甲")  # 未指定節次表 → 應回退預設表
    r = client.get(f"/api/class-units/{c['id']}/period-table")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == ptid
    assert any(p["type"] == "lunch" for p in body["periods"])
    assert any(p["type"] == "regular" for p in body["periods"])


# ── 課表草稿 CRUD ─────────────────────
def test_create_and_list_timetable(env2):
    client, sid, tid, _ = env2
    lst = client.get(f"/api/timetables?semester_id={sid}").json()
    assert len(lst) == 1 and lst[0]["name"] == "草稿A" and lst[0]["entry_count"] == 0
    assert client.delete(f"/api/timetables/{tid}").status_code == 204
    assert client.get(f"/api/timetables?semester_id={sid}").json() == []


# ── H1 班級不衝堂 ─────────────────────
def test_h1_class_conflict(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 3, "301")
    t1, t2 = _teacher(client, sid, "王師"), _teacher(client, sid, "李師")
    s1, s2 = _subject(client, sid, "國文"), _subject(client, sid, "數學")
    a1 = _assign(client, sid, class_id=c["id"], subject_id=s1["id"], teacher_ids=[t1["id"]])
    a2 = _assign(client, sid, class_id=c["id"], subject_id=s2["id"], teacher_ids=[t2["id"]])
    assert _place(client, tid, a1["id"], 1, 1).status_code == 201
    # 不過:同班同時段
    assert "H1" in _codes(_check(client, tid, a2["id"], 1, 1))
    assert _place(client, tid, a2["id"], 1, 1).status_code == 409
    # 過:同班不同時段
    assert _check(client, tid, a2["id"], 1, 2)["ok"] is True
    assert _place(client, tid, a2["id"], 1, 2).status_code == 201


def test_h1_different_classes_same_slot_ok(env2):
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 3, "301"), _class(client, sid, 3, "302")
    t1, t2 = _teacher(client, sid, "王師"), _teacher(client, sid, "李師")
    s = _subject(client, sid, "國文")
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"], teacher_ids=[t1["id"]])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"], teacher_ids=[t2["id"]])
    assert _place(client, tid, a1["id"], 1, 1).status_code == 201
    assert _place(client, tid, a2["id"], 1, 1).status_code == 201  # 不同班、不同師 → 可


# ── H2 教師不衝堂(驗收①)────────────
def test_h2_teacher_conflict_message(env2):
    """驗收①:王師已在週一第一節有課,再排他班同時段 →
    「教師王師 週一第一節 已有 302 班數學」(時段以節次表名稱呈現)"""
    client, sid, tid, _ = env2
    c302, c301 = _class(client, sid, 3, "302"), _class(client, sid, 3, "301")
    wang = _teacher(client, sid, "王師")
    math, chinese = _subject(client, sid, "數學"), _subject(client, sid, "國文")
    a302 = _assign(client, sid, class_id=c302["id"], subject_id=math["id"],
                   teacher_ids=[wang["id"]])
    a301 = _assign(client, sid, class_id=c301["id"], subject_id=chinese["id"],
                   teacher_ids=[wang["id"]])
    assert _place(client, tid, a302["id"], 1, 1).status_code == 201

    res = _check(client, tid, a301["id"], 1, 1)
    assert res["ok"] is False
    assert "H2" in _codes(res)
    msg = next(c["message"] for c in res["conflicts"] if c["code"] == "H2")
    assert msg == "教師王師 週一第一節 已有 302 班數學"
    assert _place(client, tid, a301["id"], 1, 1).status_code == 409


def test_h2_teacher_free_other_slot_ok(env2):
    client, sid, tid, _ = env2
    c302, c301 = _class(client, sid, 3, "302"), _class(client, sid, 3, "301")
    wang = _teacher(client, sid, "王師")
    math = _subject(client, sid, "數學")
    a302 = _assign(client, sid, class_id=c302["id"], subject_id=math["id"],
                   teacher_ids=[wang["id"]])
    a301 = _assign(client, sid, class_id=c301["id"], subject_id=math["id"],
                   teacher_ids=[wang["id"]])
    _place(client, tid, a302["id"], 1, 1)
    assert _check(client, tid, a301["id"], 1, 2)["ok"] is True  # 同師不同節 → 可


def test_h2_coteaching_counts(env2):
    """協同教師也算佔用。"""
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 1, "甲"), _class(client, sid, 1, "乙")
    t1, t2 = _teacher(client, sid, "主教"), _teacher(client, sid, "協同")
    s = _subject(client, sid, "實習")
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"],
                 teacher_ids=[t1["id"], t2["id"]])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"], teacher_ids=[t2["id"]])
    _place(client, tid, a1["id"], 1, 1)
    assert "H2" in _codes(_check(client, tid, a2["id"], 1, 1))  # 協同教師撞課


def test_slot_label_uses_period_name_not_index(env):
    """迴歸:訊息中的時段須用節次表名稱(早自習/午休/第一節),不可用內部 period_no。

    國中範本的「第一節」period_no 是 2(第 1 格是早自習),先前硬拼 f"第{period_no}節"
    會顯示「第2節」,與教學組長的認知不符(2026-07-10 實機驗證發現)。
    """
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post(
        "/api/semesters",
        json={"academic_year": 117, "term": 1, "template_key": "junior_high"},
    ).json()["id"]
    tid = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿"}).json()["id"]

    c301, c302 = _class(client, sid, 3, "301"), _class(client, sid, 3, "302")
    wang = _teacher(client, sid, "王師")
    math = _subject(client, sid, "數學二")
    chin = _subject(client, sid, "國文二")
    a302 = _assign(client, sid, class_id=c302["id"], subject_id=math["id"],
                   teacher_ids=[wang["id"]])
    a301 = _assign(client, sid, class_id=c301["id"], subject_id=chin["id"],
                   teacher_ids=[wang["id"]])

    # 範本:period_no 1=早自習、2=第一節、6=午休
    assert _place(client, tid, a302["id"], 1, 2).status_code == 201

    h2 = next(c["message"] for c in _check(client, tid, a301["id"], 1, 2)["conflicts"]
              if c["code"] == "H2")
    assert h2 == "教師王師 週一第一節 已有 302 班數學二"
    assert "第2節" not in h2

    h5_lunch = next(c["message"] for c in _check(client, tid, a301["id"], 1, 6)["conflicts"]
                    if c["code"] == "H5")
    assert h5_lunch.startswith("週一午休")

    h5_morning = next(c["message"] for c in _check(client, tid, a301["id"], 1, 1)["conflicts"]
                      if c["code"] == "H5")
    assert h5_morning.startswith("週一早自習")


# ── H3 場地不衝堂 ─────────────────────
def test_h3_room_conflict(env2):
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 1, "甲"), _class(client, sid, 1, "乙")
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s = _subject(client, sid, "自然")
    lab = _room(client, sid, "理化教室")
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"], teacher_ids=[t1["id"]],
                 room_id=lab["id"])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"], teacher_ids=[t2["id"]],
                 room_id=lab["id"])
    _place(client, tid, a1["id"], 1, 1)
    assert "H3" in _codes(_check(client, tid, a2["id"], 1, 1))       # 不過:同場地同時段
    assert _check(client, tid, a2["id"], 1, 2)["ok"] is True          # 過:不同時段


def test_h3_different_rooms_ok(env2):
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 1, "甲"), _class(client, sid, 1, "乙")
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s = _subject(client, sid, "自然")
    r1, r2 = _room(client, sid, "理化教室"), _room(client, sid, "生物教室")
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"],
                 teacher_ids=[t1["id"]], room_id=r1["id"])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"],
                 teacher_ids=[t2["id"]], room_id=r2["id"])
    _place(client, tid, a1["id"], 1, 1)
    assert _check(client, tid, a2["id"], 1, 1)["ok"] is True


# ── 格位場地(M3-1:schedule_entries.room_id)────
def test_entry_room_overrides_assignment_room(env2):
    """格位放到與配課不同的場地後,H3 以「格位的場地」判定佔用,而非配課上的預設場地。"""
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 1, "甲"), _class(client, sid, 1, "乙")
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s = _subject(client, sid, "自然")
    lab, bio = _room(client, sid, "理化教室"), _room(client, sid, "生物教室")
    # 甲班的自然課「配課」在理化教室,但這一格改上生物教室
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"],
                 teacher_ids=[t1["id"]], room_id=lab["id"])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"],
                 teacher_ids=[t2["id"]], room_id=bio["id"])
    r = _place(client, tid, a1["id"], 1, 1, room_id=bio["id"])
    assert r.status_code == 201, r.text

    entry = _entries(client, tid)[0]
    assert entry["room"] == "生物教室"  # 課表顯示的是格位場地

    # 乙班的生物教室課撞上「移過去的那一格」
    assert "H3" in _codes(_check(client, tid, a2["id"], 1, 1))
    # 理化教室此時是空的,把乙班的課指過去就不衝突
    assert _check(client, tid, a2["id"], 1, 1, room_id=lab["id"])["ok"] is True


def test_entry_without_room_falls_back_to_assignment_room(env2):
    """格位未指定場地時沿用配課場地(既有行為不得退步)。"""
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 1, "甲"), _class(client, sid, 1, "乙")
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s = _subject(client, sid, "自然")
    lab = _room(client, sid, "理化教室")
    a1 = _assign(client, sid, class_id=ca["id"], subject_id=s["id"],
                 teacher_ids=[t1["id"]], room_id=lab["id"])
    a2 = _assign(client, sid, class_id=cb["id"], subject_id=s["id"],
                 teacher_ids=[t2["id"]], room_id=lab["id"])
    _place(client, tid, a1["id"], 1, 1)
    entry = _entries(client, tid)[0]
    assert entry["room"] == "理化教室" and entry["room_id"] == lab["id"]
    assert "H3" in _codes(_check(client, tid, a2["id"], 1, 1))


def test_place_rejects_room_from_other_semester(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "師一")
    s = _subject(client, sid, "自然")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    other = client.post("/api/semesters", json={"academic_year": 116, "term": 1}).json()
    foreign = _room(client, other["id"], "他校教室")
    r = _place(client, tid, a["id"], 1, 1, room_id=foreign["id"])
    assert r.status_code == 400


# ── H4 教師不可排時段 ─────────────────
def test_h4_teacher_unavailable(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "兼行政")
    s = _subject(client, sid, "國文")
    client.put(f"/api/teachers/{t['id']}/time-rules",
               json=[{"weekday": 1, "period_no": 1, "rule_type": "unavailable"}])
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    assert "H4" in _codes(_check(client, tid, a["id"], 1, 1))   # 不過
    assert _check(client, tid, a["id"], 1, 2)["ok"] is True      # 過


def test_h4_prefer_rule_is_not_hard(env2):
    """prefer/avoid 為軟約束,不擋放入。"""
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    client.put(f"/api/teachers/{t['id']}/time-rules",
               json=[{"weekday": 1, "period_no": 1, "rule_type": "avoid"}])
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    assert _check(client, tid, a["id"], 1, 1)["ok"] is True


# ── H5 節次有效性 ─────────────────────
def test_h5_lunch_slot_rejected(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    res = _check(client, tid, a["id"], 1, 4)  # p4 = 午休
    assert "H5" in _codes(res)
    assert _place(client, tid, a["id"], 1, 4).status_code == 409
    assert _place(client, tid, a["id"], 1, 5).status_code == 201  # p5 一般課 → 可


def test_h5_nonexistent_period_rejected(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    assert "H5" in _codes(_check(client, tid, a["id"], 1, 99))


# ── H6 連堂完整性(驗收②)───────────
def test_h6_block_crossing_lunch_rejected(env2):
    """驗收②:連堂課拖至跨午休位置 → 拒絕並說明。"""
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "機械一")
    t = _teacher(client, sid, "陳師")
    s = _subject(client, sid, "機械實習")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]],
                periods=6, blocks=[{"block_size": 2, "count_per_week": 3}])
    # p3(10:00) + p4(午休) → 跨午休
    res = _check(client, tid, a["id"], 1, 3, span=2)
    assert "H6" in _codes(res)
    msg = next(c["message"] for c in res["conflicts"] if c["code"] == "H6")
    assert "週一第三節" in msg and "午休" in msg
    assert _place(client, tid, a["id"], 1, 3, span=2).status_code == 409


def test_h6_block_within_regular_ok(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "機械一")
    t = _teacher(client, sid, "陳師")
    s = _subject(client, sid, "機械實習")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]],
                periods=6, blocks=[{"block_size": 2, "count_per_week": 3}])
    # p1+p2 皆一般課 → 可
    assert _check(client, tid, a["id"], 1, 1, span=2)["ok"] is True
    r = _place(client, tid, a["id"], 1, 1, span=2)
    assert r.status_code == 201
    e = _entries(client, tid)[0]
    assert e["span"] == 2
    # 連堂佔用兩節:另一課排在 p2 應撞班級
    t2, s2 = _teacher(client, sid, "李師"), _subject(client, sid, "國文")
    a2 = _assign(client, sid, class_id=c["id"], subject_id=s2["id"], teacher_ids=[t2["id"]])
    assert "H1" in _codes(_check(client, tid, a2["id"], 1, 2))


# ── H7 跑班群組同進同出(驗收③)──────
def test_h7_group_places_all_siblings_and_moves_together(env2):
    """驗收③:跑班群組某組拖到新時段,全組連動。"""
    client, sid, tid, _ = env2
    cids = [_class(client, sid, 2, f"20{i}")["id"] for i in (1, 2)]
    g = client.post(f"/api/scheduling-units?semester_id={sid}",
                    json={"name": "高二多元選修", "class_ids": cids}).json()
    subs = [_subject(client, sid, f"選修{i}") for i in range(3)]
    ts = [_teacher(client, sid, f"選修師{i}") for i in range(3)]
    aids = [_assign(client, sid, unit_id=g["id"], subject_id=subs[i]["id"],
                    teacher_ids=[ts[i]["id"]], periods=2)["id"] for i in range(3)]

    # 放入任一門 → 群組 3 門課同時排入同格
    assert _place(client, tid, aids[0], 1, 1).status_code == 201
    ents = _entries(client, tid)
    assert len(ents) == 3
    assert all(e["weekday"] == 1 and e["period_no"] == 1 for e in ents)

    # 移動其中一格 → 全組連動
    one = ents[0]
    r = client.patch(f"/api/timetables/{tid}/entries/{one['id']}",
                     json={"weekday": 2, "period_no": 3})
    assert r.status_code == 200
    ents2 = _entries(client, tid)
    assert len(ents2) == 3
    assert all(e["weekday"] == 2 and e["period_no"] == 3 for e in ents2)


def test_h7_group_rejected_if_any_member_conflicts(env2):
    """任一組(成員班級/教師)衝突則整組拒絕。"""
    client, sid, tid, _ = env2
    ca, cb = _class(client, sid, 2, "201"), _class(client, sid, 2, "202")
    g = client.post(f"/api/scheduling-units?semester_id={sid}",
                    json={"name": "選修群", "class_ids": [ca["id"], cb["id"]]}).json()
    s1, s2 = _subject(client, sid, "選修A"), _subject(client, sid, "選修B")
    t1, t2 = _teacher(client, sid, "師A"), _teacher(client, sid, "師B")
    ga = _assign(client, sid, unit_id=g["id"], subject_id=s1["id"],
                 teacher_ids=[t1["id"]], periods=2)
    _assign(client, sid, unit_id=g["id"], subject_id=s2["id"],
            teacher_ids=[t2["id"]], periods=2)

    # 先讓成員班 201 在週一第1節被單班課佔用
    solo_s, solo_t = _subject(client, sid, "國文"), _teacher(client, sid, "國文師")
    solo = _assign(client, sid, class_id=ca["id"], subject_id=solo_s["id"],
                   teacher_ids=[solo_t["id"]])
    _place(client, tid, solo["id"], 1, 1)

    # 整組排入同格 → 因成員班 201 衝堂而整組拒絕(零寫入)
    assert "H1" in _codes(_check(client, tid, ga["id"], 1, 1))
    assert _place(client, tid, ga["id"], 1, 1).status_code == 409
    assert len(_entries(client, tid)) == 1  # 仍只有先前那一格


def test_h7_group_siblings_sharing_teacher_conflict(env2):
    """同群組兩門課共用同一教師 → 無法同時段開課。"""
    client, sid, tid, _ = env2
    cids = [_class(client, sid, 2, f"20{i}")["id"] for i in (1, 2)]
    g = client.post(f"/api/scheduling-units?semester_id={sid}",
                    json={"name": "選修群", "class_ids": cids}).json()
    s1, s2 = _subject(client, sid, "選修A"), _subject(client, sid, "選修B")
    shared = _teacher(client, sid, "共用師")
    ga = _assign(client, sid, unit_id=g["id"], subject_id=s1["id"],
                 teacher_ids=[shared["id"]], periods=2)
    _assign(client, sid, unit_id=g["id"], subject_id=s2["id"],
            teacher_ids=[shared["id"]], periods=2)
    assert "H2" in _codes(_check(client, tid, ga["id"], 1, 1))


# ── H9 鎖定 ───────────────────────────
def test_h9_locked_entry_cannot_move_or_delete(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    _place(client, tid, a["id"], 1, 1)
    eid = _entries(client, tid)[0]["id"]

    move = {"weekday": 2, "period_no": 2}
    client.post(f"/api/timetables/{tid}/entries/{eid}/lock?locked=true")
    assert _entries(client, tid)[0]["locked"] is True
    assert client.patch(f"/api/timetables/{tid}/entries/{eid}", json=move).status_code == 409
    assert client.delete(f"/api/timetables/{tid}/entries/{eid}").status_code == 409

    # 解鎖後可移動
    client.post(f"/api/timetables/{tid}/entries/{eid}/lock?locked=false")
    assert client.patch(f"/api/timetables/{tid}/entries/{eid}", json=move).status_code == 200
    assert client.delete(f"/api/timetables/{tid}/entries/{eid}").status_code == 204


# ── H10 每日科目上限 ──────────────────
def test_h10_daily_subject_cap(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]], periods=5)
    assert _place(client, tid, a["id"], 1, 1).status_code == 201
    assert _place(client, tid, a["id"], 1, 2).status_code == 201  # 同日 2 節 → 上限
    assert "H10" in _codes(_check(client, tid, a["id"], 1, 3))    # 第 3 節同日 → 不過
    assert _place(client, tid, a["id"], 1, 3).status_code == 409
    assert _place(client, tid, a["id"], 2, 1).status_code == 201  # 換一天 → 可


def test_h10_block_exempt(env2):
    """連堂不受每日上限限制。"""
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "機械一")
    t = _teacher(client, sid, "陳師")
    s = _subject(client, sid, "機械實習")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]],
                periods=6, blocks=[{"block_size": 3, "count_per_week": 2}])
    assert _place(client, tid, a["id"], 1, 1, span=3).status_code == 201  # 3 連堂 > 上限 2 但豁免


def test_h10_leftover_single_periods_still_capped(env2):
    """連堂課「剩下的單節」仍受每日上限限制。

    豁免的是連堂本身(一次上完的整塊),不是整筆配課。定義以 solver/validator.py 為準:
    每日上限只計節長 1 的格位。
    """
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "機械一")
    t = _teacher(client, sid, "陳師")
    s = _subject(client, sid, "機械實習")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]],
                periods=8, blocks=[{"block_size": 3, "count_per_week": 2}])
    assert _place(client, tid, a["id"], 1, 1).status_code == 201  # 單節 1/2
    assert _place(client, tid, a["id"], 1, 2).status_code == 201  # 單節 2/2
    assert "H10" in _codes(_check(client, tid, a["id"], 1, 3))    # 第 3 個單節 → 不過
    assert _check(client, tid, a["id"], 2, 1)["ok"] is True       # 換一天 → 可


# ── 每週節數守恆(放入面)──────────────
def test_cannot_exceed_periods_per_week(env2):
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]], periods=2)
    assert _place(client, tid, a["id"], 1, 1).status_code == 201
    assert _place(client, tid, a["id"], 2, 1).status_code == 201
    r = _place(client, tid, a["id"], 3, 1)  # 已排滿 2 節
    assert r.status_code == 409
    assert "每週" in r.json()["detail"]


# ── 移動與 ignore 自身 ────────────────
def test_move_ignores_self(env2):
    """移動時忽略自身格位;移到原地或鄰格不應與自己相衝。"""
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t = _teacher(client, sid, "王師")
    s = _subject(client, sid, "國文")
    a = _assign(client, sid, class_id=c["id"], subject_id=s["id"], teacher_ids=[t["id"]])
    _place(client, tid, a["id"], 1, 1)
    eid = _entries(client, tid)[0]["id"]
    # check-conflict 帶 ignore_entry_id → 原地不衝突
    assert _check(client, tid, a["id"], 1, 1, ignore_entry_id=eid)["ok"] is True
    # 不帶 ignore → 與自己相衝(H1)
    assert _check(client, tid, a["id"], 1, 1)["ok"] is False
    r = client.patch(f"/api/timetables/{tid}/entries/{eid}", json={"weekday": 1, "period_no": 2})
    assert r.status_code == 200


def test_same_class_can_hold_multiple_subjects(env2):
    """同班多科目可各自排入不同格位(排課單位不應被整體連動)。"""
    client, sid, tid, _ = env2
    c = _class(client, sid, 1, "甲")
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s1, s2 = _subject(client, sid, "國文"), _subject(client, sid, "數學")
    a1 = _assign(client, sid, class_id=c["id"], subject_id=s1["id"], teacher_ids=[t1["id"]])
    a2 = _assign(client, sid, class_id=c["id"], subject_id=s2["id"], teacher_ids=[t2["id"]])
    assert _place(client, tid, a1["id"], 1, 1).status_code == 201
    assert _place(client, tid, a2["id"], 1, 2).status_code == 201
    assert len(_entries(client, tid)) == 2
    # 移動數學不應動到國文
    e_math = next(e for e in _entries(client, tid) if e["subject"] == "數學")
    client.patch(f"/api/timetables/{tid}/entries/{e_math['id']}",
                 json={"weekday": 3, "period_no": 1})
    ents = {e["subject"]: (e["weekday"], e["period_no"]) for e in _entries(client, tid)}
    assert ents["國文"] == (1, 1) and ents["數學"] == (3, 1)


# ── D7 跨節次表牆鐘時間重疊(驗收⑤)──
ELEM_SLOTS = [  # 40 分/節
    (1, "第一節", "08:00", "08:40", "regular"),
    (2, "第二節", "08:50", "09:30", "regular"),
    (3, "第三節", "09:40", "10:20", "regular"),
    (4, "第四節", "10:30", "11:10", "regular"),
]
SENIOR_SLOTS = [  # 50 分/節
    (1, "第一節", "08:10", "09:00", "regular"),
    (2, "第二節", "09:10", "10:00", "regular"),
    (3, "第三節", "10:10", "11:00", "regular"),
    (4, "第四節", "11:10", "12:00", "regular"),
]


@pytest.fixture
def mixed(env):
    """完全中學情境:國小部(40 分)與高中部(50 分)兩套節次表 + 一位跨部教師。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={"academic_year": 116, "term": 1}).json()["id"]
    pt_e = client.post(f"/api/semesters/{sid}/period-tables",
                       json={"name": "國小部", "is_default": True}).json()
    pt_s = client.post(f"/api/semesters/{sid}/period-tables", json={"name": "高中部"}).json()
    client.put(f"/api/period-tables/{pt_e['id']}/periods", json=_periods(ELEM_SLOTS))
    client.put(f"/api/period-tables/{pt_s['id']}/periods", json=_periods(SENIOR_SLOTS))
    tid = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿"}).json()["id"]
    return client, sid, tid, pt_e["id"], pt_s["id"]


def test_d7_cross_table_time_overlap_conflict(mixed):
    """驗收⑤:國小部第4節 10:30-11:10 與高中部第3節 10:10-11:00 牆鐘時間重疊 → 教師衝突。"""
    client, sid, tid, pt_e, pt_s = mixed
    c_e = _class(client, sid, 4, "國小四甲", period_table_id=pt_e)
    c_s = _class(client, sid, 1, "高一甲", period_table_id=pt_s)
    wang = _teacher(client, sid, "王師")
    s1, s2 = _subject(client, sid, "自然"), _subject(client, sid, "物理")
    a_e = _assign(client, sid, class_id=c_e["id"], subject_id=s1["id"], teacher_ids=[wang["id"]])
    a_s = _assign(client, sid, class_id=c_s["id"], subject_id=s2["id"], teacher_ids=[wang["id"]])

    # 王師先在國小部週一第 4 節(10:30-11:10)
    assert _place(client, tid, a_e["id"], 1, 4).status_code == 201
    # 再排高中部週一第 3 節(10:10-11:00):節次號不同,但時間重疊 → H2
    res = _check(client, tid, a_s["id"], 1, 3)
    assert res["ok"] is False, res
    assert "H2" in _codes(res)
    assert _place(client, tid, a_s["id"], 1, 3).status_code == 409


def test_d7_cross_table_no_overlap_ok(mixed):
    """節次號相同但牆鐘時間不重疊 → 可排(證明非以 period_no 相等誤判)。"""
    client, sid, tid, pt_e, pt_s = mixed
    c_e = _class(client, sid, 4, "國小四甲", period_table_id=pt_e)
    c_s = _class(client, sid, 1, "高一甲", period_table_id=pt_s)
    wang = _teacher(client, sid, "王師")
    s1, s2 = _subject(client, sid, "自然"), _subject(client, sid, "物理")
    a_e = _assign(client, sid, class_id=c_e["id"], subject_id=s1["id"], teacher_ids=[wang["id"]])
    a_s = _assign(client, sid, class_id=c_s["id"], subject_id=s2["id"], teacher_ids=[wang["id"]])
    # 國小部第 4 節 10:30-11:10 vs 高中部第 4 節 11:10-12:00 → 相接不重疊
    assert _place(client, tid, a_e["id"], 1, 4).status_code == 201
    assert _check(client, tid, a_s["id"], 1, 4)["ok"] is True
    assert _place(client, tid, a_s["id"], 1, 4).status_code == 201


def test_d7_cross_table_room_overlap(mixed):
    """跨表場地衝突同樣以牆鐘時間判定。"""
    client, sid, tid, pt_e, pt_s = mixed
    c_e = _class(client, sid, 4, "國小四甲", period_table_id=pt_e)
    c_s = _class(client, sid, 1, "高一甲", period_table_id=pt_s)
    t1, t2 = _teacher(client, sid, "師一"), _teacher(client, sid, "師二")
    s1, s2 = _subject(client, sid, "自然"), _subject(client, sid, "物理")
    lab = _room(client, sid, "自然科教室")
    a_e = _assign(client, sid, class_id=c_e["id"], subject_id=s1["id"],
                  teacher_ids=[t1["id"]], room_id=lab["id"])
    a_s = _assign(client, sid, class_id=c_s["id"], subject_id=s2["id"],
                  teacher_ids=[t2["id"]], room_id=lab["id"])
    _place(client, tid, a_e["id"], 1, 4)  # 10:30-11:10
    assert "H3" in _codes(_check(client, tid, a_s["id"], 1, 3))  # 10:10-11:00 重疊


# ── 效能(驗收④)──────────────────────
def test_check_conflict_performance(env2):
    """驗收④:具規模資料下 check-conflict 應遠低於 100ms。"""
    client, sid, tid, _ = env2
    # 建 40 班,每班 5 科各排 1 節(共 200 格位)
    teachers = [_teacher(client, sid, f"師{i}")["id"] for i in range(40)]
    subjects = [_subject(client, sid, f"科{i}")["id"] for i in range(5)]
    for ci in range(40):
        c = _class(client, sid, 1, f"班{ci}")
        for si in range(5):
            a = _assign(client, sid, class_id=c["id"], subject_id=subjects[si],
                        teacher_ids=[teachers[(ci + si) % 40]], periods=5)
            wd = si + 1
            r = _place(client, tid, a["id"], wd, 1)
            assert r.status_code == 201, r.text
    assert len(_entries(client, tid)) == 200

    probe = _assign(client, sid, class_id=_class(client, sid, 9, "探測班")["id"],
                    subject_id=subjects[0], teacher_ids=[teachers[0]], periods=5)
    samples = []
    for _ in range(20):
        t0 = _time.perf_counter()
        client.post(
            f"/api/timetables/{tid}/check-conflict",
            json={"course_assignment_id": probe["id"], "weekday": 1,
                  "period_no": 2, "span": 1},
        )
        samples.append((_time.perf_counter() - t0) * 1000)
    samples.sort()
    p95 = samples[int(0.95 * (len(samples) - 1))]
    assert p95 < 100, f"check-conflict p95 {p95:.1f}ms(最慢 {samples[-1]:.1f}ms),超過 100ms 目標"


# ── 手動排課的每日上限必須與自動排課同源(不可寫死 2)──
def test_daily_cap_follows_the_semester_config(env):
    """PUT /solver/config 把上限調到 3 → 手動拖第 3 節同科目不再報 H10。

    寫死的常數會讓同一張草稿出現「自動排課排得出來、手動拖曳卻報違規」的雙軌判定,
    而 M4 調代課直接重用這支檢查器。
    """
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})

    sid = client.post("/api/semesters", json={
        "academic_year": 180, "term": 1, "template_key": "junior_high"}).json()["id"]
    c = client.post(f"/api/class-units?semester_id={sid}",
                    json={"grade": 3, "name": "301", "track": "junior_high"}).json()
    s = client.post(f"/api/subjects?semester_id={sid}", json={"name": "國文"}).json()
    t = client.post(f"/api/teachers?semester_id={sid}",
                    json={"name": "王師", "base_periods": 20}).json()
    a = client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": c["id"], "subject_id": s["id"], "periods_per_week": 6,
        "teachers": [{"teacher_id": t["id"]}], "block_rules": []}).json()
    tt = client.post(f"/api/timetables?semester_id={sid}", json={"name": "草稿A"}).json()

    slots = client.get(f"/api/class-units/{c['id']}/period-table").json()["periods"]
    day1 = [p["period_no"] for p in slots if p["weekday"] == 1 and p["type"] == "regular"]

    def place(pno):
        return client.post(f"/api/timetables/{tt['id']}/entries", json={
            "course_assignment_id": a["id"], "weekday": 1, "period_no": pno, "span": 1})

    assert place(day1[0]).status_code == 201
    assert place(day1[1]).status_code == 201

    # 預設上限 2 → 第 3 節同科目被擋
    blocked = place(day1[2])
    assert blocked.status_code == 409
    assert "每日上限 2 節" in str(blocked.json()["detail"])

    # 學期設定改為 3 → 同一格立刻放得下,訊息裡的數字也跟著變
    client.put(f"/api/solver/config?semester_id={sid}", json={
        "daily_subject_cap": 3, "teacher_daily_max": 6,
        "teacher_consecutive_max": 3, "weights": {}})
    assert place(day1[2]).status_code == 201

    blocked = place(day1[3])
    assert blocked.status_code == 409
    assert "每日上限 3 節" in str(blocked.json()["detail"])
