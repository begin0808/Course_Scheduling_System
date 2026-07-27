#!/usr/bin/env bash
# 排課與調代課系統 — Linux / macOS / NAS 一鍵安裝
#
# 把「建資料夾 → 下載設定檔 → 編輯 .env → 啟動 → 找出連線網址」壓成一次執行。
# 過程只問三件事:校名、管理員密碼、對外埠號;SECRET_KEY 自動產生。
#
# 刻意設計成「下載後執行」而非 curl | sh:這是要進學校主機的東西,
# 使用者應該能先打開看過內容再跑。
#
#   curl -fLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.sh
#   less install.sh          # 先看過
#   bash install.sh
#
# 用法:bash install.sh [選項]
#   --path <目錄>        安裝位置(預設 ~/scheduling)
#   --school-name <名稱> 校名
#   --admin-password <密碼>
#   --port <埠號>        對外埠號(預設 80,被占用時自動改建議值)
#   --project-name <名稱> compose 專案名稱(預設 scheduling)。同名 = 同一套部署,
#                        要在同一台主機再裝一套(如測試環境)必須指定不同名稱
#   --timezone <時區>    預設 Asia/Taipei
#   --ref <分支或標籤>   要拉哪一版設定檔(預設 main)
#   --image-tag <標籤>   映像版本(預設 latest)
#   --skip-start         只產生設定檔,不啟動
#   --reconfigure        已安裝過時,重新設定 .env
#   --yes                不詢問,全用預設值/參數值

set -euo pipefail

REPO_URL="https://github.com/begin0808/Course_Scheduling_System"
REF="main"
INSTALL_PATH="${HOME}/scheduling"
SCHOOL_NAME=""
ADMIN_PASSWORD=""
PORT=""
PROJECT_NAME=""
TIMEZONE="Asia/Taipei"
IMAGE_TAG="latest"
SKIP_START=0
RECONFIGURE=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --path)           INSTALL_PATH="$2"; shift 2 ;;
    --school-name)    SCHOOL_NAME="$2"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="$2"; shift 2 ;;
    --port)           PORT="$2"; shift 2 ;;
    --project-name)   PROJECT_NAME="$2"; shift 2 ;;
    --timezone)       TIMEZONE="$2"; shift 2 ;;
    --ref)            REF="$2"; shift 2 ;;
    --image-tag)      IMAGE_TAG="$2"; shift 2 ;;
    --skip-start)     SKIP_START=1; shift ;;
    --reconfigure)    RECONFIGURE=1; shift ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    -h|--help)        sed -n '2,29p' "$0"; exit 0 ;;
    *) echo "未知的選項:$1(用 --help 看說明)" >&2; exit 1 ;;
  esac
done

RAW_BASE="https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/${REF}"

# ── 輸出小工具 ────────────────────────────────────────────────
if [ -t 1 ]; then
  C_HEAD=$'\033[36m'; C_OK=$'\033[32m'; C_WARN=$'\033[33m'
  C_ERR=$'\033[31m';  C_DIM=$'\033[90m'; C_OFF=$'\033[0m'
else
  C_HEAD=""; C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
head_()  { printf '\n  %s%s%s\n' "$C_HEAD" "$1" "$C_OFF"; }
step_()  { printf '  → %s\n' "$1"; }
ok_()    { printf '  %s✓ %s%s\n' "$C_OK" "$1" "$C_OFF"; }
note_()  { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }
attn_()  { printf '  %s! %s%s\n' "$C_WARN" "$1" "$C_OFF"; }
die_() {
  printf '\n  %s✗ %s%s\n' "$C_ERR" "$1" "$C_OFF"; shift
  for line in "$@"; do printf '    %s%s%s\n' "$C_WARN" "$line" "$C_OFF"; done
  printf '\n'; exit 1
}

# ── 1. Docker 檢查 ───────────────────────────────────────────
head_ '[1/5] 檢查 Docker'

if ! command -v docker >/dev/null 2>&1; then
  die_ '找不到 Docker。' \
    '本系統以 Docker 執行。在 Ubuntu / Debian 可用官方腳本安裝:' \
    '' \
    '  curl -fsSL https://get.docker.com | sudo sh' \
    '  sudo usermod -aG docker $USER' \
    '' \
    '接著「登出再登入」讓群組生效,然後重新執行本腳本。' \
    'NAS(Synology / QNAP)請先在套件中心安裝 Container Manager / Container Station。'
fi

if ! docker info >/dev/null 2>&1; then
  # 權限不足與引擎沒開是兩件事,錯誤訊息長得很像,但解法完全不同
  if docker info 2>&1 | grep -qi 'permission denied'; then
    die_ '目前的使用者沒有權限操作 Docker。' \
      '把自己加進 docker 群組,然後「登出再登入」(只重開終端機不夠):' \
      '' \
      '  sudo usermod -aG docker $USER' \
      '' \
      '或者這次先用 sudo 執行:sudo bash install.sh'
  fi
  die_ 'Docker 已安裝,但引擎沒有在執行。' \
    '請先啟動 Docker:' \
    '' \
    '  sudo systemctl start docker' \
    '' \
    'macOS 請開啟 Docker Desktop,等選單列的鯨魚圖示不再轉動。'
fi
ok_ "Docker 引擎執行中(版本 $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '未知'))"

if ! docker compose version >/dev/null 2>&1; then
  die_ '這個 Docker 沒有 Compose 外掛。' \
    '請升級 Docker(近期版本內建 Compose v2),或安裝 docker-compose-plugin。' \
    '注意:舊的 docker-compose(有連字號)不適用,本專案需要 docker compose v2。'
fi
ok_ 'Docker Compose 可用'

# ── 2. 目錄與設定檔 ──────────────────────────────────────────
head_ '[2/5] 準備安裝目錄'
mkdir -p "$INSTALL_PATH"
INSTALL_PATH="$(cd "$INSTALL_PATH" && pwd)"
ok_ "使用目錄 $INSTALL_PATH"

# compose 的專案名稱決定「哪些容器與 volume 屬於同一套」。預設寫死在
# docker-compose.yml 的 name: scheduling,可由 .env 的 COMPOSE_PROJECT_NAME 蓋過。
resolve_project_() {
  if [ -n "$PROJECT_NAME" ]; then
    case "$PROJECT_NAME" in
      [a-z0-9]*) ;;
      *) die_ "專案名稱「${PROJECT_NAME}」不合法。" \
           'Docker 要求:只能用小寫英數字、底線與連字號,且開頭須為英數字。' \
           '例如:scheduling-test' ;;
    esac
    if printf '%s' "$PROJECT_NAME" | grep -q '[^a-z0-9_-]'; then
      die_ "專案名稱「${PROJECT_NAME}」不合法。" \
        'Docker 要求:只能用小寫英數字、底線與連字號,且開頭須為英數字。'
    fi
    printf '%s' "$PROJECT_NAME"; return
  fi
  if [ -f "${INSTALL_PATH}/.env" ]; then
    local found
    found="$(sed -n 's/^COMPOSE_PROJECT_NAME="\?\([^"[:space:]]\+\)"\?.*/\1/p' \
             "${INSTALL_PATH}/.env" | tail -1)"
    if [ -n "$found" ]; then printf '%s' "$found"; return; fi
  fi
  printf 'scheduling'   # 與 docker-compose.yml 的 name: 一致
}

# 同名專案若指向別的目錄,docker compose up 會直接接管那一套——包含它的資料庫 volume。
# 這是本腳本唯一可能毀掉既有資料的路徑,所以擋在啟動之前。
assert_no_conflict_() {
  local project="$1" mine others answer
  mine="${INSTALL_PATH}/docker-compose.yml"
  others="$(docker ps -a --filter "label=com.docker.compose.project=${project}" \
            --format '{{.Label "com.docker.compose.project.config_files"}}' 2>/dev/null \
            | grep -v '^$' | sort -u | grep -vxF "$mine" || true)"
  [ -n "$others" ] || return 0

  printf '\n'
  attn_ "這台主機上已經有一套名為「${project}」的部署,但它在別的資料夾:"
  printf '%s\n' "$others" | while IFS= read -r o; do note_ "  $o"; done
  printf '\n'
  attn_ '繼續下去會「接管」那一套,而不是另外裝一套新的——'
  attn_ '它的容器會被依這裡的設定重建,資料庫 volume 也是同一份。'
  printf '\n'
  note_ '若你要的是「再裝一套獨立的測試環境」,請改用不同的專案名稱重跑,例如:'
  note_ '  bash install.sh --project-name scheduling-test --path ~/scheduling-test'
  printf '\n'

  if [ "$ASSUME_YES" = "1" ]; then
    die_ '為避免誤覆蓋既有部署,--yes 模式下不接管別的目錄。' \
      '請加上 --project-name 指定新名稱,或移除 --yes 以互動方式確認。'
  fi
  read -r -p '  確定要接管既有的那一套嗎?(輸入 yes 繼續,其他任意鍵取消) ' answer </dev/tty || answer=""
  if [ "$answer" != "yes" ]; then printf '\n  已取消。\n\n'; exit 0; fi
}

fetch_() {
  # NAS 上常常只有 wget 沒有 curl,兩個都試
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest" && return 0
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$url" && return 0
  else
    die_ '系統上既沒有 curl 也沒有 wget,無法下載設定檔。' \
      '請先安裝其一(例:sudo apt install curl)。'
  fi
  die_ "下載失敗:$url" \
    '請確認這台主機能連上網際網路(GitHub)。若學校網路有防火牆或 Proxy,' \
    '可手動下載下列兩個檔案放進安裝目錄,再加 --skip-start 重跑:' \
    "  ${RAW_BASE}/docker-compose.yml" \
    "  ${RAW_BASE}/.env.example"
}

PROJECT="$(resolve_project_)"
assert_no_conflict_ "$PROJECT"

head_ '[3/5] 取得設定檔'
fetch_ "${RAW_BASE}/docker-compose.yml" "${INSTALL_PATH}/docker-compose.yml"
fetch_ "${RAW_BASE}/.env.example"       "${INSTALL_PATH}/.env.example"
ok_ '已下載 docker-compose.yml 與 .env.example'

# ── 3. 產生 .env ─────────────────────────────────────────────
gen_secret_() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif [ -r /dev/urandom ] && command -v od >/dev/null 2>&1; then
    od -An -tx1 -N32 /dev/urandom | tr -d ' \n'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  else
    die_ '找不到可用的亂數來源,無法產生 SECRET_KEY。' \
      '請安裝 openssl 後重試。'
  fi
}

port_free_() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ! ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN
  elif command -v netstat >/dev/null 2>&1; then
    ! netstat -ltn 2>/dev/null | grep -qE "[:.]$p[[:space:]]"
  else
    return 0   # 查不到就別擋使用者
  fi
}

ask_() {
  # $1=提示 $2=預設值
  local answer
  if [ "$ASSUME_YES" = "1" ]; then printf '%s' "$2"; return; fi
  read -r -p "  $1 [$2] " answer </dev/tty || answer=""
  if [ -z "$answer" ]; then printf '%s' "$2"; else printf '%s' "$answer"; fi
}

ask_password_() {
  local p1 p2
  while true; do
    read -r -s -p '  管理員密碼(輸入時不會顯示): ' p1 </dev/tty; printf '\n'
    if [ "${#p1}" -lt 8 ]; then attn_ '至少 8 個字元,請重新輸入。'; continue; fi
    case "$p1" in *'"'*|*'\'*) attn_ '請避免使用 " 與 \ 這兩個字元。'; continue ;; esac
    read -r -s -p '  再輸入一次確認: ' p2 </dev/tty; printf '\n'
    if [ "$p1" != "$p2" ]; then attn_ '兩次輸入不一致,請重來。'; continue; fi
    printf '%s' "$p1"; return
  done
}

write_env_() {
  # 以 .env.example 為底逐行取代,而不是自己拼一份:
  # 日後 .env.example 新增設定項時,這裡會自動跟上,不會漏。
  local example="${INSTALL_PATH}/.env.example" dest="${INSTALL_PATH}/.env"
  ENV_ADMIN_USERNAME="admin" \
  ENV_ADMIN_PASSWORD="$1" \
  ENV_SCHOOL_NAME="$2" \
  ENV_TZ="$3" \
  ENV_SECRET_KEY="$4" \
  ENV_HTTP_PORT="$5" \
  ENV_IMAGE_TAG="$6" \
  ENV_HTTPS_PORT="$7" \
  ENV_COMPOSE_PROJECT_NAME="$8" \
  awk '
    function emit(k, v) {
      # docker compose 會對 .env 的值做變數展開,值裡的 $ 必須寫成 $$。
      # 不 escape 的話,密碼 my$ecret123 會被解讀成 my + ${ecret123} 而變成 my,
      # 而且全程沒有任何錯誤訊息,使用者只會發現自己登不進去。
      gsub(/\$/, "$$", v)
      # 含中文或空白的值加引號;純數字/十六進位不加,避免被當字串
      if (v ~ /^[A-Za-z0-9_.:\/-]+$/) print k "=" v; else print k "=\"" v "\""
    }
    BEGIN {
      n = split("ADMIN_USERNAME ADMIN_PASSWORD SCHOOL_NAME TZ SECRET_KEY " \
                "HTTP_PORT HTTPS_PORT IMAGE_TAG COMPOSE_PROJECT_NAME", wanted, " ")
    }
    /^[A-Z_][A-Z0-9_]*=/ {
      key = substr($0, 1, index($0, "=") - 1)
      val = ENVIRON["ENV_" key]
      if (val != "") { emit(key, val); handled[key] = 1; next }
    }
    { print }
    END {
      # .env.example 裡是註解掉的項目(如 HTTPS_PORT)不會被上面比對到,補在檔尾
      first = 1
      for (i = 1; i <= n; i++) {
        k = wanted[i]
        v = ENVIRON["ENV_" k]
        if (v != "" && !(k in handled)) {
          if (first) { print ""; print "# ── 由安裝程式加入 ──────────────────"; first = 0 }
          emit(k, v)
        }
      }
    }
  ' "$example" > "$dest"
  chmod 600 "$dest"   # 裡面有密碼,不讓同機其他使用者讀
}

NEED_CONFIG=1
if [ -f "${INSTALL_PATH}/.env" ] && [ "$RECONFIGURE" = "0" ]; then
  attn_ '偵測到既有的 .env,保留原設定(校名、密碼、金鑰都不動)。'
  note_ '要重新設定請加 --reconfigure 重跑。'
  NEED_CONFIG=0
fi

if [ "$NEED_CONFIG" = "1" ]; then
  printf '\n  %s請回答三個問題(直接按 Enter 即採用預設值):%s\n\n' "$C_HEAD" "$C_OFF"

  [ -n "$SCHOOL_NAME" ] || SCHOOL_NAME="$(ask_ '學校名稱(顯示在介面與課表上)' '示範學校')"

  if [ -z "$ADMIN_PASSWORD" ]; then
    if [ "$ASSUME_YES" = "1" ]; then die_ '--yes 需要同時提供 --admin-password。'; fi
    note_ '管理員帳號固定為 admin,首次登入後系統會要求你再改一次密碼。'
    ADMIN_PASSWORD="$(ask_password_)"
  else
    # 走參數的路徑同樣要擋:互動輸入那邊擋了,這邊不擋就成了漏洞
    [ "${#ADMIN_PASSWORD}" -ge 8 ] || die_ '--admin-password 至少需 8 個字元。'
    case "$ADMIN_PASSWORD" in *'"'*|*'\'*) die_ '--admin-password 不可含 " 或 \ 字元。' ;; esac
  fi

  if [ -z "$PORT" ]; then
    CANDIDATE=80
    if ! port_free_ 80; then
      attn_ '埠號 80 已被其他程式占用(常見於 Apache、Nginx 或另一套 Web 服務)。'
      CANDIDATE=8080
      while ! port_free_ "$CANDIDATE" && [ "$CANDIDATE" -lt 8100 ]; do
        CANDIDATE=$((CANDIDATE + 1))
      done
      note_ "改用 ${CANDIDATE}。往後連線網址要多帶埠號,例如 http://主機IP:${CANDIDATE}"
    fi
    while true; do
      PORT="$(ask_ '對外連接埠' "$CANDIDATE")"
      case "$PORT" in
        ''|*[!0-9]*) attn_ '請輸入數字。' ;;
        *) if [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ]; then break; fi
           attn_ '請輸入 1–65535 之間的數字。' ;;
      esac
    done
  fi

  # compose 是「無條件」發布 443 的,即使根本沒啟用 HTTPS。443 被別的服務占著時
  # web 容器會起不來,而 Docker 只說「Bind for 0.0.0.0:443 failed」,
  # 使用者完全看不出跟自己設的 80 有什麼關係。先幫他閃開。
  HTTPS_PORT=443
  if ! port_free_ 443; then
    HTTPS_PORT=8443
    while ! port_free_ "$HTTPS_PORT" && [ "$HTTPS_PORT" -lt 8500 ]; do
      HTTPS_PORT=$((HTTPS_PORT + 1))
    done
    attn_ "埠號 443 已被占用,HTTPS 埠改用 ${HTTPS_PORT}(目前走 HTTP,不影響使用)。"
  fi

  # 只在非預設時寫入:留白的話就沿用 docker-compose.yml 裡的 name: scheduling
  WRITE_PROJECT=""
  [ "$PROJECT" = "scheduling" ] || WRITE_PROJECT="$PROJECT"

  write_env_ "$ADMIN_PASSWORD" "$SCHOOL_NAME" "$TIMEZONE" "$(gen_secret_)" \
             "$PORT" "$IMAGE_TAG" "$HTTPS_PORT" "$WRITE_PROJECT"
  ok_ "已寫入 ${INSTALL_PATH}/.env(含自動產生的 SECRET_KEY,權限 600)"
  [ -z "$WRITE_PROJECT" ] || note_ "此部署的專案名稱為 ${PROJECT}(記在 .env,後續指令會自動沿用)"
  note_ '這個檔案含有密碼,請勿上傳到雲端硬碟或 GitHub。'
fi

# 讀回實際生效的埠號(保留既有 .env 時,以檔案裡的為準)
ACTIVE_PORT="$(sed -n 's/^HTTP_PORT="\?\([0-9]\+\)"\?.*/\1/p' "${INSTALL_PATH}/.env" | tail -1)"
[ -n "$ACTIVE_PORT" ] || ACTIVE_PORT=80

if [ "$SKIP_START" = "1" ]; then
  head_ '已產生設定檔,依 --skip-start 未啟動'
  note_ "檢查無誤後,在 ${INSTALL_PATH} 執行:docker compose up -d"
  printf '\n'; exit 0
fi

# ── 4. 啟動 ──────────────────────────────────────────────────
head_ '[4/5] 下載映像並啟動(首次約需數分鐘)'
cd "$INSTALL_PATH"

step_ '下載官方映像…'
if ! docker compose pull; then
  die_ '映像下載失敗。' \
    '常見原因:網路不通、或學校防火牆擋住 ghcr.io。' \
    '可改用「從原始碼建置」的方式,見安裝指南。'
fi

step_ '啟動六個容器…'
if ! docker compose up -d --wait --wait-timeout 300; then
  docker compose ps || true
  die_ '容器啟動未成功。' \
    "請在 ${INSTALL_PATH} 執行下列指令查看原因:" \
    '  docker compose logs --tail 50' \
    '' \
    '若錯誤訊息提到 "port is already allocated",是埠號被占用:' \
    '改 .env 的 HTTP_PORT(網頁埠)或 HTTPS_PORT(即使沒用 HTTPS 也會被占用),' \
    '然後重跑 docker compose up -d'
fi

step_ '確認系統回應…'
HEALTHY=0
TRIES=0
while [ "$TRIES" -lt 30 ]; do
  TRIES=$((TRIES + 1))
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "http://localhost:${ACTIVE_PORT}/api/health" >/dev/null 2>&1 && { HEALTHY=1; break; }
  else
    wget -qO- "http://localhost:${ACTIVE_PORT}/api/health" >/dev/null 2>&1 && { HEALTHY=1; break; }
  fi
  sleep 2
done
if [ "$HEALTHY" = "1" ]; then ok_ '系統已就緒'
else attn_ '容器起來了,但健康檢查沒過。稍等一分鐘再開網頁看看。'; fi

# ── 5. 完成 ──────────────────────────────────────────────────
lan_address_() {
  if command -v hostname >/dev/null 2>&1 && hostname -I >/dev/null 2>&1; then
    hostname -I | tr ' ' '\n' | grep -v '^$' | grep -v '^127\.' | grep -v '^172\.1[7-9]\.' | head -1
  elif command -v ipconfig >/dev/null 2>&1; then
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true
  elif command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]}' | head -1
  fi
}

SUFFIX=""
[ "$ACTIVE_PORT" = "80" ] || SUFFIX=":${ACTIVE_PORT}"
LAN="$(lan_address_ || true)"

head_ '[5/5] 安裝完成'
printf '\n  在這台主機上開:\n'
printf '    %shttp://localhost%s%s\n' "$C_OK" "$SUFFIX" "$C_OFF"
if [ -n "$LAN" ]; then
  printf '  校內其他電腦開:\n'
  printf '    %shttp://%s%s%s\n' "$C_OK" "$LAN" "$SUFFIX" "$C_OFF"
  note_ '(若連不到,多半是主機防火牆擋住,需放行該埠號)'
fi
printf '\n  帳號 admin,密碼是你剛才設定的那組;登入後會要求改一次密碼,\n'
printf '  接著進入「設定精靈」,照畫面五個步驟建立學期、教師、班級、科目。\n\n'
note_ "安裝目錄:${INSTALL_PATH}"
note_ '停止:docker compose down    重新啟動:docker compose up -d(需先 cd 到上面的目錄)'
note_ "操作手冊與部署文件:${REPO_URL}"
printf '\n'
