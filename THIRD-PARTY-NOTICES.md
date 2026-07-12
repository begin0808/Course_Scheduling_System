# 第三方元件與授權 Third-Party Notices

本專案(排課與調代課系統)以 **MIT** 授權釋出。系統運行時會用到下列第三方元件。這些元件皆以**獨立函式庫**(動態相依)或**獨立程式**(子行程呼叫)的形式使用,不會將其授權條款加諸於本專案的原始碼——因此與本專案的 MIT 授權相容,可自由散布。

各元件的權威授權以其官方專案為準;下表為概述,便於採用單位做合規查核。

## 後端執行相依(Python)

| 元件 | 授權 |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| SQLAlchemy | MIT |
| Alembic | MIT |
| **psycopg (psycopg3)** | **LGPL-3.0-or-later** |
| Pydantic / pydantic-settings | MIT |
| redis-py | MIT |
| RQ (rq) | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| bcrypt | Apache-2.0 |
| itsdangerous | BSD-3-Clause |
| openpyxl | MIT |
| OR-Tools | Apache-2.0 |
| WeasyPrint(worker 匯出用) | BSD-3-Clause |

## worker 映像的系統套件(Debian,以系統程式庫或子行程使用)

| 元件 | 授權 | 使用方式 |
|---|---|---|
| **poppler-utils**(`pdftoppm`) | **GPL-2.0** | 以**子行程**呼叫,轉 PDF→PNG |
| Pango / Cairo / gdk-pixbuf | LGPL | WeasyPrint 的系統相依(動態連結) |
| fonts-noto-cjk(Noto Sans/Serif CJK) | SIL Open Font License 1.1 | 內嵌於匯出的 PDF |
| postgresql-client(`pg_dump`/`pg_restore`) | PostgreSQL License(寬鬆) | 以子行程呼叫,備份/還原 |

## 前端相依

| 元件 | 授權 |
|---|---|
| Vue 3 / Vue Router / Pinia | MIT |
| Naive UI | MIT |
| Vite | MIT |

## 執行時基礎映像(由部署者自官方來源拉取,非本專案散布)

| 映像 | 授權 |
|---|---|
| PostgreSQL(`postgres:16-alpine`) | PostgreSQL License |
| Redis(`redis:7-alpine`) | BSD-3-Clause / 視版本 |
| Caddy(`caddy:2-alpine`) | Apache-2.0 |

## 關於 copyleft 元件的說明

- **psycopg(LGPL-3.0)**:以獨立函式庫**動態相依**方式使用(未修改、未靜態連結進本專案)。LGPL 對此種使用不要求本專案採用相同授權,故 MIT 相容。
- **poppler-utils / `pdftoppm`(GPL-2.0)**:僅以**子行程**呼叫的獨立命令列程式(mere aggregation),GPL 的 copyleft 不延伸至呼叫它的本專案程式碼。
- **Pango / Cairo 等(LGPL)**:動態連結的系統程式庫,與上述 LGPL 說明同理。

若你要**修改並再散布**這些 copyleft 元件本身(而非僅使用),請遵循其各自的授權條款。單純部署與使用本系統不涉及此義務。
