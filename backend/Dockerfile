# 後端映像:兩個 target。
#   base   → api 服務(精簡)
#   worker → 背景任務(額外裝 WeasyPrint 系統依賴與中文內嵌字型,供 M5-1 PDF 匯出)
FROM python:3.12-slim AS base

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
    && rm -rf /var/lib/apt/lists/*

RUN pip install '.[export]'

CMD ["worker"]
