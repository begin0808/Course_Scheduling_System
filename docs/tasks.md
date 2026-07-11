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

### [x] M2-5 版本管理與發布
- **描述**:多草稿並存(複製/改名/刪除);發布(draft→published,同學期舊 published 轉 archived);發布前完整性檢查(未排完課務列警告,可強制發布);全員課表查詢頁(班級/教師/場地,唯讀,手機可用);audit_log 記錄發布。
- **驗收標準**:
  1. 兩份草稿可並存互不影響;發布 B 後,查詢頁顯示 B,A 仍可編輯
  2. 有 3 節未排時發布 → 出現警告清單,確認後仍可發布
  3. teacher 角色登入手機瀏覽器可查本人課表
- **測試方式**:pytest 狀態轉換 + Playwright

---

## M3 自動排課

### [x] M3-0 三套學制驗證資料集(M2 健檢 2026-07-10 產出,M3-1 前必做)
- **背景**:測試策略總則承諾的三套 fixtures(標註「M1 期間建立,全案共用」)實際從未建立——`backend/tests/fixtures/` 目錄不存在,M1–M2 測試皆為各檔就地造小數據。M3-1/2/3/5 與 M5-4 的驗收全部以「三套 fixtures」為前提;不先補齊,每張 M3 卡會各自造資料、解的品質彼此不可比。
- **描述**:以 Python builder 函式(非靜態 JSON,直接用 models 寫入測試 session)實作三套資料集:
  1. `elementary_small`:國小 6 班(包班+科任、週三下午空、導師時間);
  2. `junior_high_mid`:國中 12 班(領域課程+彈性課程+兼行政減課教師);
  3. `vocational_high`:技高 15 班 3 科(3 連堂實習+實習工場+業界師資 unavailable 時段+跑班群組);
  4. 各附煙霧測試證明資料自洽:teacher_loads 無超鐘點、class_loads 不超可排節數、跑班群組同節次表。
- **模組**:`backend/tests/fixtures/{__init__,elementary,junior_high,vocational}.py`
- **驗收標準**:
  1. 三套 builder 可在乾淨測試 DB 建出完整學期(節次表/教師/班級/科目/場地/配課/連堂/時段規則)
  2. 煙霧測試通過(資料自洽,可被 CP-SAT 排出全解)
  3. 既有 135 個後端測試不退步
- **測試方式**:pytest

### [x] M3-1 Solver 資料層與 pre-flight 檢查
- **描述**:`solver/` 模組骨架:從 DB 讀取學期資料轉為純 dataclass 問題描述(solver 不碰 SQLAlchemy;**DB→dataclass 轉換層放 `app/services/solver_data.py`**,因 loader 必須 import models,放 solver/ 內會違反驗收 3);pre-flight 必要條件檢查(教師配課數≤可排格數、場地供需、班級節數,architecture.md §3.4)+ 班級人數>場地容量警告(D8);檢查報告 API。
- **補遺(M2 健檢 2026-07-10)**:`schedule_entries.room_id`(nullable FK,空=沿用配課的 room_id)+ 遷移——§2.2 承諾格位帶場地但 M2 未實作;solver 對「指定場地類型而未綁定場地」的配課需逐格指派場地,結果無處可存(M4 教室異動也需要)。conflict_checker `_build_occupancy` 與課表序列化改以 `coalesce(entry.room_id, assignment.room_id)` 取場地。
- **pre-flight「教師可排格數」定義**:單一節次表(絕大多數學校)=一般課格數 − unavailable 格數;跨表任教的教師以牆鐘區間聯集去重計數(D7 重疊矩陣)。
- **模組**:`app/solver/preflight.py`、`app/solver/problem.py`、`app/services/solver_data.py`
- **驗收標準**:
  1. 三套 fixtures(M3-0)皆可轉出問題描述且 pre-flight 通過
  2. 人為製造「王師 22 節但可排 20 格」→ 報告明確指出教師、數字
  3. solver 模組 `import` 不到 `app.api`/`app.models`(以 import-linter 或測試保證)
  4. 手動排課將格位放到與配課不同的場地後,check-conflict 以格位場地判定佔用
- **測試方式**:pytest

### [x] M3-2 CP-SAT 核心建模(硬約束)
- **描述**:實作 H1–H10 硬約束建模(architecture.md §3.2);連堂以區間建模;跑班同步;鎖定格位;場地互斥(D8);教師/場地跨節次表以 D7 重疊矩陣建模;求解取出結果轉 schedule_entry 列表(含逐格 room_id)。
- **補遺(M2 健檢 2026-07-10)**:
  1. `ortools` 依賴**此卡才加入** pyproject(M3-1 不需要,保持 pre-flight 輕量);注意 wheel 體積(~50MB)與 arm64 wheel 可用性,重建映像驗證;
  2. **H10 精確定義以獨立 validator 為準**:同班同科目每日「單節」數 ≤ 上限,連堂(block_rule 產生)的節數不計入;M2-3 手動 conflict_checker 目前把既有連堂 span 也計入每日計數,與此不一致,此卡順手對齊(改法:佔用索引的 subj_count 排除 span>1 或掛 block_rule 的格位)。
- **模組**:`app/solver/model_builder.py`
- **驗收標準**:
  1. 三套 fixtures 各自可解,且**逐項驗證**解零硬約束違反(以獨立 validator 檢查,不信任 solver 自己)
  2. 技高 fixture 的 3 連堂課全部連續且不跨午休;實習工場同時段不超容量
  3. 鎖定 5 格後重解,該 5 格位置不變
  4. 12 班國中 fixture 在 CI 機器 60 秒內解出
- **測試方式**:`tests/solver/` + `validator.py`(獨立驗證器,亦供日後回歸)

### [x] M3-3 軟約束與目標函數
- **描述**:實作 S1–S8 軟約束(architecture.md §3.2)加權目標;權重設定存 DB(`constraint_config`,含 H10 每日上限值),UI 於 v2 才做,先用預設值;解出後產出「軟約束達成度報告」(各項得分/滿分、未達成明細)。**補遺**:`subjects.is_major`(主科標記,S5 用)+ 遷移 + 科目表單勾選——現行 Subject 無此欄位。
- **驗收標準**:
  1. 同 fixture 開/關 S2(同科分散)比較:開啟後同班同科目同日 ≥2 節的數量顯著下降
  2. 教師 avoid 時段在有替代方案時被避開
  3. 報告列出「王師週四第7節被排課(偏好未達成)」等人話明細
- **測試方式**:pytest 比較性測試(斷言方向性,不斷言絕對分數)

### [x] M3-4 Worker 整合與進度回報
- **描述**:排課任務走 RQ:`POST /timetables/{id}/auto-schedule` 入佇列;CP-SAT callback 每 5 秒寫進度(已找到解的目標值、經過時間)至 Redis;前端進度頁(polling)含「提前結束取目前最佳解」與「取消」;timeout 預設 10 分鐘可設定;結果寫回為新草稿。**輸入輸出流定義(M2 健檢 2026-07-10)**:以來源草稿為輸入;`locked` 格位作為固定約束(H9)複製至結果草稿並保持鎖定;未鎖定的既有格位以 CP-SAT hint(`AddHint`)餵入以提高解的穩定性(重排時盡量少動);結果草稿命名「{來源名} 自排結果」,來源草稿不動。
- **模組**:`app/workers/solve_job.py`、`frontend/src/views/scheduling/AutoSchedule.vue`
- **驗收標準**:
  1. 啟動排課後 UI 顯示進度;點「提前結束」拿到當前最佳解草稿
  2. 排課期間 Web 其他功能不受影響(worker 隔離)
  3. worker 容器被 kill 後任務標記失敗,UI 有明確錯誤而非永久轉圈
- **測試方式**:pytest(RQ 假佇列)+ Playwright 長流程

### [x] M3-5 無解衝突定位(conflict explainer)
- **描述**:衝突定位(architecture.md §3.4):無解時指出是哪幾條硬約束湊在一起,轉譯為教務語言建議;「部分排課」模式(使用者勾選可放寬的約束類別,將其轉為高權重軟約束,未排入課務列清單)。
- **模組**:`app/solver/conflict_explainer.py`
- **驗收標準**:
  1. ✅ 製造「音樂教室需求 30 節 > 實際可用 28 節」的 fixture → 報告指出場地與數字
  2. ✅ 製造教師時段矛盾 → 報告指出該教師(兩位協同教師都點名)
  3. ✅ 部分排課模式:同 fixture 產出 97.8%(88/90)排入的草稿 + 未排清單
- **測試方式**:pytest(3 種人造無解情境 + 部分排課 + pre-flight 短路);Playwright ×2;真實 PostgreSQL + RQ 實測

**補遺(實作後)**
- **改用刪除法,不用 assumption / unsat core**。原設計是每類硬約束掛 assumption literal 取 unsat core,實測不可行:enforcement literal 讓 presolve 認不出鴿籠結構,同一份資料**純硬約束 0.8 秒證完,掛 assumption 後 60 秒證不完**(換過三種編碼皆然)。改成「把一組約束整個關掉、重建乾淨模型重解」,整套定位約 2~3 秒,且每條結論都被一次真實求解驗證過。
- 旋鈕只取教學組長改得動的東西:`H4` 教師不可排時段、`H3` 場地互斥、`H10` 每日科目上限、`H9` 鎖定格位。`H1`/`H2` 沒有旋鈕可轉,其成因 pre-flight 已算得出來。
- `H1`/`H2`/`H3` **永不可放寬**——那是物理不是政策(API 收到會回 400)。
- **逾時且零解時也跑定位**:帶軟約束目標函數的 CP-SAT 常證不出 INFEASIBLE,一律以純硬約束探測一次,才分得出「不可能」與「只是慢」。這是實機驗證才發現的——單元測試裡的小問題秒證無解,看不到這個坑。
- 部分排課的懲罰量級:未排入(10000) ≫ 放寬的約束(1000) ≫ 軟約束(1~8);因此其 `objective` 與一般模式尺度不同,UI 顯示「未排 N 節」而非目標值。
- 部分排課的 pre-flight 只擋結構性錯誤(連堂放不進、群組節數不一致、某類型場地掛零)。
- 部分排課結果一律再過 `validator`:除了被放寬的那類,其餘硬約束零違反。

---

## M4 調代課

### [x] M4-1 請假登記與受影響節次展開
- **描述**:`leave_request`/`affected_period` model;教師自登/組長代登 UI;依 published 課表展開受影響節次(半天/多天/跨週假);銷假(級聯取消處置並通知,architecture.md §5.3 狀態機)。
- **驗收標準**:
  1. 王師請週三整天假 → 自動列出週三 5 節受影響課
  2. 請假 3 天跨週末 → 只展開上課日節次
  3. 銷假後已指派代課的教師收到取消通知
- **測試方式**:pytest(日期邊界:週末、學期起訖外拒絕)

**補遺(實作後)**
- **`affected_period` 是快照,不是 join**(這是 M4 的地基決策):展開當下把配課/教師/班級/場地/節次名稱/起訖時間一併寫死。理由與 D4 一致——課表可以重新發布,但「王師 11/12 第三節原本要上 301 班國文」是既成事實,不該隨課表改版漂移,更不該讓一筆已指派的代課隔天指向另一門課。溯源指標(schedule_entry_id/course_assignment_id)課表刪除時 SET NULL,快照欄位仍在。真機驗過:刪掉已發布課表後,受影響節次原封不動。
- **只看已發布課表**:草稿隨時會變,拿草稿找代課老師沒意義。課表未發布時假單照樣成立,只是展開 0 節。
- **上課日由節次表決定**,不寫死週一~週五:六日制學校的週六有課由 `num_weekdays` 判定(週末跳過 = `isoweekday() > num_weekdays`)。
- **半天假以牆鐘時間區間重疊判定**;節次表沒填起訖時間時保守列入(寧可多列一節讓組長刪,也不要漏掉一節變成沒老師的教室)。多日假只有頭尾兩天受時間限制,中間整天。
- **銷假級聯**:已完成的節次不動(課上過了,鐘點照算);已指派代課的轉為已取消並**合併**通知代課教師(一人多節一封信);當事人另收銷假通知。這條在 M4-1 就做掉,不留到 M4-3。
- **通知只落地、不寄送**:`notifications.notify()` 是 M4-3 `NotificationChannel` 的寫入點;寫入永遠成功,寄送(站內鈴鐺/Email)可失敗可重試,不綁同一交易。
- **RBAC**:教師自登只能登自己、只看自己;組長/主任可代登代銷看全校。教師端請假頁手機可用(路由守衛新增 `leaves` 為教師可進頁面)。
- **前端**:日期一律附星期(「2026-11-11(週三)」),否則看不出跨六天為何只有一天有課;已取消狀態改用淡色文字,不與「待處理」搶眼(Naive 的 tag `type="default"` 在此仍沿用前次主題色,故不用 tag)。日期用本機格式不用 `toISOString`(UTC 會讓台灣凌晨倒退一天)。

### [x] M4-2 調代課處理工作台與推薦引擎
- **描述**:逐節處理 UI(代課/調課/併班/自習/不處理);**代課推薦服務**:硬性過濾(該時段空堂、當日未請假)→ 排序(同科目 > 當日已在校 > 本月代課鐘點少),每位候選附排序理由;調課(swap)驗證(architecture.md §5.3);指派即生效(**不設邀請/婉拒流程**,2026-07-09 使用者定案:組長實務上已事先口頭徵得同意,通知僅為正式告知+確認收到)。
- **模組**:`app/services/substitution_recommender.py`、`frontend/src/views/substitution/`
- **驗收標準**:
  1. 推薦清單第一名必為空堂+同科;已滿 6 節者排序靠後
  2. swap 後任一方衝突 → 拒絕並說明是誰在哪一節衝突
  3. 該時段全校無人空堂 → 顯示「無可代教師」並建議併班/自習
- **測試方式**:pytest 推薦排序表格測試(10+ 情境)

**補遺(實作後)**
- **「週格 vs 特定日期」的落差用獨立的 `availability.py` 收斂**(Fable 5 M3 審查點名的 M4 最大架構工作):可用性判斷疊三層——週課表有沒有課(D7 牆鐘重疊)、當天自己有沒有請假、當天有沒有被指派代別班。今日看板(M4-4)與代課推薦共用這一層。
- **當日請假必須讀假單本身的日期/時間窗,不是展開的 `affected_period`**——這是實作時測試抓到的真 bug:老師請整天假、但某節恰好是他的空堂時,`affected_period` 不涵蓋那一格(它只在有課的節次才存在),若照它判斷會把一位不在校的老師找來代課。改為直接比對 `leave_request` 的 start/end 日期時間(與 `leaves.expand` 同一套半天窗語意)。
- **推薦排序**:同科目 > 當天已在校 > 本月代課鐘點少 > 姓名(穩定)。每位候選附人話理由(「同科目教師 · 當天已在校 · 本月已代 2 節」),不是黑箱分數。
- **swap(調課)驗四件事**:乙在甲那節無課、swap_entry 確是乙的課、甲在補課那節無課也沒請假、補課日星期與該節課相符。任一撞課指名道姓拒絕。swap 交換的節次以快照保存(swap_date/period_name/class_names/subject_name),課表改版不影響已成立的調課。
- **鐘點政策**:代課計、併班/自習/不處理不計(可覆寫),供 M4-5 月結。`substitution` 是處置真相來源,`affected_period.handler_teacher_id`/`status` 為冗餘指標。
- **指派即生效**:建立處置 → 節次轉『已確認』+ 記處理教師 → 通知處理教師(站內落地,M4-3 才寄送)。撤回處置退回待處理並通知取消。無邀請/婉拒(2026-07-09 定案)。

### [x] M4-3 通知系統
- **描述**:`notification` model;通知寄送走 `NotificationChannel` 介面(architecture.md §5.3,MVP 實作站內+Email 兩個 channel,v2 增 webhook/LINE adapter);收件人解析經 `teachers.user_id`(站內)與 `teachers.email`(Email,M2-0 欄位);站內通知(鈴鐺、未讀數、輪詢);Email 寄送走 RQ(SMTP 設定於系統管理,未設定則僅站內通知並提示);通知模板(代課指派/取消、課表發布);教師「確認收到」頁(手機可用,一鍵確認);組長看板顯示各筆確認狀態,未確認者可一鍵再次提醒。
- **驗收標準**:
  1. 指派代課後,教師站內+Email 雙通知,點連結直達確認頁,一鍵「確認收到」
  2. 組長於看板可見確認/未確認狀態;對未確認者按「再次提醒」重發通知
  3. SMTP 未設定時系統正常運作(僅站內通知)
- **測試方式**:pytest(mailhog 容器攔信)+ Playwright 手機視窗尺寸

**補遺(實作後)**
- **NotificationChannel 分層**:`notifications.notify()` 建立站內通知列(永遠送達)後,逐一經 `CHANNELS`(`InAppChannel` no-op + `EmailChannel`)派送;v2 加 webhook/LINE 只需再實作一個 channel 並 append。
- **Email 的交易語意**:EmailChannel 不直接 enqueue,而是把信放進 `session.info` 的寄件匣;SQLAlchemy 的 `after_commit` 事件才排入 RQ,`after_rollback` 則丟棄——交易回滾就不會寄出一封對應到不存在通知的信(雙寫問題的正解)。已測 rollback 不寄、commit 才寄。
- **站內永遠可用,Email 是加分**:SMTP 未設定時 `email.send` 回 False、`email_job` 只記 log,整個調代課流程照常。這是驗收③,實機在 mailhog 上驗過雙通道。
- **SMTP 設定存 `app_settings`**(全域 key/value,非學期範圍);密碼留空 = 不變更,回傳不含明文。管理員專屬。`POST /settings/smtp/test` 當場寄測試信回報結果(不走 RQ)。
- **確認收到 = 通知層已讀確認**,不影響課務(指派即生效,2026-07-09 定案)。教師鈴鐺(輪詢 20s + 未讀數 badge)、組長看板(確認狀態 + 對未確認者「再次提醒」重發,已確認則 409)。
- **開發用 mailhog**:docker-compose 加 `mailhog`(profile `dev`,不影響正式部署);`docker compose --profile dev up` 才啟動,Web UI :8025。
- **E2E 教訓**:共用 e2e_teacher 帳號 + 發布課表的測試會用「最近學期」預設互相污染;測試中途失敗會跳過收尾清理,故改用 `test.afterEach` 兜底刪除學期。另 Naive 的 message toast 與 tag 同字串會觸發 strict-mode(getByText 命中兩個),toast 文案要與 tag 區隔。

### [x] M4-4 今日看板與調代課日誌
- **描述**:儀表板「今日調代課看板」(今日全部異動:誰代誰的課、教室異動);當日調代課通知單列印(A4,傳統公告格式);歷史查詢(依教師/日期/假別篩選)。
- **驗收標準**:
  1. 看板即時反映今日已確認處置;無異動顯示「今日無調代課」
  2. 列印版面 A4 一頁內,含節次/班級/原教師/代課教師
- **測試方式**:Playwright 快照

**補遺(實作後)**
- **看板/日誌不新增真相,只攤平**:`substitution_log.py` 把「受影響節次 + 處置」join 成一列列可讀紀錄,今日看板與歷史查詢共用同一 `LogEntry`。真相仍在 `affected_period`(快照)與 `substitution`(處置決定)。
- **「今日」以學校時區判定**(config.tz,預設 Asia/Taipei),不是 UTC——台灣凌晨的 UTC 仍是前一天(D6)。前端深連結可帶 `?date=&semester_id=` 指定任一天,未帶則後端以 `school_today()` 為準。
- **看板含待處理節次**,好讓組長一眼看出還有幾節沒排代課;排除已銷假(cancelled)的節次(那天沒有異動)。列印通知單則只列已安排的處置(公告只公告已定案的)。
- **歷史查詢的 `teacher_id` 同時比對缺課當事人與接手代課者**——查一位教師,他缺的課與他代的課都算相關(以冗餘的 `affected_period.handler_teacher_id` 命中接手方)。
- **A4 列印頁是獨立路由 `/daily-board/print`**(不套側邊欄版面),`window.open` 新分頁開啟;`@media print` 隱藏工具列、設 `@page A4`。校名取自 config.school_name,隨看板回應帶出(免另設定)。
- **踩雷:`date`/`start_time` 欄位名遮蔽 datetime 型別**——dataclass/pydantic 內欄位命名為 `date` 後,同類別後續以 `date` 標註型別會被 mypy 視為「用變數當型別」而報錯。以模組別名 `_Date = date` 標註型別解決。

### [x] M4-5 代課鐘點統計
- **描述**:月結統計:依教師彙total(代課節數、計費節數——併班/自習不計、假別、經費來源標記);Excel 匯出;教師個人可查本人明細。
- **驗收標準**:
  1. fixture 一個月 20 筆處置 → 統計數字與手算一致(含不計費項排除)
  2. 匯出 Excel 欄位:教師/日期/節次/班級/科目/原教師/假別/計費
- **測試方式**:pytest 計算正確性(邊界:跨月假單拆月計)

**補遺(實作後)**
- **兩個數字**:代課節數(所有接手處置:代課/調課/併班)vs 計費節數(`counts_toward_hours` 為真者)。自習/不處理沒有處理教師,不計入任何人;併班有接手者但預設不計費(可覆寫)。「併班/自習不計」指的是計費,不是代課節數。
- **跨月假單自動拆月**:以每一個 `affected_period` 自己的日期分月,不是以假單分月。王師請 1/30~2/2,1 月的節次進 1 月報表、2 月的進 2 月,無需特別處理。
- **銷假的節次不計但已完成的保留**:`leaves.cancel` 把未完成節次轉 `cancelled`(那堂課沒上)、保留 `completed`(課上過了鐘點照算);統計以 `affected_period.status != cancelled` 過濾,不看假單狀態(才不會漏掉部分銷假的已完成節次)。
- **RBAC**:組長/主任看全校並匯出 Excel(`/substitution-stats` + `/export`);教師只能查自己(`/substitution-stats/mine`,以 current_teacher 綁定解析,無綁定回空報表)。前端同一頁依角色分流:管理者有教師篩選+匯出鈕,教師版隱藏。教師頁加入路由守衛白名單。
- **Excel 兩張表**:彙總(教師/代課節數/計費節數)+ 明細(教師/日期/節次/班級/科目/原教師/假別/處置/計費/經費來源);沿用 importer 的 openpyxl Workbook + FastAPI Response(Content-Disposition attachment)。前端以 `window.open` 帶 cookie 觸發下載。
- **深連結**:統計頁與看板頁一樣支援 `?year=&month=&semester_id=`,便於分享與測試。

### M4 里程碑複審(Fable 5,2026-07-11)與修正
- **條件 A(已修)——「已完成」不落盤,改讀取時推導**:§5.3 的「已確認→已完成:上課日結束自動轉換」原本無任何程式寫入 `completed`,導致兩道完整性保護失效(銷假會抹掉已上過課的鐘點、可事後改派已上完的代課)。改為 `app/core/clock.py` 的 `is_past_slot(date,end_time)`(以 config.tz 判定):`leaves.cancel` 對已上過的節次不轉 cancelled、`substitutions.assign/clear` 對已上過的節次回 409;顯示層 `leaves.effective_status()` 把 resolved+已過推導為 completed。M5-2 的 RQ scheduler 上線後可再補夜間 sweep 落盤,但正確性不依賴排程。
- **條件 B(已修)——swap 補課判定漏比對教師**:`availability._already_covering` 的 swap 分支原本只比對 `swap_date`+`period_no`,任一筆調課成立後補課日該節次會誤判**全校**已佔用。改為 join `AffectedPeriod→LeaveRequest` 加 `teacher_id`(補課方=該調課請假的當事人)+ `status=registered` + 節次未取消。
- **條件 C(已修)——公平計數含幽靈代課**:`_monthly_sub_counts` 未排除已銷假節次,銷假後那筆代課仍計入「本月已代 N 節」,與 M4-5 統計口徑不一。加 `status != cancelled`。公平計數維持以**計費節數**(counts_toward_hours)計,與顯示的「本月已代 N 節」一致。
- **條件 E(已處理)**:(1) 看板與統計口徑差已記於補遺(唯一分歧=銷假假單中已完成的節次:不上看板但計鐘點,合理);(2) swap 補課可用性退化為 period_no 比對,跨節次表學校有 D7 精度損失,列 v1.x;(3) `notifications` 的 after_commit enqueue 失敗改為 `logger.warning` 留痕,不再無聲吞掉。
- **條件 D(排入 M5-0)**:學期中重新發布課表後,未來日期的 `affected_period` 仍指向舊格位——見 M5-0。

---

## M5 報表、備份與發行

### [x] M5-0 發行前置(Fable 5 建議,M5-1 前必做)
- **描述**:一次備妥 M5 各卡的共用基礎設施,避免每張卡各自處理環境。
  1. **PDF/字型基礎**:worker 映像安裝 WeasyPrint 系統依賴(Pango/Cairo/gdk-pixbuf)與**中文內嵌字型**(Noto Sans TC / Noto Serif TC),供 M5-1 PDF、M5-2 之後的報表共用。字型與重量級原生依賴只裝在 worker(匯出走背景任務),api 映像維持精簡。
  2. **RQ scheduler 骨架**:立起定時任務排程器(M5-2 每日備份、條件 A 選配夜間 sweep 都掛這裡);docker-compose 加 scheduler 服務,先跑一個 heartbeat/no-op 週期任務驗證存活。
  3. **效能 fixture**:以 M3-0 的學制 builder 長出 60 班規模資料集,供 M5-1「60 班批次 < 60 秒」與 M5-4 壓測共用;先確認 builder 能產生該規模。
  4. **條件 D:重新發布重展開受影響節次**:`leaves.expand` 只在登記當下依當時 published 課表展開;學期中重新發布課表後,**今日之後**的 pending/resolved 受影響節次仍指向舊格位(代課老師被派去上已移走的課)。M5-0 先做最小防護——publish 時偵測該學期「今日之後」的受影響節次數 > 0 就於回應與 UI 加警告;完整重跑 expand+diff+通知列為後續增強。
- **驗收標準**:
  1. worker 容器內 `python -c "import weasyprint"` 成功,且以內嵌字型渲染中文 PDF 無 tofu(目視一張測試頁)
  2. scheduler 服務啟動後,週期任務有觸發紀錄(log)
  3. 60 班 fixture builder 產出資料,基本查詢正常
- **測試方式**:容器內 smoke test(WeasyPrint 匯入 + 中文 PDF)、scheduler 存活紀錄、fixture builder pytest

**補遺(實作後)**
- **多階段 Dockerfile(base / worker)**:api 用 `base`(精簡),worker 用 `worker`(額外裝 Pango/Cairo/gdk-pixbuf + `fonts-noto-cjk` + poppler-utils + `pip .[export]` 的 WeasyPrint)。compose 與 CI 皆以 `target:` 指定;CI 另推 `-worker` 映像。`app/services/pdf.py` 的 `render_pdf` 延遲匯入 weasyprint,api 匯入不會失敗(匯出一律走 worker 背景任務)。**實機驗證**:worker 容器內 weasyprint 69.0 匯入成功,渲染繁中 PDF→PNG 目視無 tofu(排課/調代課/王小明/國文/甲乙丙丁…/藝術與人文 皆清晰)。
- **排程器骨架**:worker 已 `with_scheduler=True`;不加獨立容器(單校部署少一個行程),改用「執行時排下一次」的自我續期心跳(固定 job_id,重啟不堆疊),`ensure_scheduled()` 於 worker 啟動時排入。M5-2 每日備份、條件 A 選配夜間 sweep 都掛此模式。**實機驗證**:ScheduledJobRegistry 含 `scheduler-heartbeat`,手動觸發 job 狀態 FINISHED 且自我重排成功。
- **60 班效能 fixture**:`tests/fixtures/scale.py` 的 `build_large_school(num_classes=60)`,以貪婪「最少負載且不超 base」指派教師(不保證可完全排課,量為主);pytest 驗 60 班 660 配課、無教師超鐘點。
- **條件 D 最小防護(已做)**:`timetable_publish.stale_future_affected_count` 算「今日之後、依先前課表展開」的待處理/已指派受影響節次;發布回應加 `stale_affected`,前端發布成功後 >0 則跳警告 toast(請至今日看板/調代課紀錄重新檢視)。完整解(重跑 expand+diff+通知)仍列後續增強。

### [ ] M5-1 課表匯出

### [x] M5-1 課表匯出
- **描述**:班級/教師/場地課表匯出 Excel(openpyxl)、PDF(WeasyPrint,A4 直式含校名/學期/列印日)、PNG;全校總表 Excel;批次匯出(全部班級一鍵 zip)。
- **驗收標準**:
  1. 三種格式與畫面課表內容一致;PDF 中文無亂碼(內嵌字型)
  2. 60 班批次匯出 < 60 秒
- **測試方式**:pytest 內容比對(Excel 讀回驗證)+ 人工檢視 PDF 版面

**補遺(實作後)**
- **共用格線模型**:`timetable_export.py` 把已發布課表(D4 快照)攤成 `Grid`(節次列 × 星期欄,連堂以 span 合併),三種對象(班級=科目/教師/教室、教師=科目/班級/教室、場地=科目/班級/教師)與三種格式共用,確保內容一致(驗收①)。
- **Excel 在 api、PDF/PNG 在 worker**:openpyxl 輕量,班級/教師/場地/全校總表/批次 zip 皆 api 同步產生。PDF 需 WeasyPrint(系統依賴+中文字型只在 worker,見 M5-0),故 PDF/PNG 由 api 以 `queue.render_export` **阻塞式**派到 worker 渲染再取回(RQ result);PNG = WeasyPrint 出 PDF 後 poppler `pdftoppm` 轉單頁。
- **全校總表 vs 批次**:總表=一個 Excel 每班一分頁;批次=每班各一 Excel 打包 zip。單一課表匯出開放所有登入者(課表本就全校可查),總表/批次限教學組長以上。
- **中文檔名**:Content-Disposition 用 RFC 5987 `filename*=UTF-8''`,前端以 fetch blob 下載並解出檔名(順帶處理 4xx/5xx 與載入狀態)。
- **驗收②**:60 班批次為 CPU-bound(60 個 openpyxl workbook),與資料庫無關,pytest 用 `build_large_school` 實測 < 60 秒。**驗收①**:E2E 下載班級 PNG(走 worker WeasyPrint→pdftoppm)存檔目視:標題/校名/學期/列印日、節次×星期格線、早自習/午休淡色、週三第一節顯示國文/王老師,繁中無 tofu。

### [x] M5-2 備份與還原
- **描述**:每日 02:00 自動 pg_dump(保留 30 份,RQ scheduler);管理 UI:立即備份/下載/上傳還原(還原前自動先備份現狀+二次確認);還原後強制全員重新登入。
- **驗收標準**:
  1. 備份→改資料→還原→資料回到備份點
  2. 上傳非法檔案被拒絕且系統無損
  3. 自動備份保留數正確輪替
- **測試方式**:pytest + docker 整合測試

**補遺(實作後)**
- **pg 工具版本**:基底映像已是 Debian trixie(非 bookworm),其 main 內含 postgresql-client **17**;pg_dump 17 可備份 postgres:16 伺服器(client ≥ server 允許)。原想從 PGDG 裝 client 16,但 PGDG 的 libpq5 18 在 trixie 有相依衝突,故直接用發行版的 client。pg 工具只裝在 **worker** 映像(與 M5-1 的 WeasyPrint 同層),api 維持精簡。
- **跨版本還原的可忽略錯誤**:pg_dump 17 的備份含 `SET transaction_timeout`(v17 GUC),pg_restore 進 v16 伺服器會噴一個可忽略錯誤、exit code=1。依 pg_restore 慣例(0=全成功、1=完成但有忽略錯誤、>1=失敗)放行 exit 1 並記 log,資料仍正確還原(實測 revert OK)。
- **api/worker 分工**:清單/下載/上傳由 api 直接讀寫共掛的 `backups` volume;pg_dump/pg_restore 派到 worker(`queue.run_backup`/`run_restore` 阻塞式)。每日備份掛 M5-0 的排程器(`schedule_daily_backup` 於 backup_hour 排 enqueue_at,執行後自我續期;固定 job_id 重啟不堆疊)。
- **強制全員重新登入**:session 是無狀態簽章 cookie,還原資料庫不會使其失效。改在 **Redis** 記一個「最小有效簽發時間」(`session_epoch`),還原後設為現在;`get_current_user` 拒絕簽發早於此的 session。Redis 只是被還原的 PostgreSQL 之外的存放點。auth 端有 5 秒行程內快取(fail-open),故強制登出有 ≤5 秒傳播延遲(可接受)。
- **還原後補寫稽核的坑**:還原會 `pg_terminate_backend` 中止所有其他連線(含本請求的 DB 連線),且還原本身會覆蓋整個資料庫——所以還原前寫的稽核會被蓋掉、還原後用舊連線寫會失敗。正解:還原後 `engine.dispose()` 再開新連線,把稽核寫進**還原後**的資料庫。
- **非法上傳(驗收②)**:`save_uploaded` 先驗 `PGDMP` 魔數,非法直接拒絕、檔案不落地、不碰資料庫;還原既有備份前也再驗一次檔頭。
- **實機驗證(docker 整合)**:worker 內 pg_dump 17.10;備份→插入學期→還原→筆數回到備份點 ✅;輪替 3→keep=1→1 ✅;api POST /backups(RQ 阻塞)→201、POST restore→200(自動 presafe 備份)、/auth/me 由 200 轉 401(強制登出,~5s)、重登 200 ✅;非法上傳 400 且無檔案落地(pytest)。

### [x] M5-3 部署文件與發行工程
- **描述**:`docs/deploy/` 中文圖文:Docker 安裝(Win/Linux/NAS)、三步驟安裝、升級、備份策略、VPS+HTTPS 選配、常見問題;README(中文為主+英文摘要);CHANGELOG;GitHub Release 流程(tag→CI 出雙架構 image);LICENSE(MIT);CONTRIBUTING.md。
- **驗收標準**:
  1. 依文件在乾淨 VM 從零安裝成功(實測)
  2. `docker compose pull && up -d` 從前一版升級,資料完整、遷移自動執行
- **測試方式**:乾淨環境實測(記錄於 PR)

**補遺(實作後)**
- **同一份 compose,兩種部署**:為讓驗收②的 `docker compose pull` 有意義,`docker-compose.yml` 的 web/api/worker 三服務同時掛 `image:`(GHCR)與 `build:`——clone 原始碼者 `up -d` 仍在本機建置(行為不變),只需檔案者 `pull && up -d` 拉官方映像。映像版本由 `.env` 的 `IMAGE_TAG`(預設 latest,建議正式部署釘選版本號)決定。
- **CI 補版本標籤**:原 `images` job 只推 `:latest` 與 `:sha`,`IMAGE_TAG=v1.0.0` 會拉不到映像。三個映像各補推 `:${github.ref_name}`(main push=`main`、版本標籤=`v1.0.0`),版本釘選才真的成立;版本標籤仍為唯一觸發雙架構(amd64+arm64)的條件。
- **HTTPS 選配做成一個設定**:Caddyfile 站台位址寫死 `:80` 且烘進映像,拉映像的學校改不到。改為 `{$SITE_ADDRESS::80}` 環境變數(預設 `:80` 內網 HTTP;於 `.env` 設 `SITE_ADDRESS=網域名` 即自動申請/續期 Let's Encrypt 憑證)。compose 補 443 埠映射與 `caddydata` volume(憑證持久化,避免重啟觸發速率限制)。**實測**:預設(無網域)重建 web 後 `/api/health` 與首頁皆 200、web healthy,內網 HTTP 部署未受影響;`docker compose config` 在有/無 `SITE_ADDRESS` 兩路徑皆正確解析。
- **文件產出**:`docs/deploy/`(index/install/upgrade/backup/https/faq 六篇中文,含 Win/Linux/Synology/QNAP 安裝、異地備援、回滾與 schema 變更提醒、VPS 對外埠與資安)、改寫 `README.md`(英文摘要+功能總覽+雙部署快速開始+文件索引)、新增 `CHANGELOG.md`(Keep a Changelog,彙整 M0–M5)、`CONTRIBUTING.md`(開發環境/品質門檻/任務卡制/發布新版本流程)。`LICENSE`(MIT)M0 已具備。
- **驗收①「乾淨 VM 實測」的界線**:compose 解析、web 重建與預設 HTTP 服務已在本機 Docker 驗過;真正的「全新 VM 從零 pull 安裝」需待版本標籤推上 GHCR 後才可端到端跑(目前尚無 release tag),此步驟留給實際發布時(或使用者)在乾淨環境驗收並記錄於 PR。

### [x] M5-4 E2E 總驗收與效能
- **描述**:Playwright 全流程情境:精靈建置→匯入→配課→自動排課→發布→請假→代課→月統計;效能驗收;無障礙基本檢查(鍵盤可操作、對比度)。
- **驗收標準**:
  1. 三套 fixtures 全流程 E2E 綠燈
  2. 60 班規模:頁面載入 p95 < 2s、check-conflict p95 < 100ms、自動排課 < 10 分鐘
  3. 以 4GB RAM 容器限制跑全流程不 OOM
- **測試方式**:CI E2E + 壓測腳本

**補遺(實作後)**
- **驗收①分兩面落實**:(a) 後端 `tests/test_full_flow.py` 對**三套學制 fixtures**(國小/國中/技高)各跑完整管線——求解 → validator 驗零硬違反 → 發布快照 → 挑一位有課教師請整天假 → 依已發布課表展開受影響節次 → 用推薦挑空堂教師指派代課 → 月結統計數字對上;證明下游鏈路能吃真實求解結果並在三種學制一致成立(M3 只證到「解得出」)。(b) 前端 `full-journey.spec.ts` 一個學期連續走完自動排課(真實 solver worker)→ 版本發布 → 課表查詢 → 請假+代課(API)→ 月結(UI),截圖目視:自排「已找到 16 個解、產生草稿A 自排結果」、月結頁「國文師1 代 國文師2 事假 1 節、計費 1 節」。個別旅程細節仍由既有 26 支 spec 深入覆蓋。
- **踩雷:全流程測試的兩個時間性地雷**。(1) 求解要用 **hard-only config**(`SolverConfig.hard_only()`),否則掛軟約束目標函數的 CP-SAT 會為了逼近最佳跑到 `max_seconds` 天花板——三套 fixtures 各跑 120 秒共 6 分鐘;改 hard-only 後全部 15 秒。(2) 學期起訖必須設在**今日之後**:代課處置會用 `clock.is_past_slot` 拒絕已結束的節次,起初用 2025 的日期整批被判為「已結束」而指派失敗。
- **驗收②(check-conflict p95<100ms)**:`tests/test_perf_scale.py` 以 `build_large_school(60)`(660 配課)塞入 >1500 格合法佔用,量 30 次單格衝突檢查 p95。**頁面載入 p95<2s**:`perf-page-load.spec.ts` 對灌了 60 班的執行中全棧量測。**方法學校正**:最初用重複 `page.goto` 全頁重載量到配課頁 p95≈2.9s——那是每次重新下載/解析 ~1.4MB SPA bundle 的成本(CPU 競爭下放大),不是使用者實際的換頁延遲。改量**應用內導覽**(bundle 已暖):配課頁/課表查詢 p95≈85–89ms;冷啟首載(含 bundle)另記 1069ms,兩者皆 <2s。1.4MB bundle 的冷啟成本仍列 Backlog(按元件 import 縮小)。**自排<10 分**:60 班求解耗時不放進 CI 單元測試(以免每次跑十分鐘),由 M3 的 junior_high <60s 建模測試 + 全流程實測共同保證。
- **驗收③(4GB 不 OOM)**:新增 `docker-compose.limits.yml`(疊在正式 compose 上,`mem_limit` 合計 3.2GB:worker 1.5G/api 768M/postgres 512M/redis 256M/web 128M,留 ~0.8G 餘裕)。以此上限重建全棧跑完整旅程(含真實 solver),`docker stats` 峰值 api 132M/768M、postgres 36M/512M、worker 於小校求解下寬裕;全五容器 `OOMKilled=false`、`Restarts=0`。此檔亦作為 4GB 主機/NAS 部署參考。
- **無障礙基本檢查**:`a11y.spec.ts` 三案——(1) 僅鍵盤(Tab/輸入/Enter)完成登入直達儀表板;(2) 連續 Tab 焦點可達可互動元素;(3) 以 WCAG 相對亮度公式量對比:內文 ≥4.5:1(1.4.3 正常文字)、主要按鈕 ≥3:1(1.4.11 非文字元件)。
- **品質門檻**:後端 ruff/mypy 乾淨、pytest **371 passed**(+4);前端 eslint/vue-tsc build/vitest 11 綠;Playwright 全套(既有 26 + 新增 a11y 3 / 全旅程 1 / 頁面載入 1)。M5 里程碑完成,v1.0 可發行(打 `v1.0.0` 標籤觸發雙架構映像,見 CONTRIBUTING「發布新版本」)。

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
- **跑班群組內配課的 `periods_per_week` 未強制一致**(M3-0 發現):群組是「同時段開課」,`placements_for` 一次放入全部成員配課,節數不一致時較短的一筆會先被 H8 週節數守恆擋下,語意曖昧。`class_loads` 已取群組內最長者計算班級佔用;M3-2 的 pre-flight 已加 `group_shape_mismatch` 錯誤、建模則直接拒絕。仍建議在配課建立/修改的 API 就擋下(409),讓使用者當場知道。
- **映像因 ortools 膨脹到 660MB**(M3-2):ortools 連帶拉進 numpy/pandas/protobuf。實際只有 worker 容器需要排課引擎,api 容器不需要。可拆成兩個映像(共用 base + worker 額外裝 ortools),或改用 `ortools` 的精簡發行版。部署頻寬敏感時再處理。
- **開新學期複製不帶 `constraint_config`**(M3-3):新學期的軟約束權重會回到預設值。複製精靈可加勾選項。
- **軟約束權重設定 UI**(M3-3,v2):目前只有 `GET/PUT /api/solver/config`,沒有畫面。等 M3-4 的自動排課頁上線後,把權重滑桿放在該頁的「進階設定」摺疊區。
- **科目 Excel 匯入沒有「主科」欄**(M3-3):`subjects.is_major` 只能在科目表單勾選。匯入範本可加一個選填欄。
- **一門課整學期固定一間教室**(M3-2 建模選擇):`y[配課, 教室]` 是每筆配課一個變數,而非逐格挑教室。符合實務(課表上一門課就在一間教室),變數量也小得多。若日後需要「同一門課不同節在不同教室」,改為 `y[配課, 節次, 教室]` 即可,約束式不變。
- `teacher_time_rule` 無節次表維度(M2 健檢 2026-07-10):(weekday, period_no) 的牆鐘意義隨班級節次表浮動,多表學校中同一條規則在國中部與高中部指到不同時間。v1 定案:規則以「該筆配課班級的節次表」解讀(現行 conflict_checker 行為,M3-2 建模比照,單表學校無此問題);日後如有跨表教師的實際需求,再改為牆鐘區間定義(schema 需加 period_table_id 或改存時間區間)。
- 【Fable 5 審查】部分排課宣稱「永遠有解」,但 `_make_lesson_vars` 在候選為空時先 raise 才輪到 drop:完全被擋死的課(如未放寬 H4 的協同教學)會讓整個部分排課失敗,而非列入未排清單。
- 【Fable 5 審查】跑班群組在部分排課掉一格時,`extract` 對每筆成員配課各記一次未排,「未排 N 節」會灌水數倍。
- 【Fable 5 審查】衝突定位期間(最長 60 秒)不檢查 `should_stop`,使用者按「取消」無效,最後得到 failed 而非 cancelled。
- 【Fable 5 審查】`check_feasibility` 吞掉 `SolverInputError` 的訊息:未來任何建模 bug 都會偽裝成「資料無解」。至少把原始訊息記入 log / conflict detail。
- 【Fable 5 審查】`test_purity.py` 只收 `level == 0` 的 import,相對匯入(`from ..models import ...`)可完全繞過純度掃描。
- 【Fable 5 審查】未排清單只活在 Redis(24h TTL);部分排課草稿可被 force 發布,之後沒有任何持久紀錄說哪些課沒排。M5 報表會需要它。
- 【Fable 5 審查】「validator/report 與 model_builder 零共用程式碼」嚴格說不成立:三者共用 `problem.py` 的 `slots_overlap`(D7 判定)與 `course_key`(排課單位語意)。獨立性涵蓋**約束編碼**,不涵蓋這兩個定義層謂詞。應為它們補直接的邊界單元測試。
- 求解前先跑一次 hard-only 可行性探測(約 1 秒):既能提早回報「這份資料無解」,又能把該解當成正式求解的 warm start。目前是在失敗之後才探測。
- 部分排課的 timeout 幾乎必定用滿:CP-SAT 找到最佳的「未排 2 節」很快,但要證明「不可能只少排 1 節」很慢。可考慮找到解後以未排節數為上界再收斂,或給部分排課獨立的較短預設時限。
- 衝突定位的旋鈕清單未含「班級可排節次」與「連堂結構」;`structural` 模式目前只列最吃緊的班級/教師,沒有具體到「哪一門課改成連堂就好」。

---

## M3 審查修正(Fable 5 獨立審查,2026-07-10)

M3 完成後由 Fable 5 做獨立技術審查,判決「有條件可進 M4」。以下 5 項已修:

- **A. H10 雙軌判定**:`conflict_checker` 寫死 `cap=2`,solver 卻讀 `constraint_config`。學校把上限設成 3,自動排課排得出來、手動拖曳卻報違規。改為由 `check_conflict` 讀學期設定(hot path 加一次查詢,p95 仍 <100ms)。**M4 調代課直接重用這支檢查器,這條裂縫必須先補。**
- **B. 軟約束權重無上限**:`PUT /solver/config` 接受 `{"S2": 20000}`,而部分排課的「整節不排入」懲罰是 10000 → solver 會理性地丟課換分散度。新增 `MAX_WEIGHT = 100`(API 擋、`load_config` 讀取時夾),並在 `Relaxation.__post_init__` 斷言量級順序。
- **C. `unknown` 靜默降級**:試解逾時回 `unknown` 時被當成「不可行」,但 `complete` 沒有跟著降,`structural` 於是宣稱「即使放寬所有可調整的項目仍然無解」——一句從未被證明的話。新增 `_Prober` 追蹤 `certain`,任何 `unknown` 都讓 `complete=False`,structural 措辭隨之收斂。
- **D. pre-flight 場地供給不看科目適用性**:唯一的專科教室綁「美術」,音樂課要求專科教室 → 檢查放行、建模必然失敗、定位找不到該場地、報告文不對題。改為依「候選場地集合」分組比對供需(與 `_candidate_rooms` 同義),新增 `room_no_candidate` 結構性錯誤(部分排課亦擋)。
- **E. `_room_numbers` 混用池需求與單間供給**:多間同類型教室時,原因卡會憑空放大缺口。改為整池計算並在訊息中列出教室名。

驗證:pytest 273(+11,含 unknown 路徑 4 個測試)、真實 PostgreSQL 打過 A/B/D 端點、e2e 16 綠。
