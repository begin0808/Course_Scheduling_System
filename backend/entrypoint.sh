#!/usr/bin/env bash
# 後端容器進入點。第一個參數決定角色:api(預設)或 worker。
set -e

ROLE="${1:-api}"

if [ "$ROLE" = "api" ]; then
    echo "[entrypoint] 執行資料庫遷移 alembic upgrade head ..."
    alembic upgrade head
    echo "[entrypoint] 啟動 API (uvicorn) ..."
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$ROLE" = "worker" ]; then
    echo "[entrypoint] 啟動 RQ worker ..."
    exec python -m app.workers.worker
else
    echo "[entrypoint] 未知角色: $ROLE(可用:api、worker)" >&2
    exit 1
fi
