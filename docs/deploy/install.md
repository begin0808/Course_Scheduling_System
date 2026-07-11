# 安裝指南

從零把系統架起來。整個過程約 15 分鐘(含下載映像)。

---

## 步驟 0:先裝好 Docker

系統以 Docker Compose 運行,主機只需要裝 **Docker**(含 Docker Compose,現代版本已內建)。

### Windows

1. 下載並安裝 [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)。
2. 安裝時若提示啟用 WSL 2,照著開啟即可。
3. 安裝後開啟 Docker Desktop,等左下角變綠燈(Engine running)。
4. 開「終端機 / PowerShell」,執行 `docker --version` 有版本號即成功。

### Linux(Ubuntu / Debian,校內伺服器常見)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # 讓目前使用者免 sudo 用 docker(需重新登入生效)
```

重新登入後 `docker compose version` 有版本號即成功。

### NAS(Synology / QNAP)

- **Synology**:「套件中心」安裝 **Container Manager**(舊機型為 Docker)。DSM 7.2+ 的 Container Manager 內建 Compose,可直接在「專案」頁貼上 `docker-compose.yml`。
- **QNAP**:「App Center」安裝 **Container Station**,其中的「應用程式(Applications)」支援 docker-compose.yml。
- NAS 記憶體建議 ≥ 4GB;自動排課較吃資源,尖峰時建議 8GB。

> NAS 圖形介面的操作細節各機型略有差異,但核心都是「貼上 compose 設定 → 提供 .env 環境變數 → 建立專案」。以下命令列步驟同樣適用於在 NAS 上開 SSH 操作。

---

## 步驟 1:取得設定檔

### 方式 A:拉取官方預建映像(推薦)

只需要兩個檔案:`docker-compose.yml` 與 `.env`。建立一個空資料夾(例如 `scheduling`),放入本專案的 `docker-compose.yml`,並在同層建立 `.env`(見步驟 2)。

```bash
mkdir scheduling && cd scheduling
# 下載 docker-compose.yml 與 .env.example(從專案 Releases 頁或原始碼取得)
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
curl -fL  https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/.env.example -o .env
```

### 方式 B:從原始碼建置

```bash
git clone https://github.com/begin0808/Course_Scheduling_System.git
cd Course_Scheduling_System
cp .env.example .env
```

---

## 步驟 2:修改 `.env`(至少改兩項)

用文字編輯器打開 `.env`,**最少**改這幾項:

```ini
ADMIN_PASSWORD=改成你的管理員密碼      # 首次登入後系統會再要求你改一次
SCHOOL_NAME=○○國民中學                # 顯示在介面與匯出的課表上
SECRET_KEY=改成一長串隨機字元          # 見下方產生方式,務必更換
```

**產生隨機 `SECRET_KEY`**(session 簽章金鑰,關係到登入安全,一定要換掉預設值):

```bash
openssl rand -hex 32        # Linux/Mac/Git Bash
```

其餘設定(資料庫帳密、Redis、時區)維持預設即可。詳細每一項說明見 `.env.example` 內的註解。

> **`.env` 含機密,切勿上傳到 GitHub、雲端硬碟或任何公開處。** 本專案的 `.gitignore` 已排除它。

---

## 步驟 3:啟動

### 方式 A(拉取映像)

```bash
docker compose pull      # 下載官方映像(首次較久)
docker compose up -d     # 背景啟動五個容器
```

### 方式 B(從原始碼建置)

```bash
docker compose up -d     # 首次會自動建置映像,需數分鐘
```

啟動後首次會**自動執行資料庫遷移**(建立所有資料表),你不需要手動做任何 SQL。

---

## 驗證安裝成功

```bash
docker compose ps        # 五個容器應皆為 running / healthy
curl http://localhost/api/health
# 預期回應:{"status":"ok"}
```

用瀏覽器開:

- 本機:<http://localhost>
- 校內其他電腦:`http://<主機的區網IP>`(例如 `http://192.168.1.50`,IP 用 `ipconfig` / `ip a` 查)

以 `.env` 設定的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登入,系統會要求你**首次改密碼**,接著進入**設定精靈**,依畫面五步驟建立學期、教師、班級、科目即可開始使用。

---

## 硬體最低需求

| 項目 | 最低 | 建議(含自動排課) |
|---|---|---|
| CPU | 2 核 | 4 核 |
| 記憶體 | 4 GB | 8 GB |
| 磁碟 | 10 GB | 20 GB(含備份保留 30 份) |
| 架構 | x86-64 或 ARM64(NAS/樹莓派可) | — |

官方映像同時提供 `linux/amd64` 與 `linux/arm64`,Docker 會自動挑選符合你主機的版本。

---

## 埠號被占用怎麼辦?

預設對外走 80 埠。若該埠已被其他服務使用,改 `.env`:

```ini
HTTP_PORT=8080
```

重新 `docker compose up -d`,改用 `http://<主機IP>:8080` 連線。

---

下一步:設定[每日自動備份與異地備援](backup.md);若要讓校外也能連,見[網域與 HTTPS](https.md)。遇到問題見 [FAQ](faq.md)。
