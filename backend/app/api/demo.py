"""示範資料:一鍵建出一所完整的示範國中。管理員專用。

存在的理由:剛裝好的系統是空的,要看到自動排課做了什麼,得先手 key 十八個班級、
四十幾位教師、四百多筆配課。這道門檻會擋掉絕大多數想評估這套系統的人。

安全性:只在「完全沒有任何學期」時才允許執行。用學期是否為空來判斷不夠——
使用者可能已經開了新學期正準備建資料,一鍵灌進 18 個班會讓他不知所措。
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.services import demo_data

router = APIRouter(tags=["demo"])

admin_only = require_roles(Role.admin)


class DemoDataOut(BaseModel):
    semester_id: int
    classes: int
    teachers: int
    subjects: int
    rooms: int
    assignments: int
    total_periods: int
    max_overtime_used: int
    under_target: int


class DemoDataStatus(BaseModel):
    available: bool
    reason: str = ""


@router.get("/demo-data", response_model=DemoDataStatus)
def demo_status(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """能不能載入示範資料。前端用它決定按鈕要不要 disable。"""
    if demo_data.any_semester_exists(db):
        return DemoDataStatus(
            available=False,
            reason="系統已有學期資料。示範資料只能建在全新的系統上,以免覆蓋你的正式資料。",
        )
    return DemoDataStatus(available=True)


@router.post("/demo-data", response_model=DemoDataOut, status_code=status.HTTP_201_CREATED)
def create_demo_data(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    if demo_data.any_semester_exists(db):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "系統已有學期資料,無法載入示範資料。"
            "示範資料是給全新系統試用的;若要重來,請先刪除既有學期。",
        )
    summary = demo_data.generate(db)
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_demo_data",
        target_type="semester", target_id=summary.semester_id,
        detail=(
            f"載入示範資料:{summary.classes} 班、{summary.teachers} 位教師、"
            f"{summary.assignments} 筆配課,共 {summary.total_periods} 節"
        ),
    ))
    db.commit()
    return DemoDataOut(**summary.__dict__)
