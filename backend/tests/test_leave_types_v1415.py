"""v1.4.15 新增假別(老師建議加身心調適假;使用者定案:常用的一起加,太細少見的選「其他」)。"""

from tests.dates import WED
from tests.test_m4_hardening import w  # noqa: F401 - w 為 fixture


def test_leave_types_in_order_with_common_ones(w):  # noqa: F811
    types = w.client.get("/api/leave-types").json()
    assert list(types.values()) == [
        "公假", "事假", "病假", "身心調適假", "家庭照顧假", "生理假", "休假", "補休",
        "婚假", "喪假", "產前假(產檢假)", "產假", "陪產檢及陪產假", "公傷假", "進修", "其他",
    ]
    assert all(len(k) <= 20 for k in types), "leave_type 欄位長度 20"


def _setup(world):
    world.teacher("王師", ["國文"])
    world.teacher("陳師", ["國文"])
    world.place("王師", "國文", "701", 0)
    world.publish()


def _post(world, leave_type, reason=""):
    return world.client.post(f"/api/leaves{world.q}", json={
        "teacher_id": world.teachers["王師"], "leave_type": leave_type, "reason": reason,
        "start_date": WED.isoformat(), "end_date": WED.isoformat()})


def test_new_type_registers_and_family_care_defaults_to_self_paid(w):  # noqa: F811
    _setup(w)
    r = _post(w, "family_care")
    assert r.status_code == 201, r.json()
    assert r.json()["leave_type_label"] == "家庭照顧假"
    ap = r.json()["affected_periods"][0]
    code, body = w.assign(ap["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 200, body
    leave = w.client.get(f"/api/leaves{w.q}").json()[0]
    assert leave["affected_periods"][0]["funding_source"] == "自費代課", "併入事假計算"


def test_mental_health_leave_is_paid_by_school(w):  # noqa: F811
    _setup(w)
    r = _post(w, "mental_health")
    assert r.status_code == 201, r.json()
    ap = r.json()["affected_periods"][0]
    w.assign(ap["id"], type="substitute", handler_teacher_id=w.teachers["陳師"])
    leave = w.client.get(f"/api/leaves{w.q}").json()[0]
    assert leave["leave_type_label"] == "身心調適假"
    assert leave["affected_periods"][0]["funding_source"] == "公費代課"


def test_other_needs_a_reason(w):  # noqa: F811
    _setup(w)
    r = _post(w, "other", "  ")
    assert r.status_code == 400 and "事由" in r.json()["detail"]
    r = _post(w, "other", "捐贈骨髓假")
    assert r.status_code == 201, r.json()
    lid = r.json()["id"]
    # 改成「其他」或把事由清空,也一樣要寫事由
    assert w.client.patch(f"/api/leaves/{lid}", json={"reason": ""}).status_code == 400
    r2 = _post(w, "sick")
    assert r2.status_code == 201
    r = w.client.patch(f"/api/leaves/{r2.json()['id']}", json={"leave_type": "other"})
    assert r.status_code == 400
    r = w.client.patch(f"/api/leaves/{r2.json()['id']}",
                       json={"leave_type": "other", "reason": "原住民歲時祭儀假"})
    assert r.status_code == 200 and r.json()["leave_type_label"] == "其他"
