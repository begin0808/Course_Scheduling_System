"""併班(v1.3.5,LINE 社群使用者回報):把請假老師的班併到「這一節正在上自己班的老師」那裡一起上。

先前畫面上的「併班」沒有地方選老師,一按就是「「併班」需要指定教師」;後端又要求接手老師
必須空堂——與手冊「併到他班一起上」、以及找不到空堂老師時「建議改採併班」的提示都矛盾。
使用者定案:列出這一節有課的老師(同年級優先、同科目其次),空堂老師請用代課。
"""

from app.models.leave import AffectedPeriod
from tests.dates import WED
from tests.test_substitutions import _World, env2  # noqa: F401 - env2 為 fixture


def _options(w, affected_id):
    r = w.client.get(f"/api/affected-periods/{affected_id}/merge-options")
    assert r.status_code == 200, r.json()
    return [(o["teacher_name"], o["class_names"], o["subject_name"], o["same_grade"],
             o["same_subject"]) for o in r.json()["options"]]


def _grade8(w: _World, name: str) -> None:
    w.classes[name] = w.client.post(f"/api/class-units{w.q}", json={
        "grade": 8, "name": name, "track": "junior_high"}).json()["id"]


def _school(w):
    """王師週三第一節 701 國文請假。同一節:陳師 702 國文、林師 703 數學、李師 801 國文;
    張師空堂;趙師 704 英語但當天也請假。"""
    _grade8(w, "801")
    for name, subject in [("王師", "國文"), ("陳師", "國文"), ("林師", "數學"),
                          ("李師", "國文"), ("張師", "國文"), ("趙師", "英語")]:
        w.teacher(name, [subject])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "國文", "702", 0)
    w.place("林師", "數學", "703", 0)
    w.place("李師", "國文", "801", 0)
    w.place("趙師", "英語", "704", 0)
    w.publish()
    w.leave("趙師")
    return w.leave("王師")[0]["id"]


def test_options_are_teachers_having_class_now_same_grade_first(env2):  # noqa: F811
    w = env2
    affected_id = _school(w)
    assert _options(w, affected_id) == [
        ("陳師", "702", "國文", True, True),     # 同年級、同科目
        ("林師", "703", "數學", True, False),    # 同年級
        ("李師", "801", "國文", False, True),    # 同科目
    ]
    # 張師空堂(請用代課)、趙師也請假、王師自己都不在名單上


def test_merge_into_a_teacher_who_is_teaching_is_accepted(env2):  # noqa: F811
    """先前要求接手老師空堂,一定會被擋;現在正在上課的老師可以接手。"""
    w = env2
    affected_id = _school(w)
    code, body = w.assign(affected_id, type="merge", handler_teacher_id=w.teachers["陳師"])
    assert code == 200, body
    assert (body["type_label"], body["handler_name"]) == ("併班", "陳師")
    assert body["counts_toward_hours"] is False      # 併班不另計代課鐘點
    ap = w.db.get(AffectedPeriod, affected_id)
    assert ap.handler_teacher_id == w.teachers["陳師"]


def test_merge_into_a_teacher_on_leave_is_rejected(env2):  # noqa: F811
    w = env2
    affected_id = _school(w)
    code, body = w.assign(affected_id, type="merge", handler_teacher_id=w.teachers["趙師"])
    assert code == 409
    assert "趙師" in body["detail"] and "請假" in body["detail"]


def test_merge_still_needs_a_teacher(env2):  # noqa: F811
    w = env2
    affected_id = _school(w)
    code, body = w.assign(affected_id, type="merge")
    assert code == 409 and "需要指定教師" in body["detail"]


def test_two_classes_can_merge_into_the_same_teacher(env2):  # noqa: F811
    """王師、林師都請假,兩個班都併到陳師那裡。"""
    w = env2
    first = _school(w)
    second = w.leave("林師")[0]["id"]
    assert w.assign(first, type="merge", handler_teacher_id=w.teachers["陳師"])[0] == 200
    names = [o[0] for o in _options(w, second)]
    assert "陳師" in names
    assert w.assign(second, type="merge", handler_teacher_id=w.teachers["陳師"])[0] == 200


def test_substitute_still_needs_a_free_teacher(env2):  # noqa: F811
    """代課的規則不變:正在上課的老師不能代。"""
    w = env2
    affected_id = _school(w)
    code, body = w.assign(affected_id, type="substitute", handler_teacher_id=w.teachers["陳師"])
    assert code == 409 and "自己的課" in body["detail"]


def test_options_on_another_day_follow_that_days_timetable(env2):  # noqa: F811
    """請假那天才算:週三那一節有課的人,不會因為別天的課表出現在名單上。"""
    w = env2
    w.teacher("王師", ["國文"])
    w.teacher("陳師", ["國文"])
    w.place("王師", "國文", "701", 0)
    w.place("陳師", "國文", "702", 0, weekday=4)   # 陳師的課在週四
    w.publish()
    affected_id = w.leave("王師", WED)[0]["id"]
    assert _options(w, affected_id) == []
