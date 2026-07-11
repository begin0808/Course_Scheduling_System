"""M5-0:60 班效能資料集的煙霧測試——產得出、基本查詢正常。"""

from sqlalchemy import func, select

from app.models.assignment import CourseAssignment
from app.models.basedata import ClassUnit, Teacher
from tests.fixtures import build_large_school


def test_large_school_builds_60_classes(db):
    fx = build_large_school(db, num_classes=60)
    sid = fx.semester_id

    classes = db.scalar(
        select(func.count()).select_from(ClassUnit).where(ClassUnit.semester_id == sid))
    assert classes == 60

    # 每班 11 門課 → 660 筆配課
    assignments = db.scalar(
        select(func.count()).select_from(CourseAssignment)
        .where(CourseAssignment.semester_id == sid))
    assert assignments == 60 * 11

    # 教師負載大致均衡:無人超過 base_periods(以貪婪最少負載指派)
    teachers = list(db.scalars(select(Teacher).where(Teacher.semester_id == sid)))
    assert teachers
    loads = {t.id: 0 for t in teachers}
    for a in db.scalars(select(CourseAssignment).where(CourseAssignment.semester_id == sid)):
        for at in a.teachers:
            loads[at.teacher_id] += a.periods_per_week
    assert max(loads.values()) <= 20, "貪婪指派不應讓任何教師超過 base_periods"


def test_large_school_custom_size(db):
    fx = build_large_school(db, num_classes=30)
    classes = db.scalar(
        select(func.count()).select_from(ClassUnit).where(ClassUnit.semester_id == fx.semester_id))
    assert classes == 30
