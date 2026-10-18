"""單雙週課程(v1.3.0)。

使用者定案的典型情境:兩位老師各上一科、兩班交叉對開——
701 週一兩節連堂:單週生科(甲師)、雙週資科(乙師);702 同一時段反過來。
甲師單週在 701、雙週在 702,每週都上,但從不衝堂。

規則:學期第一週是單週,之後固定輪流;隔週的課鐘點算一半。
"""

import pytest

from app.core.week_parity import fmt_periods, overlaps, runs_in_week, week_parity
from app.services.solver_data import load_problem
from app.solver import preflight
from app.solver.model_builder import SolveOptions, solve
from app.solver.problem import SolverConfig
from app.solver.validator import validate
from tests.test_timetables import (
    _assign,
    _check,
    _class,
    _codes,
    _entries,
    _place,
    _subject,
    _teacher,
    env2,  # noqa: F401  (fixture)
)


# ── 單週/雙週的判定 ────────────────────
def test_first_week_of_the_semester_is_odd_and_weeks_alternate():
    from datetime import date

    start = date(2026, 9, 2)  # 週三開學:那一週(8/31 起)仍是第 1 週
    assert week_parity(start, date(2026, 8, 31)) == "odd"
    assert week_parity(start, date(2026, 9, 6)) == "odd"
    assert week_parity(start, date(2026, 9, 7)) == "even"
    assert week_parity(start, date(2026, 9, 14)) == "odd"
    assert week_parity(start, date(2026, 12, 28)) == "even"  # 第 18 週
    assert week_parity(start, date(2027, 1, 4)) == "odd"     # 第 19 週
    assert week_parity(None, date(2026, 9, 7)) is None


def test_parity_helpers():
    assert overlaps(None, "odd") and overlaps("odd", "odd") and not overlaps("odd", "even")
    assert runs_in_week(None, "even") and runs_in_week("odd", None)
    assert runs_in_week("odd", "odd") and not runs_in_week("odd", "even")
    assert fmt_periods(2.0) == "2" and fmt_periods(1.5) == "1.5"


# ── 建立單雙週組與配課 ──────────────────
def _alt(client, sid, class_id, name=None):
    body = {"class_id": class_id} | ({"name": name} if name else {})
    r = client.post(f"/api/alternate-units?semester_id={sid}", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _alt_assign(client, sid, unit_id, subject_id, teacher_id, week, periods=2, blocks=None):
    r = client.post(f"/api/assignments?semester_id={sid}", json={
        "scheduling_unit_id": unit_id, "subject_id": subject_id, "periods_per_week": periods,
        "teachers": [{"teacher_id": teacher_id, "is_lead": True}],
        "block_rules": blocks if blocks is not None else [{"block_size": 2, "count_per_week": 1}],
        "week_parity": week,
    })
    return r


@pytest.fixture
def crossed(env2):  # noqa: F811
    """701/702 交叉對開:甲師教生科、乙師教資科,各 2 節連堂。"""
    client, sid, tid, _ = env2
    c1 = _class(client, sid, 1, "701")["id"]
    c2 = _class(client, sid, 1, "702")["id"]
    tech, info = _subject(client, sid, "生科")["id"], _subject(client, sid, "資科")["id"]
    jia, yi = _teacher(client, sid, "甲師")["id"], _teacher(client, sid, "乙師")["id"]
    u1, u2 = _alt(client, sid, c1), _alt(client, sid, c2)
    a = {
        ("701", "odd"): _alt_assign(client, sid, u1["id"], tech, jia, "odd").json(),
        ("701", "even"): _alt_assign(client, sid, u1["id"], info, yi, "even").json(),
        ("702", "odd"): _alt_assign(client, sid, u2["id"], info, yi, "odd").json(),
        ("702", "even"): _alt_assign(client, sid, u2["id"], tech, jia, "even").json(),
    }
    return {"client": client, "sid": sid, "tid": tid, "c1": c1, "c2": c2, "u1": u1, "u2": u2,
            "tech": tech, "info": info, "jia": jia, "yi": yi, "a": a}


def test_alternate_unit_defaults_its_name_and_lists_separately(crossed):
    client, sid = crossed["client"], crossed["sid"]
    assert crossed["u1"]["name"] == "701 單雙週" and crossed["u1"]["unit_type"] == "alternate"
    again = _alt(client, sid, crossed["c1"])
    assert again["name"] == "701 單雙週 2"  # 同一班可以有好幾組
    names = [u["name"] for u in client.get(f"/api/alternate-units?semester_id={sid}").json()]
    assert names == ["701 單雙週", "701 單雙週 2", "702 單雙週"]
    # 跑班群組清單不會混進單雙週組
    assert client.get(f"/api/scheduling-units?semester_id={sid}").json() == []
    assert client.delete(f"/api/scheduling-units/{again['id']}").status_code == 204


def test_week_parity_rules_on_assignments(crossed):
    client, sid = crossed["client"], crossed["sid"]
    a = crossed["a"][("701", "odd")]
    assert a["week_parity"] == "odd"
    # 同一組已經有單週的課
    r = _alt_assign(client, sid, crossed["u1"]["id"], crossed["info"], crossed["yi"], "odd")
    assert r.status_code == 409 and "已經有單週的課" in r.json()["detail"]
    # 單雙週組的配課一定要選週別
    r = _alt_assign(client, sid, crossed["u1"]["id"], crossed["info"], crossed["yi"], None)
    assert r.status_code == 400 and "單週或雙週" in r.json()["detail"]
    # 一般配課不可以設週別
    r = client.post(f"/api/assignments?semester_id={sid}", json={
        "class_id": crossed["c1"], "subject_id": crossed["tech"], "periods_per_week": 1,
        "teachers": [{"teacher_id": crossed["jia"]}], "block_rules": [], "week_parity": "odd"})
    assert r.status_code == 400 and "只有單雙週組" in r.json()["detail"]
    # 修改自己(週別不變)不算重複
    r = client.patch(f"/api/assignments/{a['id']}", json={
        "scheduling_unit_id": crossed["u1"]["id"], "subject_id": crossed["tech"],
        "periods_per_week": 2, "teachers": [{"teacher_id": crossed["jia"], "is_lead": True}],
        "block_rules": [{"block_size": 2, "count_per_week": 1}], "week_parity": "odd"})
    assert r.status_code == 200, r.text


def test_teacher_load_counts_alternate_lessons_as_half(crossed):
    """甲師單週 701、雙週 702 各 2 節 → 每週都上 2 節;只有單週那筆的老師算 1 節。"""
    client, sid = crossed["client"], crossed["sid"]
    c3 = _class(client, sid, 1, "703")["id"]
    bing = _teacher(client, sid, "丙師")["id"]
    u3 = _alt(client, sid, c3)
    _alt_assign(client, sid, u3["id"], crossed["tech"], bing, "odd")
    loads = {x["name"]: x["assigned"]
             for x in client.get(f"/api/assignments/teacher-load?semester_id={sid}").json()}
    assert loads["甲師"] == 2 and loads["乙師"] == 2 and loads["丙師"] == 1
    # 班級每週只被占 2 節(單週、雙週同一格)
    cl = {x["name"]: x["assigned"]
          for x in client.get(f"/api/assignments/class-load?semester_id={sid}").json()}
    assert cl["701"] == 2


# ── 手動排課 ──────────────────────────
def test_placing_a_pair_puts_both_weeks_in_the_same_block(crossed):
    client, tid = crossed["client"], crossed["tid"]
    a = crossed["a"]
    r = _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2)
    assert r.status_code == 201, r.text
    ents = _entries(client, tid)
    assert len(ents) == 2
    assert {(e["weekday"], e["period_no"], e["span"]) for e in ents} == {(1, 1, 2)}
    assert sorted(e["week_parity"] for e in ents) == ["even", "odd"]


def test_crossed_pairs_share_a_slot_without_clashing(crossed):
    """甲師單週在 701、雙週在 702:同一節不算衝堂。"""
    client, tid, a = crossed["client"], crossed["tid"], crossed["a"]
    assert _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2).status_code == 201
    r = _place(client, tid, a[("702", "odd")]["id"], 1, 1, span=2)
    assert r.status_code == 201, r.text
    assert len(_entries(client, tid)) == 4


def test_same_week_clash_is_still_caught(crossed):
    """703 單週也排甲師同一節 → 甲師單週同時在 701 和 703,要擋。"""
    client, sid, tid, a = crossed["client"], crossed["sid"], crossed["tid"], crossed["a"]
    c3 = _class(client, sid, 1, "703")["id"]
    u3 = _alt(client, sid, c3)
    odd3 = _alt_assign(client, sid, u3["id"], crossed["tech"], crossed["jia"], "odd").json()
    ding = _teacher(client, sid, "丁師")["id"]
    _alt_assign(client, sid, u3["id"], crossed["info"], ding, "even")
    assert _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2).status_code == 201

    codes = _codes(_check(client, tid, odd3["id"], 1, 1, span=2))
    assert "H2" in codes
    r = _place(client, tid, odd3["id"], 1, 1, span=2)
    assert r.status_code == 409 and "甲師" in r.text and "單週" in r.text


def test_every_week_lesson_clashes_with_both_weeks(crossed):
    """甲師每週都有的課,不能排在他單週有課的那一節。"""
    client, sid, tid, a = crossed["client"], crossed["sid"], crossed["tid"], crossed["a"]
    assert _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2).status_code == 201
    c4 = _class(client, sid, 1, "704")["id"]
    reg = _assign(client, sid, class_id=c4, subject_id=crossed["tech"],
                  teacher_ids=[crossed["jia"]], periods=1)
    assert "H2" in _codes(_check(client, tid, reg["id"], 1, 2))


def test_class_slot_is_full_in_both_weeks(crossed):
    """單雙週組占滿那一格:同班的其他課不能再放進來。"""
    client, sid, tid, a = crossed["client"], crossed["sid"], crossed["tid"], crossed["a"]
    assert _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2).status_code == 201
    chinese = _subject(client, sid, "國文")["id"]
    wu = _teacher(client, sid, "戊師")["id"]
    other = _assign(client, sid, class_id=crossed["c1"], subject_id=chinese,
                    teacher_ids=[wu], periods=1)
    assert "H1" in _codes(_check(client, tid, other["id"], 1, 1))


def test_moving_and_deleting_the_pair_moves_both(crossed):
    client, tid, a = crossed["client"], crossed["tid"], crossed["a"]
    assert _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2).status_code == 201
    one = _entries(client, tid)[0]
    r = client.patch(f"/api/timetables/{tid}/entries/{one['id']}",
                     json={"weekday": 2, "period_no": 2})
    assert r.status_code == 200, r.text
    assert {(e["weekday"], e["period_no"]) for e in _entries(client, tid)} == {(2, 2)}
    assert client.delete(f"/api/timetables/{tid}/entries/{one['id']}").status_code == 204
    assert _entries(client, tid) == []


# ── 自動排課與檢查 ────────────────────
def test_preflight_requires_both_weeks(env2):  # noqa: F811
    client, sid, _tid, _ = env2
    c1 = _class(client, sid, 1, "701")["id"]
    u = _alt(client, sid, c1)
    _alt_assign(client, sid, u["id"], _subject(client, sid, "生科")["id"],
                _teacher(client, sid, "甲師")["id"], "odd")
    r = client.get(f"/api/solver/preflight?semester_id={sid}").json()
    issue = next(i for i in r["issues"] if i["code"] == "alternate_incomplete")
    assert "701 單雙週" in issue["message"] and "還缺雙週的課" in issue["message"]


def test_solver_places_crossed_pairs_and_validator_accepts(crossed, env):
    """自動排課:兩組各自同格,甲師、乙師同一週不衝堂;檢查器零違規。"""
    problem = load_problem(env[1], crossed["sid"])
    assert preflight.run(problem).ok, [i.message for i in preflight.run(problem).errors]
    result = solve(problem, SolveOptions(max_seconds=30.0, workers=4, random_seed=1),
                   config=SolverConfig.hard_only())
    assert result.solved
    assert not validate(problem, result.entries)
    slots = {}
    for e in result.entries:
        slots.setdefault(e.assignment_id, set()).add((e.weekday, e.period_no, e.span))
    a = crossed["a"]
    assert slots[a[("701", "odd")]["id"]] == slots[a[("701", "even")]["id"]]
    assert slots[a[("702", "odd")]["id"]] == slots[a[("702", "even")]["id"]]


def test_solver_keeps_same_week_teacher_apart(env2, env):  # noqa: F811
    """甲師單週在 701 與 703 都有課:自動排課不能把兩組排在同一節。"""
    client, sid, _tid, _ = env2
    tech, info = _subject(client, sid, "生科")["id"], _subject(client, sid, "資科")["id"]
    jia = _teacher(client, sid, "甲師")["id"]
    others = [_teacher(client, sid, n)["id"] for n in ("乙師", "丙師")]
    for i, name in enumerate(("701", "703")):
        u = _alt(client, sid, _class(client, sid, 1, name)["id"])
        _alt_assign(client, sid, u["id"], tech, jia, "odd", periods=1, blocks=[])
        _alt_assign(client, sid, u["id"], info, others[i], "even", periods=1, blocks=[])
    problem = load_problem(env[1], sid)
    result = solve(problem, SolveOptions(max_seconds=30.0, workers=4, random_seed=1),
                   config=SolverConfig.hard_only())
    assert result.solved and not validate(problem, result.entries)
    by_id = {a.id: a for a in problem.assignments}
    jia_slots = [(e.weekday, e.period_no) for e in result.entries
                 if jia in by_id[e.assignment_id].teacher_ids]
    assert len(jia_slots) == len(set(jia_slots)) == 2


def test_timetable_check_accepts_a_crossed_timetable(crossed):
    client, tid, a = crossed["client"], crossed["tid"], crossed["a"]
    _place(client, tid, a[("701", "odd")]["id"], 1, 1, span=2)
    _place(client, tid, a[("702", "odd")]["id"], 1, 1, span=2)
    r = client.get(f"/api/timetables/{tid}/check").json()
    assert r["issues"] == [] and r["completeness"]["complete"] is True


# ── 跟日期有關的部分:請假、代課、調課、巡堂表、匯出 ─────────────
class _Term:
    """有起訖日期的學期(請假要用),課表已發布:

    週三第一節 701/702 交叉對開——甲師單週 701 生科、雙週 702 生科;
    乙師單週 702 資科、雙週 701 資科。
    週三第二節 703(年級奇數班落單)——丁師單週生科、戊師雙週美術。丙師整天空堂。
    """

    def __init__(self, client, db):
        from app.models.user import Role
        from tests.conftest import make_user
        from tests.dates import SEM_END, SEM_START

        make_user(db, "s", "password123", roles=[Role.scheduler])
        client.post("/api/auth/login", json={"username": "s", "password": "password123"})
        self.client, self.db, self.sem_start = client, db, SEM_START
        self.sid = client.post("/api/semesters", json={
            "academic_year": 115, "term": 1, "template_key": "junior_high",
            "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
        }).json()["id"]
        self.q = q = f"?semester_id={self.sid}"

        def post(url, body):
            r = client.post(url, json=body)
            assert r.status_code == 201, r.text
            return r.json()["id"]

        tech, info, art = (post(f"/api/subjects{q}", {"name": n}) for n in ("生科", "資科", "美術"))
        self.t = {n: post(f"/api/teachers{q}", {"name": n})
                  for n in ("甲師", "乙師", "丙師", "丁師", "戊師")}
        self.c = {n: post(f"/api/class-units{q}", {"grade": 7, "name": n, "track": "junior_high"})
                  for n in ("701", "702", "703")}
        self.tt = post(f"/api/timetables{q}", {"name": "草稿A"})
        periods = client.get(f"/api/class-units/{self.c['701']}/period-table").json()["periods"]
        wed = [p for p in periods if p["weekday"] == 3 and p["type"] == "regular"]
        self.first, self.second = wed[0], wed[1]

        plan = {
            "701": (("odd", tech, "甲師"), ("even", info, "乙師"), self.first),
            "702": (("odd", info, "乙師"), ("even", tech, "甲師"), self.first),
            "703": (("odd", tech, "丁師"), ("even", art, "戊師"), self.second),
        }
        self.a: dict[tuple[str, str], int] = {}
        for cls, (odd, even, period) in plan.items():
            u = _alt(client, self.sid, self.c[cls])
            for week, s, t in (odd, even):
                r = _alt_assign(client, self.sid, u["id"], s, self.t[t], week,
                                periods=1, blocks=[])
                assert r.status_code == 201, r.text
                self.a[(cls, week)] = r.json()["id"]
            r = _place(client, self.tt, self.a[(cls, "odd")], 3, period["period_no"])
            assert r.status_code == 201, r.text
        assert client.post(f"/api/timetables/{self.tt}/publish").status_code == 200

    def week(self, day):
        return week_parity(self.sem_start, day)

    def days(self):
        """(單週的週三, 雙週的週三)。"""
        from tests.dates import WED, WED2

        return (WED, WED2) if self.week(WED) == "odd" else (WED2, WED)

    def leave(self, teacher, day):
        r = self.client.post(f"/api/leaves{self.q}", json={
            "teacher_id": self.t[teacher], "leave_type": "sick",
            "start_date": day.isoformat(), "end_date": day.isoformat()})
        assert r.status_code == 201, r.text
        return r.json()["affected_periods"]


@pytest.fixture
def term(env):
    return _Term(*env)


def test_leave_only_lists_the_lessons_of_that_week(term):
    """甲師請週三:單週那天缺的是 701,雙週那天缺的是 702——不會兩班都列。"""
    odd_day, even_day = term.days()
    assert [(p["class_names"], p["subject_name"]) for p in term.leave("甲師", odd_day)] == [
        ("701", "生科")]
    assert [(p["class_names"], p["subject_name"]) for p in term.leave("甲師", even_day)] == [
        ("702", "生科")]
    # 丁師只有單週的課:雙週那天請假,沒有任何一節受影響
    assert term.leave("丁師", even_day) == []


def test_teacher_with_only_one_week_is_free_in_the_other(term):
    """丁師只有 703 單週那一節:雙週同一時段他有空;戊師正好相反。"""
    from app.services.availability import Availability, Interval

    odd_day, even_day = term.days()
    av = Availability(term.db, term.sid)
    slot = Interval(3, term.second["period_no"], None, None)
    assert av.conflict_for(term.t["丁師"], odd_day, slot) is not None
    assert av.conflict_for(term.t["丁師"], even_day, slot) is None
    assert av.conflict_for(term.t["戊師"], odd_day, slot) is None
    assert av.conflict_for(term.t["戊師"], even_day, slot) is not None


def test_substitute_recommendation_respects_the_week(term):
    """乙師請假(第一節):甲師同一節兩週都在上課,不會被推薦;丙師空堂會。"""
    odd_day, _even_day = term.days()
    ap = term.leave("乙師", odd_day)[0]
    rec = term.client.get(f"/api/affected-periods/{ap['id']}/recommendations").json()
    names = {c["teacher_name"] for c in rec["candidates"]}
    assert "甲師" not in names and "丙師" in names


def test_patrol_sheet_shows_the_lesson_of_that_week(term):
    odd_day, even_day = term.days()
    expected = {odd_day: ("生科", "甲師"), even_day: ("資科", "乙師")}
    for day, want in expected.items():
        sheets = term.client.get(f"/api/patrol-sheets{term.q}&date_from={day.isoformat()}").json()
        page = sheets["pages"][0]
        col = page["classes"].index("701")
        row = next(r for r in page["rows"] if r["ordinal"] == 1)
        assert (row["cells"][col]["subject"], row["cells"][col]["teacher"]) == want


def test_exported_timetables_show_both_weeks(term):
    from app.models.basedata import ClassUnit, Teacher
    from app.services.timetable_export import _Published, class_grid, teacher_grid

    pub = _Published(term.db, term.sid)
    grid = class_grid(pub, term.db.get(ClassUnit, term.c["701"]))
    assert ("單 生科 甲師", "雙 資科 乙師") in [c.lines for r in grid.rows for c in r.cells]
    # 甲師的課表:同一格單週 701、雙週 702
    tg = teacher_grid(pub, term.db.get(Teacher, term.t["甲師"]))
    assert ("單 生科 701", "雙 生科 702") in [c.lines for r in tg.rows for c in r.cells]


def test_swap_needs_the_partner_lesson_to_run_that_week(term):
    """調課:對方那堂課要在補課那一週真的有上,否則擋下並說明。"""
    odd_day, even_day = term.days()
    ap = term.leave("甲師", odd_day)[0]
    entries = term.client.get(f"/api/timetables/{term.tt}").json()["entries"]
    ding = next(e for e in entries if "丁師" in e["teachers"])  # 丁師只有單週那堂
    r = term.client.put(f"/api/affected-periods/{ap['id']}/substitution", json={
        "type": "swap", "handler_teacher_id": term.t["丁師"],
        "swap_entry_id": ding["id"], "swap_date": even_day.isoformat()})
    assert r.status_code == 409 and "那一週沒有這堂課" in r.json()["detail"]
    # 可對調清單也不會列出雙週那天
    opts = term.client.get(
        f"/api/affected-periods/{ap['id']}/swap-options?teacher_id={term.t['丁師']}&weeks=3").json()
    dates = {o["date"] for p in opts["partners"] for o in p["options"]}
    assert even_day.isoformat() not in dates


def test_locked_pair_stays_put_in_auto_schedule(crossed, env):
    """鎖定的單雙週組(例如課後輔導那類先鎖再排的做法)自動排課不會移動。"""
    from app.models.timetable import Timetable

    client, tid, a = crossed["client"], crossed["tid"], crossed["a"]
    assert _place(client, tid, a[("701", "odd")]["id"], 2, 2, span=2).status_code == 201
    one = _entries(client, tid)[0]
    assert client.post(f"/api/timetables/{tid}/entries/{one['id']}/lock").status_code == 200
    assert all(e["locked"] for e in _entries(client, tid))  # 兩堂一起鎖

    db = env[1]
    problem = load_problem(db, crossed["sid"], db.get(Timetable, tid))
    result = solve(problem, SolveOptions(max_seconds=30.0, workers=4, random_seed=1),
                   config=SolverConfig.hard_only())
    assert result.solved and not validate(problem, result.entries)
    for week in ("odd", "even"):
        placed = {(e.weekday, e.period_no, e.span) for e in result.entries
                  if e.assignment_id == a[("701", week)]["id"]}
        assert placed == {(2, 2, 2)}
