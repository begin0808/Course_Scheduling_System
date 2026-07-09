"""Excel 匯入 API:範本下載、上傳匯入。"""

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.auth import require_roles
from app.core.db import get_db
from app.models.semester import Semester
from app.models.user import Role
from app.services import importer

router = APIRouter(tags=["import"])

editor = require_roles(Role.scheduler)

VALID_ENTITIES = {"subjects", "teachers", "classes", "assignments"}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FILENAMES = {
    "subjects": "subjects", "teachers": "teachers",
    "classes": "classes", "assignments": "assignments",
}


def _check_entity(entity: str) -> None:
    if entity not in VALID_ENTITIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未知的匯入類型")


@router.get("/import/templates/{entity}")
def download_template(entity: str, _: object = Depends(editor)) -> Response:
    _check_entity(entity)
    data = importer.build_template(entity)
    filename = f"{_FILENAMES[entity]}_template.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import/{entity}")
async def upload_import(
    entity: str,
    semester_id: int = Query(...),
    create_accounts: bool = Query(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: object = Depends(editor),
) -> dict:
    _check_entity(entity)
    if db.get(Semester, semester_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到學期")
    content = await file.read()
    try:
        result = importer.run_import(db, entity, semester_id, content, create_accounts)
    except Exception:
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "無法讀取檔案,請確認為有效的 Excel 檔"
        ) from None
    return {"imported": result.imported, "errors": result.errors}
