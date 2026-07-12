# 排課與調代課系統 · Course Scheduling System

[![CI](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml/badge.svg)](https://github.com/begin0808/Course_Scheduling_System/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**開源免費、單校自架、純 Web 的中小學排課與調代課系統。** 適用國小、國中、普通型高中、綜合型高中、技術型高中,以**教學組長**的日常工作流程為中心設計。

從學期基礎資料、手動與自動排課(OR-Tools CP-SAT 引擎),到學期中最繁瑣的請假、代課、調課、通知與鐘點統計,一套涵蓋。以 Docker Compose 一鍵部署在校內一台主機上,資料不出校。

> **English summary:** A free, open-source (MIT), self-hosted, web-based course-scheduling and teacher-substitution system for Taiwanese K–12 schools. It covers the school-timetabling office's full workflow: semester/period setup, manual drag-and-drop scheduling, automatic scheduling via an OR-Tools CP-SAT engine with human-readable conflict explanation, and the day-to-day of leave requests, substitute assignment, notifications, and substitution-hour reporting. One school, one self-hosted deployment (no multi-tenant SaaS). One-command Docker Compose install. UI is Traditional Chinese with Taiwan educational terminology.

---

## 功能總覽

| 領域 | 內容 |
|---|---|
| **基礎資料** | 學期/節次表(多學制範本)、教師/班級/科目/場地、Excel 匯入、設定精靈、開新學期複製、混合學制(班級↔節次表指派) |
| **配課與手動排課** | 配課管理(跑班群組、協同教學、連堂)、鐘點即時統計、拖拉式週課表、單格衝突檢查(<100ms)、多草稿版本管理與發布 |
| **自動排課** | OR-Tools CP-SAT 引擎,H1–H10 硬約束 + S1–S8 軟約束加權;背景求解含即時進度;**無解時以教務語言定位衝突**並支援部分排課 |
| **調代課** | 請假登記與受影響節次展開、代課推薦引擎、調課驗證、指派即生效、站內+Email 通知與確認、今日看板與 A4 公告列印、月結鐘點統計(Excel) |
| **報表/匯出** | 班級/教師/場地課表匯出 Excel / PDF(內嵌中文字型)/ PNG、全校總表、批次 zip |
| **維運** | 每日自動備份 + 手動備份 / 下載 / 上傳還原(還原前自動保護、還原後強制重登)、稽核紀錄、RBAC(管理員/主任/組長/教師) |

---

## 快速開始

需先安裝 [Docker](https://docs.docker.com/get-docker/)。**完整步驟(含 Windows / Linux / NAS)見 [部署手冊](docs/deploy/README.md)。**

### 拉取官方映像(推薦)

```bash
mkdir scheduling && cd scheduling
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
curl -fL  https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/.env.example -o .env
# 編輯 .env:改 ADMIN_PASSWORD、SCHOOL_NAME、SECRET_KEY
docker compose pull
docker compose up -d
```

### 從原始碼建置

```bash
git clone https://github.com/begin0808/Course_Scheduling_System.git
cd Course_Scheduling_System
cp .env.example .env      # 改 ADMIN_PASSWORD、SCHOOL_NAME、SECRET_KEY
docker compose up -d      # 首次會建置映像,需數分鐘
```

啟動後開瀏覽器連 `http://<主機IP>`(本機為 <http://localhost>),以 `.env` 的管理員帳密登入,依設定精靈完成建置。

- 健康檢查:`http://localhost/api/health` → `{"status":"ok"}`
- 容器狀態:`docker compose ps`(五個容器皆應 healthy)

### 硬體最低需求

2 核 / 4GB RAM / 10GB 磁碟(自動排課建議 4 核 8GB)。支援 x86-64 與 ARM64(NAS / 樹莓派)。

---

## 文件

| 文件 | 內容 |
|---|---|
| [**教學組長操作手冊**](https://begin0808.github.io/Course_Scheduling_System/)（[原始檔](docs/index.html)） | 給使用者:設定精靈、配課、排課、調代課、匯出、備份、FAQ(11 章圖文網頁) |
| [部署手冊](docs/deploy/README.md) | 給安裝者:安裝、升級、備份、網域 HTTPS、FAQ |
| [架構設計](docs/architecture.md) | 需求、資料模型、排課引擎、技術棧(規格權威來源) |
| [開發任務卡](docs/tasks.md) | Milestone 與逐卡實作紀錄 |
| [變更紀錄](CHANGELOG.md) | 各版本變更 |
| [貢獻指南](CONTRIBUTING.md) | 開發環境、程式風格、測試、發布流程 |

---

## 技術棧

| 層 | 技術 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Naive UI |
| 後端 | Python 3.12 + FastAPI + SQLAlchemy 2 + Pydantic v2 |
| 排課引擎 | Google OR-Tools CP-SAT(RQ + Redis 背景執行) |
| 匯出 | openpyxl(Excel)、WeasyPrint(PDF,內嵌 Noto CJK)、poppler(PNG) |
| 資料庫 | PostgreSQL 16 |
| 反向代理 | Caddy(內網 HTTP;設網域即自動 HTTPS) |
| 部署 | Docker Compose(5 容器:web / api / worker / postgres / redis) |

---

## 專案狀態

**v1.0.0 已發行(2026-07-12)。** 六大里程碑 M0–M5 全部完成,官方映像(amd64 + arm64)已發布於 GHCR。詳見 [CHANGELOG](CHANGELOG.md) 與 [docs/tasks.md](docs/tasks.md)。

---

## 回報問題與意見回饋

發現錯誤、有功能建議,或想分享貴校的使用經驗,都非常歡迎:

- **回報問題 / 提出建議**:於本專案開 [GitHub Issue](https://github.com/begin0808/Course_Scheduling_System/issues)(附上操作步驟與 `docker compose logs` 片段會更快解決)
- **來信聯絡**:專案開發者 **國立南大附中 李佳恩老師** — [begin0808@gmail.com](mailto:begin0808@gmail.com)

這套系統是為第一線教學組長而寫的,你的實際使用回饋對它的改進最有幫助。

## 授權

[MIT](LICENSE) — 可自由使用、修改、散布。歡迎各校自架與二次開發。

執行時使用的第三方元件與其授權見 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)(皆與 MIT 相容)。
