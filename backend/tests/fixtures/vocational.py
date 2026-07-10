"""vocational_high:技高 15 班 3 科(機械/電機/資訊,每科 5 班)。

特徵(tasks.md 測試策略總則):
- **3 連堂實習**:實習工場每班每週 6 節 = 3 連堂 × 2 次(block_rule)
- **實習工場**:每科 2 座工場,班級固定綁定,容量 30 人
- **業界師資**:每科 1 位外聘,僅週二/週四到校(其餘日全為 unavailable 硬約束)
- **協同教學**:三年級實習由業界師資主教 + 校內實習教師協同
- **跑班群組**:二年級 6 班(跨 3 科)組成「二年級多元選修」,群組內 5 門選修
  同時段開課,學生跑班

每班 35 節,可排格數 40(每日 8 節一般課 × 5 天)。
"""

from sqlalchemy.orm import Session

from app.models.basedata import ClassTrack, RoomType

from ._common import Builder, Fixture

DEPARTMENTS = ["機械科", "電機科", "資訊科"]
# 每科的班級:(班名後綴, 年級)
CLASS_SUFFIXES = [("一甲", 1), ("一乙", 1), ("二甲", 2), ("二乙", 2), ("三甲", 3)]

# 部定共同科目 → (每班節數, 教師數)。教師以 round-robin 認養 15 個班。
COMMON_SUBJECTS: dict[str, tuple[int, int]] = {
    "國文": (4, 4),
    "英文": (4, 4),
    "數學": (4, 4),
    "體育": (2, 2),
    "彈性學習": (2, 2),
}

# 群科專業科目:一/三年級 7 節、二年級 4 節(二年級以多元選修補足)
# 跑班群組的 5 門選修 → 任教教師(取自共同科目教師中負擔較輕者)
ELECTIVES = {
    "機器人程式設計": "國文師4",
    "電子商務實務": "英文師4",
    "生活科技應用": "數學師4",
    "桌球專項": "體育師2",
    "日語會話": "彈性學習師2",
}

GROUP_NAME = "二年級多元選修"
EXTERNAL_TEACHER_DAYS = [2, 4]  # 業界師資到校日:週二、週四


def _common_teacher_name(subject: str, idx: int) -> str:
    return f"{subject}師{idx + 1}"


def build_vocational_high(db: Session, academic_year: int = 115, term: int = 1) -> Fixture:
    b = Builder(db, academic_year, term, "vocational")

    b.subject("實習工場", required_room_type=RoomType.workshop, default_block_size=3)
    b.subject("體育", required_room_type=RoomType.outdoor)
    for elective in ELECTIVES:
        b.subject(elective, domain="多元選修")

    # ── 共同科目教師 ──
    for subject, (_periods, count) in COMMON_SUBJECTS.items():
        for i in range(count):
            b.teacher(_common_teacher_name(subject, i), base_periods=20, subjects=[subject])

    # ── 場地 ──
    b.room("操場", room_type=RoomType.outdoor, capacity=200, subjects=["體育"])
    for dept in DEPARTMENTS:
        for wing in ("A", "B"):
            b.room(
                f"{dept}工場{wing}",
                room_type=RoomType.workshop,
                capacity=30,
                subjects=["實習工場"],
            )

    # ── 各科教師、班級、專業配課 ──
    for dept in DEPARTMENTS:
        short = dept[:2]  # 機械 / 電機 / 資訊
        prof = [f"{short}專業師{i + 1}" for i in range(4)]
        practicum = [f"{short}實習師{i + 1}" for i in range(2)]
        external = f"{short}業界師"

        for name in prof + practicum:
            b.teacher(name, base_periods=20, subjects=["專業實習", "群科專業科目"])
        # 業界師資:基本鐘點低、僅週二/週四到校
        b.teacher(external, base_periods=6, is_external=True, subjects=["實習工場"])
        b.unavailable_days(external, [d for d in range(1, 6) if d not in EXTERNAL_TEACHER_DAYS])

        classes = [f"{short}{suffix}" for suffix, _grade in CLASS_SUFFIXES]
        homeroom_pool = prof + practicum  # 6 位,足夠讓 5 班各有專屬導師
        for i, ((_suffix, grade), cname) in enumerate(zip(CLASS_SUFFIXES, classes, strict=True)):
            b.klass(
                cname,
                grade=grade,
                track=ClassTrack.vocational.value,
                department=dept,
                student_count=30,
                homeroom=homeroom_pool[i],
            )
            b.room(f"{cname}教室", room_type=RoomType.normal, capacity=32)

        c1, c2, c3, c4, c5 = classes  # 一甲 一乙 二甲 二乙 三甲

        # 專業實習 6 節/班:專業師1 帶 3 班(18 節)、專業師2 帶 2 班(12 節)
        b.assign(subject="專業實習", teachers=[prof[0]], periods=6, classes=[c1, c2, c3])
        b.assign(subject="專業實習", teachers=[prof[1]], periods=6, classes=[c4, c5])

        # 群科專業科目:專業師3 帶一年級(各 7 節=14)、專業師4 帶二三年級(7+4+4=15)
        b.assign(subject="群科專業科目", teachers=[prof[2]], periods=7, classes=[c1, c2])
        b.assign(subject="群科專業科目", teachers=[prof[3]], periods=7, classes=[c5])
        b.assign(subject="群科專業科目", teachers=[prof[3]], periods=4, classes=[c3, c4])

        # 實習工場 6 節 = 3 連堂 × 2;一甲/一乙/二甲在工場A,二乙/三甲在工場B
        for cname, teacher, wing in (
            (c1, practicum[0], "A"),
            (c2, practicum[0], "A"),
            (c3, practicum[1], "A"),
            (c4, practicum[1], "B"),
        ):
            b.assign(
                subject="實習工場",
                teachers=[teacher],
                periods=6,
                classes=[cname],
                room=f"{dept}工場{wing}",
                required_room_type=RoomType.workshop,
                blocks=(3, 2),
                lock_room=True,
            )
        # 三年級:業界師資主教 + 校內實習師2 協同
        b.assign(
            subject="實習工場",
            teachers=[external, practicum[1]],
            periods=6,
            classes=[c5],
            room=f"{dept}工場B",
            required_room_type=RoomType.workshop,
            blocks=(3, 2),
            lock_room=True,
        )

    # ── 共同科目:15 班 round-robin ──
    all_classes = list(b.classes)
    for subject, (periods, count) in COMMON_SUBJECTS.items():
        for idx, cname in enumerate(all_classes):
            b.assign(
                subject=subject,
                teachers=[_common_teacher_name(subject, idx % count)],
                periods=periods,
                classes=[cname],
                room="操場" if subject == "體育" else None,
                required_room_type=RoomType.outdoor if subject == "體育" else None,
            )

    # ── 跑班群組:二年級 6 班(跨 3 科),5 門選修同時段開課 ──
    g2_classes = [f"{d[:2]}{suffix}" for d in DEPARTMENTS for suffix, grade in CLASS_SUFFIXES
                  if grade == 2]
    b.group(GROUP_NAME, g2_classes)
    for elective, teacher in ELECTIVES.items():
        b.assign(subject=elective, teachers=[teacher], periods=3, group=GROUP_NAME)

    return b.build()
