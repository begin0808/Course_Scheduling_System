#Requires -Version 5.1
<#
.SYNOPSIS
    排課與調代課系統 — Windows 一鍵安裝

.DESCRIPTION
    把「建資料夾 → 下載設定檔 → 編輯 .env → 啟動 → 找出連線網址」壓成一次執行。
    過程只問三件事:校名、管理員密碼、對外埠號;SECRET_KEY 自動產生。

    刻意設計成「下載後執行」而非 irm | iex:這是要進學校主機的東西,
    使用者應該能先打開看過內容再跑。

.EXAMPLE
    .\install.ps1
    互動安裝到 %USERPROFILE%\scheduling。

.EXAMPLE
    .\install.ps1 -InstallPath D:\scheduling -Port 8080
    指定安裝位置與埠號,其餘仍會詢問。

.EXAMPLE
    .\install.ps1 -SchoolName "○○國中" -AdminPassword "..." -Port 80 -Yes
    完全不互動(供自動化或重建環境使用)。

.LINK
    https://github.com/begin0808/Course_Scheduling_System
#>
[CmdletBinding()]
param(
    # 安裝目錄。裡面只會有 docker-compose.yml 與 .env,資料都在 Docker volume
    [string]$InstallPath = (Join-Path $HOME 'scheduling'),
    [string]$SchoolName,
    [string]$AdminPassword,
    [ValidateRange(1, 65535)]
    [int]$Port,
    [string]$TimeZone = 'Asia/Taipei',
    # Docker compose 專案名稱。同名就是同一套部署——想在同一台主機上再裝一套
    # (例如與正式環境並存的測試環境)必須指定不同的名稱,否則會接管既有那一套。
    [string]$ProjectName,
    # 要拉哪一版設定檔與映像。預設 main(最新);正式部署可釘 v1.1.2
    [string]$Ref = 'main',
    [string]$ImageTag = 'latest',
    # 只產生設定檔,不啟動(想先自己看過 .env 再手動 docker compose up -d 時用)
    [switch]$SkipStart,
    # 已安裝過時,重新設定 .env(預設會保留既有設定,不動你的密碼)
    [switch]$Reconfigure,
    # 全部用預設值/參數值,不詢問
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# 舊版 Windows 預設不啟用 TLS 1.2,不設會連不上 GitHub
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RepoUrl = 'https://github.com/begin0808/Course_Scheduling_System'
$RawBase = "https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/$Ref"

# PowerShell 5.1 的地雷:對原生程式做 2>&1 時,stderr 的每一行都會被包成 ErrorRecord,
# 在 $ErrorActionPreference='Stop' 之下會直接拋例外——即使該程式回傳 0。
# docker 很愛往 stderr 寫正常訊息,所以凡是需要「收下輸出並看結果」的呼叫都走這裡。
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @Arguments 2>&1 | Out-String
        return [pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Output = $out.Trim() }
    }
    finally { $ErrorActionPreference = $prev }
}

# ── 輸出小工具 ────────────────────────────────────────────────
function Write-Head($t) { Write-Host ''; Write-Host "  $t" -ForegroundColor Cyan }
function Write-Step($t) { Write-Host "  → $t" -ForegroundColor White }
function Write-Ok($t)   { Write-Host "  ✓ $t" -ForegroundColor Green }
function Write-Note($t) { Write-Host "    $t" -ForegroundColor DarkGray }
function Write-Attn($t) { Write-Host "  ! $t" -ForegroundColor Yellow }

function Stop-WithHelp {
    param([string]$Message, [string[]]$Hints)
    Write-Host ''
    Write-Host "  ✗ $Message" -ForegroundColor Red
    foreach ($h in $Hints) { Write-Host "    $h" -ForegroundColor Yellow }
    Write-Host ''
    exit 1
}

function Read-Default {
    param([string]$Prompt, [string]$Default)
    if ($Yes) { return $Default }
    $shown = if ($Default) { "$Prompt [$Default]" } else { $Prompt }
    $v = Read-Host "  $shown"
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
    return $v.Trim()
}

# ── 0. Docker 檢查 ───────────────────────────────────────────
function Test-DockerReady {
    Write-Head '[1/5] 檢查 Docker'

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Stop-WithHelp '找不到 Docker。' @(
            '本系統以 Docker 執行,請先安裝 Docker Desktop:'
            ''
            '  方式一(最快,系統內建的套件管理員):'
            '    winget install Docker.DockerDesktop'
            ''
            "  方式二:到官網下載安裝"
            '    https://docs.docker.com/desktop/install/windows-install/'
            ''
            '安裝完成後請「重新開機」,並確認 Docker Desktop 已啟動(工作列鯨魚圖示),'
            '然後重新執行本腳本。'
        )
    }

    # docker 指令在、但引擎沒跑,是最常見的情況——錯誤訊息一長串英文,先攔下來講人話
    if (-not (Invoke-Native docker @('info')).Ok) {
        Stop-WithHelp 'Docker 已安裝,但引擎沒有在執行。' @(
            '請從「開始」功能表開啟 Docker Desktop,等工作列的鯨魚圖示不再轉動'
            '(左下角顯示 Engine running),再重新執行本腳本。'
            ''
            '若剛裝好還沒重開機,請先重開機。'
        )
    }

    $v = (Invoke-Native docker @('version', '--format', '{{.Server.Version}}')).Output
    Write-Ok "Docker 引擎執行中(版本 $v)"

    if (-not (Invoke-Native docker @('compose', 'version')).Ok) {
        Stop-WithHelp '這個 Docker 沒有 Compose 外掛。' @(
            '請升級 Docker Desktop 到近期版本(內建 Compose v2)。'
        )
    }
    Write-Ok 'Docker Compose 可用'
}

# ── 1. 目錄與設定檔 ──────────────────────────────────────────
function Get-InstallDir {
    Write-Head '[2/5] 準備安裝目錄'

    if (-not (Test-Path $InstallPath)) {
        $null = New-Item -ItemType Directory -Path $InstallPath -Force
        Write-Ok "已建立 $InstallPath"
    }
    else {
        Write-Ok "使用既有目錄 $InstallPath"
    }
    return (Resolve-Path $InstallPath).Path
}

# compose 的專案名稱決定「哪些容器與 volume 屬於同一套」。預設寫死在
# docker-compose.yml 的 name: scheduling,可由 .env 的 COMPOSE_PROJECT_NAME 蓋過。
function Resolve-ProjectName([string]$Dir) {
    if ($ProjectName) {
        if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]*$') {
            Stop-WithHelp "專案名稱「$ProjectName」不合法。" @(
                'Docker 要求:只能用小寫英數字、底線與連字號,且開頭須為英數字。'
                '例如:scheduling-test'
            )
        }
        return $ProjectName
    }
    $envFile = Join-Path $Dir '.env'
    if (Test-Path $envFile) {
        foreach ($l in [System.IO.File]::ReadAllLines($envFile)) {
            if ($l -match '^COMPOSE_PROJECT_NAME="?([^"\s]+)"?') { return $Matches[1] }
        }
    }
    return 'scheduling'   # 與 docker-compose.yml 的 name: 一致
}

# 同名專案若指向別的目錄,docker compose up 會直接接管那一套——包含它的資料庫 volume。
# 這是本腳本唯一可能毀掉既有資料的路徑,所以擋在啟動之前。
function Assert-NoProjectConflict([string]$Dir, [string]$Project) {
    # 千萬別用 --format '{{.Label "…"}}':PowerShell 5.1 傳給原生程式時會把內層引號
    # 吃掉,docker 收到殘缺的 template 直接報錯,於是這道檢查會「靜默失效」——
    # 看起來一切正常,實際上完全沒在擋。踩過一次,改用不含引號的 compose ls。
    $r = Invoke-Native docker @('compose', 'ls', '--all', '--format', 'json')
    if (-not $r.Ok -or -not $r.Output) {
        Write-Attn '無法列出既有的 docker compose 專案,略過重複安裝檢查。'
        return
    }
    # 這裡的寫法有講究:PS 5.1 的 ConvertFrom-Json 會把整個 JSON 陣列當成「一個」
    # 管線項目送出,所以 @($x | ConvertFrom-Json) 得到的是 1 個元素(內含全部專案),
    # 後續逐一比對永遠不相等——這道檢查就靜默失效了。必須先指派再 @() 展開。
    try {
        $parsed = $r.Output | ConvertFrom-Json
        $projects = @($parsed)
    }
    catch {
        Write-Attn '無法解析 docker compose 專案清單,略過重複安裝檢查。'
        return
    }

    $mine = Join-Path $Dir 'docker-compose.yml'
    $others = @()
    foreach ($p in $projects) {
        if ($p.Name -ne $Project) { continue }
        if ($p.PSObject.Properties.Name -notcontains 'ConfigFiles') { continue }
        foreach ($cfg in ([string]$p.ConfigFiles -split ',')) {
            $c = $cfg.Trim()
            # PowerShell 的 -ne 對字串預設不分大小寫,正好符合 Windows 路徑語意
            if ($c -and ($c -ne $mine)) { $others += $c }
        }
    }
    $others = @($others | Select-Object -Unique)
    if ($others.Count -eq 0) { return }

    Write-Host ''
    Write-Attn "這台主機上已經有一套名為「$Project」的部署,但它在別的資料夾:"
    foreach ($o in $others) { Write-Note "  $o" }
    Write-Host ''
    Write-Attn '繼續下去會「接管」那一套,而不是另外裝一套新的——'
    Write-Attn '它的容器會被依這裡的設定重建,資料庫 volume 也是同一份。'
    Write-Host ''
    Write-Note '若你要的是「再裝一套獨立的測試環境」,請改用不同的專案名稱重跑,例如:'
    Write-Note '  .\install.ps1 -ProjectName scheduling-test -InstallPath D:\scheduling-test'
    Write-Host ''

    if ($Yes) {
        Stop-WithHelp '為避免誤覆蓋既有部署,-Yes 模式下不接管別的目錄。' @(
            '請加上 -ProjectName 指定新名稱,或移除 -Yes 以互動方式確認。'
        )
    }
    $a = Read-Host '  確定要接管既有的那一套嗎?(輸入 yes 繼續,其他任意鍵取消)'
    if ($a -ne 'yes') { Write-Host ''; Write-Host '  已取消。' -ForegroundColor Yellow; exit 0 }
}

function Save-RemoteFile {
    param([string]$Url, [string]$Dest)
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    }
    catch {
        Stop-WithHelp "下載失敗:$Url" @(
            "錯誤:$($_.Exception.Message)"
            ''
            '請確認這台主機能連上網際網路(GitHub)。若學校網路有防火牆或 Proxy,'
            '可改成手動下載下列兩個檔案,放進安裝目錄後,加上 -SkipStart 重跑本腳本:'
            "  $RawBase/docker-compose.yml"
            "  $RawBase/.env.example"
        )
    }
}

# ── 2. 產生 .env ─────────────────────────────────────────────
function New-SecretKey {
    # 用 .NET 的密碼學亂數。Windows 沒有內建 openssl,原文件的 openssl rand 在此無法執行
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Read-AdminPassword {
    while ($true) {
        $s1 = Read-Host '  管理員密碼(輸入時不會顯示)' -AsSecureString
        $p1 = ConvertFrom-SecureStringPlain $s1
        if ($p1.Length -lt 8) { Write-Attn '至少 8 個字元,請重新輸入。'; continue }
        if ($p1 -match '["\\]') { Write-Attn '請避免使用 " 與 \ 這兩個字元。'; continue }
        $s2 = Read-Host '  再輸入一次確認' -AsSecureString
        if ($p1 -ne (ConvertFrom-SecureStringPlain $s2)) { Write-Attn '兩次輸入不一致,請重來。'; continue }
        return $p1
    }
}

function ConvertFrom-SecureStringPlain([System.Security.SecureString]$s) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Test-PortFree([int]$p) {
    try {
        $used = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        return ($null -eq $used)
    }
    catch { return $true }   # 舊系統沒有這個 cmdlet,就別擋使用者
}

function Resolve-Port {
    if ($Port) {
        if (-not (Test-PortFree $Port)) { Write-Attn "埠號 $Port 目前已被占用,啟動可能失敗。" }
        return $Port
    }
    $candidate = 80
    if (-not (Test-PortFree 80)) {
        Write-Attn '埠號 80 已被其他程式占用(常見於 IIS、Skype 或另一套 Web 服務)。'
        $candidate = 8080
        while (-not (Test-PortFree $candidate) -and $candidate -lt 8100) { $candidate++ }
        Write-Note "改用 $candidate。往後連線網址要多帶埠號,例如 http://主機IP:$candidate"
    }
    while ($true) {
        $answer = Read-Default '對外連接埠' $candidate
        $parsed = 0
        if ([int]::TryParse($answer, [ref]$parsed) -and $parsed -ge 1 -and $parsed -le 65535) {
            return $parsed
        }
        Write-Attn '請輸入 1–65535 之間的數字。'
    }
}

function Resolve-HttpsPort {
    # compose 是「無條件」發布 443 的,即使你根本沒啟用 HTTPS。
    # 443 被別的服務占著時,web 容器會起不來,而 Docker 吐的錯誤訊息只說
    # 「Bind for 0.0.0.0:443 failed」——使用者完全看不出跟自己設的 80 有什麼關係。
    # 這裡先幫他閃開,不必為了一個沒在用的埠卡住整個安裝。
    if (Test-PortFree 443) { return 443 }
    $c = 8443
    while (-not (Test-PortFree $c) -and $c -lt 8500) { $c++ }
    Write-Attn "埠號 443 已被占用,HTTPS 埠改用 $c(目前走 HTTP,不影響使用)。"
    return $c
}

function Write-EnvFile {
    param([string]$Dir, [hashtable]$Values)

    # 以 .env.example 為底逐行取代,而不是自己拼一份:
    # 日後 .env.example 新增設定項時,這裡會自動跟上,不會漏。
    $example = Join-Path $Dir '.env.example'
    $lines = [System.IO.File]::ReadAllLines($example, [System.Text.Encoding]::UTF8)
    $handled = @{}

    $out = foreach ($line in $lines) {
        $m = [regex]::Match($line, '^([A-Z_][A-Z0-9_]*)=')
        if ($m.Success -and $Values.ContainsKey($m.Groups[1].Value)) {
            $key = $m.Groups[1].Value
            $handled[$key] = $true
            $val = [string]$Values[$key]
            # docker compose 會對 .env 的值做變數展開,值裡的 $ 必須寫成 $$。
            # 不escape 的話,密碼 my$ecret123 會被解讀成 my + ${ecret123} 而變成 my——
            # 實測確認過,而且從頭到尾沒有任何錯誤訊息,使用者只會發現自己登不進去。
            $val = $val.Replace('$', '$$')
            # 含中文或空白的值加引號(校名、密碼);純數字/十六進位不加,避免被當字串
            if ($val -match '^[A-Za-z0-9_.:\/-]+$') { "$key=$val" } else { "$key=`"$val`"" }
        }
        else { $line }
    }

    # .env.example 裡是註解掉的項目(如 HTTPS_PORT)不會被上面比對到,補在檔尾
    $extra = foreach ($key in ($Values.Keys | Where-Object { -not $handled.ContainsKey($_) } | Sort-Object)) {
        $val = ([string]$Values[$key]).Replace('$', '$$')
        if ($val -match '^[A-Za-z0-9_.:\/-]+$') { "$key=$val" } else { "$key=`"$val`"" }
    }
    if ($extra) {
        $out = @($out) + @('', '# ── 由安裝程式加入 ──────────────────') + @($extra)
    }

    # 關鍵:UTF-8 但「不加 BOM」。加了 BOM,docker compose 讀 .env 時
    # 第一個變數名會變成「\ufeffADMIN_USERNAME」而讀不到。記事本另存很容易踩到。
    $dest = Join-Path $Dir '.env'
    [System.IO.File]::WriteAllText($dest, (($out -join "`n") + "`n"),
        (New-Object System.Text.UTF8Encoding $false))
}

# ── 3. 啟動 ──────────────────────────────────────────────────
function Start-Stack([string]$Dir, [int]$p) {
    Write-Head '[4/5] 下載映像並啟動(首次約需數分鐘)'
    Push-Location $Dir
    # docker 把下載進度寫在 stderr。使用者若把整個腳本的輸出導向檔案存記錄
    # (.\install.ps1 > log.txt 2>&1),PS 5.1 會把那些進度行當成致命錯誤而中斷安裝。
    # 這裡改用退出碼判斷成敗,不讓 stderr 決定生死。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Write-Step '下載官方映像…'
        & docker compose pull
        if ($LASTEXITCODE -ne 0) {
            Stop-WithHelp '映像下載失敗。' @(
                '常見原因:網路不通、或學校防火牆擋住 ghcr.io。'
                '可改用「從原始碼建置」的方式,見安裝指南。'
            )
        }

        Write-Step '啟動六個容器…'
        & docker compose up -d --wait --wait-timeout 300
        if ($LASTEXITCODE -ne 0) {
            & docker compose ps
            Stop-WithHelp '容器啟動未成功。' @(
                "請在 $Dir 執行下列指令查看原因:"
                '  docker compose logs --tail 50'
                ''
                '若錯誤訊息提到 "port is already allocated",是埠號被占用:'
                '改 .env 的 HTTP_PORT(網頁埠)或 HTTPS_PORT(即使沒用 HTTPS 也會被占用),'
                '然後重跑 docker compose up -d'
            )
        }
    }
    finally {
        $ErrorActionPreference = $prevEap
        Pop-Location
    }

    Write-Step '確認系統回應…'
    $ok = $false
    foreach ($attempt in 1..30) {
        try {
            $r = Invoke-WebRequest "http://localhost:$p/api/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        }
        catch { }
        Start-Sleep -Seconds 2
    }
    if ($ok) { Write-Ok '系統已就緒' }
    else { Write-Attn '容器起來了,但健康檢查沒過。稍等一分鐘再開網頁看看。' }
    return $ok
}

function Get-LanAddress {
    try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*' -and
                # 排除 Docker / WSL / Hyper-V 的虛擬網卡,那些位址校內其他電腦連不到
                $_.InterfaceAlias -notlike '*Loopback*' -and
                $_.InterfaceAlias -notlike 'vEthernet*' -and
                $_.InterfaceAlias -notlike '*WSL*' -and
                $_.InterfaceAlias -notlike '*Docker*'
            } |
            Sort-Object -Property InterfaceMetric |
            Select-Object -First 1
        if ($ip) { return $ip.IPAddress }
    }
    catch { }
    return $null
}

# ══ 主流程 ═══════════════════════════════════════════════════
Write-Host ''
Write-Host '  排課與調代課系統 · 安裝程式' -ForegroundColor Cyan
Write-Host '  ─────────────────────────────' -ForegroundColor DarkGray
Write-Host '  資料全部留在這台主機,不會上傳到任何地方。' -ForegroundColor DarkGray

Test-DockerReady
$dir = Get-InstallDir
$project = Resolve-ProjectName $dir
Assert-NoProjectConflict -Dir $dir -Project $project

Write-Head '[3/5] 取得設定檔'
Save-RemoteFile "$RawBase/docker-compose.yml" (Join-Path $dir 'docker-compose.yml')
Save-RemoteFile "$RawBase/.env.example"       (Join-Path $dir '.env.example')
Write-Ok '已下載 docker-compose.yml 與 .env.example'

$envPath = Join-Path $dir '.env'
$needConfig = $true
if ((Test-Path $envPath) -and -not $Reconfigure) {
    Write-Attn '偵測到既有的 .env,保留原設定(校名、密碼、金鑰都不動)。'
    Write-Note '要重新設定請加參數 -Reconfigure 重跑。'
    $needConfig = $false
}

if ($needConfig) {
    Write-Host ''
    Write-Host '  請回答三個問題(直接按 Enter 即採用預設值):' -ForegroundColor Cyan
    Write-Host ''

    $school = if ($SchoolName) { $SchoolName } else { Read-Default '學校名稱(顯示在介面與課表上)' '示範學校' }

    if ($AdminPassword) {
        # 走參數的路徑同樣要擋:互動輸入那邊擋了,這邊不擋就成了漏洞
        if ($AdminPassword.Length -lt 8) { Stop-WithHelp '-AdminPassword 至少需 8 個字元。' @() }
        if ($AdminPassword -match '["\\]') { Stop-WithHelp '-AdminPassword 不可含 " 或 \ 字元。' @() }
        $pw = $AdminPassword
    }
    elseif ($Yes) { Stop-WithHelp '-Yes 需要同時提供 -AdminPassword。' @() }
    else {
        Write-Note '管理員帳號固定為 admin,首次登入後系統會要求你再改一次密碼。'
        $pw = Read-AdminPassword
    }

    $chosenPort = Resolve-Port

    $values = @{
        ADMIN_USERNAME = 'admin'
        ADMIN_PASSWORD = $pw
        SCHOOL_NAME    = $school
        TZ             = $TimeZone
        SECRET_KEY     = (New-SecretKey)
        HTTP_PORT      = $chosenPort
        HTTPS_PORT     = (Resolve-HttpsPort)
        IMAGE_TAG      = $ImageTag
    }
    # 只在非預設時寫入:留白的話就沿用 docker-compose.yml 裡的 name: scheduling
    if ($project -ne 'scheduling') { $values['COMPOSE_PROJECT_NAME'] = $project }

    Write-EnvFile -Dir $dir -Values $values
    Write-Ok "已寫入 $envPath(含自動產生的 SECRET_KEY)"
    if ($project -ne 'scheduling') { Write-Note "此部署的專案名稱為 $project(記在 .env,後續指令會自動沿用)" }
    Write-Note '這個檔案含有密碼,請勿上傳到雲端硬碟或 GitHub。'
}

# 讀回實際生效的埠號(保留既有 .env 的情況下,埠號以檔案裡的為準)
$activePort = 80
foreach ($l in [System.IO.File]::ReadAllLines($envPath)) {
    if ($l -match '^HTTP_PORT="?(\d+)"?') { $activePort = [int]$Matches[1] }
}

if ($SkipStart) {
    Write-Head '已產生設定檔,依 -SkipStart 未啟動'
    Write-Note "檢查無誤後,在 $dir 執行:docker compose up -d"
    Write-Host ''
    exit 0
}

$healthy = Start-Stack -Dir $dir -p $activePort

# ── 4. 完成 ──────────────────────────────────────────────────
$suffix = if ($activePort -eq 80) { '' } else { ":$activePort" }
$lan = Get-LanAddress

Write-Head '[5/5] 安裝完成'
Write-Host ''
Write-Host '  在這台主機上開:' -ForegroundColor White
Write-Host "    http://localhost$suffix" -ForegroundColor Green
if ($lan) {
    Write-Host '  校內其他電腦開:' -ForegroundColor White
    Write-Host "    http://$lan$suffix" -ForegroundColor Green
    Write-Note '(若連不到,多半是這台主機的 Windows 防火牆擋住,需放行該埠號)'
}
Write-Host ''
Write-Host '  帳號 admin,密碼是你剛才設定的那組;登入後會要求改一次密碼,' -ForegroundColor White
Write-Host '  接著進入「設定精靈」,照畫面五個步驟建立學期、教師、班級、科目。' -ForegroundColor White
Write-Host ''
Write-Note "安裝目錄:$dir"
Write-Note "停止:docker compose down    重新啟動:docker compose up -d(需先 cd 到上面的目錄)"
Write-Note "操作手冊與部署文件:$RepoUrl"
Write-Host ''

if ($healthy -and -not $Yes) { Start-Process "http://localhost$suffix" }
