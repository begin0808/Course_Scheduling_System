"""Fable 5 最終總體檢 A/B 的回歸測試:SECRET_KEY 防呆、HTTPS 自動開 cookie Secure。"""

import re

from app.core.config import Settings


def _mk(**kw) -> Settings:
    # _env_file=None:不讀取任何 .env,測試只看傳入值與衍生邏輯
    return Settings(_env_file=None, **kw)


# ── A:SECRET_KEY 防呆 ──────────────────────────────────────
def test_default_secret_is_replaced_with_random():
    s = _mk(secret_key="dev-insecure-change-me")
    assert s.secret_key != "dev-insecure-change-me"
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_example_secret_is_replaced():
    s = _mk(secret_key="please-change-this-to-a-random-secret")
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_empty_secret_is_replaced():
    s = _mk(secret_key="")
    assert re.fullmatch(r"[0-9a-f]{64}", s.secret_key)


def test_real_secret_is_preserved():
    s = _mk(secret_key="a-real-configured-secret-value-123")
    assert s.secret_key == "a-real-configured-secret-value-123"


def test_two_defaults_get_different_random_keys():
    assert _mk(secret_key="").secret_key != _mk(secret_key="").secret_key


# ── B:SITE_ADDRESS 網域 → cookie_secure 自動 True ──────────
def test_domain_enables_cookie_secure():
    assert _mk(secret_key="x-real", site_address="school.example.edu.tw").cookie_secure is True


def test_no_domain_keeps_cookie_secure_false():
    assert _mk(secret_key="x-real").cookie_secure is False


def test_port_only_site_address_is_not_a_domain():
    assert _mk(secret_key="x-real", site_address=":80").cookie_secure is False


def test_explicit_cookie_secure_overrides_derivation():
    # 設了網域但顯式 COOKIE_SECURE=false → 尊重顯式設定,不自動翻 True
    s = _mk(secret_key="x-real", site_address="school.example.edu.tw", cookie_secure=False)
    assert s.cookie_secure is False
