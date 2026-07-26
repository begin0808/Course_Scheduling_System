"""建立 E2E 驗收所需的前置狀態(僅供開發機與 CI 使用,正式站不要執行)。

- 教學組長帳號 e2e_scheduler / e2etest1234(見 frontend/e2e/helpers.ts)
- 教師帳號 e2e_teacher / e2eteacher1234(供測試綁定「陳老師」)
- 系統管理員帳號 e2e_admin / e2eadmin1234(系統管理頁的備份/SMTP 卡片只有 admin 看得到)
- **首次登入帳號** e2e_newuser / e2enewuser1234(`must_change_password=True`)
- 將設定精靈標記為已完成(否則路由守衛會把組長導回 /wizard,
  wizard.spec 會自行 reset 再走完整流程,不受影響)

冪等:已存在的帳號不重建、不改密碼。**唯一例外是 e2e_newuser**——見下方說明。
用法(容器內):
    docker compose exec -T api python -m app.scripts.seed_e2e
"""

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.user import Role, User
from app.models.wizard import SINGLETON_ID, WizardState
from app.services.users import create_user

_ACCOUNTS: list[tuple[str, str, Role, str]] = [
    ("e2e_scheduler", "e2etest1234", Role.scheduler, "E2E 教學組長"),
    ("e2e_teacher", "e2eteacher1234", Role.teacher, "E2E 教師"),
    ("e2e_admin", "e2eadmin1234", Role.admin, "E2E 系統管理員"),
]

# 「首次登入強制改密」是每位新使用者必經的第一個畫面,而那一頁**只有在強制狀態下進得去**
# (路由守衛會把非強制狀態的人導回儀表板)。測試跑完必然把這個狀態消耗掉——它就是去改密碼的——
# 所以這個帳號每次 seed 都強制重設回「首次登入」,否則第二次跑 e2e 會因為狀態已被用掉而失敗。
NEW_USER = ("e2e_newuser", "e2enewuser1234", Role.scheduler, "E2E 首次登入使用者")


def _reset_first_login_account(db) -> None:
    username, password, role, display = NEW_USER
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        create_user(
            db, username, password, [role],
            display_name=display, must_change_password=True,
        )
        print(f"已建立帳號:{username}(首次登入狀態)")
        return
    user.password_hash = hash_password(password)
    user.must_change_password = True
    print(f"已重設回首次登入狀態:{username}")


def seed() -> None:
    with SessionLocal() as db:
        for username, password, role, display in _ACCOUNTS:
            if db.scalar(select(User).where(User.username == username)):
                print(f"帳號已存在,略過:{username}")
                continue
            create_user(
                db, username, password, [role],
                display_name=display, must_change_password=False,
            )
            print(f"已建立帳號:{username}({role.value})")

        _reset_first_login_account(db)

        state = db.get(WizardState, SINGLETON_ID)
        if state is None:
            state = WizardState(id=SINGLETON_ID, current_step=0, completed=True)
            db.add(state)
        else:
            state.completed = True
        db.commit()
        print("設定精靈已標記完成")


if __name__ == "__main__":
    seed()
