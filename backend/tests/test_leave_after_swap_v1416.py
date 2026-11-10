"""先調課、再請假(v1.4.16,LINE 社群組長回報)。

導師那天要外出一整天:組長先用「新增調課(未請假)」把他當天的課調走,
再登記請假讓系統排代導。原本請假又依固定課表把那幾節列成「待處理」——
已經調走的課,再調一次、選停課都不對,待處理就一直掛著。

規則:同一節不能處理兩次。已經在別張有效假單或調課裡的節次,登記請假時不再列入,
回傳在 `skipped` 讓畫面說明;代導照常產生(導師人不在)。
"""

from tests.dates import WED, WED2
from tests.test_homeroom_cover import _homeroom, _leave
from tests.test_substitutions import _find_entry, env2  # noqa: F401 - env2 為 fixture
from tests.test_swap_without_leave import _create, _school


def _swap_first(w) -> dict:
    """王師週三兩節都放進「調課(未請假)」,第一節和陳師對調。"""
    code, req = _create(w, [w.wed[0]["period_no"], w.wed[1]["period_no"]])
    assert code == 201, req
    ap = req["affected_periods"][0]
    code, body = w.assign(ap["id"], type="swap", handler_teacher_id=w.teachers["陳師"],
                          swap_entry_id=_find_entry(w, "陳師"), swap_date=WED2.isoformat())
    assert code == 200, body
    return req


def test_leave_skips_periods_already_swapped(env2):  # noqa: F811
    w = env2
    _school(w)
    _homeroom(w, "701", "王師")
    _swap_first(w)

    leave = _leave(w, "王師", WED)
    assert leave["affected_periods"] == [], "兩節都已在調課裡,不再列成待處理"
    assert leave["pending_count"] == 0
    assert [(s["period_name"], s["taken_by"]) for s in leave["skipped"]] == [
        (w.wed[0]["name"], "調課(未請假)"), (w.wed[1]["name"], "調課(未請假)")]
    assert len(leave["homeroom_covers"]) == 1, "導師人不在,照樣要代導"

    # 之後再讀假單,不再帶 skipped(只有登記當下回傳)
    again = w.client.get(f"/api/leaves/{leave['id']}").json()
    assert again["skipped"] == [] and again["affected_count"] == 0


def test_leave_keeps_periods_not_yet_handled(env2):  # noqa: F811
    """只調走第一節:請假只列第二節。"""
    w = env2
    _school(w)
    code, req = _create(w, [w.wed[0]["period_no"]])
    assert code == 201, req

    leave = _leave(w, "王師", WED)
    assert [p["period_name"] for p in leave["affected_periods"]] == [w.wed[1]["name"]]
    assert [s["period_name"] for s in leave["skipped"]] == [w.wed[0]["name"]]


def test_second_leave_on_same_day_does_not_duplicate(env2):  # noqa: F811
    """同一天重複登記兩張假:第二張不再重複列出同樣的節次。"""
    w = env2
    _school(w)
    first = _leave(w, "王師", WED)
    assert len(first["affected_periods"]) == 2 and first["skipped"] == []
    second = _leave(w, "王師", WED)
    assert second["affected_periods"] == []
    assert {s["taken_by"] for s in second["skipped"]} == {"事假"}


def test_cancelled_swap_no_longer_blocks(env2):  # noqa: F811
    """調課已銷假,那兩節回到王師身上:請假照常列入。"""
    w = env2
    _school(w)
    req = _swap_first(w)
    assert w.client.post(f"/api/leaves/{req['id']}/cancel").status_code == 200

    leave = _leave(w, "王師", WED)
    assert len(leave["affected_periods"]) == 2 and leave["skipped"] == []


def test_other_teachers_and_days_unaffected(env2):  # noqa: F811
    """只看同一位老師、同一天的節次。"""
    w = env2
    _school(w)
    _swap_first(w)
    chen = _leave(w, "陳師", WED)
    assert len(chen["affected_periods"]) == 1 and chen["skipped"] == []
    next_week = _leave(w, "王師", WED2)
    assert len(next_week["affected_periods"]) == 2 and next_week["skipped"] == []
