# 開發交棒計畫 — Milestone 與任務卡

> 版本:v1.0(2026-07-07)
> 前置閱讀:**[architecture.md](architecture.md)**(需求、資料模型、引擎設計、技術棧皆以該文件為準)
> 使用方式:開發 AI(Opus 4.8 / Sonnet 5)每次領取**一張任務卡**,實作 → 依「驗收標準」自我驗證 → 回報 → 經使用者驗收後才進下一張。
> 任務卡狀態標記:`[ ]` 未開始 / `[~]` 進行中 / `[x]` 已驗收。開發者完成後請直接更新本檔的核取方塊。

---

## 專案目錄結構(M0 建立,全案遵循)

```
Course_Scheduling_System/
├── docker-compose.yml          # 正式部署用(5 容器:caddy/api/worker/postgres/redis)
├── docker-compose.dev.yml      # 開發用(熱重載)
├── .env.example                # 僅需改:管理員密碼、校名、SMTP(選填)
├── Caddyfile
├── docs/                       # 本規劃文件 + 使用者文件
│   ├── architecture.md
│   ├── tasks.md
│   └── deploy/                 # 中文部署圖文教學
├── backend/
│   ├── pyproject.toml          # uv 管理;ruff + pytest 設定
│   ├── alembic/                # 資料庫遷移
│   ├── app/
│   │   ├── core/               # 設定、DB session、auth、安全
│   │   ├── models/             # SQLAlchemy models(對應 architecture.md §2.2)
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── api/                # routers(依資源分檔:teachers.py、timetables.py …)
│   │   ├── services/           # 商業邏輯(衝突檢查、代課推薦、匯入匯出…)
│   │   ├── solver/             # OR-Tools CP-SAT 排課引擎(獨立、不 import app 其他層)
│   │   │   ├── model_builder.py    # 約束建模
│   │   │   ├── conflict_explainer.py # 無解衝突定位
│   │   │   └── preflight.py        # 排課前置檢查
│   │   ├── workers/            # RQ 任務(排課、寄信、備份)
│   │   └── main.py
│   └── tests/
│       ├── fixtures/           # 三套學制驗證資料集(見測試策略)
│       ├── unit/
│       └── solver/             # 引擎正確性測試
├── frontend/
│   ├── package.json            # pnpm;Vue 3 + TS + Vite + Pinia + Naive UI
│   ├── src/
│   │   ├── api/                # API client(openapi-typescript 產生型別)
│   │   ├── stores/
│   │   ├── components/
│   │   │   └── timetable/      # TimetableGrid 拖拉課表元件(核心)
│   │   ├── views/              # 依資訊架構分頁(見 architecture.md §5.1)
│   │   └── router/
│   └── e2e/                    # Playwright
└── .github/workflows/ci.yml    # lint + test + 雙架構 image build
```

---

## Milestone 總覽

| Milestone | 目標 | 完成的可見成果 |
|---|---|---|
| M0 專案骨架 | 可跑起來的空殼 | `docker compose up -d` 後可登入看到空儀表板 |
| M1 基礎資料 | 建置學校資料 | 設定精靈走完,教師/班級/科目/場地齊備 |
| M2 手動排課 | 拖拉排課可用 | 手動排完一張班級課表並發布,教師可查詢 |
| M3 自動排課 | 引擎上線 | 一鍵自動排課出草稿,無解時給人話報告 |
| M4 調代課 | 學期中日常運作 | 請假→代課→通知→確認 全流程 |
| M5 報表與上線 | 對外可發行 | 匯出/備份/部署文件完成,可發布 v1.0 |

---

## M0 專案骨架

### [x] M0-1 Repo 初始化與 Docker Compose 骨架
- **描述**:建立上述目錄結構;`docker-compose.yml`(5 容器)與 `docker-compose.dev.yml`;FastAPI hello endpoint(`GET /api/health`);Vue 3 空專案由 Caddy 服務;Alembic 初始化;`.env.example`。
- **模組**:根目錄、`backend/app/main.py`、`frontend/`、`Caddyfile`
- **驗收標準**:
  1. 全新機器上 `cp .env.example .env && docker compose up -d` 後,瀏覽器開 `http://localhost` 見前端頁面,`/api/health` 回 `{"status":"ok"}`
  2. `docker compose ps` 五容器皆 healthy
  3. dev compose 支援前後端熱重載
- **測試方式**:CI 內 `docker compose up` + curl 煙霧測試

### [x] M0-2 帳號、登入與 RBAC
- **描述**:`user`/`user_role` model 與遷移;bcrypt + session cookie 登入;RBAC 依賴注入(admin/scheduler/director/teacher);首次啟動以 `.env` 建立 admin;首次登入強制改密碼;登入頁 UI。
- **模組**:`app/core/auth.py`、`app/api/auth.py`、`app/models/user.py`、`frontend/src/views/Login.vue`
- **驗收標準**:
  1. admin 可登入/登出;錯誤密碼 5 次鎖定 15 分鐘
  2. 未登入呼叫受保護 API 回 401;teacher 角色呼叫 scheduler API 回 403
  3. 首次登入被導向改密碼頁,改完才能進系統
- **測試方式**:pytest(auth 流程 8+ 案例)+ Playwright 登入 E2E

### [x] M0-3 CI 與程式品質基線
- **描述**:GitHub Actions:ruff + mypy + pytest / eslint + vitest / Playwright / 雙架構(amd64+arm64)image build push。pre-commit 設定。
- **驗收標準**:PR 觸發全部檢查;main 分支 push 產出 image;README 掛 CI badge
- **測試方式**:開測試 PR 驗證

---

## M1 基礎資料管理

### [x] M1-0 地基補強(M0 架構健檢產出,先做完才進 M1-1)
- **描述**:健檢發現三項「現在改便宜、日後改痛」的地基問題:
  1. **Session 撤銷**:session token 由 `{"uid"}` 改為 `{"uid", "pv": password_hash[-12:]}`,`get_current_user` 驗證 `pv` 與現行密碼一致,不符回 401(改密碼即失效所有舊 session);
  2. **naming_convention**:`Base.metadata` 加入標準約束命名慣例(ix/uq/ck/fk/pk),確保跨資料庫遷移可靠;
  3. **時區政策落地**(architecture.md D6):`.env.example` 與 config 增 `TZ=Asia/Taipei` 設定;compose 傳入容器。
- 順手項:CI 增加「PostgreSQL service container 跑 `alembic upgrade head`」遷移驗證步驟;前端 `client.ts` 加 401 全域處理(清 store → 導向登入)。
- **模組**:`app/core/{security,auth,db,config}.py`、`tests/`、`.github/workflows/ci.yml`、`frontend/src/api/client.ts`
- **驗收標準**:
  1. 登入後改密碼,以「舊 cookie」呼叫 `/api/auth/me` 回 401(新增 pytest 案例)
  2. `Base.metadata.naming_convention` 已定義,`alembic upgrade head` 在 PostgreSQL 全新資料庫成功(CI 驗證)
  3. session 過期或被撤銷後,前端任何 API 操作自動導回登入頁
  4. 既有 15 個 auth 測試不退步
- **測試方式**:pytest + CI 遷移 job

### [x] M1-1 學期與節次表
- **描述**:`semester`/`period_table`/`period` CRUD(model+API+UI);節次表視覺化編輯器(表格點選標記節次類型:一般課/午休/導師時間/固定用途);五種學制範本資料(JSON seed,含預設節次表與科目清單);同學期多套節次表(完全中學)。
- **模組**:`app/models/{semester,period}.py`、`app/api/semesters.py`、`frontend/src/views/settings/PeriodTable.vue`
- **驗收標準**:
  1. 可建立 115 學年第 1 學期,選「國小範本」自動帶入 40 分節次表(含週三下午空)
  2. 可將週五第 7 節改為「導師時間」,排課時段檢查 API 即反映
  3. 可為同學期建第二套節次表並指派給不同班級群
- **測試方式**:pytest CRUD + 範本載入;Vitest 元件測試

### [x] M1-2 教師、班級、科目、場地 CRUD
- **描述**:四實體完整 CRUD(對應 architecture.md §2.2 欄位);教師任教科目多選、行政職減課、業界師資標記;班級的學制標籤與群科(技高);場地類型與容量;清單頁支援搜尋/排序。
- **模組**:`app/models/`、`app/api/`、`frontend/src/views/basedata/`
- **驗收標準**:
  1. 四實體皆可增刪改查,刪除有引用檢查(被配課引用的教師不可刪,提示改為「離職」狀態)
  2. 教師頁可設定「不可排時段」與「偏好時段」(週×節 點選格子)
  3. 技高班級可填群科;國小班級可指定導師
- **測試方式**:pytest(含引用完整性案例)

### [x] M1-3 Excel 匯入
- **描述**:教師、班級、科目三種 Excel 範本(系統內可下載,含填寫說明列與範例列);上傳→逐列驗證→錯誤清單(「第 N 列:XX 原因」)→全對才交易式入庫;匯入教師時可勾選「同時建立帳號」(預設密碼規則+強制首登改密)。
- **模組**:`app/services/importer.py`、`frontend/src/views/basedata/Import.vue`
- **驗收標準**:
  1. 下載範本→填 30 位教師→上傳→全數入庫且帳號建立
  2. 故意填錯(科目不存在、重複姓名+身分末四碼)→回報確切列號與原因,資料庫零寫入
  3. 範本欄位有中文說明列,匯入時自動略過
- **測試方式**:pytest 用 fixtures 內的正確/錯誤 Excel 檔

### [x] M1-4 設定精靈
- **描述**:首次登入(無任何學期資料時)自動進入五步驟精靈(architecture.md §5.2);每步可略過/回上一步;完成後導向配課管理;之後可從系統管理重新啟動精靈。
- **模組**:`frontend/src/views/wizard/`、`app/api/wizard.py`(進度狀態)
- **驗收標準**:
  1. 全新系統登入即入精靈;五步走完後儀表板顯示資料摘要(N 位教師、N 個班級)
  2. 中途關瀏覽器,再登入從上次步驟繼續
  3. 使用者測試:不看文件 30 分鐘內完成國中範本建置(以 fixtures 資料模擬)
- **測試方式**:Playwright E2E 全精靈流程

### [x] M1-5 開新學期複製精靈
- **描述**:從既有學期複製教師/班級/科目/場地/節次表到新學期(可勾選項目);班級年級自動 +1(可關閉),畢業年級提示移除。
- **驗收標準**:複製後兩學期資料獨立(改 A 學期教師不影響 B);年級進位正確
- **測試方式**:pytest

### [x] M1-6 混合學制支援:班級 ↔ 節次表指派(M2 前必做,架構健檢 2026-07-09 產出)
- **領域背景(使用者提供)**:台灣完全中學通常全校統一 50 分/節(國中部配合高中部作息),故多數學校只需一套節次表;真正需要多套表的是**附設國小部、K-12 實驗學校、進修部/夜間部**。設計原則:預設路徑零負擔,彈性只在需要時浮現。
- **描述**:班級尚無「所屬節次表」關聯,M2 衝突檢查/排課引擎無從得知每班合法時段。實作:
  1. `class_units.period_table_id`(nullable FK,空=學期預設節次表)+ 遷移;
  2. 班級表單增「節次表」下拉——**僅於該學期有 ≥2 套節次表時顯示**(單一表學校完全看不到此欄位);Excel 班級範本增「節次表」欄(選填,以名稱對應);
  3. 提供 helper `resolve_period_table(class_unit)`(指定表 → 回退學期預設表),**無論單表或多表學校,M2 起所有時段邏輯一律走此函式**;
  4. 刪除節次表時檢查是否被班級引用(引用中則擋)。
- **模組**:`app/models/basedata.py`、`app/api/basedata.py`、`app/services/importer.py`、`frontend/src/views/basedata/ClassesTab.vue`
- **驗收標準**:
  1. 完全中學情境:同學期兩套節次表(國中 45 分/高中 50 分),301 班指到國中表、501 班指到高中表,各自 available-slots 正確
  2. 未指派節次表的班級回退學期預設表
  3. 被班級引用的節次表刪除時回 409
  4. Excel 匯入班級可指定節次表名稱,名稱不存在時報列號錯誤
- **測試方式**:pytest(完全中學 fixture 情境)

---

## M2 配課與手動排課

### [x] M2-0 教師帳號綁定與聯絡資訊(M1 健檢 2026-07-09 產出,M2-1 前必做)
- **背景**:`user.py` docstring 承諾的 User↔Teacher 綁定在 M1 未實作(匯入建帳號僅存 display_name,無外鍵)。此綁定是 M2-5「教師查本人課表」、M4 全部(請假自登、代課確認、通知收件人)的前提。另使用者需求:教師需有聯絡欄位以利調代課通知。
- **描述**:
  1. `teachers.user_id`(nullable FK → users,`ondelete=SET NULL`,同學期唯一 uq(semester_id, user_id));Excel 匯入「同時建立帳號」時自動綁定;教師表單(admin/scheduler)可選擇綁定既有帳號;
  2. `teachers.email` / `teachers.phone` / `teachers.line_id`(皆 nullable String)——聯絡資訊掛教師(學期快照),因外聘/業界師資可能無系統帳號;
  3. Excel 教師範本增 Email/手機/LINE ID 三選填欄;教師表單增欄位;
  4. `semester_copy` 複製 user_id 與三個聯絡欄位(綁定跨學期延續);
  5. helper `current_teacher(db, user, semester_id)`:由登入者解析其在指定學期的教師主檔(M2-5/M4 共用)。
- **模組**:`app/models/basedata.py`、`app/services/{importer,semester_copy}.py`、`app/api/basedata.py`、`frontend/src/views/basedata/TeachersTab.vue`
- **驗收標準**:
  1. 匯入 30 位教師勾「建立帳號」→ 每筆 `teachers.user_id` 正確綁定新帳號
  2. 開新學期複製後,新學期教師仍綁定同一帳號、聯絡資訊完整
  3. 同一帳號在同學期綁第二位教師 → 409
  4. Email 格式錯誤時表單與匯入均回報錯誤
- **測試方式**:pytest(綁定/複製/唯一性);既有匯入測試不退步

### [x] M2-1 配課管理
- **描述**:`scheduling_unit`/`course_assignment`/`assignment_teacher`/`block_rule` model 與 CRUD;配課建立 UI(班級選科目→指定教師→週節數→連堂→場地需求);跑班群組建立(選多班級組成 group,群組內建多筆配課);教師鐘點即時統計側欄(配課數 vs 基本鐘點,超/不足變色);Excel 批次匯入配課。
- **模組**:`app/models/assignment.py`、`app/api/assignments.py`、`frontend/src/views/scheduling/Assignments.vue`
- **驗收標準**:
  1. 可建立「301 班 × 國文 × 王師 × 每週 5 節」與「高二多元選修跑班群組(3 班 5 組)」
  2. 可建立「機械科實習 × 2 位協同教師 × 每週 6 節含 3 連堂×2」
  3. 王師配 22 節、基本鐘點 20 → 側欄顯示「+2 超鐘點」紅字
  4. 班級週配課總節數 > 可排節次數(經 `resolve_period_table`+`regular_slots`)時警告
  5. 跑班群組成員班級的節次表不一致 → 建立被拒(architecture.md D7 第 4 點)
- **測試方式**:pytest(含跑班/協同/連堂三種結構)

### [x] M2-2 TimetableGrid 課表元件
- **描述**:前端核心元件:CSS Grid 週課表,依節次表渲染(含反灰不排課時段);格位卡片(科目/教師/場地/鎖定圖示);HTML5 拖拉(從未排清單拖入、格間移動、拖出移除);視覺狀態(可放綠框/衝突紅框+原因浮窗);響應式(平板可用,手機唯讀)。**純展示+事件元件,不含商業邏輯**。
- **模組**:`frontend/src/components/timetable/`
- **驗收標準**:
  1. Storybook(或示範頁)展示:國小 40 分節次表與技高 50 分節次表各一張
  2. 拖曳過程觸發 `check` 事件、放下觸發 `drop` 事件,由父層決定結果
  3. Vitest 元件測試涵蓋渲染/拖放事件/鎖定顯示
- **測試方式**:Vitest + 示範頁人工檢視

### [x] M2-3 衝突檢查服務與手動排課 API
- **描述**:`timetable`/`schedule_entry` model;衝突檢查服務(H1–H10 硬約束的單格檢查版,architecture.md §3.2);**教師/場地衝突在跨節次表時以牆鐘時間區間重疊判定**(architecture.md D7,同表退化為 period_no 相等);API:建立草稿、格位增刪改、`POST /timetables/{id}/check-conflict`(<100ms)、鎖定/解鎖;跑班群組拖一格連動全組。
- **模組**:`app/services/conflict_checker.py`、`app/api/timetables.py`
- **驗收標準**:
  1. 王師已在週一第一節有課,再排他班同時段 → 回衝突「教師王師 週一第一節 已有 302 班數學」
     (時段一律以**節次表中的名稱**呈現:早自習/午休/第一節,不可用內部 period_no 索引)
  2. 連堂課拖至跨午休位置 → 拒絕並說明
  3. 跑班群組某組拖到新時段,全組連動;任一組衝突則整組拒絕
  4. check-conflict 在 60 班資料量下 p95 < 100ms
  5. 跨節次表衝突:王師在國小部(40 分/節)週一第 4 節 10:30–11:10 有課,再排他至高中部(50 分/節)週一第 3 節 10:10–11:00 → 回報衝突(牆鐘時間重疊)
- **測試方式**:pytest 覆蓋 H1–H10 每項至少 2 案例(過/不過);效能測試腳本

### [x] M2-4 排課工作台整合
- **描述**:整合 M2-2 元件與 M2-3 API 成完整工作台(architecture.md §5.1 線框):左側未排課務清單(含剩餘節數)、三視角切換(班級/教師/場地)、草稿自動儲存、復原/重做(前端 command stack)。
- **模組**:`frontend/src/views/scheduling/Workbench.vue`
- **驗收標準**:
  1. 以國中 fixtures 手動排完一個班整週課表,未排清單歸零
  2. 三視角資料一致(班級視角排的課,教師視角立即可見)
  3. Ctrl+Z 可復原最近 20 步
- **測試方式**:Playwright E2E「排完一班」情境

### [ ] M2-5 版本管理與發布
- **描述**:多草稿並存(複製/改名/刪除);發布(draft→published,同學期舊 published 轉 archived);發布前完整性檢查(未排完課務列警告,可強制發布);全員課表查詢頁(班級/教師/場地,唯讀,手機可用);audit_log 記錄發布。
- **驗收標準**:
  1. 兩份草稿可並存互不影響;發布 B 後,查詢頁顯示 B,A 仍可編輯
  2. 有 3 節未排時發布 → 出現警告清單,確認後仍可發布
  3. teacher 角色登入手機瀏覽器可查本人課表
- **測試方式**:pytest 狀態轉換 + Playwright

---

## M3 自動排課

### [ ] M3-1 Solver 資料層與 pre-flight 檢查
- **描述**:`solver/` 模組骨架:從 DB 讀取學期資料轉為純 dataclass 問題描述(solver 不碰 SQLAlchemy);pre-flight 必要條件檢查(教師配課數≤可排格數、場地供需、班級節數,architecture.md §3.4);檢查報告 API。
- **模組**:`app/solver/preflight.py`、`app/solver/problem.py`
- **驗收標準**:
  1. 三套 fixtures 皆可轉出問題描述且 pre-flight 通過
  2. 人為製造「王師 22 節但可排 20 格」→ 報告明確指出教師、數字
  3. solver 模組 `import` 不到 `app.api`/`app.models`(以 import-linter 或測試保證)
- **測試方式**:pytest

### [ ] M3-2 CP-SAT 核心建模(硬約束)
- **描述**:實作 H1–H10 硬約束建模(architecture.md §3.2);連堂以區間建模;跑班同步;鎖定格位;求解取出結果轉 schedule_entry 列表。
- **模組**:`app/solver/model_builder.py`
- **驗收標準**:
  1. 三套 fixtures 各自可解,且**逐項驗證**解零硬約束違反(以獨立 validator 檢查,不信任 solver 自己)
  2. 技高 fixture 的 3 連堂課全部連續且不跨午休;實習工場同時段不超容量
  3. 鎖定 5 格後重解,該 5 格位置不變
  4. 12 班國中 fixture 在 CI 機器 60 秒內解出
- **測試方式**:`tests/solver/` + `validator.py`(獨立驗證器,亦供日後回歸)

### [ ] M3-3 軟約束與目標函數
- **描述**:實作 S1–S8 軟約束(architecture.md §3.2)加權目標;權重設定存 DB(`constraint_config`),UI 於 v2 才做,先用預設值;解出後產出「軟約束達成度報告」(各項得分/滿分、未達成明細)。
- **驗收標準**:
  1. 同 fixture 開/關 S2(同科分散)比較:開啟後同班同科目同日 ≥2 節的數量顯著下降
  2. 教師 avoid 時段在有替代方案時被避開
  3. 報告列出「王師週四第7節被排課(偏好未達成)」等人話明細
- **測試方式**:pytest 比較性測試(斷言方向性,不斷言絕對分數)

### [ ] M3-4 Worker 整合與進度回報
- **描述**:排課任務走 RQ:`POST /timetables/{id}/auto-schedule` 入佇列;CP-SAT callback 每 5 秒寫進度(已找到解的目標值、經過時間)至 Redis;前端進度頁(polling)含「提前結束取目前最佳解」與「取消」;timeout 預設 10 分鐘可設定;結果寫回為新草稿。
- **模組**:`app/workers/solve_job.py`、`frontend/src/views/scheduling/AutoSchedule.vue`
- **驗收標準**:
  1. 啟動排課後 UI 顯示進度;點「提前結束」拿到當前最佳解草稿
  2. 排課期間 Web 其他功能不受影響(worker 隔離)
  3. worker 容器被 kill 後任務標記失敗,UI 有明確錯誤而非永久轉圈
- **測試方式**:pytest(RQ 假佇列)+ Playwright 長流程

### [ ] M3-5 無解衝突定位(conflict explainer)
- **描述**:assumption-based 衝突定位(architecture.md §3.4):各類硬約束掛 assumption literal,INFEASIBLE 時取 unsat core,轉譯為教務語言建議;「部分排課」模式(使用者勾選可放寬的約束類別,將其轉為高權重軟約束,未排入課務列清單)。
- **模組**:`app/solver/conflict_explainer.py`
- **驗收標準**:
  1. 製造「音樂教室需求 35 節>供給 30 節」的 fixture → 報告指出場地與數字
  2. 製造教師時段矛盾 → 報告指出該教師
  3. 部分排課模式:同 fixture 可產出 95%+ 排入的草稿 + 未排清單
- **測試方式**:pytest(3 種人造無解情境)

---

## M4 調代課

### [ ] M4-1 請假登記與受影響節次展開
- **描述**:`leave_request`/`affected_period` model;教師自登/組長代登 UI;依 published 課表展開受影響節次(半天/多天/跨週假);銷假(級聯取消處置並通知,architecture.md §5.3 狀態機)。
- **驗收標準**:
  1. 王師請週三整天假 → 自動列出週三 5 節受影響課
  2. 請假 3 天跨週末 → 只展開上課日節次
  3. 銷假後已指派代課的教師收到取消通知
- **測試方式**:pytest(日期邊界:週末、學期起訖外拒絕)

### [ ] M4-2 調代課處理工作台與推薦引擎
- **描述**:逐節處理 UI(代課/調課/併班/自習/不處理);**代課推薦服務**:硬性過濾(該時段空堂、當日未請假)→ 排序(同科目 > 當日已在校 > 本月代課鐘點少),每位候選附排序理由;調課(swap)驗證(architecture.md §5.3);指派即生效(**不設邀請/婉拒流程**,2026-07-09 使用者定案:組長實務上已事先口頭徵得同意,通知僅為正式告知+確認收到)。
- **模組**:`app/services/substitution_recommender.py`、`frontend/src/views/substitution/`
- **驗收標準**:
  1. 推薦清單第一名必為空堂+同科;已滿 6 節者排序靠後
  2. swap 後任一方衝突 → 拒絕並說明是誰在哪一節衝突
  3. 該時段全校無人空堂 → 顯示「無可代教師」並建議併班/自習
- **測試方式**:pytest 推薦排序表格測試(10+ 情境)

### [ ] M4-3 通知系統
- **描述**:`notification` model;通知寄送走 `NotificationChannel` 介面(architecture.md §5.3,MVP 實作站內+Email 兩個 channel,v2 增 webhook/LINE adapter);收件人解析經 `teachers.user_id`(站內)與 `teachers.email`(Email,M2-0 欄位);站內通知(鈴鐺、未讀數、輪詢);Email 寄送走 RQ(SMTP 設定於系統管理,未設定則僅站內通知並提示);通知模板(代課指派/取消、課表發布);教師「確認收到」頁(手機可用,一鍵確認);組長看板顯示各筆確認狀態,未確認者可一鍵再次提醒。
- **驗收標準**:
  1. 指派代課後,教師站內+Email 雙通知,點連結直達確認頁,一鍵「確認收到」
  2. 組長於看板可見確認/未確認狀態;對未確認者按「再次提醒」重發通知
  3. SMTP 未設定時系統正常運作(僅站內通知)
- **測試方式**:pytest(mailhog 容器攔信)+ Playwright 手機視窗尺寸

### [ ] M4-4 今日看板與調代課日誌
- **描述**:儀表板「今日調代課看板」(今日全部異動:誰代誰的課、教室異動);當日調代課通知單列印(A4,傳統公告格式);歷史查詢(依教師/日期/假別篩選)。
- **驗收標準**:
  1. 看板即時反映今日已確認處置;無異動顯示「今日無調代課」
  2. 列印版面 A4 一頁內,含節次/班級/原教師/代課教師
- **測試方式**:Playwright 快照

### [ ] M4-5 代課鐘點統計
- **描述**:月結統計:依教師彙total(代課節數、計費節數——併班/自習不計、假別、經費來源標記);Excel 匯出;教師個人可查本人明細。
- **驗收標準**:
  1. fixture 一個月 20 筆處置 → 統計數字與手算一致(含不計費項排除)
  2. 匯出 Excel 欄位:教師/日期/節次/班級/科目/原教師/假別/計費
- **測試方式**:pytest 計算正確性(邊界:跨月假單拆月計)

---

## M5 報表、備份與發行

### [ ] M5-1 課表匯出
- **描述**:班級/教師/場地課表匯出 Excel(openpyxl)、PDF(WeasyPrint,A4 直式含校名/學期/列印日)、PNG;全校總表 Excel;批次匯出(全部班級一鍵 zip)。
- **驗收標準**:
  1. 三種格式與畫面課表內容一致;PDF 中文無亂碼(內嵌字型)
  2. 60 班批次匯出 < 60 秒
- **測試方式**:pytest 內容比對(Excel 讀回驗證)+ 人工檢視 PDF 版面

### [ ] M5-2 備份與還原
- **描述**:每日 02:00 自動 pg_dump(保留 30 份,RQ scheduler);管理 UI:立即備份/下載/上傳還原(還原前自動先備份現狀+二次確認);還原後強制全員重新登入。
- **驗收標準**:
  1. 備份→改資料→還原→資料回到備份點
  2. 上傳非法檔案被拒絕且系統無損
  3. 自動備份保留數正確輪替
- **測試方式**:pytest + docker 整合測試

### [ ] M5-3 部署文件與發行工程
- **描述**:`docs/deploy/` 中文圖文:Docker 安裝(Win/Linux/NAS)、三步驟安裝、升級、備份策略、VPS+HTTPS 選配、常見問題;README(中文為主+英文摘要);CHANGELOG;GitHub Release 流程(tag→CI 出雙架構 image);LICENSE(MIT);CONTRIBUTING.md。
- **驗收標準**:
  1. 依文件在乾淨 VM 從零安裝成功(實測)
  2. `docker compose pull && up -d` 從前一版升級,資料完整、遷移自動執行
- **測試方式**:乾淨環境實測(記錄於 PR)

### [ ] M5-4 E2E 總驗收與效能
- **描述**:Playwright 全流程情境:精靈建置→匯入→配課→自動排課→發布→請假→代課→月統計;效能驗收;無障礙基本檢查(鍵盤可操作、對比度)。
- **驗收標準**:
  1. 三套 fixtures 全流程 E2E 綠燈
  2. 60 班規模:頁面載入 p95 < 2s、check-conflict p95 < 100ms、自動排課 < 10 分鐘
  3. 以 4GB RAM 容器限制跑全流程不 OOM
- **測試方式**:CI E2E + 壓測腳本

---

## 測試策略總則

1. **三套學制驗證資料集**(`backend/tests/fixtures/`,M1 期間建立,全案共用):
   - `elementary_small`:國小 6 班(包班+科任+週三下午空+導師時間)
   - `junior_high_mid`:國中 12 班(領域課程+彈性課程+兼行政減課教師)
   - `vocational_high`:技高 15 班 3 科(3 連堂實習+工場容量限制+業界師資限定時段+跑班)
2. **排課引擎雙重驗證**:所有 solver 測試以獨立 `validator.py` 逐項檢查硬約束,絕不以 solver 自身狀態為準;validator 同時用於「匯入外部課表檢查衝突」功能的基礎。
3. **測試金字塔**:pytest 單元(服務層/引擎)為主體;Vitest 覆蓋 TimetableGrid 等核心元件;Playwright 僅覆蓋六大關鍵旅程(登入、精靈、手排、自排、調代課、匯出)。
4. **每張任務卡的完成定義(DoD)**:功能實作 + 卡上驗收標準自驗通過 + 新增測試綠燈 + 既有測試不退步 + ruff/eslint 乾淨。

---

## 給開發 AI 的固定工作準則

1. 開工前先讀 `docs/architecture.md` 對應章節;規格衝突時以 architecture.md 為準並回報矛盾。
2. 一次只做一張卡;卡外的好點子記入本檔末尾「Backlog」區,不順手實作。
3. UI 文案一律繁體中文台灣教務用語(節次、科任、配課、鐘點、跑班)。
4. 資料庫 schema 變更必附 Alembic 遷移,且可從前一版順向升級。
5. 完成後更新本檔核取方塊為 `[x]`,並在 PR/回報中逐條對照驗收標準說明驗證方式與結果。
6. **UI 驗收由 AI 以 Playwright 直接執行**(2026-07-09 起,使用者已授權):對含 UI 的任務卡,撰寫 Playwright 驗收腳本,以 headed + slowMo 模式在使用者螢幕上可見地執行,關鍵步驟截圖存 `frontend/e2e/screenshots/`(gitignore),AI 讀取截圖確認後向使用者回報;腳本存入 `frontend/e2e/` 累積為迴歸測試套件(即 M5-4 的分攤)。使用者僅需在旁觀看並對 UX/文案給回饋,不再手動逐步操作。

## Backlog(開發中冒出的點子記這裡,不排程)

- 前端 bundle 偏大(~1.4MB,主因 `app.use(naive)` 全量註冊 Naive UI)。M2 課表頁完成後改為按元件 import 或用 `naive-ui/es` 自動匯入,縮小體積。
- M0-3 CI 的 Playwright E2E job 尚未加入(目前無 E2E 測試),待 M5-4 建立 e2e 測試時補進 workflow。
- 前端 CI 用 `npm install`(未提交 package-lock.json);日後可提交 lock 檔改用 `npm ci` 以完全重現。
- `docker compose up` 端到端煙霧測試尚未納入 CI(需在 runner 起完整 stack),可於 M5 部署驗證時再加。
- **LINE 通知 adapter(v2)**:LINE Notify 已停用(2025-03),改走 LINE 官方帳號 Messaging API:各校自申請 OA 取得 channel token 填入系統設定;教師加 OA 好友後以綁定碼綁定取得推播用 userId(`teachers.line_id` 為人工聯絡用,不能直接推播)。實作為 `NotificationChannel` 的一個 adapter。
- 開新學期複製目前不帶學期起訖日,新學期需手動補填;可於複製對話框加起訖日欄位。
- 班級名稱同學期無唯一性約束(可建兩個「301」);可加 uq(semester_id, name)。
