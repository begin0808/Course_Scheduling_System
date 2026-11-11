"""調課後重新發布課表,補課那一節要接到新課表(v1.4.18,LINE 社群組長回報)。

組長把週四第五節和週三第六節對調,之後又改課表重新發布:週課表只有週四那格變紅,
週三補課那格變回原本的課。原因是調課記的是「舊課表的哪一格」,新課表每一格都是新的。
連帶:老師本人的週課表少了補課那一節,調課清單也以為那一節還能再拿去調。
"""

import importlib.util
from datetime import timedelta
from pathlib import Path

from app.models.substitution import Substitution
from app.models.timetable import ScheduleEntry
from tests.dates import WED
from tests.test_substitutions import _options
from tests.test_timetable_week import _at, _week, w  # noqa: F401 - w 為 fixture

THU = WED + timedelta(days=1)
FRI = WED + timedelta(days=2)


def _world(world):
    """王師週四第五節 701 國文請假;林師週三第六節在 701 上輔導。"""
    world.teacher("王師", ["國文"])
    world.teacher("林師", ["輔導"])
    world.place("王師", "國文", "701", 4, weekday=4)
    world.place("林師", "輔導", "701", 5, weekday=3)
    world.publish()
    aid = world.leave("王師", THU)[0]["id"]
    opt = next(o for o in _options(world, aid, "林師")["partners"][0]["options"]
               if o["date"] == WED.isoformat())
    code, body = world.assign(aid, type="swap", handler_teacher_id=world.teachers["林師"],
                          swap_entry_id=opt["entry_id"], swap_date=opt["date"],
                          swap_period_no=opt["period_no"])
    assert code == 200, body
    return aid


def _republish(world, move: tuple[int, int] | None = None) -> dict:
    """複製目前的課表成新草稿再發布;move=(weekday, period_no) 時先把林師的輔導搬走。"""
    new = world.client.post(f"/api/timetables/{world.tt}/duplicate", json={"name": "草稿B"}).json()
    if move is not None:
        e = next(x for x in new["entries"] if x["weekday"] == 3)
        r = world.client.patch(f"/api/timetables/{new['id']}/entries/{e['id']}",
                           json={"weekday": move[0], "period_no": move[1]})
        assert r.status_code == 200, r.json()
    r = world.client.post(f"/api/timetables/{new['id']}/publish?force=true")
    assert r.status_code == 200, r.json()
    world.tt = new["id"]
    return r.json()


def _swap_entry(world) -> ScheduleEntry:
    world.db.expire_all()
    sub = world.db.query(Substitution).filter(Substitution.type == "swap").one()
    return world.db.get(ScheduleEntry, sub.swap_entry_id)


def test_republish_keeps_the_makeup_period(w):  # noqa: F811
    _world(w)
    out = _republish(w)
    assert out["swap_unlinked"] == 0
    assert _swap_entry(w).timetable_id == w.tt, "補課那一節接到新課表的格子"

    cls = _week(w, "class", w.classes["701"]).json()
    assert _at(cls, THU, 5)[0][2] == "swap"
    assert _at(cls, WED, 6)[0][:3] == ("國文", "王師", "swap"), "補課那格照樣變紅"
    wang = _week(w, "teacher", w.teachers["王師"]).json()
    assert _at(wang, WED, 6)[0][2] == "swap", "老師本人的週課表看得到補課那一節"


def test_republish_does_not_offer_the_same_period_again(w):  # noqa: F811
    """重新發布後,林師週三第六節已經換給王師補課,不能再換給別人。"""
    _world(w)
    _republish(w)
    w.teacher("張師", ["英文"])
    # 張師週五 701 英文請假:林師週三那一節不能再拿來對調
    new = w.client.post(f"/api/timetables/{w.tt}/duplicate", json={"name": "草稿C"}).json()
    w.tt = new["id"]
    w.place("張師", "英文", "701", 0, weekday=5)
    r = w.client.post(f"/api/timetables/{w.tt}/publish?force=true")
    assert r.status_code == 200, r.json()
    aid = w.leave("張師", FRI)[0]["id"]
    partners = _options(w, aid, "林師")["partners"]
    offered = [o["date"] for p in partners for o in p["options"]]
    assert WED.isoformat() not in offered


def test_moved_lesson_is_reported(w):  # noqa: F811
    """新課表把林師的輔導搬走了:補課那一節已經沒有這堂課,接不上,發布後回報筆數。"""
    _world(w)
    slots = [p for p in w.client.get(
        f"/api/class-units/{w.classes['701']}/period-table").json()["periods"]
        if p["weekday"] == 2 and p["type"] == "regular"]
    out = _republish(w, move=(2, slots[0]["period_no"]))
    assert out["swap_unlinked"] == 1
    assert _swap_entry(w).timetable_id != w.tt, "不猜,維持原樣"


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0020_relink_swaps.py"
    spec = importlib.util.spec_from_file_location("m0020", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_upgrade_relinks_swaps_made_before_v1418(w):  # noqa: F811
    """升級前就已經發生的:調課還指著舊課表的格子,升級後接回目前的課表。"""
    _world(w)
    old_entry = _swap_entry(w)
    _republish(w)
    # 模擬 v1.4.17 以前:發布時沒有接過去
    sub = w.db.query(Substitution).filter(Substitution.type == "swap").one()
    sub.swap_entry_id = old_entry.id
    w.db.commit()
    assert _at(_week(w, "class", w.classes["701"]).json(), WED, 6)[0][2] == "normal"

    assert _migration().relink(w.db.connection()) == 1
    w.db.commit()
    assert _swap_entry(w).timetable_id == w.tt
    assert _at(_week(w, "class", w.classes["701"]).json(), WED, 6)[0][2] == "swap"
    assert _migration().relink(w.db.connection()) == 0, "再跑一次不會重複改"
