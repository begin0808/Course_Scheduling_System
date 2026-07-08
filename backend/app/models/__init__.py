"""ORM models 匯總。

新增 model 時在此 import,Alembic 的 autogenerate 與 env.py 才能偵測到 metadata。
"""

from app.models.user import Role, User, UserRole

__all__ = ["Role", "User", "UserRole"]
