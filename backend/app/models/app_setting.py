"""全域系統設定(M4-3)。

不隸屬任何學期的單校設定,以 key/value 存放(同 constraint_config 的理由:
加一個設定不該要一次遷移)。目前只放 SMTP 寄信設定;日後備份排程、校名等亦可入此。
密碼類欄位存明文——單校自架、DB 僅校內存取;真正的隔離靠部署環境,不在應用層加密。
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), default="")
