"""停課日(v1.4.19):全校、年級或指定班級,整天或第幾節到第幾節不上課。

RBAC:看,所有登入的人(老師在課表查詢也會看到停課);設定,教學組長與教務主任。
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.basedata import ClassUnit
from app.models.semester import Semester
from app.models.suspension import ClassSuspension
from app.models.user import Role, User
from app.schemas.suspension import SuspensionIn, SuspensionOut, SuspensionSaved
from app.services import suspensions as suspension_service

router = APIRouter(tags=["suspensions"])

registrar = require_roles(Role.scheduler, Role.director)

MAX_DAYS = 180   # 和單張假單同一個上限,擋住手殘輸入的 2099 年


def _classes(db: Session, semester_id: int) -> list[ClassUnit]:
    return list(db.scalars(
        select(ClassUnit).where(ClassUnit.semester_id == semester_id)
        .order_by(ClassUnit.grade, ClassUnit.name)))


def _out(s: ClassSuspension, all_classes: list[ClassUnit]) -> SuspensionOut:
    return SuspensionOut(
        id=s.id, start_date=s.start_date, end_date=s.end_date, whole_school=s.whole_school,
        class_ids=[c.id for c in s.classes], all_day=s.all_day,
        from_ordinal=s.from_ordinal, to_ordinal=s.to_ordinal, reason=s.reason,
        target_text=suspension_service.target_text(s, all_classes),
        period_text=suspension_service.period_text(s),
        created_by_name=s.created_by_name,
    )


def _apply(db: Session, s: ClassSuspension, body: SuspensionIn, semester: Semester) -> None:
    """檢查並寫入;不合法時丟 400。"""
    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "結束日期不可早於開始日期")
    if (body.end_date - body.start_date).days + 1 > MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"一筆停課最長 {MAX_DAYS} 天")
    if ((semester.start_date and body.start_date < semester.start_date)
            or (semester.end_date and body.end_date > semester.end_date)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "停課日期要在學期期間內")
    if body.all_day:
        lo = hi = None
    else:
        if body.from_ordinal is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "請選擇從第幾節開始停課")
        lo, hi = body.from_ordinal, body.to_ordinal or body.from_ordinal
        if hi < lo:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "結束節次不可早於開始節次")
    classes: list[ClassUnit] = []
    if not body.whole_school:
        ids = set(body.class_ids)
        if not ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "請選擇停課的年級或班級")
        classes = list(db.scalars(
            select(ClassUnit).where(ClassUnit.id.in_(ids), ClassUnit.semester_id == semester.id)))
        if len(classes) != len(ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "班級清單含無效或跨學期的班級")
    s.start_date, s.end_date = body.start_date, body.end_date
    s.whole_school = body.whole_school
    s.classes = classes
    s.from_ordinal, s.to_ordinal = lo, hi
    s.reason = body.reason.strip()


def _saved(db: Session, s: ClassSuspension, user: User, action: str) -> SuspensionSaved:
    all_classes = _classes(db, s.semester_id)
    item = _out(s, all_classes)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action=action,
        target_type="class_suspension", target_id=s.id,
        detail=(f"{s.start_date}~{s.end_date} {item.target_text} {item.period_text}"
                f" {s.reason}")[:500],
    ))
    conflicts = [c.text for c in suspension_service.conflicts(db, s)]
    db.commit()
    return SuspensionSaved(item=item, conflicts=conflicts)


@router.get("/suspensions", response_model=list[SuspensionOut])
def list_suspensions(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
) -> list[SuspensionOut]:
    all_classes = _classes(db, semester_id)
    rows = db.scalars(
        select(ClassSuspension).where(ClassSuspension.semester_id == semester_id)
        .order_by(ClassSuspension.start_date, ClassSuspension.id))
    return [_out(s, all_classes) for s in rows]


@router.post("/suspensions", response_model=SuspensionSaved,
             status_code=status.HTTP_201_CREATED)
def create_suspension(
    body: SuspensionIn,
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(registrar),
) -> SuspensionSaved:
    semester = db.get(Semester, semester_id)
    if semester is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    s = ClassSuspension(semester_id=semester_id, created_by_name=user.username)
    _apply(db, s, body, semester)
    db.add(s)
    db.flush()
    return _saved(db, s, user, "create_suspension")


@router.put("/suspensions/{suspension_id}", response_model=SuspensionSaved)
def update_suspension(
    suspension_id: int,
    body: SuspensionIn,
    db: Session = Depends(get_db),
    user: User = Depends(registrar),
) -> SuspensionSaved:
    s = db.get(ClassSuspension, suspension_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這筆停課")
    semester = db.get(Semester, s.semester_id)
    assert semester is not None
    _apply(db, s, body, semester)
    db.flush()
    return _saved(db, s, user, "update_suspension")


@router.delete("/suspensions/{suspension_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_suspension(
    suspension_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(registrar),
) -> None:
    s = db.get(ClassSuspension, suspension_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這筆停課")
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="delete_suspension",
        target_type="class_suspension", target_id=s.id,
        detail=f"{s.start_date}~{s.end_date} {s.reason}"[:500],
    ))
    db.delete(s)
    db.commit()
