import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso } from '../dates'
import { ensureDemoData, get, loginAsAdmin, pickLeaveDay, post, publishBySolver } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片 05:調課。請用 scripts/video/build_video.py swap 執行。
// 示範站要有已發布的課表(全新站也可以:會自己建示範學校並自動排課發布)。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }
const LEAVE_TEACHER = '王大明' // 請公假去研習,改採調課
const SWAP_TEACHER = '張文華'  // 沒請假,新增調課

test.describe.configure({ mode: 'serial' })
test.use({ baseURL: BASE })

let sid = 0
let swapDay = ''

/** 這位老師從 from 起算兩週內,第一個還有可處理節次的平日。 */
async function dayWithPeriods(page: Page, teacherId: number, from: Date, skip = ''): Promise<string> {
  for (let i = 0; i < 14; i++) {
    const d = new Date(from)
    d.setDate(from.getDate() + i)
    if (d.getDay() === 0 || d.getDay() === 6 || iso(d) === skip) continue
    const periods = await get(page,
      `/api/teachers/${teacherId}/day-periods?semester_id=${sid}&date=${iso(d)}`)
    if (periods.some((p: { is_past: boolean; taken_by: string }) => !p.is_past && !p.taken_by)) return iso(d)
  }
  throw new Error('兩週內找不到有課的日子')
}

test('準備示範資料(不錄影)', async ({ page }) => {
  test.setTimeout(300_000)
  await loginAsAdmin(page)
  sid = await ensureDemoData(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await publishBySolver(page, sid)
  const teachers = await get(page, `/api/teachers?semester_id=${sid}`)
  const id = (name: string) => teachers.find((t: { name: string }) => t.name === name).id
  const first = new Date(await pickLeaveDay(page, sid))
  const leaveDay = await dayWithPeriods(page, id(LEAVE_TEACHER), first)
  swapDay = await dayWithPeriods(page, id(SWAP_TEACHER), first, leaveDay)
  // 請假登記的操作在 04 影片示範過,這裡直接建好
  await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: id(LEAVE_TEACHER), leave_type: 'official', reason: '參加研習',
    start_date: leaveDay, end_date: leaveDay,
  })
})

test('錄影:調課', async ({ browser }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('swap')
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

  const card = page.getByTestId('sub-leave').filter({ hasText: LEAVE_TEACHER }).first()
  await d.seg('open', async () => {
    await page.waitForTimeout(500)
    await d.menu('調代課', '調代課處理')
    await expect(card).toBeVisible({ timeout: 20_000 })
    await d.point(card, 1500)
  })
  await d.seg('handle', async () => {
    await d.click(card.getByTestId('sub-handle').first())
    await expect(page.getByTestId('sub-swap')).toBeVisible({ timeout: 20_000 })
    await d.click(page.getByTestId('sub-swap'))
  })
  const panel = page.getByTestId('sub-swap-panel')
  await d.seg('partners', async () => {
    await expect(panel.getByTestId('sub-swap-option').first()).toBeVisible({ timeout: 20_000 })
    await d.point(panel.getByTestId('sub-swap-partner').first(), 1500)
    await d.point(panel.getByTestId('sub-swap-weeks'), 1500)
  })
  await d.seg('pick', async () => {
    await d.click(panel.getByTestId('sub-swap-option').first())
    await expect(card.getByTestId('sub-print-leave')).toBeVisible({ timeout: 20_000 })
  })

  await d.seg('new-swap', async () => {
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(600)
    await d.click(page.getByTestId('sub-new-swap'))
    await expect(page.getByTestId('sub-new-swap-modal')).toBeVisible()
  })
  await d.seg('ns-form', async () => {
    await d.pick(page.getByTestId('sub-ns-teacher'), SWAP_TEACHER)
    const input = page.getByTestId('sub-ns-date').locator('input')
    await d.click(input)
    await input.pressSequentially(swapDay, { delay: 70 })
    await input.press('Enter')
    const period = page.getByTestId('sub-ns-period').and(page.locator(':not(.n-checkbox--disabled)')).first()
    await expect(period).toBeVisible({ timeout: 20_000 })
    await d.click(period)
  })
  await d.seg('ns-pick', async () => {
    await d.click(page.getByTestId('sub-ns-create'))
    await expect(page.getByTestId('sub-swap-option').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(800)
    await d.click(page.getByTestId('sub-swap-option').first())
    await expect(page.getByTestId('sub-leave').filter({ hasText: SWAP_TEACHER }).getByTestId('sub-print-leave'))
      .toBeVisible({ timeout: 20_000 })
  })
  await d.seg('print', async () => {
    await d.click(card.getByTestId('sub-print-leave'))
    await expect(page.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(4500) // 等旁白念到「往下捲」再捲
    // 教師調課單有整週課表,比代課單長:直接平滑捲到班級通知單
    await page.getByTestId('slip-class').first()
      .evaluate((e) => e.scrollIntoView({ block: 'start', behavior: 'smooth' }))
  })
  await d.seg('outro', async () => {
    await d.card('調課完成', '下一支影片:06 課表匯出與列印')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
