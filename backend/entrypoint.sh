#!/usr/bin/env bash
# 後端容器進入點。第一個參數決定角色:api(預設)或 worker。
#
#   worker        → 守 default 佇列(自動排課)
#   worker ops    → 守 ops 佇列(匯出/備份/還原/寄信 + 定時任務)
# 兩者同一個映像,只差在守哪條佇列(M6-2)。
set -e

# 不以 root 執行(v1.5.0):以 root 啟動時,先把備份 volume 的擁有者改成 app
# (v1.4 以前的備份是 root 寫入的),再降成 app 使用者重新執行本腳本。
# docker compose exec 進來的維運指令(reset_admin 等)不經過這裡,照常可用。
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /backups 2>/dev/null || true
    exec setpriv --reuid=app --regid=app --init-groups env HOME=/home/app "$0" "$@"
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
