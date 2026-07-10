"""驗證器本身要有牙齒。

`test_model_builder` 用 validator 斷言「解零違反」;若 validator 什麼都抓不到,
那些斷言就毫無意義。這裡逐項餵給它壞課表,確認每條硬約束都會被指名抓出。
"""

from dataclasses import replace

from app.models.basedata import ClassTrack, RoomType
from app.services.solver_data import load_problem
from app.solver.problem import FixedEntry, SolvedEntry
from app.solver.validator import validate
from tests.fixtures import Builder

# 國中範本:period_no 2–5 為上午一般課、7–9 為下午一般課(6 是午休)


def _base(db, year: int):
    b = Builder(db, year, 1, "junior_high")
    b.teacher("甲師", base_periods=40)
    b.teacher("乙師", base_periods=40)
    b.klass("301", grade=3, track=ClassTrack.junior_high.value)
    b.klass("302", grade=3, track=ClassTrack.junior_high.value)
    return b


def _codes(violations) -> set[str]:
    return {v.code for v in violations}


def test_clean_timetable_has_no_violations(db):
    b = _base(db, 140)
    a = b.assign(subject="國文", teachers=["甲師"], periods=2, classes=["301"])[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    entries = [
        SolvedEntry(a.id, 1, 2, 1, None),
        SolvedEntry(a.id, 2, 2, 1, None),
    ]
    assert validate(problem, entries) == ()


def test_h1_class_double_booked(db):
    b = _base(db, 141)
    guo = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["301"])[0]
    shu = b.assign(subject="數學", teachers=["乙師"], periods=1, classes=["301"])[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    entries = [SolvedEntry(guo.id, 1, 2, 1, None), SolvedEntry(shu.id, 1, 2, 1, None)]
    v = validate(problem, entries)
    assert "H1" in _codes(v)
    assert "301" in next(x for x in v if x.code == "H1").message


def test_h2_teacher_double_booked(db):
    b = _base(db, 142)
    a1 = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["301"])[0]
    a2 = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["302"])[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    v = validate(problem, [SolvedEntry(a1.id, 1, 2, 1, None), SolvedEntry(a2.id, 1, 2, 1, None)])
    assert "H2" in _codes(v)
    assert "甲師" in next(x for x in v if x.code == "H2").message


def test_h3_room_double_booked_and_room_type(db):
    b = _base(db, 143)
    b.room("理化實驗室", room_type=RoomType.special, capacity=30)
    b.room("操場", room_type=RoomType.outdoor, capacity=200)
    a1 = b.assign(subject="自然科學", teachers=["甲師"], periods=1, classes=["301"],
                  room="理化實驗室", required_room_type=RoomType.special)
    a2 = b.assign(subject="自然科學", teachers=["乙師"], periods=1, classes=["302"],
                  room="理化實驗室", required_room_type=RoomType.special)
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    clash = [SolvedEntry(a1[0].id, 1, 2, 1, None), SolvedEntry(a2[0].id, 1, 2, 1, None)]
    assert "H3" in _codes(validate(problem, clash))

    # 格位場地覆寫成錯誤類型 → room_type 違反
    playground = fx.rooms["操場"].id
    v2 = validate(problem, [SolvedEntry(a1[0].id, 1, 2, 1, playground)])
    assert "room_type" in _codes(v2)


def test_h4_teacher_unavailable(db):
    from app.models.basedata import TeacherRuleType, TeacherTimeRule

    b = _base(db, 144)
    a = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["301"])[0]
    db.add(TeacherTimeRule(teacher_id=b.teachers["甲師"].id, weekday=1, period_no=2,
                           rule_type=TeacherRuleType.unavailable.value))
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    v = validate(problem, [SolvedEntry(a.id, 1, 2, 1, None)])
    assert "H4" in _codes(v)


def test_h5_non_regular_slot_and_h6_block_crossing_lunch(db):
    b = _base(db, 145)
    single = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["301"])[0]
    block = b.assign(subject="彈性學習", teachers=["乙師"], periods=3, classes=["302"],
                     blocks=(3, 1))[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    assert "H5" in _codes(validate(problem, [SolvedEntry(single.id, 1, 6, 1, None)]))  # 午休
    # 3 連堂從第 5 節起 → 涵蓋第 6 節(午休)
    assert "H6" in _codes(validate(problem, [SolvedEntry(block.id, 1, 5, 3, None)]))


def test_h7_group_out_of_sync(db):
    b = _base(db, 146)
    b.group("多元選修", ["301", "302"])
    b.subject("選修甲")
    b.subject("選修乙")
    a1 = b.assign(subject="選修甲", teachers=["甲師"], periods=1, group="多元選修")[0]
    a2 = b.assign(subject="選修乙", teachers=["乙師"], periods=1, group="多元選修")[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    ok = [SolvedEntry(a1.id, 1, 2, 1, None), SolvedEntry(a2.id, 1, 2, 1, None)]
    assert validate(problem, ok) == ()

    bad = [SolvedEntry(a1.id, 1, 2, 1, None), SolvedEntry(a2.id, 1, 3, 1, None)]
    assert "H7" in _codes(validate(problem, bad))


def test_h8_weekly_periods_and_block_shape(db):
    b = _base(db, 147)
    a = b.assign(subject="國文", teachers=["甲師"], periods=3, classes=["301"])[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    short = [SolvedEntry(a.id, 1, 2, 1, None), SolvedEntry(a.id, 2, 2, 1, None)]
    assert "H8" in _codes(validate(problem, short))

    # 節數對但用連堂排 → 與 block_rule 不符
    wrong_shape = [SolvedEntry(a.id, 1, 2, 3, None)]
    assert "H8" in _codes(validate(problem, wrong_shape))


def test_h9_locked_entry_moved(db):
    b = _base(db, 148)
    a = b.assign(subject="國文", teachers=["甲師"], periods=1, classes=["301"])[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)
    pinned = replace(problem, fixed_entries=(FixedEntry(a.id, 1, 2, 1, None, locked=True),))

    assert validate(pinned, [SolvedEntry(a.id, 1, 2, 1, None)]) == ()
    assert "H9" in _codes(validate(pinned, [SolvedEntry(a.id, 1, 3, 1, None)]))


def test_h10_daily_cap_counts_single_periods_only(db):
    b = _base(db, 149)
    single = b.assign(subject="國文", teachers=["甲師"], periods=3, classes=["301"])[0]
    block = b.assign(subject="彈性學習", teachers=["乙師"], periods=6, classes=["302"],
                     blocks=(3, 2))[0]
    fx = b.build()
    problem = load_problem(db, fx.semester_id)

    over = [SolvedEntry(single.id, 1, p, 1, None) for p in (2, 3, 4)]
    v = validate(problem, over)
    assert "H10" in _codes(v)
    assert "3 節" in next(x for x in v if x.code == "H10").message

    # 同日兩個 3 連堂共 6 節,但連堂不計入每日上限
    blocks = [SolvedEntry(block.id, 1, 2, 3, None), SolvedEntry(block.id, 2, 2, 3, None)]
    assert "H10" not in _codes(validate(problem, blocks))
