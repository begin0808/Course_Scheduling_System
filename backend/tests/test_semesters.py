"""學期與節次表測試。對應 M1-1 驗收標準。"""

from app.models.user import Role
from tests.conftest import make_user

PW = "password123"


def login(client, db, roles=(Role.scheduler,), username="s"):
    make_user(db, username, PW, roles=list(roles))
    resp = client.post("/api/auth/login", json={"username": username, "password": PW})
    assert resp.status_code == 200


def test_list_templates(env):
    client, db = env
    login(client, db)
    resp = client.get("/api/school-templates")
    assert resp.status_code == 200
    keys = {t["key"] for t in resp.json()}
    assert {"elementary", "junior_high", "senior_high", "comprehensive", "vocational"} <= keys


def test_create_semester_from_elementary_template(env):
    """驗收①:建立 115 學年第 1 學期,選國小範本自動帶入節次表(含週三下午空)。"""
    client, db = env
    login(client, db)
    resp = client.post(
        "/api/semesters",
        json={"academic_year": 115, "term": 1, "template_key": "elementary"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["label"] == "115 學年度第 1 學期"
    assert len(body["period_tables"]) == 1
    table = body["period_tables"][0]
    assert table["is_default"] is True

    # 週三(weekday=3)下午(第五~七節,period_no 7/8/9)應為 reserved(不排課)
    wed_pm = [
        p for p in table["periods"]
        if p["weekday"] == 3 and p["period_no"] in (7, 8, 9)
    ]
    assert len(wed_pm) == 3
    assert all(p["type"] == "reserved" for p in wed_pm)


def test_create_duplicate_semester_conflict(env):
    client, db = env
    login(client, db)
    payload = {"academic_year": 115, "term": 1}
    assert client.post("/api/semesters", json=payload).status_code == 201
    assert client.post("/api/semesters", json=payload).status_code == 409


def test_available_slots_reflects_type_change(env):
    """驗收②:將某格改為導師時間後,可排時段查詢即時反映(該格消失)。"""
    client, db = env
    login(client, db)
    sem = client.post(
        "/api/semesters",
        json={"academic_year": 115, "term": 1, "template_key": "junior_high"},
    ).json()
    table = sem["period_tables"][0]
    table_id = table["id"]

    before = client.get(f"/api/period-tables/{table_id}/available-slots").json()
    # 找週五(5)一個 regular 格位,改成 homeroom
    target = next(
        p for p in table["periods"]
        if p["weekday"] == 5 and p["type"] == "regular"
    )
    for p in table["periods"]:
        if p["id"] == target["id"]:
            p["type"] = "homeroom"
    payload = [
        {k: p[k] for k in ("weekday", "period_no", "name", "start_time", "end_time", "type")}
        for p in table["periods"]
    ]
    assert client.put(f"/api/period-tables/{table_id}/periods", json=payload).status_code == 200

    after = client.get(f"/api/period-tables/{table_id}/available-slots").json()
    assert len(after) == len(before) - 1
    assert not any(
        s["weekday"] == 5 and s["period_no"] == target["period_no"] for s in after
    )


def test_second_period_table_and_default_switch(env):
    """驗收③:同學期建第二套節次表,設為預設會取代原預設。"""
    client, db = env
    login(client, db)
    sem = client.post(
        "/api/semesters",
        json={"academic_year": 115, "term": 1, "template_key": "senior_high"},
    ).json()
    sid = sem["id"]
    first_table_id = sem["period_tables"][0]["id"]

    resp = client.post(
        f"/api/semesters/{sid}/period-tables",
        json={"name": "國中部節次表", "template_key": "junior_high", "is_default": True},
    )
    assert resp.status_code == 201

    full = client.get(f"/api/semesters/{sid}").json()
    assert len(full["period_tables"]) == 2
    defaults = [t for t in full["period_tables"] if t["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] != first_table_id


def test_update_semester_status(env):
    client, db = env
    login(client, db)
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    resp = client.patch(f"/api/semesters/{sem['id']}", json={"status": "active"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_delete_semester_cascades(env):
    client, db = env
    login(client, db)
    sem = client.post(
        "/api/semesters",
        json={"academic_year": 115, "term": 1, "template_key": "elementary"},
    ).json()
    assert client.delete(f"/api/semesters/{sem['id']}").status_code == 204
    assert client.get(f"/api/semesters/{sem['id']}").status_code == 404


def test_teacher_cannot_create_semester(env):
    client, db = env
    login(client, db, roles=(Role.teacher,), username="t")
    assert client.post("/api/semesters", json={"academic_year": 115, "term": 1}).status_code == 403


def test_replace_periods_rejects_duplicate_cell(env):
    client, db = env
    login(client, db)
    sem = client.post("/api/semesters", json={"academic_year": 115, "term": 1}).json()
    table = client.post(
        f"/api/semesters/{sem['id']}/period-tables", json={"name": "空表"}
    ).json()
    dup = [
        {"weekday": 1, "period_no": 1, "name": "第一節", "type": "regular"},
        {"weekday": 1, "period_no": 1, "name": "重複", "type": "regular"},
    ]
    assert client.put(f"/api/period-tables/{table['id']}/periods", json=dup).status_code == 400
