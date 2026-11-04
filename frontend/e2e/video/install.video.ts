import { expect, test } from '@playwright/test'
import { Director, loadScript } from './director'

// 操作示範影片 01:安裝。請用 scripts/video/build_video.py install 執行。
// 安裝程式在主機的 PowerShell 裡跑,系統畫面錄不到,所以用終端機示意畫面呈現;
// 內容取自實際執行 install.ps1 的輸出(版本號、目錄、IP 換成一般學校會看到的樣子)。
// 最後一段開示範站的登入頁(任何示範站都可以,不會登入)。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }
const TITLE = 'Windows PowerShell(示意)'

test.use({ baseURL: BASE })

const DOWNLOAD = [
  'PS> Invoke-WebRequest https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/install.ps1 -OutFile install.ps1',
  'PS> .\\install.ps1',
]
const QUESTIONS = [
  '',
  '  排課與調代課系統 · 安裝程式',
  '  ─────────────────────────────',
  '  資料全部留在這台主機,不會上傳到任何地方。',
  '',
  '  [1/5] 檢查 Docker',
  '  ✓ Docker 引擎執行中',
  '  ✓ Docker Compose 可用',
  '  [2/5] 準備安裝目錄',
  '  ✓ 已建立 C:\\Users\\組長\\scheduling',
  '  [3/5] 取得設定檔',
  '  ✓ 已下載 docker-compose.yml 與 .env.example',
  '',
  '  請回答三個問題(直接按 Enter 即採用預設值):',
  '  學校名稱(顯示在介面與課表上) [示範學校]: ⏎ 示範國中',
  '    管理員帳號固定為 admin,首次登入後系統會要求你再改一次密碼。',
  '  管理員密碼(輸入時不會顯示): ⏎ ********',
  '  再輸入一次確認: ⏎ ********',
  '  對外連接埠 [80]: ⏎ ',
  '  ✓ 已寫入 C:\\Users\\組長\\scheduling\\.env(含自動產生的 SECRET_KEY)',
  '    這個檔案含有密碼,請勿上傳到雲端硬碟或 GitHub。',
]
const START = [
  '',
  '  [4/5] 下載映像並啟動(首次約需數分鐘)',
  '  → 下載官方映像…',
  '  → 啟動六個容器…',
  '  → 確認系統回應…',
  '  ✓ 系統已就緒',
]
const DONE = [
  '',
  '  [5/5] 安裝完成',
  '',
  '  在這台主機上開:',
  '    http://localhost',
  '  校內其他電腦開:',
  '    http://192.168.1.10',
  '    (若連不到,多半是這台主機的 Windows 防火牆擋住,需放行該埠號)',
  '',
  '  帳號 admin,密碼是你剛才設定的那組;登入後會要求改一次密碼,',
  '  接著進入「設定精靈」,照畫面五個步驟建立學期、教師、班級、科目。',
]

test('錄影:安裝', async ({ browser }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('install')
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)

  await d.sync()
  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await d.seg('prepare', async () => {
    await d.card('安裝前的準備', '一台主機(2 核、4GB 記憶體以上)+ Docker Desktop')
  })
  await d.seg('download', async () => {
    await d.terminal(TITLE, DOWNLOAD)
  })
  await d.seg('questions', async () => {
    await d.terminal(TITLE, QUESTIONS, { append: true })
  })
  await d.seg('start', async () => {
    await d.terminal(TITLE, START, { append: true })
  })
  await d.seg('done', async () => {
    await d.terminal(TITLE, DONE, { append: true })
  })
  await d.seg('browser', async () => {
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(800)
    await d.type(page.getByPlaceholder('請輸入帳號'), 'admin')
    await d.point(page.getByPlaceholder('請輸入密碼'), 1500)
  })
  await d.seg('outro', async () => {
    await d.card('安裝完成', '下一支影片:02 第一次設定')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
