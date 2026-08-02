"""校名設定測試。

校名先前只能在安裝時以 .env 的 SCHOOL_NAME 指定,要改就得編輯檔案並重啟容器——
對只會用網頁的教學組長來說形同改不了。現在存進資料庫、隨時可改。
"""

from app.core.config import settings as env_settings
from app.models.user import Role
from app.services import settings as app_settings
from tests.conftest import make_user

PW = "password123"


def _admin(client, db):
    make_user(db, "adm", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    return client


def test_falls_back_to_env_when_unset(env):
    """既有部署升級後行為不變:沒設定過就沿用 .env 的值。"""
    client, db = env
    assert app_settings.school_name(db) == env_settings.school_name
    assert _admin(client, db).get("/api/settings/school").json()["school_name"] == (
        env_settings.school_name
    )


def test_can_be_changed_without_restart(env):
    client, db = env
    _admin(client, db)
    r = client.put("/api/settings/school", json={"school_name": "臺南市市立敦品國中"})
    assert r.status_code == 200
    assert r.json()["school_name"] == "臺南市市立敦品國中"
    assert app_settings.school_name(db) == "臺南市市立敦品國中"


def test_blank_name_is_rejected(env):
    """空校名會讓匯出課表的表頭變成一片空白,擋在這裡。"""
    client, db = env
    _admin(client, db)
    assert client.put("/api/settings/school", json={"school_name": ""}).status_code == 422
    assert client.put("/api/settings/school", json={"school_name": "   "}).status_code == 200
    # 全空白會被 strip 成空字串,取值時退回 .env
    assert app_settings.school_name(db) == env_settings.school_name


def test_non_admin_cannot_change_it(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    assert client.put("/api/settings/school", json={"school_name": "X"}).status_code == 403


def test_demo_data_sets_the_school_name(env):
    """載入示範資料時校名一併設好,不必再叫使用者去改 .env。"""
    client, db = env
    _admin(client, db)
    client.post("/api/demo-data")
    assert app_settings.school_name(db) == "臺南市市立敦品國中"
