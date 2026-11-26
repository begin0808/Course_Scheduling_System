#!/usr/bin/env bash
# 後端容器進入點。第一個參數決定角色:api(預設)或 worker。
#
#   worker        → 守 default 佇列(自動排課)
#   worker ops    → 守 ops 佇列(匯出/備份/還原/寄信 + 定時任務)
# 兩者同一個映像,只差在守哪條佇列(M6-2)。
set -e

# 不以 root 執行(v1.7.0 起映像以 USER app 啟動)。v1.5.0~v1.6.x 由這裡以 root 把
# v1.4 以前 root 寫入的備份 volume 改成 app 所有再降權;現在沒有 root 可用,
# 所以從 v1.4 以前直接跳升會寫不進備份資料夾——先擋下來,不要在沒有備份的情況下升級資料庫。
BACKUP_DIR="${BACKUP_DIR:-/backups}"
if [ -d "$BACKUP_DIR" ] && [ ! -w "$BACKUP_DIR" ]; then
    cat >&2 <<EOF
[entrypoint] 備份資料夾 $BACKUP_DIR 無法寫入,系統先不啟動。
[entrypoint] 這通常是從 v1.4.x 以前的版本直接升級到 v1.7.0 以後造成的。請分兩次升級:
[entrypoint]   1. 把 .env 的 IMAGE_TAG 改成 v1.6.1,執行 docker compose pull 與 docker compose up -d,
[entrypoint]      等系統正常啟動(v1.6.1 會自動修正備份資料夾的權限);
[entrypoint]   2. 再把 IMAGE_TAG 改成要升級的版本,重新 pull 與 up -d。
[entrypoint] 資料沒有任何變動。詳見升級指南:docs/deploy/upgrade.md
EOF
    exit 1
fi

ROLE="${1:-api}"

if [ "$ROLE" = "api" ]; then
    # 結構要升級時先自動備份(v1.3.0;備份失敗照常升級並提示系統管理員)
    echo "[entrypoint] 執行資料庫遷移(結構有變更時先自動備份)..."
    python -m app.scripts.migrate
    echo "[entrypoint] 啟動 API (uvicorn) ..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$ROLE" = "worker" ]; then
    shift
    echo "[entrypoint] 啟動 RQ worker(佇列:${*:-default})..."
    exec python -m app.workers.worker "$@"
else
    echo "[entrypoint] 未知角色: $ROLE(可用:api、worker [佇列])" >&2
    exit 1
fi
