import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso } from '../dates'
import { ensureDemoData, get, loginAsAdmin, pickLeaveDay, publishBySolver } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片:請假與代課。請用 scripts/video/build_video.py leave-substitute 執行
// (它會先產生旁白語音,再跑這支錄影,最後合成 MP4)。
// 需要一個全新的示範站(同 manual-shots:docker compose -p manual,ADMIN_PASSWORD=DemoSetup2026!)。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }
const TEACHER = '陳志明' // 703 導師,教數學

test.describe.configure({ mode: 'serial' })
test.use({ baseURL: BASE })

let sid = 0
let day = ''

test('準備示範資料(不錄影)', async ({ page }) => {
  test.setTimeout(300_000)
  await loginAsAdmin(page)
  sid = await ensureDemoData(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await publishBySolver(page, sid)
  // 找陳老師之後兩週內、至少有兩節課、還沒有被請假占用的一天
  const teacher = (await get(page, `/api/teachers?semester_id=${sid}`))
    .find((t: { name: string }) => t.name === TEACHER)
  const first = new Date(await pickLeaveDay(page, sid))
  for (let i = 0; i < 14 && !day; i++) {
    const d = new Date(first)
    d.setDate(first.getDate() + i)
    if (d.getDay() === 0 || d.getDay() === 6) continue
    const periods = await get(page,
      `/api/teachers/${teacher.id}/day-periods?semester_id=${sid}&date=${iso(d)}`)
    if (periods.filter((p: { is_past: boolean; taken_by: string }) => !p.is_past && !p.taken_by).length >= 2) {
      day = iso(d)
    }
  }
  expect(day, `${TEACHER} 兩週內找不到有兩節課的日子`).toBeTruthy()
})

test('錄影:請假與代課', async ({ browser }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('leave-substitute')
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)
  await loginAsAdmin(page)

  const menu = async (label: string) => {
    const exact = (t: string) => page.locator('.n-menu-item-content-header', { hasText: new RegExp(`^${t}$`) }).first()
    const item = exact(label)
    if (!(await item.isVisible())) await d.click(exact('調代課'))
    await d.click(item)
    await page.waitForLoadState('networkidle')
  }
  const pick = async (select: string, option: string, scope: Page = page) => {
    await d.click(scope.getByTestId(select))
    await d.click(scope.locator('.n-base-select-option', { hasText: option }).first())
  }
  const date = async (testid: string, value: string) => {
    const input = page.getByTestId(testid).locator('input')
    await d.click(input)
    await input.pressSequentially(value, { delay: 70 })
    await input.press('Enter')
  }

  await d.sync()
  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  await d.seg('open-leaves', async () => {
    await page.waitForTimeout(500)
    await menu('請假登記')
  })
  await d.seg('teacher-type', async () => {
    await pick('lv-teacher', TEACHER)
    await pick('lv-type', '公假')
    await d.type(page.getByTestId('lv-reason').locator('input'), '參加研習')
  })
  await d.seg('dates', async () => {
    await date('lv-start', day)
    await date('lv-end', day)
    await d.point(page.getByTestId('lv-halfday'), 900)
  })
  const leaveCard = page.getByTestId('lv-card').filter({ hasText: TEACHER }).first()
  await d.seg('submit', async () => {
    await d.click(page.getByTestId('lv-submit'))
    await expect(leaveCard).toBeVisible({ timeout: 20_000 })
    await d.point(leaveCard.getByTestId('lv-affected'), 1500)
    await d.point(leaveCard.getByTestId('lv-covers'), 800)
  })

  const card = page.getByTestId('sub-leave').filter({ hasText: TEACHER }).first()
  await d.seg('open-subs', async () => {
    await menu('調代課處理')
    await expect(card).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1200)
    await d.point(card.getByTestId('sub-batch-open'), 1500)
  })
  await d.seg('recommend', async () => {
    await expect(card).toBeVisible({ timeout: 20_000 })
    await d.click(card.getByTestId('sub-handle').first())
    await expect(page.getByTestId('sub-candidate').first()).toBeVisible({ timeout: 20_000 })
    await d.point(page.getByTestId('sub-pick').first(), 1500)
    await d.point(page.getByTestId('sub-funding'), 1000)
  })
  await d.seg('assign', async () => {
    await d.click(page.getByTestId('sub-pick').first())
    await expect(card.getByTestId('sub-handler').first()).toBeVisible({ timeout: 20_000 })
  })
  await d.seg('next', async () => {
    const more = card.getByTestId('sub-handle')
    if (await more.count()) {
      await d.click(more.first())
      await expect(page.getByTestId('sub-pick').first()).toBeVisible({ timeout: 20_000 })
      await d.click(page.getByTestId('sub-pick').first())
    }
  })
  await d.seg('cover', async () => {
    await d.click(card.getByTestId('sub-cover-handle').first())
    await d.click(card.getByTestId('sub-cover-teacher'))
    await d.click(page.locator('.n-base-select-option').first())
    await d.click(card.getByTestId('sub-cover-assign'))
    await expect(card.getByTestId('sub-cover-handler').first()).toBeVisible({ timeout: 20_000 })
  })
  await d.seg('print', async () => {
    await d.click(card.getByTestId('sub-print-leave-sub'))
    await expect(page.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(5500) // 等旁白念到「往下捲」再捲
    for (let i = 0; i < 6; i++) {
      await page.mouse.wheel(0, 180)
      await page.waitForTimeout(250)
    }
  })
  await d.seg('outro', async () => {
    await d.card('謝謝收看', '更多說明請看使用手冊:begin0808.github.io/Course_Scheduling_System')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
