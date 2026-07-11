"""資料庫備份與還原(M5-2)。

以 PostgreSQL 原生工具 pg_dump / pg_restore(custom 格式,可 --clean 還原)。這些工具
只裝在 worker 映像,故實際 dump/restore 在 worker 執行;api 端負責清單、下載、上傳與派工。

- 檔名:`backup_YYYYMMDD_HHMMSS_<reason>.dump`,存放於共掛的 volume(config.backup_dir)。
- 保留 config.backup_keep 份,超出者由舊而新輪替刪除。
- 還原前先驗證檔頭(custom 格式以 `PGDMP` 開頭),非法檔案直接拒絕、不動資料庫(驗收②)。
"""

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlsplit

from app.core.config import settings

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^backup_(\d{8}_\d{6})_([a-z]+)\.dump$")

# pg_restore 進較舊伺服器時,新版 pg_dump 寫入的跨版本 GUC(如 v17 的 transaction_timeout)
# 會讓該筆 SET 失敗但資料不受影響。這類「設定參數不認得」是唯一被容忍的錯誤;
# 其餘任何 `pg_restore: error` 都可能代表資料真的沒還原完整,一律視為失敗。
_IGNORABLE_RESTORE = re.compile(r"unrecognized configuration parameter", re.IGNORECASE)


class BackupError(Exception):
    """備份/還原失敗(呼叫端轉為 4xx/5xx)。"""


@dataclass(frozen=True, slots=True)
class BackupInfo:
    name: str
    size_bytes: int
    created_at: datetime
    reason: str


def _dir() -> str:
    os.makedirs(settings.backup_dir, exist_ok=True)
    return settings.backup_dir


def _db_params() -> dict[str, str]:
    u = urlsplit(settings.database_url)
    return {
        "host": u.hostname or "localhost",
        "port": str(u.port or 5432),
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "dbname": u.path.lstrip("/") or "postgres",
    }


def _env(params: dict[str, str]) -> dict[str, str]:
    e = os.environ.copy()
    e["PGPASSWORD"] = params["password"]
    return e


def _path(name: str) -> str:
    # 防止路徑穿越:只接受單純檔名
    if os.path.basename(name) != name or not name.endswith(".dump"):
        raise BackupError("非法的備份檔名")
    return os.path.join(_dir(), name)


# ── 清單 / 輪替(任何映像可用)──────────────────────────────
def _info(name: str) -> BackupInfo | None:
    m = _NAME_RE.match(name)
    if m is None:
        return None
    full = os.path.join(_dir(), name)
    try:
        st = os.stat(full)
    except OSError:
        return None
    return BackupInfo(
        name=name, size_bytes=st.st_size,
        created_at=datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"),
        reason=m.group(2),
    )


def list_backups() -> list[BackupInfo]:
    """最新在前。"""
    out = [i for f in os.listdir(_dir()) if (i := _info(f)) is not None]
    return sorted(out, key=lambda i: i.name, reverse=True)


def prune(keep: int | None = None) -> list[str]:
    """保留最新 keep 份,刪除其餘。回傳被刪檔名。"""
    keep = settings.backup_keep if keep is None else keep
    backups = list_backups()
    removed = []
    for info in backups[keep:]:
        try:
            os.remove(os.path.join(_dir(), info.name))
            removed.append(info.name)
        except OSError:
            pass
    return removed


def is_valid_dump(path: str) -> bool:
    """custom 格式的 pg_dump 檔以魔數 `PGDMP` 開頭。"""
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"PGDMP"
    except OSError:
        return False


# ── dump / restore(需 pg_dump/pg_restore,worker 映像)──────
def create_backup(reason: str = "manual") -> BackupInfo:
    """跑 pg_dump 產生一份備份並輪替。回傳新備份資訊。"""
    reason = reason if reason.isalpha() else "manual"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}_{reason}.dump"
    path = os.path.join(_dir(), name)
    p = _db_params()
    try:
        subprocess.run(
            ["pg_dump", "-Fc", "-h", p["host"], "-p", p["port"],
             "-U", p["user"], "-d", p["dbname"], "-f", path],
            check=True, env=_env(p), capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise BackupError("找不到 pg_dump(需在 worker 映像執行)") from e
    except subprocess.CalledProcessError as e:
        raise BackupError(f"備份失敗:{e.stderr or e}") from e
    prune()
    info = _info(name)
    if info is None:
        raise BackupError("備份檔產生後無法讀取")
    return info


def _terminate_other_connections(p: dict[str, str]) -> None:
    """還原前踢掉其他連線,避免 pg_restore 的 DROP 被鎖住(盡力而為)。"""
    try:
        import psycopg
        with psycopg.connect(
            host=p["host"], port=int(p["port"]), user=p["user"],
            password=p["password"], dbname=p["dbname"], connect_timeout=5,
        ) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (p["dbname"],),
            )
            conn.commit()
    except Exception:  # noqa: BLE001 - 盡力而為,失敗不阻止還原
        pass


def _classify_restore_stderr(stderr: str) -> list[str]:
    """檢視 pg_restore 的 stderr,回傳可忽略的警告摘要。

    只有「設定參數不認得」(跨版本 GUC 噪音)被容忍;出現任何其他 `pg_restore: error`
    就擲 BackupError——只憑 returncode==1 分不出「跨版本噪音」與「某張表 COPY 失敗」,
    後者若被當成成功,會把資料缺漏報成還原成功。
    """
    warnings: list[str] = []
    for raw in stderr.splitlines():
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if "pg_restore: error" in low or "; error while" in low:
            if _IGNORABLE_RESTORE.search(s):
                warnings.append(s)
                continue
            raise BackupError(f"還原時出現非預期錯誤:{s}")
        if "warning" in low or "errors ignored on restore" in low:
            warnings.append(s)
    return warnings


def restore_backup(name: str) -> list[str]:
    """從指定備份還原(先驗證檔頭)。回傳可忽略的警告摘要;呼叫端負責事後強制重新登入。"""
    path = _path(name)
    if not os.path.exists(path):
        raise BackupError("找不到備份檔")
    if not is_valid_dump(path):
        raise BackupError("這不是有效的備份檔(格式不符),已拒絕還原")
    p = _db_params()
    _terminate_other_connections(p)
    try:
        proc = subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges",
             "-h", p["host"], "-p", p["port"], "-U", p["user"], "-d", p["dbname"], path],
            check=False, env=_env(p), capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise BackupError("找不到 pg_restore(需在 worker 映像執行)") from e
    # returncode>1 直接失敗;==1 需逐行判別是「可忽略的跨版本噪音」還是真正的資料錯誤。
    if proc.returncode > 1:
        raise BackupError(f"還原失敗:{proc.stderr or proc.returncode}")
    warnings = _classify_restore_stderr(proc.stderr) if proc.returncode == 1 else []
    if warnings:
        logger.warning("pg_restore 完成但有可忽略的警告:%s", " | ".join(warnings))
    return warnings


def save_uploaded(name_hint: str, data: bytes) -> str:
    """把上傳的備份檔寫入備份目錄,先驗證格式;回傳實際檔名。非法則拒絕不落地。"""
    if data[:5] != b"PGDMP":
        raise BackupError("這不是有效的備份檔(格式不符)")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"backup_{ts}_upload.dump"
    with open(os.path.join(_dir(), name), "wb") as f:
        f.write(data)
    return name
