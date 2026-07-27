# 安裝指南

從零把系統架起來。整個過程約 15 分鐘(含下載映像)。

**有兩條路,選一條就好:**

| | 適合誰 | 你要做的事 |
|---|---|---|
| **[一鍵安裝腳本](#一鍵安裝推薦)** | 絕大多數人 | 裝 Docker → 執行腳本 → 回答三個問題 |
| [手動安裝](#手動安裝) | 想完全掌握每一步、或環境特殊 | 下面的步驟 0～3 |

兩者做的事完全一樣,腳本只是把手動的步驟 1～3 自動化(含產生金鑰、閃開被占用的埠號)。

---

## 一鍵安裝(推薦)

### 步驟 A:先裝好 Docker

同下方[步驟 0](#步驟-0先裝好-docker),裝完請確認 Docker 已啟動。

### 步驟 B:下載腳本,看過再執行

腳本刻意設計成「先下載、再執行」而不是一行指令直接跑——**這是要進學校主機的東西,你應該能先打開看過內容**。

**Windows(PowerShell)**:

```powershell
cd $HOME\Downloads
Invoke-WebRequest https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.ps1 -OutFile install.ps1
notepad install.ps1        # 先看過(可略)
.\install.ps1
```

> 若出現「因為這個系統上停用指令碼執行」的訊息,先執行一次:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
> (只對這個視窗有效,關掉就恢復原設定。)

**Linux / macOS / NAS**:

```bash
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.sh
less install.sh            # 先看過(可略)
bash install.sh
```

### 腳本會做什麼

1. 檢查 Docker 裝好沒、引擎有沒有在跑(沒有的話直接告訴你該怎麼辦)
2. 建立安裝資料夾,下載 `docker-compose.yml`
3. **問你三件事**:校名、管理員密碼(輸入時不顯示)、對外埠號
4. 自動產生 `SECRET_KEY`(不需要 openssl)
5. 寫出 `.env`——你不必開文字編輯器
6. 下載映像、啟動六個容器、確認系統回應
7. 印出**校內其他電腦要連的網址**,並開啟瀏覽器

埠號 80 或 443 被其他服務占用時,腳本會自動改用可用的埠並告訴你。

### 常用選項

```bash
bash install.sh --path /opt/scheduling    # 指定安裝位置(Windows 用 -InstallPath)
bash install.sh --port 8080               # 指定埠號
bash install.sh --skip-start              # 只產生設定檔,先不啟動(想自己看過 .env)
bash install.sh --reconfigure             # 已裝過,要重新設定校名/密碼
```

裝好之後直接跳到[驗證安裝成功](#驗證安裝成功)。

### 想在同一台主機再裝一套(測試環境)

**這件事有陷阱,務必看一下。** Docker 用「專案名稱」決定哪些容器與資料屬於同一套,本系統固定叫 `scheduling`。所以在同一台主機的另一個資料夾重跑安裝,**不會產生第二套,而是會接管既有那一套**——連資料庫也是同一份。

腳本會偵測到這個情況並擋下來,提示你改用不同的專案名稱:

```bash
# Linux / macOS / NAS
bash install.sh --project-name scheduling-test --path ~/scheduling-test --port 8090

# Windows PowerShell
.\install.ps1 -ProjectName scheduling-test -InstallPath D:\scheduling-test -Port 8090
```

這樣兩套會完全獨立:容器、資料庫、備份各走各的,可以同時執行(埠號要不同)。專案名稱會記在該資料夾的 `.env` 裡,之後在該目錄下 `docker compose` 各項指令都會自動沿用,不必每次加參數。

> 要移除測試環境:`cd` 到它的資料夾執行 `docker compose down -v`(`-v` 會一併刪掉資料)。
> **執行前務必確認自己在測試環境的資料夾**,在正式環境的資料夾下這條指令會刪光你的排課資料。

---

## 手動安裝

以下是腳本背後實際做的事。想自己一步步來、或環境特殊(例如需要走 Proxy)時看這段。

---

## 步驟 0:先裝好 Docker

系統以 Docker Compose 運行,主機只需要裝 **Docker**(含 Docker Compose,現代版本已內建)。

### Windows

最快的方式是用 Windows 內建的套件管理員,在 PowerShell 執行一行:

```powershell
winget install Docker.DockerDesktop
```

或到 [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) 下載安裝檔。

接著:

1. 安裝時若提示啟用 WSL 2,照著開啟即可。
2. **裝完請重新開機**(WSL 2 需要)。
3. 開啟 Docker Desktop,等左下角變綠燈(Engine running)。
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

**Linux / macOS / Git Bash**:

```bash
mkdir scheduling && cd scheduling
# 下載 docker-compose.yml 與 .env.example(從專案 Releases 頁或原始碼取得)
curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml
curl -fL  https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/.env.example -o .env
```

**Windows PowerShell**:

```powershell
mkdir scheduling; cd scheduling
$base = "https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main"
Invoke-WebRequest "$base/docker-compose.yml" -OutFile docker-compose.yml
Invoke-WebRequest "$base/.env.example"       -OutFile .env
```

> Windows 請照上面這段,**不要照抄 bash 那段的 `curl`**。PowerShell 的 `curl` 是
> `Invoke-WebRequest` 的別名,吃不懂 `-fLO` 這種參數,會直接報錯。真要用內建的
> curl 程式必須寫全名 `curl.exe`。

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
openssl rand -hex 32        # Linux / macOS / Git Bash
```

Windows 沒有內建 `openssl`(它是隨 Git for Windows 一起裝的),在 PowerShell 改用:

```powershell
$b = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
($b | ForEach-Object { $_.ToString('x2') }) -join ''
```

把印出來的那 64 個字元貼到 `SECRET_KEY=` 後面即可。

> 沒改 `SECRET_KEY` 不會讓系統起不來——程式偵測到仍是範例值時會自動換一把隨機金鑰。
> 但那把金鑰只存在記憶體裡,**容器一重啟所有人就被登出**,所以還是設一個固定值為宜。

其餘設定(資料庫帳密、Redis、時區)維持預設即可。詳細每一項說明見 `.env.example` 內的註解。

> **`.env` 含機密,切勿上傳到 GitHub、雲端硬碟或任何公開處。** 本專案的 `.gitignore` 已排除它。

---

## 步驟 3:啟動

### 方式 A(拉取映像)

```bash
docker compose pull      # 下載官方映像(首次較久)
docker compose up -d     # 背景啟動六個容器
```

### 方式 B(從原始碼建置)

```bash
docker compose up -d     # 首次會自動建置映像,需數分鐘
```

啟動後首次會**自動執行資料庫遷移**(建立所有資料表),你不需要手動做任何 SQL。

---

## 驗證安裝成功

```bash
docker compose ps        # 六個容器應皆為 running / healthy
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

**另外要注意 443 埠**:系統會**無條件占用 443**,即使你沒有啟用 HTTPS。若主機上已有其他服務(例如另一套網站系統)占著 443,啟動時會出現:

```
Bind for 0.0.0.0:443 failed: port is already allocated
```

這個訊息只提 443,很容易誤以為跟自己設的 80 埠有關。解法是在 `.env` 加一行改掉它:

```ini
HTTPS_PORT=8443
```

不影響內網以 HTTP 使用;日後真要啟用網域 HTTPS 時再調整即可。(一鍵安裝腳本會自動偵測並閃開。)

---

下一步:設定[每日自動備份與異地備援](backup.md);若要讓校外也能連,見[網域與 HTTPS](https.md)。遇到問題見 [FAQ](faq.md)。
