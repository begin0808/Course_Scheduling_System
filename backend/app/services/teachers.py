"""教師相關共用邏輯。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.basedata import Teacher
from app.models.user import User


def current_teacher(db: Session, user: User, semester_id: int) -> Teacher | None:
    """解析登入者在指定學期綁定的教師主檔(無綁定則回 None)。

    M2-5「教師查本人課表」、M4 請假自登/代課確認皆以此定位當前教師。
    綁定唯一性由 uq(semester_id, user_id) 保證,故至多一筆。
    """
    return db.scalar(
        select(Teacher).where(
            Teacher.semester_id == semester_id, Teacher.user_id == user.id
        )
    )
