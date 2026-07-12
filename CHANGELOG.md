# 變更紀錄 Changelog

本檔記錄各版本的重要變更。格式依循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.1.0/),版本號依循 [語意化版本](https://semver.org/lang/zh-TW/)。

破壞性變更(需人工介入才能升級)以 ⚠️ 標註。

## [Unreleased]

尚無變更。

## [1.0.0] — 2026-07-12

**首次公開發行。** 完整涵蓋一所學校從基礎資料建置、配課、手動與自動排課、發布,到學期中調代課、匯出與備份的全流程。

官方映像(amd64 + arm64 雙架構)已發布於 GHCR:
`ghcr.io/begin0808/course_scheduling_system-{api,worker,web}:v1.0.0`

### 安全與發行前強化
- **SECRET_KEY 防呆**:未設定(仍為預設/範例值)時自動改用隨機金鑰並警告,避免以公開金鑰簽署 session cookie。
- **HTTPS 自動安全 cookie**:設定 `SITE_ADDRESS` 網域(啟用 HTTPS)時,登入 cookie 自動加上 `Secure` 旗標。
- **請求體上限**:Caddy 限制 200MB,避免超大上傳耗盡單校主機記憶體。
- **背景任務韌性**:排課進行中禁止還原(避免資料庫被無預警覆蓋);阻塞式任務逾時即取消;每日備份鏈具自我續期與心跳自癒。
- **還原容錯收緊**:`pg_restore` 僅容忍跨版本設定參數噪音,其餘錯誤一律視為失敗(避免資料缺漏被誤報為成功);可忽略警告顯示於介面。
- 新增 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)(第三方元件授權揭露,皆與 MIT 相容)。
- 新增[教學組長操作手冊](https://begin0808.github.io/Course_Scheduling_System/)(11 章網頁)。

### 部署與發行(M5-3)
- `docker-compose.yml` 同時支援兩種部署:從原始碼 `docker compose up -d` 建置,或 `docker compose pull` 拉取官方預建映像;映像版本由 `.env` 的 `IMAGE_TAG` 控制(預設 `latest`,建議正式部署釘選版本)。
- Caddy 站台位址改由環境變數 `SITE_ADDRESS` 決定:預設內網 HTTP;設為網域名即自動申請並續期 Let's Encrypt HTTPS 憑證(憑證存於 `caddydata` volume)。
- 新增中文部署手冊 `docs/deploy/`:安裝(Windows/Linux/NAS)、升級、備份與異地備援、網域與 HTTPS、常見問題。
- 新增 `CHANGELOG.md`、`CONTRIBUTING.md`;改寫 README(含英文摘要與功能總覽)。

### 報表、備份與匯出(M5-0 ~ M5-2)
- **課表匯出**:班級/教師/場地課表匯出 Excel、PDF(WeasyPrint,內嵌 Noto CJK 中文字型,A4)、PNG;全校總表 Excel;批次匯出全部班級為 zip。
- **備份與還原**:每日自動 `pg_dump`(可設定時刻與保留份數,預設 02:00 / 30 份、自動輪替);系統管理介面立即備份、下載、上傳還原;還原前自動備份現狀、還原後強制全員重新登入(以 Redis 記錄 session 時效,獨立於被還原的 PostgreSQL)。
- **發行前置**:多階段 Docker 映像(api 精簡 / worker 含 PDF 字型與 PostgreSQL client);RQ 定時任務排程骨架(自我續期心跳);60 班規模效能 fixture。
- 重新發布課表後,對「今日之後」仍指向舊格位的受影響節次於發布時提出警告(條件 D 最小防護)。

### 調代課(M4)
- 請假登記與受影響節次展開(快照保存,不隨課表改版漂移;半天/多天/跨週假、六日制學校支援)。
- 調代課處理工作台與代課推薦引擎(同科目 > 當天已在校 > 本月代課鐘點少,附人話理由);調課(swap)四項驗證;指派即生效(無邀請/婉拒流程)。
- 通知系統:站內(鈴鐺、未讀數)+ Email(SMTP 選配,經 `NotificationChannel`,交易後才寄送);教師「確認收到」;組長看板未確認者一鍵再提醒。
- 今日調代課看板、A4 公告列印、歷史查詢;月結代課鐘點統計(代課節數 vs 計費節數,跨月假單自動拆月,Excel 匯出,教師可查本人)。

### 自動排課(M3)
- 三套學制驗證資料集(國小/國中/技高)。
- OR-Tools CP-SAT 排課引擎:solver 資料層與 pre-flight 檢查、H1–H10 硬約束建模、S1–S8 軟約束加權目標;連堂、跑班同步、鎖定格位、跨節次表牆鐘重疊建模。
- Worker 背景求解含即時進度、提前結束取當前最佳解、逾時可設定;結果寫回新草稿(鎖定格位固定、既有格位作 hint)。
- 無解衝突定位:以刪除法逐類探測,轉譯為教務語言建議;部分排課模式(可放寬的約束轉高權重軟約束,未排入者列清單)。

### 配課與手動排課(M2)
- 教師帳號綁定與聯絡資訊;配課管理(跑班群組、協同教學、連堂)與鐘點即時統計。
- TimetableGrid 拖拉週課表元件;衝突檢查服務與手動排課 API(單格 <100ms,跨節次表以牆鐘時間重疊判定)。
- 排課工作台(三視角、草稿自動儲存、復原/重做);多草稿版本管理與發布(發布為不可變快照)。

### 基礎資料(M1)
- 學期與節次表(五種學制範本、同學期多套節次表);教師/班級/科目/場地 CRUD(含引用完整性)。
- Excel 匯入(逐列驗證、交易式入庫);首次登入設定精靈;開新學期複製精靈;混合學制班級↔節次表指派。

### 專案骨架(M0)
- Docker Compose 五容器骨架與開發熱重載設定;帳號、bcrypt 登入、session cookie 與 RBAC(admin/director/scheduler/teacher);首次登入強制改密。
- CI:ruff + mypy + pytest / eslint + vue-tsc + build + vitest / PostgreSQL 遷移驗證 / 雙架構映像建置發布。

[Unreleased]: https://github.com/begin0808/Course_Scheduling_System/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/begin0808/Course_Scheduling_System/releases/tag/v1.0.0
