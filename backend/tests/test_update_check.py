"""v1.2.3:系統版本與新版本提醒。

一律不真的連外:以 monkeypatch 取代 `_fetch_latest`,並計算被呼叫幾次——
「最多一天查一次」「連不上也不會每次開頁面都重試」是這個功能對學校主機的承諾。
"""

from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.models.user import Role
from app.services import update_check
from tests.conftest import make_user

PW = "password123"


@pytest.mark.parametrize("tag, expected", [
    ("v1.2.3", (1, 2, 3)),
    ("1.10.0", (1, 10, 0)),
    ("v1.3.0-rc1", None),
    ("dev", None),
    ("main-abc1234", None),
    ("", None),
])
def test_parse_version(tag, expected):
    assert update_check.parse_version(tag) == expected


class _FakeGitHub:
    def __init__(self, tag="v1.2.3", fail=False):
        self.tag, self.fail, self.calls = tag, fail, 0

    def __call__(self, url):
        self.calls += 1
        if self.fail:
            raise OSError("network unreachable")
        return {"latest": self.tag, "latest_url": f"https://example.test/{self.tag}",
                "published_at": "2026-09-20T00:00:00Z"}


@pytest.fixture
def gh(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "app_version", "v1.2.2")
    monkeypatch.setattr(s, "update_check_enabled", True)
    fake = _FakeGitHub()
    monkeypatch.setattr(update_check, "_fetch_latest", fake)
    return fake


def _age_cache(db, delta):
    """把快取的查詢時間往前推,模擬時間經過。"""
    import json

    from app.services import settings as app_settings

    cache = json.loads(app_settings.get(db, update_check.CACHE_KEY))
    checked = update_check.datetime.fromisoformat(cache["checked_at"]) - delta
    cache["checked_at"] = checked.isoformat()
    app_settings.set_value(db, update_check.CACHE_KEY, json.dumps(cache))
    db.flush()


def test_newer_release_is_reported_and_cached_for_a_day(db, gh):
    st = update_check.status(db)
    assert (st.current, st.latest, st.update_available) == ("v1.2.2", "v1.2.3", True)
    assert st.latest_url.endswith("v1.2.3") and st.checked_at and st.error == ""

    update_check.status(db)
    update_check.status(db, refresh=True)  # 一分鐘內的「立即檢查」也不連外
    assert gh.calls == 1

    _age_cache(db, timedelta(hours=25))
    update_check.status(db)
    assert gh.calls == 2


def test_refresh_after_a_minute_queries_again(db, gh):
    update_check.status(db)
    _age_cache(db, timedelta(minutes=2))
    update_check.status(db, refresh=True)
    assert gh.calls == 2


def test_same_or_older_release_is_not_an_update(db, gh, monkeypatch):
    gh.tag = "v1.2.2"
    assert update_check.status(db).update_available is False
    monkeypatch.setattr(get_settings(), "app_version", "v1.3.0")
    _age_cache(db, timedelta(hours=25))
    assert update_check.status(db).update_available is False


def test_dev_build_shows_latest_but_never_claims_an_update(db, gh, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_version", "dev")
    st = update_check.status(db)
    assert st.latest == "v1.2.3" and st.update_available is False


def test_offline_school_keeps_last_known_version_and_does_not_retry(db, gh):
    update_check.status(db)                      # 先成功一次
    gh.fail = True
    _age_cache(db, timedelta(hours=25))
    st = update_check.status(db)
    assert "無法連線" in st.error
    assert st.latest == "v1.2.3" and st.update_available is True  # 沿用上次查到的
    update_check.status(db)
    assert gh.calls == 2                         # 失敗也快取,不會每次開頁面都重試


def test_disabled_never_connects(db, gh, monkeypatch):
    monkeypatch.setattr(get_settings(), "update_check_enabled", False)
    st = update_check.status(db, refresh=True)
    assert st.enabled is False and st.current == "v1.2.2" and st.latest == ""
    assert gh.calls == 0


def test_api_version_for_everyone_update_status_for_admin_only(env, gh):
    client, db = env
    make_user(db, "t", PW, roles=[Role.teacher])
    make_user(db, "adm", PW, roles=[Role.admin])

    client.post("/api/auth/login", json={"username": "t", "password": PW})
    assert client.get("/api/system/version").json() == {"version": "v1.2.2"}
    assert client.get("/api/system/update").status_code == 403

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "adm", "password": PW})
    body = client.get("/api/system/update").json()
    assert body["enabled"] is True and body["update_available"] is True
    assert body["latest"] == "v1.2.3"
