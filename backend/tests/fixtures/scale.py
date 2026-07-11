"""大規模效能資料集(M5-0):~60 班的國中,供 M5-1「60 班批次匯出 < 60 秒」與
M5-4 壓測共用。

重點是**量**而非嚴格教學合理性:班級數、配課數、教師負載大致均衡即可,不保證可完全排課
(可排性由三套學制 fixtures 保證)。教師以「最少負載優先」貪婪指派,讓總鐘點大致平均。
"""

from sqlalchemy.orm import Session

from ._common import Builder, Fixture

# 標準國中每週課程(科目, 每週節數),合計 30 節
_CURRICULUM: list[tuple[str, int]] = [
    ("國文", 5), ("英語", 4), ("數學", 4), ("自然", 4), ("社會", 4),
    ("體育", 2), ("藝術", 2), ("音樂", 1), ("綜合", 2), ("資訊", 1), ("健康", 1),
]


def build_large_school(
    db: Session, *, academic_year: int = 120, term: int = 1, num_classes: int = 60
) -> Fixture:
    """建一所 num_classes 班的國中(預設 60 班)。"""
    b = Builder(db, academic_year, term, "junior_high")

    for name, _ in _CURRICULUM:
        b.subject(name)

    base = 20
    periods_per_class = sum(p for _, p in _CURRICULUM)
    total_periods = num_classes * periods_per_class
    teacher_names = [f"t{i:03d}" for i in range(max(1, total_periods // 18))]
    for tn in teacher_names:
        b.teacher(tn, base_periods=base)
    load = dict.fromkeys(teacher_names, 0)

    def pick(periods: int) -> str:
        """挑一位加上這幾節後仍不超過 base 的教師(最少負載優先);都不合就多聘一位。"""
        fit = [n for n in teacher_names if load[n] + periods <= base]
        if not fit:
            n = f"t{len(teacher_names):03d}"
            b.teacher(n, base_periods=base)
            teacher_names.append(n)
            load[n] = 0
            fit = [n]
        chosen = min(fit, key=lambda n: load[n])
        load[chosen] += periods
        return chosen

    b.room("體育館", capacity=200)
    b.room("自然實驗室", capacity=40)

    # 班級:三個年級平均分配
    per_grade = num_classes // 3
    remainder = num_classes % 3
    made = 0
    for gi, grade in enumerate((7, 8, 9)):
        count = per_grade + (1 if gi < remainder else 0)
        for k in range(count):
            cls = f"{grade}{k + 1:02d}"
            b.klass(cls, grade=grade, track="junior_high")
            for subject, periods in _CURRICULUM:
                b.assign(subject=subject, teachers=[pick(periods)], periods=periods, classes=[cls])
            made += 1

    assert made == num_classes
    return b.build()
