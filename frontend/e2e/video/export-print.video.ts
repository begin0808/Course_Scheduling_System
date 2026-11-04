import path from 'node:path'
import { expect, test } from '@playwright/test'
import { YEAR, TERM, get, loginAsAdmin } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片 06:課表匯出與列印。請用 scripts/video/build_video.py export-print 執行。
// 起點是錄完 04(leave-substitute)的示範站:有已發布課表,陳志明那天有兩節代課與代導。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }

test.use({ baseURL: BASE })

test('錄影:課表匯出與列印', async ({ browser }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('export-print')
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
    acceptDownloads: true,
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)
  await loginAsAdmin(page)

  // 要有代課的那一天(04 影片建的假)
  const sem = (await get(page, '/api/semesters'))
    .find((s: { academic_year: number; term: number }) => s.academic_year === YEAR && s.term === TERM)
  expect(sem, '示範站沒有學期:請先錄 02~04').toBeTruthy()
  const leaves = await get(page, `/api/leaves?semester_id=${sem.id}`)
  expect(leaves.length, '示範站沒有請假:請先錄 04(leave-substitute)').toBeGreaterThan(0)
  const day: string = leaves[0].start_date
  // 影片裡示範匯出 702 的 PNG。伺服器渲染要十幾秒,又會拖慢錄影的畫格,
  // 所以先在錄影前請伺服器產生好,錄影時按下 PNG 直接交出這一份(檔案內容與伺服器產生的相同)
  const classes = await get(page, `/api/class-units?semester_id=${sem.id}`)
  const c702 = classes.find((c: { name: string }) => c.name === '702')
  const pngUrl = `/api/export/timetable?semester_id=${sem.id}&view=class&target_id=${c702.id}&fmt=png`
  const t0 = Date.now()
  const png = await page.request.get(pngUrl, { timeout: 120_000 })
  expect(png.ok(), `PNG 產生失敗 ${png.status()}`).toBeTruthy()
  console.log(`PNG 預先產生 ${Date.now() - t0} ms`)
  const pngBody = await png.body()
  const pngHeaders = png.headers()
  await page.route(`**${pngUrl}`, (route) =>
    route.fulfill({ status: 200, headers: pngHeaders, body: pngBody }))

  const back = async () => {
    await page.goBack()
    await page.waitForLoadState('networkidle')
  }
  // 看板日期:從列印頁返回時會回到今天,所以每次都要重選
  const setDay = async (animate: boolean) => {
    const input = page.getByTestId('board-date').locator('input')
    if (animate) await d.click(input)
    else await input.click()
    await input.press('Control+A')
    await input.pressSequentially(day, { delay: animate ? 70 : 0 })
    await input.press('Enter')
    await expect(page.getByTestId('board-table')).toBeVisible({ timeout: 20_000 })
  }

  await d.sync()
  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  await d.seg('query', async () => {
    await page.waitForTimeout(500)
    await d.click(page.locator('.n-menu-item-content-header', { hasText: /^課表查詢$/ }).first())
    await page.waitForLoadState('networkidle')
    await expect(page.getByTestId('tq-grid')).toBeVisible({ timeout: 20_000 })
    await d.pick(page.getByTestId('tq-class'), '702')
    await page.waitForTimeout(800)
  })
  await d.seg('export-one', async () => {
    await d.point(page.getByTestId('export-xlsx'), 600)
    await d.point(page.getByTestId('export-pdf'), 600)
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      d.click(page.getByTestId('export-png')),
    ])
    const file = path.join(OUT, 'export.png')
    await download.saveAs(file)
    await page.waitForTimeout(600)
    await d.image(file, download.suggestedFilename())
    await page.waitForTimeout(3000) // 讓匯出的圖多停一下
  })
  await d.seg('export-all', async () => {
    await d.hideSheet()
    await d.point(page.getByTestId('export-school'), 1500)
    await d.point(page.getByTestId('export-batch'), 1500)
    await d.point(page.getByTestId('export-batch-pdf'), 800)
  })
  await d.seg('teacher-view', async () => {
    await d.click(page.getByTestId('tq-view-teacher'))
    await page.waitForTimeout(1200)
    await d.point(page.getByTestId('export-school'), 1000)
  })

  await d.seg('board', async () => {
    await d.menu('調代課', '今日調代課')
    await setDay(true)
    await page.waitForTimeout(500)
    await d.point(page.getByTestId('board-table'), 1500)
    await d.point(page.getByTestId('board-covers'), 1000)
  })
  await d.seg('board-print', async () => {
    await d.click(page.getByTestId('board-print'))
    await expect(page.getByTestId('print-btn')).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(3500)
  })
  await d.seg('patrol', async () => {
    await back()
    await setDay(false)
    await d.point(page.getByTestId('board-patrol-xlsx'), 1000)
    await d.click(page.getByTestId('board-patrol'))
    await expect(page.getByTestId('patrol-page').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1500)
    const note = page.getByTestId('patrol-note').filter({ hasText: /\S/ }).first()
    if (await note.count()) await d.point(note, 2000)
  })
  await d.seg('stats', async () => {
    await back()
    await d.menu('調代課', '代課鐘點統計')
    await expect(page.getByTestId('stats-summary')).toBeVisible({ timeout: 20_000 })
    await d.point(page.getByTestId('stats-month'), 1000)
    await d.point(page.getByTestId('stats-summary'), 1500)
    await d.point(page.getByTestId('stats-export'), 1000)
  })
  await d.seg('outro', async () => {
    await d.card('匯出與列印', '下一支影片:07 備份與升級')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
