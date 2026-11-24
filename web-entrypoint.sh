#!/bin/sh
# web 容器進入點(v1.5.0,數發部源碼檢測「容器以 root 執行」)。
#
# 以 root 啟動只為了一件事:把 HTTPS 憑證的 volume(/data、/config)擁有者改成 caddy——
# v1.4 以前是 root 寫進去的,不改的話降權後讀不到既有憑證、也續不了期。
# 改完立刻降成 caddy 使用者執行(做法同官方 postgres、redis 映像)。
# 綁 80/443 不需要 root:Docker 預設允許容器內一般使用者綁任何埠號。
set -e

if [ "$(id -u)" = "0" ]; then
    chown -R caddy:caddy /data /config
    exec su-exec caddy "$@"
fi
exec "$@"
