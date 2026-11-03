"""課表匯出:班級/教師/場地 Excel/PDF/PNG、全校總表、批次 zip(M5-1)。

全校總表與批次 zip 原本只有 Excel,v1.4.6 加上 PDF(LINE 社群組長)。

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
    # 教師版是後來補的(使用者回報 #22);預設 class 讓舊的呼叫方式照常運作
    view: str = Query("class", pattern="^(class|teacher)$"),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """全校總表:一個 Excel,每班(或每位教師)一個分頁。"""
    try:
        data = tex.school_workbook(db, semester_id, view)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    name = "全校教師課表總表" if view == "teacher" else "全校課表總表"
    return _download(data, f"{name}_{semester_id}", "xlsx")


def _school_pdfs(db: Session, semester_id: int, view: str, *, split: bool):
    """全校課表渲染成 PDF:split=False 一份(每張一頁起),True 每張一檔(v1.4.6)。"""
    try:
        items, meta = tex.school_grids(db, semester_id, view)
    except tex.ExportError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    if not items:
        what = "在職教師" if view == "teacher" else "班級"
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"這學期沒有{what},沒有課表可以匯出")
    try:
        pdfs = job_queue.render_export_set(
            [tex.grid_to_html(g, meta) for _, g in items], split=split)
    except job_queue.RenderError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return items, pdfs


@router.get("/export/school.pdf")
def export_school_pdf(
    semester_id: int = Query(...),
    view: str = Query("class", pattern="^(class|teacher)$"),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """全校總表 PDF:一個檔,每班(或每位教師)一頁,方便一次列印(LINE 社群組長,v1.4.6)。"""
    _, pdfs = _school_pdfs(db, semester_id, view, split=False)
    name = "全校教師課表總表" if view == "teacher" else "全校課表總表"
    return _download(pdfs[0], f"{name}_{semester_id}", "pdf")


@router.get("/export/batch.zip")
def export_batch(
    semester_id: int = Query(...),
    view: str = Query("class", pattern="^(class|teacher)$"),
    # PDF 是後來補的(LINE 社群組長,v1.4.6);預設 xlsx 讓舊的呼叫方式照常運作
    fmt: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """批次匯出:全部班級(或全部教師)各一個 Excel 或 PDF,打包成 zip。"""
    if fmt == "pdf":
        items, pdfs = _school_pdfs(db, semester_id, view, split=True)
        data = tex.zip_files(
            [(f"{name}.pdf", pdf) for (name, _), pdf in zip(items, pdfs, strict=True)])
    else:
        try:
            data = tex.batch_zip(db, semester_id, view)
        except tex.ExportError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    name = "全校教師課表" if view == "teacher" else "全校班級課表"
    suffix = "_PDF" if fmt == "pdf" else ""
    return _download(data, f"{name}{suffix}_{semester_id}", "zip")
