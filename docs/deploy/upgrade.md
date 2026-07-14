# 升級指南

系統採「向前相容遷移」:升級時**資料保留**,資料表結構的變更由 `api` 容器啟動時自動執行(`alembic upgrade head`),你不需要手動改資料庫。

> **開始前先備份。** 升級本身不會刪資料,但任何重大操作前留一份備份是好習慣。到「系統管理 → 資料備份與還原 → 立即備份」,或見[備份指南](backup.md)。

## ⚠️ 升級到 v1.1:同學期班名不再允許重複

v1.1 起,同一個學期內不能有兩個同名的班級(衝突訊息、課表、匯出都以班名指稱班級,重複時你根本分不出是哪一班)。

**若你既有的資料裡就有重複班名**,升級時系統會自動把後面那幾筆改名為「301 (2)」「301 (3)」這樣——**不會刪掉任何班級、課表或配課**。升級後請到「基礎資料 → 班級」看一下有沒有這種名字,改成正確的班名即可。

## ⚠️ 升級到 v1.1:多了一個容器

v1.1 把背景工作拆成兩條佇列(排課歸排課、匯出/備份/寄信歸維運),因此**新增了 `worker-ops` 容器**——這樣你在等自動排課的那幾分鐘裡,按「匯出課表」仍然是秒回的。

**升級時務必連 `docker-compose.yml` 一起更新到 v1.1 的版本**(方式 A 請重新下載該檔,方式 B 的 `git pull` 會自動帶到)。若只換了映像卻沿用舊的 compose 檔,系統會照常啟動、排課也正常,但**匯出、備份、還原、寄信會全部逾時失敗**——因為沒有任何行程在守 `ops` 佇列。升級後用 `docker compose ps` 確認 `worker-ops` 在跑。

---

## 方式 A:拉取映像部署(最常見)

在放 `docker-compose.yml` 的資料夾內:

```bash
# 1)(建議)先在系統內按「立即備份」

# 2)(v1.1 起)更新 docker-compose.yml 到新版
#    https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml

# 3) 選擇版本:編輯 .env
#    釘選版本(可控):IMAGE_TAG=v1.1.0
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

- **正式環境建議 `IMAGE_TAG=v1.0.0` 這樣釘住特定版本**,你才能決定何時升級、升到哪一版,而不是每次 `pull` 都可能變動。
- 想升級時,把 `IMAGE_TAG` 改成新版本號,再 `docker compose pull && up -d`。
- 各版本的變更內容見專案根目錄的 [CHANGELOG.md](../../CHANGELOG.md);破壞性變更(若有)會在該版本明確標註 ⚠️ 與對應處置。

---

## 回滾(升級後想退回舊版)

因為資料與映像分離,回滾映像很單純:

```bash
# .env 改回舊版本號,例如 IMAGE_TAG=v1.0.0
docker compose pull
docker compose up -d
```

> ⚠️ **注意資料庫遷移方向**:若新版本引入了資料表結構變更,退回舊映像後其程式可能不認得新結構。**最保險的回滾是:退回舊映像 + 還原「升級前那份備份」**(見[備份指南](backup.md)的還原流程)。若該次升級的 CHANGELOG 未標註 schema 變更,則單純換映像即可。

---

## 升級檢查清單

- [ ] 升級前已「立即備份」
- [ ] 已讀該版本 CHANGELOG,確認有無 ⚠️ 破壞性變更
- [ ] **(v1.1 起)`docker-compose.yml` 已更新到新版**——v1.1 新增了 `worker-ops` 容器
- [ ] `docker compose pull` 成功拉到新映像
- [ ] `docker compose up -d` 後六容器 healthy
- [ ] `/api/health` 回 ok,登入資料完整
- [ ] (如有 schema 變更)確認關鍵頁面正常
