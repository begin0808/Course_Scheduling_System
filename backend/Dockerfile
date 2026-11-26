# 後端映像:兩個 target。
#   base   → api 服務(精簡)
#   worker → 背景任務(額外裝 WeasyPrint 系統依賴/中文字型與 PostgreSQL client)
# 明確鎖 trixie:其 main 內含 postgresql-client(17),pg_dump 可備份 v16 伺服器。
FROM python:3.12-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 供 healthcheck 使用;postgresql-client 供「結構升級前自動備份」(v1.3.0)——
# 遷移在 api 容器啟動時執行,備份必須在同一個容器、遷移之前完成。
#
# 系統套件釘版本(v1.7.0,數發部源碼檢測「未固定相依版本」):每次建置裝到的都一樣。
# 代價:Debian 釋出安全更新後舊版本會從套件庫移除,建置就會失敗——
# 發版前執行 python scripts/update_apt_pins.py 更新成目前版本即可(會一併檢查 amd64/arm64)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl=8.14.1-2+deb13u7 \
        postgresql-client=17+278+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

# 不以 root 執行(v1.5.0 起;v1.7.0 改用 USER 指令,容器一啟動就是 app 使用者)。
# 備份資料夾在映像裡就屬於 app,新建的 volume 會沿用這個擁有者;
# v1.4 以前 root 寫入的舊 volume 由 v1.5.0~v1.6.x 啟動時修正過,所以舊版要先升到 v1.6.1。
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /backups && chown app:app /backups

# 先裝相依(利用 layer 快取)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# 應用程式原始碼
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

USER app

# 系統版本(v1.2.3):CI 打版本標籤時以 --build-arg APP_VERSION=v1.2.3 注入,
# 系統管理頁據此顯示目前版本並判斷是否有新版。放在最後,改版號不會讓前面的層失效。
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]

# ── worker:PDF 匯出的重量級原生依賴只裝在這裡,api 映像維持精簡 ──
# WeasyPrint 需 Pango/Cairo/gdk-pixbuf;中文內嵌字型用 Noto CJK;
# poppler-utils 供匯出 PNG 與驗證用(PDF→影像)。
FROM base AS worker

# 安裝系統套件需要 root,裝完切回 app
USER root

# PDF/PNG(WeasyPrint + poppler + 中文字型)+ 備份(postgresql-client,M5-2)。
# trixie 的 postgresql-client 為 17,可 pg_dump/pg_restore 對上 postgres:16 伺服器
# (client ≥ server 允許;server 較新才是不支援的方向)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0=1.56.3-1 \
        libpangocairo-1.0-0=1.56.3-1 \
        libpangoft2-1.0-0=1.56.3-1 \
        libgdk-pixbuf-2.0-0=2.42.12+dfsg-4+deb13u1 \
        libcairo2=1.18.4-1+b1 \
        libffi8=3.4.8-2 \
        libjpeg62-turbo=1:2.1.5-4 \
        fonts-noto-cjk=1:20240730+repack1-1 \
        poppler-utils=25.03.0-5+deb13u4 \
        postgresql-client=17+278+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install '.[export]'

USER app

CMD ["worker"]
