"""v1.5.1 寄測試信:用已儲存的設定寄出,失敗時寫出可能原因(自簽憑證、帳密錯誤、找不到主機…)。

v1.6.0:一律加密,設定不再有 use_tls;測試用的 SMTP 密碼執行時產生。
"""

import secrets
import smtplib
import socket
import ssl

import pytest

from app.models.user import Role
from app.services import email as email_service
from app.services.settings import SmtpConfig
from tests.conftest import make_user

PW = "password123"
CFG = SmtpConfig(host="smtp.example.edu.tw", port=587, user="u",
                 password=secrets.token_urlsafe(8), sender="noreply@example.edu.tw")


@pytest.fixture
def admin(env):
    client, db = env
    make_user(db, "admin2", PW, roles=[Role.admin])
    client.post("/api/auth/login", json={"username": "admin2", "password": PW})
    return client


def _save(client, host="smtp.example.edu.tw"):
    r = client.put("/api/settings/smtp", json={
        "host": host, "port": 587, "user": "u", "password": CFG.password,
        "sender": "noreply@example.edu.tw"})
    assert r.status_code == 200


def test_sends_with_saved_settings(admin, monkeypatch):
    _save(admin)
    sent = []
    monkeypatch.setattr(email_service, "send", lambda db, **kw: sent.append(kw) or True)
    r = admin.post("/api/settings/smtp/test", json={"to": " teacher@example.edu.tw "})
    assert r.status_code == 200 and r.json() == {"sent": True, "to": "teacher@example.edu.tw"}
    assert sent[0]["to"] == "teacher@example.edu.tw" and "測試信" in sent[0]["subject"]


def test_unconfigured_and_bad_address_are_rejected(admin):
    r = admin.post("/api/settings/smtp/test", json={"to": "teacher@example.edu.tw"})
    assert r.status_code == 400 and "尚未設定" in r.json()["detail"]
    _save(admin)
    for bad in ["", "teacher", "a b@example.edu.tw", "teacher@localhost"]:
        r = admin.post("/api/settings/smtp/test", json={"to": bad})
        assert r.status_code == 400 and "格式不正確" in r.json()["detail"], bad


def test_failure_explains_self_signed_certificate(admin, monkeypatch):
    _save(admin)

    def boom(db, **kw):
        raise ssl.SSLCertVerificationError(
            1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate")
    monkeypatch.setattr(email_service, "send", boom)
    r = admin.post("/api/settings/smtp/test", json={"to": "teacher@example.edu.tw"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "自簽憑證" in detail and "CERTIFICATE_VERIFY_FAILED" in detail


def test_requires_admin(env):
    client, db = env
    make_user(db, "leader", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "leader", "password": PW})
    r = client.post("/api/settings/smtp/test", json={"to": "teacher@example.edu.tw"})
    assert r.status_code == 403


@pytest.mark.parametrize(("exc", "expected"), [
    (smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials"), "帳號或密碼不正確"),
    (smtplib.SMTPSenderRefused(553, b"not allowed", "noreply@example.edu.tw"),
     "拒絕寄件人「noreply@example.edu.tw」"),
    (smtplib.SMTPRecipientsRefused({"x@example.edu.tw": (550, b"no such user")}), "拒收這個收件人"),
    (smtplib.SMTPNotSupportedError("STARTTLS extension not supported."), "不支援 STARTTLS"),
    (smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "中斷了連線"),
    (ssl.SSLCertVerificationError(1, "certificate verify failed"), "自簽憑證"),
    (ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version"), "連接埠可能不對"),
    (socket.gaierror(-2, "Name or service not known"), "找不到郵件主機「smtp.example.edu.tw」"),
    (TimeoutError("timed out"), "smtp.example.edu.tw:587 逾時"),
    (ConnectionRefusedError(111, "Connection refused"), "smtp.example.edu.tw:587 拒絕連線"),
    (OSError(101, "Network is unreachable"), "連不上郵件主機 smtp.example.edu.tw:587"),
    (RuntimeError(), "寄送失敗(原始訊息:RuntimeError)"),
])
def test_describe_error(exc, expected):
    msg = email_service.describe_error(exc, CFG)
    assert expected in msg and "原始訊息" in msg
