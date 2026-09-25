"""調代課處理工作台:代課推薦、指派處置、調課(M4-2)。

處置是行政決定,一律限教學組長/教務主任。教師端不在這裡處理(只在通知端「確認收到」)。
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.leave import AffectedPeriod
from app.models.substitution import (
    FUNDING_SOURCES,
    SUBSTITUTION_TYPE_CN,
    Substitution,
    SubstitutionType,
)
from app.models.user import Role, User
from app.schemas.substitution import (
    AssignRequest,
    CandidateOut,
    RecommendationOut,
    SlipsOut,
    SubstitutionOut,
    SwapOptionsOut,
)
from app.services import sub_slips, swap_options, swap_slips
from app.services import substitution_recommender as recommender
from app.services import substitutions as sub_service
from app.services.slip_layout import SlipError

router = APIRouter(tags=["substitutions"])

editor = require_roles(Role.scheduler, Role.director)


def _get_affected(db: Session, affected_id: int) -> AffectedPeriod:
    ap = db.get(AffectedPeriod, affected_id)
    if ap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到受影響節次")
    return ap


def _sub_out(sub: Substitution) -> SubstitutionOut:
    return SubstitutionOut(
        id=sub.id, affected_period_id=sub.affected_period_id, type=sub.type,
        type_label=SUBSTITUTION_TYPE_CN.get(sub.type, sub.type),
        handler_teacher_id=sub.handler_teacher_id,
        handler_name=sub.handler.name if sub.handler else None,
        counts_toward_hours=sub.counts_toward_hours, funding_source=sub.funding_source,
        swap_date=sub.swap_date, swap_period_name=sub.swap_period_name,
        swap_class_names=sub.swap_class_names, swap_subject_name=sub.swap_subject_name,
        created_by_name=sub.created_by_name,
    )


@router.get("/affected-periods/{affected_id}/recommendations", response_model=RecommendationOut)
def get_recommendations(
    affected_id: int, db: Session = Depends(get_db), _: User = Depends(editor)
):
    """這一節該找誰代:硬性過濾後排序,每位候選附理由。"""
    affected = _get_affected(db, affected_id)
    rec = recommender.recommend(db, affected)
    return RecommendationOut(
        affected_period_id=rec.affected_period_id,
        no_candidate_hint=rec.no_candidate_hint,
        candidates=[
            CandidateOut(
                teacher_id=c.teacher_id, teacher_name=c.teacher_name,
                same_subject=c.same_subject, at_school_that_day=c.at_school_that_day,
                sub_periods_this_month=c.sub_periods_this_month, reasons=list(c.reasons),
            )
            for c in rec.candidates
        ],
    )


@router.get("/affected-periods/{affected_id}/swap-options", response_model=SwapOptionsOut)
def get_swap_options(
    affected_id: int,
    teacher_id: int | None = Query(default=None),
    weeks: int = Query(default=swap_options.DEFAULT_WEEKS, ge=1, le=swap_options.MAX_WEEKS),
    db: Session = Depends(get_db),
    _: User = Depends(editor),
):
    """調課:列出請假那週起 `weeks` 週內可對調的節次。未指定教師時只找也教這個班的老師。"""
    affected = _get_affected(db, affected_id)
    return SwapOptionsOut.model_validate(
        asdict(swap_options.search(db, affected, teacher_id=teacher_id, weeks=weeks)))


@router.get("/swap-slips", response_model=SlipsOut)
def get_swap_slips(
    semester_id: int = Query(...),
    affected_period_ids: list[int] = Query(..., min_length=1, max_length=500),
    db: Session = Depends(get_db),
    _: User = Depends(editor),
):
    """調課通知單(教師調課單 + 班級調課單)的列印資料。非調課的節次略過。"""
    try:
        slips = swap_slips.build(db, semester_id, affected_period_ids)
    except SlipError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return SlipsOut.model_validate(asdict(slips))


@router.get("/substitute-slips", response_model=SlipsOut)
def get_substitute_slips(
    semester_id: int = Query(...),
    affected_period_ids: list[int] = Query(..., min_length=1, max_length=500),
    db: Session = Depends(get_db),
    _: User = Depends(editor),
):
    """代課通知單(教師代課單 + 班級代課單)的列印資料。代課與併班以外的節次略過。"""
    try:
        slips = sub_slips.build(db, semester_id, affected_period_ids)
    except SlipError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return SlipsOut.model_validate(asdict(slips))


@router.put("/affected-periods/{affected_id}/substitution", response_model=SubstitutionOut)
def assign_substitution(
    affected_id: int,
    body: AssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(editor),
):
    """指派處置(代課/調課/併班/自習/不處理);指派即生效並通知處理教師。"""
    affected = _get_affected(db, affected_id)
    try:
        sub = sub_service.assign(
            db, affected,
            sub_type=body.type, handler_teacher_id=body.handler_teacher_id,
            counts_toward_hours=body.counts_toward_hours, funding_source=body.funding_source,
            swap_entry_id=body.swap_entry_id, swap_date=body.swap_date,
            swap_period_no=body.swap_period_no,
            created_by_user_id=user.id, created_by_name=user.username,
        )
    except sub_service.SubstitutionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.add(AuditLog(
        user_id=user.id, username=user.username, action="assign_substitution",
        target_type="affected_period", target_id=affected.id,
        detail=(
            f"{affected.leave_request.teacher.name} {affected.date} {affected.period_name}"
            f" → {SUBSTITUTION_TYPE_CN.get(sub.type, sub.type)}"
            + (f"({sub.handler.name})" if sub.handler else "")
        )[:500],
    ))
    db.commit()
    db.refresh(sub)
    return _sub_out(sub)


@router.delete("/affected-periods/{affected_id}/substitution", status_code=status.HTTP_200_OK)
def clear_substitution(
    affected_id: int, db: Session = Depends(get_db), user: User = Depends(editor)
):
    """撤回處置:退回待處理,已指派教師收到取消通知。"""
    affected = _get_affected(db, affected_id)
    try:
        sub_service.clear(db, affected, actor_name=user.username)
    except sub_service.SubstitutionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return {"affected_period_id": affected.id, "status": affected.status}


@router.get("/substitution-types", response_model=dict[str, str])
def substitution_types(_: User = Depends(editor)):
    return {t.value: SUBSTITUTION_TYPE_CN[t.value] for t in SubstitutionType}


@router.get("/substitution-funding-sources", response_model=list[str])
def substitution_funding_sources(_: User = Depends(editor)):
    """代課鐘點的計費方式常用選項(印在代課通知單上);畫面也允許自行輸入。"""
    return list(FUNDING_SOURCES)


@router.get("/affected-periods/{affected_id}/substitution", response_model=SubstitutionOut | None)
def get_substitution(
    affected_id: int, db: Session = Depends(get_db), _: User = Depends(editor)
):
    sub = db.scalar(select(Substitution).where(Substitution.affected_period_id == affected_id))
    return _sub_out(sub) if sub else None
