# 網域與 HTTPS(選配)

**校內網路使用不需要這篇** —— 用 `http://<主機IP>` 即可,免設定。

本篇適用於:要讓**校外**(在家、手機行動網路)也能連,並使用網域 + HTTPS 加密。系統的 web 容器用 Caddy,設定網域後會**自動申請並續期 Let's Encrypt 憑證**,你不必手動處理憑證。

---

## 你需要先具備

1. **一個網域名**(例如 `school.example.edu.tw`,或自備的網域)。
2. 一台**具公開 IP 的主機**(校內對外伺服器,或雲端 VPS)。
3. 能編輯該網域的 **DNS**,把網域指向主機 IP。
4. 主機的 **80 與 443 埠可從外網連入**(防火牆/資安設備放行;Let's Encrypt 簽發需要 80 埠)。

---

## 設定步驟

### 1. DNS 指向主機

在網域管理處新增一筆 **A 記錄**:

```
school.example.edu.tw   →   你的主機公開 IP
```

等 DNS 生效(數分鐘到數十分鐘)。可用 `nslookup school.example.edu.tw` 確認解析到正確 IP。

### 2. 在 `.env` 設定網域

```ini
SITE_ADDRESS=school.example.edu.tw
HTTPS_PORT=443
```

- `SITE_ADDRESS` 一填成網域,Caddy 就會自動走 HTTPS 並把 HTTP 轉址到 HTTPS。
- 不填(或留 `:80`)則維持內網 HTTP 模式。

### 3. 重啟

```bash
docker compose up -d
docker compose logs -f web     # 觀察憑證申請過程
```

第一次啟動時 Caddy 會向 Let's Encrypt 申請憑證,log 出現 `certificate obtained successfully` 即成功。之後用 `https://school.example.edu.tw` 連線,瀏覽器顯示鎖頭。

憑證存放於 `caddydata` volume,重啟不會重新申請;續期由 Caddy 自動處理。

---

## 在雲端 VPS 上部署(校內無法對外時)

若學校網路無法對外開埠,可租一台小型 VPS(1–2 vCPU / 2–4GB RAM 即可跑基本功能,自動排課建議 4 核 8GB):

1. 依[安裝指南](install.md)在 VPS 上裝好 Docker 並起好系統。
2. 依本篇設定網域與 `SITE_ADDRESS`。
3. VPS 防火牆/安全群組放行 **80、443**;**不要**對外開放 5432(PostgreSQL)、6379(Redis)、8000(api)——這些只在容器內部網路互通,compose 預設也不對外映射它們。

> **資料落在 VPS 上**,務必依[備份指南](backup.md)設好異地備援(定期下載 `.dump` 到校內或雲端硬碟)。VPS 若停租或損毀,只有異地備份能救回資料。

---

## 常見狀況

**憑證申請失敗(log 出現 challenge failed / timeout)**
- 多半是 80/443 沒對外通,或 DNS 還沒指到這台主機。先確認外網能連到主機的 80 埠。
- 網域必須是**真實可解析**的公開網域;`localhost` 或純 IP 無法申請公開憑證。

**只想要 HTTPS 但用自簽/內部憑證(純內網)**
- Caddy 對非公開網域可用其內部 CA。進階需求請參考 [Caddy 官方文件](https://caddyserver.com/docs/),或改用純 HTTP 內網部署。

**改了網域要換成另一個**
- 改 `.env` 的 `SITE_ADDRESS` 後 `docker compose up -d`。舊憑證留在 `caddydata` 不影響。

**80 埠被學校既有網站占用**
- HTTPS 自動簽發需要 80 埠做驗證,較難共用。建議此情境改用獨立 VPS,或與網管協調子網域與埠。
