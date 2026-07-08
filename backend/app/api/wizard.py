"""設定精靈 API:進度狀態讀寫、重新啟動。"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role
from app.models.wizard import SINGLETON_ID, TOTAL_STEPS, WizardState
from app.schemas.wizard import WizardStateOut, WizardStateUpdate

router = APIRouter(tags=["wizard"])

viewer = require_roles(Role.scheduler, Role.director)
editor = require_roles(Role.scheduler)


def _get_or_create(db: Session) -> WizardState:
    state = db.get(WizardState, SINGLETON_ID)
    if state is None:
        state = WizardState(id=SINGLETON_ID, current_step=0, completed=False)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _to_out(db: Session, state: WizardState) -> WizardStateOut:
    has_semesters = bool(db.scalar(select(func.count()).select_from(Semester)))
    return WizardStateOut(
        current_step=state.current_step,
        completed=state.completed,
        semester_id=state.semester_id,
        total_steps=TOTAL_STEPS,
        has_semesters=has_semesters,
    )


@router.get("/wizard/state", response_model=WizardStateOut)
def get_state(db: Session = Depends(get_db), _: object = Depends(viewer)) -> WizardStateOut:
    return _to_out(db, _get_or_create(db))


@router.patch("/wizard/state", response_model=WizardStateOut)
def update_state(
    body: WizardStateUpdate, db: Session = Depends(get_db), _: object = Depends(editor)
) -> WizardStateOut:
    state = _get_or_create(db)
    data = body.model_dump(exclude_unset=True)
    if "current_step" in data and data["current_step"] is not None:
        state.current_step = max(0, min(data["current_step"], TOTAL_STEPS - 1))
    if "completed" in data and data["completed"] is not None:
        state.completed = data["completed"]
    if "semester_id" in data:
        state.semester_id = data["semester_id"]
    db.commit()
    db.refresh(state)
    return _to_out(db, state)


@router.post("/wizard/reset", response_model=WizardStateOut)
def reset_state(db: Session = Depends(get_db), _: object = Depends(editor)) -> WizardStateOut:
    state = _get_or_create(db)
    state.current_step = 0
    state.completed = False
    state.semester_id = None
    db.commit()
    db.refresh(state)
    return _to_out(db, state)
