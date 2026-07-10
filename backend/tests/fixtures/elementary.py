"""elementary_small:國小 6 班(一~六年級各一班)。

特徵(tasks.md 測試策略總則):
- **包班**:導師教自己班的國語/數學/生活(低年級)或自然+社會(中高年級)/綜合活動
- **科任**:英語、藝術、健康與體育各由專任教師跨班任教
- **週三下午空**:來自國小範本(週三第 5–7 節為 reserved)
- **導師時間**:週五第七節改為導師時間(不排課)

可排格數 31(每日 7 節一般課 × 5 天 − 週三下午 3 節 − 週五導師時間 1 節)。
"""

from sqlalchemy.orm import Session

from app.models.basedata import ClassTrack, RoomType
from app.models.period import PeriodType

from ._common import Builder, Fixture

# 每班每週節數:低年級 23 節、中高年級 28 節(皆 ≤ 31 可排格數)
LOWER_GRADES = (1, 2)

# 導師包班科目 → 節數
HOMEROOM_LOWER = {"國語": 6, "數學": 4, "生活": 6, "綜合活動": 2}
HOMEROOM_UPPER = {"國語": 6, "數學": 4, "自然": 3, "社會": 3, "綜合活動": 3}

CLASS_NAMES = {
    1: "一年甲班",
    2: "二年甲班",
    3: "三年甲班",
    4: "四年甲班",
    5: "五年甲班",
    6: "六年甲班",
}
HOMEROOM_TEACHERS = {
    1: "林淑芬",
    2: "陳美玲",
    3: "王雅婷",
    4: "張怡君",
    5: "李佳蓉",
    6: "黃志偉",
}


def build_elementary_small(db: Session, academic_year: int = 115, term: int = 1) -> Fixture:
    b = Builder(db, academic_year, term, "elementary")

    # 週五第七節改為導師時間(週三下午已由範本標為 reserved)
    b.set_period(weekday=5, period_no=9, ptype=PeriodType.homeroom, name="導師時間")

    b.subject("藝術", required_room_type=RoomType.special)
    b.subject("健康與體育", required_room_type=RoomType.outdoor)

    # 導師:國小導師基本鐘點 22 節,包班 18–19 節
    for grade, name in HOMEROOM_TEACHERS.items():
        b.teacher(name, base_periods=22)
        b.klass(
            CLASS_NAMES[grade],
            grade=grade,
            track=ClassTrack.elementary.value,
            student_count=26,
            homeroom=name,
        )

    # 科任
    b.teacher("吳英傑", base_periods=20, subjects=["英語", "本土語文"])  # 16 節
    b.teacher("蔡文玲", base_periods=20, subjects=["藝術"])            # 12 節
    b.teacher("鄭建宏", base_periods=20, subjects=["健康與體育"])       # 18 節

    b.room("音樂教室", room_type=RoomType.special, capacity=35, subjects=["藝術"])
    b.room("操場", room_type=RoomType.outdoor, capacity=120, subjects=["健康與體育"])
    for name in CLASS_NAMES.values():
        b.room(f"{name}教室", room_type=RoomType.normal, capacity=32)

    for grade, cname in CLASS_NAMES.items():
        lower = grade in LOWER_GRADES
        homeroom = HOMEROOM_TEACHERS[grade]

        for subject, periods in (HOMEROOM_LOWER if lower else HOMEROOM_UPPER).items():
            b.assign(subject=subject, teachers=[homeroom], periods=periods, classes=[cname])

        b.assign(subject="英語", teachers=["吳英傑"], periods=1 if lower else 2, classes=[cname])
        b.assign(subject="本土語文", teachers=["吳英傑"], periods=1, classes=[cname])
        b.assign(
            subject="健康與體育",
            teachers=["鄭建宏"],
            periods=3,
            classes=[cname],
            room="操場",
            required_room_type=RoomType.outdoor,
            lock_room=True,
        )
        if not lower:  # 低年級的藝術涵蓋於「生活」課程
            b.assign(
                subject="藝術",
                teachers=["蔡文玲"],
                periods=3,
                classes=[cname],
                room="音樂教室",
                required_room_type=RoomType.special,
                lock_room=True,
            )

    return b.build()
