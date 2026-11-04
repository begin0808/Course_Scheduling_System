import { expect, test } from '@playwright/test'
import { loginAsAdmin } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片 07:備份與升級。請用 scripts/video/build_video.py backup-upgrade 執行。
// 任何已登入過的示範站都可以(會真的按一次「立即備份」)。升級的終端機畫面是示意,
// 輸出格式取自實際的 docker compose。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }

test.use({ baseURL: BASE })

const UPGRADE = [
  '# 1) 先在系統裡按「立即備份」',
  '# 2) 下載新版的 docker-compose.yml(容器組成可能有變動)',
  '$ curl -fsSLO https://raw.githubusercontent.com/begin0808/Course_Scheduling_System/main/docker-compose.yml',
  '# 3) 編輯 .env,把 IMAGE_TAG 改成新版本',
  '$ grep IMAGE_TAG .env',
  'IMAGE_TAG=v1.4.8',
  '# 4) 拉新映像並重啟',
  '$ docker compose pull',
  ' ✔ Image ghcr.io/begin0808/course_scheduling_system-api:v1.4.8     Pulled',
  ' ✔ Image ghcr.io/begin0808/course_scheduling_system-worker:v1.4.8  Pulled',
  ' ✔ Image ghcr.io/begin0808/course_scheduling_system-web:v1.4.8     Pulled',
  '$ docker compose up -d',
  ' ✔ Container scheduling-api-1         Healthy',
  ' ✔ Container scheduling-worker-1      Started',
  ' ✔ Container scheduling-worker-ops-1  Started',
  ' ✔ Container scheduling-web-1         Healthy',
]

test('錄影:備份與升級', async ({ browser }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('backup-upgrade')
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)
  await loginAsAdmin(page)

  await d.sync()
  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  const card = page.getByTestId('backup-card')
  await d.seg('open', async () => {
    await page.waitForTimeout(500)
    await d.click(page.locator('.n-menu-item-content-header', { hasText: /^系統管理$/ }).first())
    await page.waitForLoadState('networkidle')
    await card.evaluate((e) => e.scrollIntoView({ block: 'start', behavior: 'smooth' }))
    await page.waitForTimeout(800)
    await d.point(card.locator('.n-text').first(), 1500)
  })
  await d.seg('backup-now', async () => {
    const before = await card.getByTestId('backup-row').count()
    await d.click(card.getByTestId('backup-now'))
    await expect(card.getByTestId('backup-row')).toHaveCount(before + 1, { timeout: 60_000 })
    await d.point(card.getByTestId('backup-row').first(), 1000)
  })
  await d.seg('download', async () => {
    await d.point(card.getByTestId('backup-row').first().getByRole('button', { name: '下載' }), 1800)
  })
  await d.seg('restore', async () => {
    await d.point(card.getByTestId('backup-restore').first(), 1500)
    await d.point(card.getByTestId('backup-upload'), 1500)
  })
  await d.seg('version', async () => {
    const version = page.getByTestId('version-card')
    await version.evaluate((e) => e.scrollIntoView({ block: 'start', behavior: 'smooth' }))
    await page.waitForTimeout(800)
    await d.point(page.getByTestId('version-current'), 1500)
    const latest = page.getByTestId('version-latest')
    if (await latest.count()) await d.point(latest, 1500)
  })
  await d.seg('upgrade', async () => {
    await d.terminal('主機的終端機(示意)', UPGRADE)
    await page.waitForTimeout(1500)
  })
  await d.seg('after', async () => {
    await d.hideSheet()
    await d.point(page.getByText(/^版本 v/).first(), 2500)
  })
  await d.seg('outro', async () => {
    await d.card('備份與升級', '安裝系統請看:01 安裝')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
