# 常見問題 FAQ

## 安裝與啟動

**Q:`docker compose up -d` 後開網頁看到「502」或「無法連線」。**
容器可能還在啟動(尤其首次要跑資料庫遷移)。等 20–30 秒再試,並看狀態:

```bash
docker compose ps          # 看是否都 healthy
docker compose logs api    # 看 api 是否卡在遷移或報錯
```

**Q:`docker compose ps` 有容器一直 restarting。**
看該容器 log 找原因:

```bash
docker compose logs --tail=50 <服務名>   # 例如 api / worker / postgres
```

常見:`.env` 的 `DATABASE_URL` 與 `POSTGRES_*` 帳密不一致;`SECRET_KEY` 未設。

**Q:80 埠被占用,啟動失敗(port is already allocated)。**
改 `.env` 的 `HTTP_PORT`(例如 `8080`)再 `docker compose up -d`,改用 `http://<主機IP>:8080`。

**Q:校內其他電腦連不到。**
確認用的是主機的**區網 IP**(非 `localhost`),且主機防火牆放行該埠。手機/平板需與主機同一網段(同一 Wi-Fi)。

---

## 帳號與登入

**Q:忘記管理員密碼怎麼辦?**
若你還記得 `.env` 的初始 `ADMIN_PASSWORD`,那是**首次登入**用的;登入後改過的密碼存在資料庫。若連改過的都忘了,目前需由具資料庫存取權者重設。最務實的做法是**還原一份記得密碼的舊備份**(見[備份指南](backup.md)),或聯繫維護者。請妥善保管管理員密碼。

**Q:還原備份後大家被登出了。**
這是預期行為。還原會替換整個資料庫(含帳號),為安全起見系統會強制所有人以還原時點的帳密重新登入。

**Q:老師收不到調代課 Email。**
Email 為**選配**;未在「系統管理」設定 SMTP 時,只有站內通知(鈴鐺),系統一切正常。要寄 Email 需填學校的 SMTP 主機資訊,並可按「寄測試信」當場驗證。

---

## 資料與備份

**Q:我的資料存在哪?會不會不見?**
存在 Docker volume `pgdata`。只要不刪這個 volume,`docker compose down` / 重啟 / 升級都不會動到資料。**但主機硬碟壞掉 volume 會一起沒**,所以務必做[異地備援](backup.md)。

**Q:`docker compose down` 會刪資料嗎?**
不會。`down` 只停止並移除容器,volume 保留。**只有 `docker compose down -v` 的 `-v` 會刪 volume(含你的資料)**,請勿誤用。

**Q:怎麼把系統搬到新主機?**
新主機裝好空系統 → 舊主機下載一份備份 `.dump` → 新主機「系統管理 → 上傳還原」。詳見[備份指南](backup.md)。

---

## 效能與規模

**Q:自動排課很慢或跑不出來。**
排課是計算密集工作,受班級數、約束複雜度影響。建議主機 ≥ 4 核 8GB。無解時系統會給「衝突定位」報告,依提示放寬條件或補資源。可設定求解逾時(預設 10 分鐘),逾時取當前最佳解。

**Q:頁面偶爾轉圈久。**
自動排課/大量匯出時 worker 較忙,但與 api 分離,一般操作不受影響。自 v1.1 起排課(`worker`)與匯出/備份(`worker-ops`)分屬兩個容器,**排課進行中按匯出仍是秒回**。若持續緩慢,查主機資源(`docker stats`)是否吃緊。

**Q:匯出/備份時出現「維運背景服務(worker-ops)沒有在執行」。**

你的 `docker-compose.yml` 少了 `worker-ops` 這個容器(多半是用了舊版的 compose 檔)。它負責匯出、備份、還原、寄信與每日自動備份——沒有它,這些功能全都沒人處理,而且**每日自動備份是無聲停擺的**。

取得最新的 compose 檔再重啟即可,資料不受影響:

```bash
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
docker compose up -d
docker compose ps          # 應看到六個容器,含 worker 與 worker-ops
```

**Q:匯出課表 / 備份失敗,說「背景忙碌或逾時」。**

`worker-ops` 有在跑但沒做完。查它的 log:

```bash
docker compose ps worker-ops
docker compose logs --tail=50 worker-ops
```

PDF/PNG 匯出在低階機器上偶爾會超過 90 秒;主機吃緊(`docker stats`)時先讓自動排課跑完再試。

---

## 升級與版本

**Q:怎麼知道有沒有新版、這版改了什麼?**
看專案 [CHANGELOG.md](../../CHANGELOG.md) 與 GitHub Releases。升級步驟見[升級指南](upgrade.md)。

**Q:升級會不會弄壞資料?**
資料表結構變更由 `api` 啟動時自動、向前相容地遷移,資料保留。仍建議升級前先「立即備份」。破壞性變更(若有)會在 CHANGELOG 該版本以 ⚠️ 標註。

---

## 其他

**Q:可以多所學校共用一套嗎?**
本系統設計為**單校自架**,一所學校一套部署,資料彼此隔離、最單純也最安全。多校請各自部署。

**Q:如何完全移除?**

```bash
docker compose down -v     # ⚠️ 連同資料 volume 一起刪除,不可復原,請先備份!
```

**Q:找不到答案 / 想回報問題?**
到專案 GitHub 開 Issue(見 [CONTRIBUTING.md](../../CONTRIBUTING.md))。回報時附上 `docker compose logs` 相關片段會更快解決。
