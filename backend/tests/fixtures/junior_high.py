"""junior_high_mid:國中 12 班(七/八/九年級各 4 班)。

特徵(tasks.md 測試策略總則):
- **領域課程**:國文/英語/數學/自然科學/社會/健康與體育/藝術/綜合活動/科技
- **彈性課程**:彈性學習每班 3 節
- **兼行政減課教師**:教學組長(減 6 節)、訓育組長(減 4 節),配課量相應減少
- **場地綁定**:健康與體育 → 操場/體育館;科技 → 電腦教室甲/乙

每班 33 節,可排格數 35(每日 7 節一般課 × 5 天)。
"""

from sqlalchemy.orm import Session

from app.models.basedata import ClassTrack, RoomType

from ._common import Builder, Fixture

CLASS_NAMES = [
    "701", "702", "703", "704",
    "801", "802", "803", "804",
    "901", "902", "903", "904",
]

# 科目 → (每班節數, 任教教師姓名清單)
# 每位教師輪流認養班級(round-robin),故各科教師數決定其每人配課量。
SUBJECT_PLAN: dict[str, tuple[int, list[str]]] = {
    "國文":       (5, ["周淑貞", "許家豪", "彭麗雲"]),                    # 4 班 × 5 = 20 節
    "英語":       (4, ["何美惠", "簡佩玲", "傅冠廷"]),                    # 4 班 × 4 = 16 節
    "數學":       (4, ["曾國強", "楊子萱", "廖俊宏", "邱雅琪"]),           # 3 班 × 4 = 12 節
    "自然科學":   (3, ["宋建志", "范文君"]),                              # 6 班 × 3 = 18 節
    "社會":       (3, ["石清雄", "洪淑娟"]),
    "健康與體育": (3, ["盧志豪", "馬俊傑"]),
    "藝術":       (3, ["方雅雯", "潘俐君", "杜秉諺"]),                    # 4 班 × 3 = 12 節
    "綜合活動":   (3, ["莊惠敏", "施泓宇"]),
    "科技":       (2, ["連文彬", "唐立群"]),                              # 6 班 × 2 = 12 節
    "彈性學習":   (3, ["溫子涵", "紀勝文"]),
}

# 兼行政教師:配課量已在 SUBJECT_PLAN 以「多分幾位教師」壓低,故仍不超鐘點
ADMIN_TEACHERS = {
    "曾國強": ("教學組長", 6),   # 基本 20 − 減 6 = 應授 14;實配 12
    "方雅雯": ("訓育組長", 4),   # 基本 20 − 減 4 = 應授 16;實配 12
}

# 場地綁定:同一位教師的班級集中在同一場地,避免場地需求超過供給
ROOM_BY_TEACHER = {
    "盧志豪": "操場",
    "馬俊傑": "體育館",
    "連文彬": "電腦教室甲",
    "唐立群": "電腦教室乙",
}
ROOM_TYPE_BY_SUBJECT = {
    "健康與體育": RoomType.outdoor,
    "科技": RoomType.special,
    "藝術": RoomType.special,  # 未綁定場地,由排課引擎自專科教室中指派
}


def build_junior_high_mid(db: Session, academic_year: int = 115, term: int = 1) -> Fixture:
    b = Builder(db, academic_year, term, "junior_high")

    for subject, room_type in ROOM_TYPE_BY_SUBJECT.items():
        b.subject(subject, required_room_type=room_type)

    for subject, (_periods, names) in SUBJECT_PLAN.items():
        for name in names:
            title, reduction = ADMIN_TEACHERS.get(name, (None, 0))
            b.teacher(
                name,
                base_periods=20,
                admin_title=title,
                admin_reduction=reduction,
                subjects=[subject],
            )

    # 導師 12 位取自國文/英語/數學/自然科學教師(3+3+4+2)
    homerooms = (
        SUBJECT_PLAN["國文"][1]
        + SUBJECT_PLAN["英語"][1]
        + SUBJECT_PLAN["數學"][1]
        + SUBJECT_PLAN["自然科學"][1]
    )
    for cname, homeroom in zip(CLASS_NAMES, homerooms, strict=True):
        b.klass(
            cname,
            grade=int(cname[0]) + 6,  # 701 → 7 年級
            track=ClassTrack.junior_high.value,
            student_count=29,
            homeroom=homeroom,
        )
        b.room(f"{cname}教室", room_type=RoomType.normal, capacity=32)

    b.room("操場", room_type=RoomType.outdoor, capacity=200, subjects=["健康與體育"])
    b.room("體育館", room_type=RoomType.outdoor, capacity=150, subjects=["健康與體育"])
    b.room("電腦教室甲", room_type=RoomType.special, capacity=35, subjects=["科技"])
    b.room("電腦教室乙", room_type=RoomType.special, capacity=35, subjects=["科技"])
    b.room("音樂教室", room_type=RoomType.special, capacity=35, subjects=["藝術"])
    b.room("美術教室", room_type=RoomType.special, capacity=35, subjects=["藝術"])
    b.room("理化實驗室", room_type=RoomType.special, capacity=32, subjects=["自然科學"])

    for subject, (periods, names) in SUBJECT_PLAN.items():
        for idx, cname in enumerate(CLASS_NAMES):
            teacher = names[idx % len(names)]
            b.assign(
                subject=subject,
                teachers=[teacher],
                periods=periods,
                classes=[cname],
                room=ROOM_BY_TEACHER.get(teacher),
                required_room_type=ROOM_TYPE_BY_SUBJECT.get(subject),
                lock_room=teacher in ROOM_BY_TEACHER,
            )

    return b.build()
