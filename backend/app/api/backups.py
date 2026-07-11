"""資料庫備份與還原(M5-2)。系統管理員專用。

清單/下載/上傳由 api 直接讀寫共掛的備份 volume;實際 pg_dump/pg_restore 派到 worker。
還原一律**先自動備份現狀**(可反悔),完成後強制全員重新登入。
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.audit import AuditLog
from app.models.user import Role, User
from app.schemas.backup import BackupOut, RestoreResult
from app.services import backup as backup_service
from app.workers import queue as job_queue

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backups"])

admin_only = require_roles(Role.admin)


def _out(info: backup_service.BackupInfo) -> BackupOut:
    return BackupOut.of(info.name, info.size_bytes, info.created_at, info.reason)


@router.get("/backups", response_model=list[BackupOut])
def list_backups(_: User = Depends(admin_only)):
    return [_out(i) for i in backup_service.list_backups()]


@router.post("/backups", response_model=BackupOut, status_code=status.HTTP_201_CREATED)
def create_backup(db: Session = Depends(get_db), user: User = Depends(admin_only)):
    """立即備份(pg_dump 於 worker)。"""
    try:
        data = job_queue.run_backup("manual")
    except job_queue.BackupJobError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"備份失敗:{e}") from e
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="create_backup",
        target_type="backup", target_id=None, detail=data["name"],
    ))
    db.commit()
    return BackupOut.of(**{k: data[k] for k in ("name", "size_bytes", "created_at", "reason")})


def _get_backup(name: str) -> backup_service.BackupInfo:
    info = next((i for i in backup_service.list_backups() if i.name == name), None)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到備份")
    return info


@router.get("/backups/{name}/download")
def download_backup(name: str, _: User = Depends(admin_only)):
    info = _get_backup(name)
    from app.core.config import settings
    return FileResponse(
        path=f"{settings.backup_dir}/{info.name}",
        media_type="application/octet-stream", filename=info.name,
    )


@router.delete("/backups/{name}", status_code=status.HTTP_200_OK)
def delete_backup(name: str, db: Session = Depends(get_db), user: User = Depends(admin_only)):
    import os
    info = _get_backup(name)
    from app.core.config import settings
    try:
        os.remove(f"{settings.backup_dir}/{info.name}")
    except OSError as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "刪除失敗") from e
    db.add(AuditLog(
        user_id=user.id, username=user.username, action="delete_backup",
        target_type="backup", target_id=None, detail=info.name,
    ))
    db.commit()
    return {"deleted": info.name}


def _restore(user: User, target_name: str) -> RestoreResult:
    """先備份現狀,再還原;完成後強制全員重新登入。"""
    try:
        presafe = job_queue.run_backup("presafe")
        job_queue.run_restore(target_name)
    except job_queue.BackupJobError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"還原失敗:{e}") from e
    # 還原已覆蓋整個資料庫並中止舊連線(含本請求的連線),且原本的資料已被取代;
    # 稽核要以**新連線**寫進**還原後**的資料庫,否則不是連線已死就是紀錄被覆蓋掉。
    from app.core.db import SessionLocal, engine
    engine.dispose()
    try:
        with SessionLocal() as fresh:
            fresh.add(AuditLog(
                user_id=user.id, username=user.username, action="restore_backup",
                target_type="backup", target_id=None,
                detail=f"還原自 {target_name};現狀已備份為 {presafe['name']}",
            ))
            fresh.commit()
    except Exception:  # noqa: BLE001 - 稽核補寫失敗不該推翻已完成的還原
        logger.warning("還原後補寫稽核失敗", exc_info=True)
    return RestoreResult(restored_from=target_name, presafe_backup=presafe["name"])


@router.post("/backups/{name}/restore", response_model=RestoreResult)
def restore_backup(name: str, user: User = Depends(admin_only)):
    """從既有備份還原(還原前自動備份現狀)。"""
    _get_backup(name)
    return _restore(user, name)


@router.post("/backups/restore-upload", response_model=RestoreResult)
async def restore_from_upload(
    file: UploadFile = File(...),
    user: User = Depends(admin_only),
):
    """上傳備份檔並還原。非法檔案直接拒絕、不動資料庫(驗收②)。"""
    content = await file.read()
    try:
        name = backup_service.save_uploaded(file.filename or "upload", content)
    except backup_service.BackupError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _restore(user, name)
