# 貢獻指南

歡迎回報問題與貢獻程式。本專案為 MIT 授權、單校自架的排課與調代課系統,面向台灣中小學教學組長。

## 回報問題

到 GitHub 開 Issue,請盡量附上:

- 復現步驟、預期行為與實際行為。
- 環境:部署方式(拉映像 / 原始碼)、`IMAGE_TAG` 或 commit、作業系統。
- 相關 log:`docker compose logs --tail=100 api`(或 worker/web)。**請先移除機密**(密碼、`SECRET_KEY`)。

## 開發環境

### 熱重載全棧

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up
```

- 前端(熱重載):<http://localhost:5173>
- API 互動文件:<http://localhost:8000/api/docs>

前後端原始碼掛載進容器,存檔即時生效。含 `mailhog`(攔截外送信,Web UI <http://localhost:8025>)須以 `--profile dev` 啟動。

### 各自本機測試

```bash
# 後端
cd backend && pip install -e ".[dev]" && pytest
# 前端
cd frontend && npm install && npm run test
```

## 程式風格與品質門檻

送 PR 前請確保各項通過(CI 也會擋):

| 範圍 | 指令 | 要求 |
|---|---|---|
| 後端 lint/格式 | `ruff check .` | 零錯誤 |
| 後端型別 | `mypy app` | 零錯誤 |
| 後端測試 | `pytest` | 全綠,且不使既有測試退步 |
| 前端 lint | `npm run lint` | 零錯誤 |
| 前端建置+型別 | `npm run build`(含 vue-tsc) | 通過 |
| 前端單元測試 | `npm run test` | 全綠 |

其他約定:

- **UI 文案一律繁體中文、台灣教務用語**(節次、科任、配課、鐘點、跑班)。衝突/提示訊息用節次表中儲存的名稱(早自修/午休/第一節),不用內部 `period_no`。
- **資料庫 schema 變更必附 Alembic 遷移**,且能從前一版順向升級。
- solver 模組(`app/solver/`)不得 import `app.api` / `app.models`(以測試保證純度)。
- 架構規格以 [docs/architecture.md](docs/architecture.md) 為準;與任務卡衝突時以架構文件為準並回報矛盾。

### E2E(Playwright)

對「執行中的 Docker 全棧」驅動真實瀏覽器。需先 `docker compose up -d`,並有教學組長帳號 `e2e_scheduler`(密碼 `e2etest1234`)。

```bash
cd frontend
npx playwright install chromium   # 首次
npm run e2e            # 無頭執行
npm run e2e:headed     # 有頭 + 放慢,可在螢幕上觀看
```

## 提交與 PR

- 從 `main` 開分支開發;PR 對回 `main`。
- Commit 訊息用祈使句、精簡描述「做了什麼、為什麼」。
- PR 描述請逐條對照相關任務卡的驗收標準,說明驗證方式與結果。
- 不 force-push 共用分支;不繞過 hook 或簽章(除非明確需要)。

## 開發流程(任務卡制)

本專案以 [docs/tasks.md](docs/tasks.md) 的 Milestone 任務卡推進:一次一張卡,實作 → 依卡上「驗收標準」自我驗證 → 回報 → 驗收後才進下一張。完成後更新該卡核取方塊為 `[x]` 並補「實作後」紀錄。臨時冒出的點子記入 tasks.md 末尾的 Backlog,不順手實作。

## 發布新版本(維護者)

映像建置與發布已由 CI 自動化(見 [.github/workflows/ci.yml](.github/workflows/ci.yml)):

1. 確認 `main` 綠燈(backend / frontend / migrations 三個 job 通過)。
2. 更新 `CHANGELOG.md`:把 `[Unreleased]` 內容整理到新版本標題下並註明日期,標註破壞性變更(⚠️)。
3. 打標籤並推送:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

4. `v*` 標籤觸發 CI 的 `images` job,建置並推送**雙架構(amd64 + arm64)**映像到 GHCR:
   - `ghcr.io/begin0808/course_scheduling_system-api`
   - `ghcr.io/begin0808/course_scheduling_system-worker`
   - `ghcr.io/begin0808/course_scheduling_system-web`

   每個映像會推 `:latest`、`:<版本標籤>`(如 `v1.0.0`,即 `github.ref_name`)與 `:<commit sha>` 三個 tag。`main` push 僅建 amd64;**版本標籤才建雙架構**。
5. 在 GitHub 建立 Release,關聯該標籤,貼上該版 CHANGELOG 內容。
6. 使用者升級:`.env` 設 `IMAGE_TAG=v1.0.0` → `docker compose pull && docker compose up -d`(見 [docs/deploy/upgrade.md](docs/deploy/upgrade.md))。`IMAGE_TAG` 即對應此處推送的版本標籤。

## 授權

貢獻即表示你同意以 [MIT](LICENSE) 授權釋出你的貢獻。
