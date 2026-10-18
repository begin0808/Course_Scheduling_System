"""系統版本與新版本提醒(v1.2.3)。"""

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.services import update_check, upgrade_notice

router = APIRouter(tags=["system"])

admin_only = require_roles(Role.admin)


class VersionOut(BaseModel):
    version: str


class UpdateStatusOut(BaseModel):
    enabled: bool
    current: str
    latest: str = ""
    latest_url: str = ""
    published_at: str = ""
    checked_at: str = ""
    update_available: bool = False
    error: str = ""


@router.get("/system/version", response_model=VersionOut)
def get_version(_: User = Depends(get_active_user)):
    """目前執行的系統版本(建置映像時注入)。登入者皆可看,回報問題時用得到。"""
    return VersionOut(version=update_check.current_version())


class UpgradeNoticeOut(BaseModel):
    """資料表結構升級後的一次性提示(v1.3.0)。"""

    version: str = ""
    at: str = ""
    backup: str = ""   # 升級前自動備份的檔名
    error: str = ""    # 自動備份失敗的原因(系統仍照常升級)


@router.get("/system/upgrade-notice", response_model=UpgradeNoticeOut | None)
def get_upgrade_notice(db: Session = Depends(get_db), _: User = Depends(admin_only)):
    """最近一次結構升級的提示;按過「知道了」或從未升級過時為 null。"""
    data = upgrade_notice.get(db)
    if data is None:
        return None
    return UpgradeNoticeOut(**{k: str(data.get(k, "")) for k in UpgradeNoticeOut.model_fields})


@router.post("/system/upgrade-notice/dismiss", status_code=204)
def dismiss_upgrade_notice(db: Session = Depends(get_db), _: User = Depends(admin_only)) -> None:
    upgrade_notice.dismiss(db)
    db.commit()


@router.get("/system/update", response_model=UpdateStatusOut)
def get_update_status(
    refresh: bool = Query(default=False, description="立即重新查詢(至少間隔一分鐘)"),
    db: Session = Depends(get_db),
    _: User = Depends(admin_only),
):
    """目前版本與 GitHub 上的最新正式版。最多一天連外查一次;只提醒,不會自動升級。"""
    result = update_check.status(db, refresh=refresh)
    db.commit()
    return UpdateStatusOut(**asdict(result))
