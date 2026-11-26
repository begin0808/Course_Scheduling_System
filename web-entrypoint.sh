#!/bin/sh
# web 容器進入點(v1.5.0 起,數發部源碼檢測「容器以 root 執行」)。
#
# v1.7.0 起映像以 USER caddy 啟動,不再先用 root 修權限再降權。
# v1.5.0~v1.6.x 啟動時已把 v1.4 以前 root 寫入的 HTTPS 憑證 volume(/data)改成 caddy 所有;
# 從 v1.4 以前直接跳升的話這裡寫不進去,先擋下來並說明要分兩次升級。
# 綁 80/443 不需要 root:Docker 預設允許容器內一般使用者綁任何埠號。
set -e

if [ ! -w /data ]; then
    cat >&2 <<EOF
[web] HTTPS 憑證資料夾 /data 無法寫入,網頁先不啟動。
[web] 這通常是從 v1.4.x 以前的版本直接升級到 v1.7.0 以後造成的。請分兩次升級:
[web]   1. 把 .env 的 IMAGE_TAG 改成 v1.6.1,執行 docker compose pull 與 docker compose up -d,
[web]      等系統正常啟動(v1.6.1 會自動修正資料夾的權限);
[web]   2. 再把 IMAGE_TAG 改成要升級的版本,重新 pull 與 up -d。
[web] 資料沒有任何變動。詳見升級指南:docs/deploy/upgrade.md
EOF
    exit 1
fi
exec "$@"
