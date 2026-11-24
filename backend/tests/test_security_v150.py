"""v1.5.0 數發部源碼檢測的修補:寄信加密驗證憑證、程式碼不內建密碼與金鑰、首次啟動臨時密碼。"""

import logging
import ssl

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


# ── 寄信:465 走 SMTPS、勾 TLS 走 STARTTLS,兩者都驗證憑證 ──────────────
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


def _cfg(port: int, use_tls: bool) -> SmtpConfig:
    return SmtpConfig(host="smtp.example.edu.tw", port=port, user="u", password="p",
                      sender="noreply@example.edu.tw", use_tls=use_tls)


def _verifies(ctx: ssl.SSLContext | None) -> bool:
    return ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_smtps_on_465_verifies_certificate(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP",
                        lambda *a, **k: pytest.fail("465 不該走明文 SMTP"))
    server = email_service._connect(_cfg(465, use_tls=False))
    assert server.port == 465 and _verifies(server.context)


def test_starttls_verifies_certificate(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    server = email_service._connect(_cfg(587, use_tls=True))
    assert server.started_tls and _verifies(server.starttls_context)


def test_plain_smtp_only_when_tls_unchecked(monkeypatch):
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    server = email_service._connect(_cfg(25, use_tls=False))
    assert not server.started_tls


def test_unconfigured_smtp_defaults_to_587_with_tls(db):
    from app.services import settings as app_settings
    cfg = app_settings.smtp_config(db)
    assert (cfg.port, cfg.use_tls) == (587, True)


# ── 設定:程式碼不內建資料庫密碼、管理員密碼、金鑰 ─────────────────────
def test_database_url_built_from_postgres_settings():
    s = Settings(_env_file=None, database_url="", postgres_password=SecretStr("p@ss/word"),
                 postgres_host="db", postgres_user="sch", postgres_db="sdb")
    assert s.database_url == "postgresql+psycopg://sch:p%40ss%2Fword@db:5432/sdb"


def test_existing_database_url_wins():
    url = "postgresql+psycopg://a:b@old:5432/c"
    s = Settings(_env_file=None, database_url=url, postgres_password=SecretStr("x"))
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


# ── 首次啟動:沒設 ADMIN_PASSWORD 就產生臨時密碼寫在啟動紀錄 ─────────────
@pytest.fixture
def boot_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(users_service, "SessionLocal", Session)
    return Session


def test_first_boot_without_admin_password_logs_temp_password(boot_db, monkeypatch, caplog):
    monkeypatch.setattr(users_service.settings, "admin_password", None)
    with caplog.at_level(logging.WARNING, logger="app.users"):
        users_service.ensure_admin()
    msg = next(r.getMessage() for r in caplog.records if "臨時密碼" in r.getMessage())
    temp = msg.split("臨時密碼:")[1].split("(")[0]
    assert len(temp) == 12
    with boot_db() as db:
        admin = db.scalar(select(User))
        assert verify_password(temp, admin.password_hash)
        assert admin.must_change_password


def test_first_boot_with_admin_password_uses_it(boot_db, monkeypatch, caplog):
    monkeypatch.setattr(users_service.settings, "admin_password", SecretStr("school-pass-123"))
    with caplog.at_level(logging.WARNING, logger="app.users"):
        users_service.ensure_admin()
    assert not any("臨時密碼" in r.getMessage() for r in caplog.records)
    with boot_db() as db:
        assert verify_password("school-pass-123", db.scalar(select(User)).password_hash)
