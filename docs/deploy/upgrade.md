# 升級指南

> **首次安裝的人不需要這一頁**,直接看[安裝指南](install.md)。這裡講的是「已經在用,想換到新版」。

系統採「向前相容遷移」:升級時**資料保留**,資料表結構的變更由 `api` 容器啟動時自動執行(`alembic upgrade head`),你不需要手動改資料庫。

> **開始前先備份。** 升級本身不會刪資料,但任何重大操作前留一份備份是好習慣。到「系統管理 → 資料備份與還原 → 立即備份」,或見[備份指南](backup.md)。

## 一條規則:`docker-compose.yml` 要跟著版本走

系統的容器組成會隨版本演進(例如 v1.1 就多了一個 `worker-ops` 容器)。**升級時請連 `docker-compose.yml` 一起更新到新版**——方式 A 重新下載該檔,方式 B 的 `git pull` 會自動帶到。

沿用舊 compose 檔而漏了新容器時,系統不會默默壞掉:相關功能會**立刻**回一句說得出處置的錯誤(例如「維運背景服務(worker-ops)沒有在執行……請更新 docker-compose.yml」),補上新檔案再 `docker compose up -d` 即恢復,資料不受影響。

---

## 方式 A:拉取映像部署(最常見)

在放 `docker-compose.yml` 的資料夾內:

```bash
# 1)(建議)先在系統內按「立即備份」

# 2) 更新 docker-compose.yml 到新版(容器組成可能有變動)
#    https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml

# 3) 選擇版本:編輯 .env
#    釘選版本(可控):IMAGE_TAG=v1.1.1
#    永遠最新:        IMAGE_TAG=latest

# 4) 拉新映像並重啟
docker compose pull
docker compose up -d
```

`docker compose up -d` 只會重建映像有變動的容器;`api` 一啟動就自動跑遷移。完成後:

```bash
docker compose ps                 # 確認皆 healthy
curl http://localhost/api/health  # {"status":"ok"}
```

登入確認資料都在、版本正確(頁尾/關於頁顯示版本號)。

---

## 方式 B:從原始碼建置部署

```bash
git pull                 # 取得新版原始碼
docker compose up -d --build   # 重新建置並重啟
```

---

## 關於版本釘選

- **正式環境建議 `IMAGE_TAG=v1.1.1` 這樣釘住特定版本**,你才能決定何時升級、升到哪一版,而不是每次 `pull` 都可能變動。
- 想升級時,把 `IMAGE_TAG` 改成新版本號,再 `docker compose pull && up -d`。
- 各版本的變更內容見專案根目錄的 [CHANGELOG.md](../../CHANGELOG.md);破壞性變更(若有)會在該版本明確標註 ⚠️ 與對應處置。

---

## 回滾(升級後想退回舊版)

因為資料與映像分離,回滾映像很單純:

```bash
# .env 改回舊版本號,例如 IMAGE_TAG=v1.1.0
docker compose pull
docker compose up -d
```

> ⚠️ **注意資料庫遷移方向**:若新版本引入了資料表結構變更,退回舊映像後其程式可能不認得新結構。**最保險的回滾是:退回舊映像 + 還原「升級前那份備份」**(見[備份指南](backup.md)的還原流程)。若該次升級的 CHANGELOG 未標註 schema 變更,則單純換映像即可。

---

## 升級檢查清單

- [ ] 升級前已「立即備份」
- [ ] 已讀該版本 CHANGELOG,確認有無 ⚠️ 破壞性變更
- [ ] **`docker-compose.yml` 已更新到新版**(容器組成可能有變動)
- [ ] `docker compose pull` 成功拉到新映像
- [ ] `docker compose up -d` 後六容器 healthy
- [ ] `/api/health` 回 ok,登入資料完整
- [ ] (如有 schema 變更)確認關鍵頁面正常
