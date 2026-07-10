"""配課(M2-1)測試:單班/跑班/協同/連堂三種結構 + 五項驗收標準。"""

import io

import pytest
from openpyxl import Workbook

from app.api.imports import XLSX_MIME
from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


@pytest.fixture
def env2(env):
    """已登入教學組長 + 國中範本學期(含預設節次表與科目)。回傳 (client, sid)。"""
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sem = client.post(
        "/api/semesters", json={"academic_year": 115, "term": 1, "template_key": "junior_high"}
    ).json()
    return client, sem["id"]


def _subject(client, sid, name):
    return client.post(f"/api/subjects?semester_id={sid}", json={"name": name}).json()


def _teacher(client, sid, name, base=0):
    return client.post(
        f"/api/teachers?semester_id={sid}", json={"name": name, "base_periods": base}
    ).json()


def _class(client, sid, grade, name, track="junior_high", period_table_id=None):
    body = {"grade": grade, "name": name, "track": track}
    if period_table_id:
        body["period_table_id"] = period_table_id
    return client.post(f"/api/class-units?semester_id={sid}", json=body).json()


def _create_assignment(client, sid, **body):
    return client.post(f"/api/assignments?semester_id={sid}", json=body)


# ── 驗收① 單班 + 跑班群組 ──────────────
def test_single_assignment(env2):
    """301 班 × 國文 × 王師 × 每週 5 節。"""
    client, sid = env2
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "國文")
    t = _teacher(client, sid, "王師", 20)
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=5,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["scheduling_unit"]["unit_type"] == "single"
    assert a["scheduling_unit"]["classes"][0]["id"] == c["id"]
    assert a["periods_per_week"] == 5
    assert a["teachers"][0]["is_lead"] is True


def test_group_five_courses(env2):
    """高二多元選修跑班群組(3 班),群組內建 5 筆配課。"""
    client, sid = env2
    cids = [_class(client, sid, 2, f"20{i}", track="senior_high")["id"] for i in (1, 2, 3)]
    g = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "高二多元選修", "class_ids": cids},
    )
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    assert len(g.json()["classes"]) == 3
    for i in range(5):
        s = _subject(client, sid, f"選修{i}")
        t = _teacher(client, sid, f"選修師{i}")
        r = _create_assignment(
            client, sid, scheduling_unit_id=gid, subject_id=s["id"], periods_per_week=2,
            teachers=[{"teacher_id": t["id"]}],
        )
        assert r.status_code == 201, r.text
    items = client.get(f"/api/assignments?semester_id={sid}").json()
    group_items = [a for a in items if a["scheduling_unit"]["id"] == gid]
    assert len(group_items) == 5


# ── 驗收② 協同 + 連堂 ─────────────────
def test_coteaching_with_block(env2):
    """機械科實習 × 2 位協同教師 × 每週 6 節含 3 連堂×2。"""
    client, sid = env2
    c = _class(client, sid, 1, "機械一", track="vocational")
    s = _subject(client, sid, "機械實習")
    t1 = _teacher(client, sid, "師甲")
    t2 = _teacher(client, sid, "師乙")
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=6,
        teachers=[
            {"teacher_id": t1["id"], "is_lead": True},
            {"teacher_id": t2["id"], "is_lead": False},
        ],
        block_rules=[{"block_size": 3, "count_per_week": 2}],
    )
    assert r.status_code == 201, r.text
    a = r.json()
    assert len(a["teachers"]) == 2
    assert {t["name"] for t in a["teachers"]} == {"師甲", "師乙"}
    assert a["block_rules"][0]["block_size"] == 3
    assert a["block_rules"][0]["count_per_week"] == 2


# ── 驗收③ 教師超鐘點 ─────────────────
def test_teacher_over_hours(env2):
    """王師配 22 節、基本鐘點 20 → delta +2。"""
    client, sid = env2
    t = _teacher(client, sid, "王師", 20)
    c = _class(client, sid, 3, "301")
    s = _subject(client, sid, "國文")
    _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=22,
        teachers=[{"teacher_id": t["id"]}],
    )
    loads = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()
    wang = next(x for x in loads if x["teacher_id"] == t["id"])
    assert wang["assigned"] == 22
    assert wang["target"] == 20
    assert wang["delta"] == 2


def test_teacher_target_subtracts_admin_reduction(env2):
    """應授 = 基本鐘點 - 行政減課。"""
    client, sid = env2
    tr = client.post(
        f"/api/teachers?semester_id={sid}",
        json={"name": "組長", "base_periods": 20, "admin_reduction": 4},
    ).json()
    loads = client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()
    row = next(x for x in loads if x["teacher_id"] == tr["id"])
    assert row["target"] == 16
    assert row["assigned"] == 0
    assert row["delta"] == -16


# ── 驗收④ 班級配課超出可排節次 ────────
def test_class_over_capacity(env2):
    client, sid = env2
    c = _class(client, sid, 3, "305")
    s = _subject(client, sid, "國文")
    t = _teacher(client, sid, "師")
    # 先讀該班可排節次數(capacity)
    cl = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    cap = next(x for x in cl if x["class_id"] == c["id"])["capacity"]
    assert cap > 0
    over = min(cap + 1, 40)
    _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=over,
        teachers=[{"teacher_id": t["id"]}],
    )
    cl2 = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    row = next(x for x in cl2 if x["class_id"] == c["id"])
    assert row["assigned"] == over
    assert row["over_capacity"] is True


def test_class_load_counts_group_once(env2):
    """跑班群組的多門課同時段開課(H7),班級被佔用的是最長的一筆,不是全部相加。

    3 門 3 節的選修同時開,班級只被佔掉 3 節;若相加成 9 節,60 班規模的學校
    會滿頁誤報「超出可排節數」。
    """
    client, sid = env2
    classes = [_class(client, sid, 2, f"20{i}") for i in (1, 2)]
    gr = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "高二多元選修", "class_ids": [c["id"] for c in classes]},
    )
    assert gr.status_code == 201, gr.text
    group = gr.json()
    for name in ("選修甲", "選修乙", "選修丙"):
        s = _subject(client, sid, name)
        t = _teacher(client, sid, f"{name}師")
        r = _create_assignment(
            client, sid, scheduling_unit_id=group["id"], subject_id=s["id"],
            periods_per_week=3, teachers=[{"teacher_id": t["id"]}],
        )
        assert r.status_code == 201, r.text

    cl = client.get(f"/api/assignments/class-load?semester_id={sid}").json()
    for c in classes:
        row = next(x for x in cl if x["class_id"] == c["id"])
        assert row["assigned"] == 3, "跑班群組應計 3 節(同時段),而非 3 門 × 3 節 = 9"
        assert row["over_capacity"] is False


# ── 驗收⑤ 跑班群組節次表須一致 ────────
def test_group_requires_same_period_table(env2):
    client, sid = env2
    pt2 = client.post(
        f"/api/semesters/{sid}/period-tables",
        json={"name": "高中部節次表", "template_key": "senior_high"},
    ).json()
    ca = _class(client, sid, 2, "甲")  # 用學期預設表
    cb = _class(client, sid, 2, "乙", period_table_id=pt2["id"])  # 用另一套表
    r = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "跨表群組", "class_ids": [ca["id"], cb["id"]]},
    )
    assert r.status_code == 409


def test_group_same_table_ok(env2):
    client, sid = env2
    ca = _class(client, sid, 2, "甲")
    cb = _class(client, sid, 2, "乙")
    r = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "同表群組", "class_ids": [ca["id"], cb["id"]]},
    )
    assert r.status_code == 201


# ── 驗證與級聯 ────────────────────────
def test_block_total_exceeds_rejected(env2):
    client, sid = env2
    c = _class(client, sid, 1, "甲")
    s = _subject(client, sid, "數學")
    t = _teacher(client, sid, "師")
    r = _create_assignment(
        client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=4,
        teachers=[{"teacher_id": t["id"]}],
        block_rules=[{"block_size": 3, "count_per_week": 2}],  # 6 > 4
    )
    assert r.status_code == 422


def test_target_xor_required(env2):
    client, sid = env2
    c = _class(client, sid, 1, "甲")
    s = _subject(client, sid, "數學")
    t = _teacher(client, sid, "師")
    both = _create_assignment(
        client, sid, class_id=c["id"], scheduling_unit_id=1, subject_id=s["id"],
        periods_per_week=1, teachers=[{"teacher_id": t["id"]}],
    )
    assert both.status_code == 422
    neither = _create_assignment(
        client, sid, subject_id=s["id"], periods_per_week=1,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert neither.status_code == 422


def test_delete_group_cascades_assignments(env2):
    client, sid = env2
    cids = [_class(client, sid, 2, f"2{i}", track="senior_high")["id"] for i in (1, 2)]
    g = client.post(
        f"/api/scheduling-units?semester_id={sid}",
        json={"name": "群組X", "class_ids": cids},
    ).json()
    s = _subject(client, sid, "選修")
    t = _teacher(client, sid, "師")
    _create_assignment(
        client, sid, scheduling_unit_id=g["id"], subject_id=s["id"], periods_per_week=2,
        teachers=[{"teacher_id": t["id"]}],
    )
    assert client.delete(f"/api/scheduling-units/{g['id']}").status_code == 204
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []


def test_single_unit_reused_across_assignments(env2):
    """同班多科配課共用同一 single 排課單位。"""
    client, sid = env2
    c = _class(client, sid, 3, "301")
    t = _teacher(client, sid, "師")
    ids = set()
    for name in ("國文", "數學"):
        s = _subject(client, sid, name)
        a = _create_assignment(
            client, sid, class_id=c["id"], subject_id=s["id"], periods_per_week=3,
            teachers=[{"teacher_id": t["id"]}],
        ).json()
        ids.add(a["scheduling_unit"]["id"])
    assert len(ids) == 1


# ── Excel 匯入 ────────────────────────
def _xlsx(rows, ncols=7):
    wb = Workbook()
    ws = wb.active
    for _ in range(3):
        ws.append(["表頭"] * ncols)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_assignments(env2):
    client, sid = env2
    _class(client, sid, 3, "301")
    _subject(client, sid, "國文")
    _teacher(client, sid, "王師")
    _teacher(client, sid, "李協")
    rows = [["301", "國文", "王師、李協", 6, 3, 2, ""]]
    r = client.post(
        f"/api/import/assignments?semester_id={sid}",
        files={"file": ("a.xlsx", _xlsx(rows), XLSX_MIME)},
    )
    assert r.json() == {"imported": 1, "errors": []}
    items = client.get(f"/api/assignments?semester_id={sid}").json()
    assert len(items) == 1
    a = items[0]
    assert len(a["teachers"]) == 2
    assert a["teachers"][0]["is_lead"] is True  # 王師為主教
    assert a["block_rules"][0]["block_size"] == 3


def test_import_assignments_unknown_class_zero_write(env2):
    client, sid = env2
    _subject(client, sid, "國文")
    _teacher(client, sid, "王師")
    rows = [["不存在班", "國文", "王師", 5, "", "", ""]]
    body = client.post(
        f"/api/import/assignments?semester_id={sid}",
        files={"file": ("a.xlsx", _xlsx(rows), XLSX_MIME)},
    ).json()
    assert body["imported"] == 0
    assert any("班級" in e for e in body["errors"])
    assert client.get(f"/api/assignments?semester_id={sid}").json() == []
