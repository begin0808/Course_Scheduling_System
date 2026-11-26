"""v1.5.0 數發部源碼檢測的修補:寄信加密驗證憑證、程式碼不內建密碼與金鑰、首次啟動臨時密碼。

v1.6.0:寄信一律加密(不再有不加密的選項);測試用密碼改為執行時產生,不寫在程式碼裡。
"""

import logging
import secrets
import ssl
from urllib.parse import quote

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.core.security import verify_password
from app.models.user import User
from app.services import email as email_service
from app.services import users as users_service
from app.services.settings import SmtpConfig


# ── 寄信:465 走 SMTPS、其他埠一律 STARTTLS,兩者都驗證憑證 ────────────
class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.context = host, port, context
        self.starttls_context: ssl.SSLContext | None = None
        self.started_tls = False
        _FakeSMTP.instances.append(self)

    def starttls(self, context=None):
        self.started_tls = True
        self.starttls_context = context

    def close(self):
        pass


def _cfg(port: int) -> SmtpConfig:
    return SmtpConfig(host="smtp.example.edu.tw", port=port, user="u",
                      password=secrets.token_urlsafe(8), sender="noreply@example.edu.tw")


def _verifies(ctx: ssl.SSLContext | None) -> bool:
    return ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_smtps_on_465_verifies_certificate(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP",
                        lambda *a, **k: pytest.fail("465 不該走明文 SMTP"))
    server = email_service._connect(_cfg(465))
    assert server.port == 465 and _verifies(server.context)


@pytest.mark.parametrize("port", [587, 25, 2525])
def test_every_other_port_always_uses_starttls(monkeypatch, port):
    """v1.6.0:不再有「不勾 TLS 就明文寄」的路徑,連 25 埠也一律 STARTTLS 並驗證憑證。"""
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    server = email_service._connect(_cfg(port))
    assert server.started_tls and _verifies(server.starttls_context)


def test_server_without_starttls_fails_instead_of_sending_plaintext(monkeypatch):
    class _NoTLS(_FakeSMTP):
        closed = False

        def starttls(self, context=None):
            raise email_service.smtplib.SMTPNotSupportedError("STARTTLS extension not supported")

        def close(self):
            _NoTLS.closed = True

    monkeypatch.setattr(email_service.smtplib, "SMTP", _NoTLS)
    with pytest.raises(email_service.smtplib.SMTPNotSupportedError):
        email_service._connect(_cfg(25))
    assert _NoTLS.closed


def test_old_tls_unchecked_setting_is_ignored(db, monkeypatch):
    """舊版存了 smtp_tls=0 的學校,升級後照樣加密寄信。"""
    from app.services import settings as app_settings
    app_settings.set_value(db, "smtp_tls", "0")
    app_settings.save_smtp(db, host="smtp.example.edu.tw", port=25, user="", password="",
                           sender="noreply@example.edu.tw")
    db.commit()
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    server = email_service._connect(app_settings.smtp_config(db))
    assert server.started_tls


def test_unconfigured_smtp_defaults_to_587(db):
    from app.services import settings as app_settings
    assert app_settings.smtp_config(db).port == 587


# ── 設定:程式碼不內建資料庫密碼、管理員密碼、金鑰 ─────────────────────
def test_database_url_built_from_postgres_settings():
    # 密碼含 @ 與 / 也要正確編碼;測試用的值每次執行時產生,不寫死在程式碼裡
    secret = f"{secrets.token_urlsafe(6)}@{secrets.token_urlsafe(6)}/x"
    s = Settings(_env_file=None, database_url="", postgres_password=SecretStr(secret),
                 postgres_host="db", postgres_user="sch", postgres_db="sdb")
    assert s.database_url == f"postgresql+psycopg://sch:{quote(secret, safe='')}@db:5432/sdb"


def test_existing_database_url_wins():
    url = f"postgresql+psycopg://a:{secrets.token_hex(4)}@old:5432/c"
    s = Settings(_env_file=None, database_url=url,
                 postgres_password=SecretStr(secrets.token_hex(4)))
    assert s.database_url == url


def test_no_password_anywhere_by_default():
    s = Settings(_env_file=None, database_url="")
    assert s.database_url == "postgresql+psycopg://scheduler@postgres:5432/scheduler"
    assert s.admin_password is None
    # 沒設 SECRET_KEY → 每次啟動隨機產生
    assert s.secret_key and len(s.secret_key) == 64
    assert Settings(_env_file=None).secret_key != s.secret_key


@pytest.mark.parametrize("old", ["dev-insecure-change-me", "please-change-this-to-a-random-secret"])
def test_known_example_secrets_are_replaced(old):
    assert Settings(_env_file=None, secret_key=old).secret_key != old


# ── 首次啟動:沒設 ADMIN_PASSWORD 不再把密碼寫進紀錄(v1.7.0) ─────────────
@pytest.fixture
def boot_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(users_service, "SessionLocal", Session)
    return Session


def test_first_boot_without_admin_password_never_logs_a_password(boot_db, monkeypatch, caplog):
    # v1.5.0 會把臨時密碼寫在啟動紀錄;v1.7.0 起改請架設的人用重設指令自己設定
    monkeypatch.setattr(users_service, "temp_password", lambda: "Kx7pQ2mN9rTw")
    monkeypatch.setattr(users_service.settings, "admin_password", None)
    with caplog.at_level(logging.WARNING, logger="app.users"):
        users_service.ensure_admin()
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "Kx7pQ2mN9rTw" not in logs
    assert "app.scripts.reset_admin" in logs
    with boot_db() as db:
        admin = db.scalar(select(User))
        assert admin.username == "admin"
        assert verify_password("Kx7pQ2mN9rTw", admin.password_hash)  # 沒人知道的隨機密碼


def test_first_boot_with_admin_password_uses_it(boot_db, monkeypatch, caplog):
    chosen = secrets.token_urlsafe(10)
    monkeypatch.setattr(users_service.settings, "admin_password", SecretStr(chosen))
    with caplog.at_level(logging.WARNING, logger="app.users"):
        users_service.ensure_admin()
    assert not any("reset_admin" in r.getMessage() for r in caplog.records)
    with boot_db() as db:
        assert verify_password(chosen, db.scalar(select(User)).password_hash)
