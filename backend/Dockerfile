# 後端映像:兩個 target。
#   base   → api 服務(精簡)
#   worker → 背景任務(額外裝 WeasyPrint 系統依賴/中文字型與 PostgreSQL client)
# 明確鎖 trixie:其 main 內含 postgresql-client(17),pg_dump 可備份 v16 伺服器。
FROM python:3.12-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 供 healthcheck 使用
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先裝相依(利用 layer 快取)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# 應用程式原始碼
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]

# ── worker:PDF 匯出的重量級原生依賴只裝在這裡,api 映像維持精簡 ──
# WeasyPrint 需 Pango/Cairo/gdk-pixbuf;中文內嵌字型用 Noto CJK;
# poppler-utils 供匯出 PNG 與驗證用(PDF→影像)。
FROM base AS worker

# PDF/PNG(WeasyPrint + poppler + 中文字型)+ 備份(postgresql-client,M5-2)。
# trixie 的 postgresql-client 為 17,可 pg_dump/pg_restore 對上 postgres:16 伺服器
# (client ≥ server 允許;server 較新才是不支援的方向)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        libjpeg62-turbo \
        fonts-noto-cjk \
        poppler-utils \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install '.[export]'

CMD ["worker"]
