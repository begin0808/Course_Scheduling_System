# 排課與調代課系統

[![CI](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml/badge.svg)](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

開源免費、單校自架、純 Web 的中小學排課與調代課系統。適用國小、國中、普通型高中、綜合型高中、技術型高中,給教學組長使用。

> 目前進度:**M0-1 專案骨架**。功能里程碑見 [docs/tasks.md](docs/tasks.md),架構設計見 [docs/architecture.md](docs/architecture.md)。

## 技術棧

| 層 | 技術 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Naive UI |
| 後端 | Python 3.12 + FastAPI + SQLAlchemy 2 |
| 排課引擎 | Google OR-Tools CP-SAT(RQ + Redis 背景執行) |
| 資料庫 | PostgreSQL 16 |
| 反向代理 | Caddy |
| 部署 | Docker Compose(5 容器) |

## 快速開始(正式部署)

需先安裝 [Docker](https://docs.docker.com/get-docker/)。

```bash
cp .env.example .env      # 修改管理員密碼與校名
docker compose up -d      # 啟動(首次會建置映像,需數分鐘)
```

啟動後開瀏覽器連 `http://<主機IP>`(本機為 http://localhost)。

- 健康檢查:`http://localhost/api/health` → `{"status":"ok"}`
- 查看容器狀態:`docker compose ps`(五個容器皆應為 healthy)

### 硬體最低需求

2 核心 / 4GB RAM / 10GB 磁碟(自動排課建議 4 核 8GB)。支援 x86-64 與 ARM64(NAS/樹莓派)。

## 開發模式(熱重載)

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up
```

- 前端(熱重載):http://localhost:5173
- API 互動文件:http://localhost:8000/api/docs

前後端原始碼皆掛載進容器,存檔即時生效。

### 本機測試

```bash
# 後端
cd backend && pip install -e ".[dev]" && pytest
# 前端
cd frontend && npm install && npm run test
```

## 授權

[MIT](LICENSE)
