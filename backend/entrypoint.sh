#!/usr/bin/env bash
# 後端容器進入點。第一個參數決定角色:api(預設)或 worker。
#
#   worker        → 守 default 佇列(自動排課)
#   worker ops    → 守 ops 佇列(匯出/備份/還原/寄信 + 定時任務)
# 兩者同一個映像,只差在守哪條佇列(M6-2)。
set -e

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
