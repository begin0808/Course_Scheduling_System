"""學期與節次表 API。

權限:讀取 = 教學組長/教務主任;寫入 = 教學組長(admin 一律通過)。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.basedata import ClassUnit, Room, Subject, Teacher
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester
from app.models.user import Role
from app.schemas.semester import (
    AvailableSlot,
    PeriodIn,
    PeriodTableCreate,
    PeriodTableOut,
    PeriodTableUpdate,
    SemesterCreate,
    SemesterListItem,
    SemesterOut,
    SemesterUpdate,
    TemplateOut,
)
from app.schemas.wizard import SemesterSummary
from app.services import templates as tpl

router = APIRouter(tags=["semesters"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


# ── 內部工具 ──────────────────────────
def _get_semester(db: Session, semester_id: int) -> Semester:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    return semester


def _get_period_table(db: Session, table_id: int) -> PeriodTable:
    table = db.get(PeriodTable, table_id)
    if table is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到節次表")
    return table


def _unset_other_defaults(db: Session, semester_id: int, keep_id: int | None) -> None:
    others = db.scalars(
        select(PeriodTable).where(
            PeriodTable.semester_id == semester_id, PeriodTable.is_default.is_(True)
        )
    )
    for t in others:
        if t.id != keep_id:
            t.is_default = False


# ── 學制範本 ──────────────────────────
@router.get("/school-templates", response_model=list[TemplateOut])
def list_templates(_: object = Depends(viewer)) -> list[TemplateOut]:
    return [
        TemplateOut(
            key=t["key"],
            name=t["name"],
            minutes_per_period=t["minutes_per_period"],
            subject_count=len(t.get("subjects", [])),
        )
        for t in tpl.load_templates()
    ]


# ── 學期 ──────────────────────────────
@router.get("/semesters", response_model=list[SemesterListItem])
def list_semesters(db: Session = Depends(get_db), _: object = Depends(viewer)):
    return db.scalars(
        select(Semester).order_by(Semester.academic_year.desc(), Semester.term.desc())
    ).all()


@router.post("/semesters", response_model=SemesterOut, status_code=status.HTTP_201_CREATED)
def create_semester(
    body: SemesterCreate, db: Session = Depends(get_db), _: object = Depends(editor)
) -> Semester:
    exists = db.scalar(
        select(Semester).where(
            Semester.academic_year == body.academic_year, Semester.term == body.term
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "該學年度學期已存在")

    if body.template_key:
        if tpl.get_template(body.template_key) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知的學制範本")
        semester = tpl.create_semester_from_template(
            db,
            academic_year=body.academic_year,
            term=body.term,
            template_key=body.template_key,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    else:
        semester = Semester(
            academic_year=body.academic_year,
            term=body.term,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        db.add(semester)
    db.commit()
    db.refresh(semester)
    return semester


@router.get("/semesters/{semester_id}", response_model=SemesterOut)
def get_semester(
    semester_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> Semester:
    return _get_semester(db, semester_id)


@router.get("/semesters/{semester_id}/summary", response_model=SemesterSummary)
def semester_summary(
    semester_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> SemesterSummary:
    _get_semester(db, semester_id)

    def _count(model) -> int:
        return db.scalar(
            select(func.count()).select_from(model).where(model.semester_id == semester_id)
        ) or 0

    return SemesterSummary(
        subjects=_count(Subject), teachers=_count(Teacher),
        classes=_count(ClassUnit), rooms=_count(Room),
    )


@router.patch("/semesters/{semester_id}", response_model=SemesterOut)
def update_semester(
    semester_id: int,
    body: SemesterUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> Semester:
    semester = _get_semester(db, semester_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        semester.status = data["status"].value
    if "start_date" in data:
        semester.start_date = data["start_date"]
    if "end_date" in data:
        semester.end_date = data["end_date"]
    db.commit()
    db.refresh(semester)
    return semester


@router.delete("/semesters/{semester_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_semester(
    semester_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    semester = _get_semester(db, semester_id)
    db.delete(semester)
    db.commit()


# ── 節次表 ────────────────────────────
@router.post(
    "/semesters/{semester_id}/period-tables",
    response_model=PeriodTableOut,
    status_code=status.HTTP_201_CREATED,
)
def create_period_table(
    semester_id: int,
    body: PeriodTableCreate,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> PeriodTable:
    _get_semester(db, semester_id)

    if body.template_key:
        template = tpl.get_template(body.template_key)
        if template is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知的學制範本")
        table = tpl.build_period_table_from_template(
            template, name=body.name, is_default=body.is_default
        )
    else:
        table = PeriodTable(
            name=body.name, num_weekdays=body.num_weekdays, is_default=body.is_default
        )
    table.semester_id = semester_id
    db.add(table)
    db.flush()
    if table.is_default:
        _unset_other_defaults(db, semester_id, table.id)
    db.commit()
    db.refresh(table)
    return table


@router.get("/period-tables/{table_id}", response_model=PeriodTableOut)
def get_period_table(
    table_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> PeriodTable:
    return _get_period_table(db, table_id)


@router.patch("/period-tables/{table_id}", response_model=PeriodTableOut)
def update_period_table(
    table_id: int,
    body: PeriodTableUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> PeriodTable:
    table = _get_period_table(db, table_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        table.name = data["name"]
    if data.get("is_default") is not None:
        table.is_default = data["is_default"]
        if data["is_default"]:
            _unset_other_defaults(db, table.semester_id, table.id)
    db.commit()
    db.refresh(table)
    return table


@router.delete("/period-tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_period_table(
    table_id: int, db: Session = Depends(get_db), _: object = Depends(editor)
) -> None:
    table = _get_period_table(db, table_id)
    db.delete(table)
    db.commit()


@router.put("/period-tables/{table_id}/periods", response_model=PeriodTableOut)
def replace_periods(
    table_id: int,
    periods: list[PeriodIn],
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> PeriodTable:
    """整批取代節次表的所有格位(視覺化編輯器儲存用)。"""
    table = _get_period_table(db, table_id)

    seen: set[tuple[int, int]] = set()
    for p in periods:
        key = (p.weekday, p.period_no)
        if key in seen:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"重複的格位:星期 {p.weekday} 第 {p.period_no} 節",
            )
        seen.add(key)

    table.periods.clear()
    db.flush()
    for p in periods:
        table.periods.append(
            Period(
                weekday=p.weekday,
                period_no=p.period_no,
                name=p.name,
                start_time=p.start_time,
                end_time=p.end_time,
                type=p.type.value,
            )
        )
    db.commit()
    db.refresh(table)
    return table


@router.get("/period-tables/{table_id}/available-slots", response_model=list[AvailableSlot])
def available_slots(
    table_id: int, db: Session = Depends(get_db), _: object = Depends(viewer)
) -> list[AvailableSlot]:
    """回傳可排課時段(type=regular),供排課時段檢查使用。"""
    _get_period_table(db, table_id)
    rows = db.scalars(
        select(Period)
        .where(Period.period_table_id == table_id, Period.type == PeriodType.regular.value)
        .order_by(Period.weekday, Period.period_no)
    ).all()
    return [
        AvailableSlot(
            weekday=p.weekday,
            period_no=p.period_no,
            name=p.name,
            start_time=p.start_time,
            end_time=p.end_time,
        )
        for p in rows
    ]
