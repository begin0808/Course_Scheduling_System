"""課表匯出:班級/教師/場地 Excel/PDF/PNG、全校總表、批次 zip(M5-1)。

Excel 在 api 同步產生(openpyxl 輕量);PDF/PNG 派到 worker(WeasyPrint + 中文字型)
再取回。單一對象匯出開放給所有登入者(課表本就全校可查);全校總表/批次限教學組長以上。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_active_user, require_roles
from app.core.db import get_db
from app.models.user import Role, User
from app.services import timetable_export as tex
from app.workers import queue as job_queue

router = APIRouter(tags=["exports"])

manager = require_roles(Role.scheduler, Role.director)

_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "png": "image/png",
    "zip": "application/zip",
}


def _download(data: bytes, filename: str, ext: str) -> Response:
    # 中文檔名以 RFC 5987 filename* 表達;filename 提供 ASCII 後備
    quoted = quote(filename)
    disposition = f"attachment; filename=\"export.{ext}\"; filename*=UTF-8''{quoted}.{ext}"
    return Response(
        content=data, media_type=_MIME[ext],
        headers={"Content-Disposition": disposition},
    )


@router.get("/export/timetable")
def export_timetable(
    semester_id: int = Query(...),
    view: str = Query(..., pattern="^(class|teacher|room)$"),
    target_id: int = Query(...),
    fmt: str = Query("xlsx", pattern="^(xlsx|pdf|png)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_active_user),
):
    """單一班級/教師/場地的課表,格式 xlsx/pdf/png。"""
    try:
        grid, meta = tex.build_grid(db, semester_id, view, target_id)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e

    filename = f"{grid.title}_{meta.semester_label}"
    if fmt == "xlsx":
        return _download(tex.grids_to_xlsx([grid], meta), filename, "xlsx")

    html = tex.grid_to_html(grid, meta)
    try:
        data = job_queue.render_export(html, fmt)
    except job_queue.RenderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return _download(data, filename, fmt)


@router.get("/export/school.xlsx")
def export_school(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """全校總表:一個 Excel,每班一個分頁。"""
    try:
        data = tex.school_workbook(db, semester_id)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return _download(data, f"全校課表總表_{semester_id}", "xlsx")


@router.get("/export/batch.zip")
def export_batch(
    semester_id: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """批次匯出:全部班級各一個 Excel,打包成 zip。"""
    try:
        data = tex.class_batch_zip(db, semester_id)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    return _download(data, f"全校班級課表_{semester_id}", "zip")
