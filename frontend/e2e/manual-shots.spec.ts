import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter } from './dates'

// 操作手冊補圖產生器(不是驗收測試)。對「已灌好示範資料的乾淨測試站」逐頁截圖 → docs/manual-img/。
//   npx playwright test manual-shots.spec.ts
// 前提:測試站已有示範學期(115 學年度第 1 學期)與 admin 帳號。
// 註:01-login / 02-wizard 需在「全新未設定」的站台才截得到,已另行取得,故此處不再重截。

const SHOTS = '../docs/manual-img'
const ADMIN = 'admin'
const PW = 'DemoManual2026!'
const SID = 1

test.use({
  baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081',
  viewport: { width: 1440, height: 900 },
})

const post = async (p: Page, url: string, data: object) => (await p.request.post(url, { data })).json()
const get = async (p: Page, url: string) => (await p.request.get(url)).json()

/** 示範站學期內、今日之後的第一個週三(代課不能指派已上過的節次,故不可取過去的日子)。 */
async function pickLeaveDay(page: Page): Promise<string> {
  const sem = await get(page, `/api/semesters/${SID}`)
  const earliest = new Date()
  earliest.setDate(earliest.getDate() + 1)
  const start = new Date(sem.start_date)
  const from = start > earliest ? start : earliest
  const wed = onOrAfter(3, from)
  if (iso(wed) > sem.end_date) {
    throw new Error(`示範站學期(${sem.start_date}~${sem.end_date})已過期,請重建示範資料再截圖`)
  }
  return iso(wed)
}

async function selectSemester(page: Page) {
  const sel = page.locator('.n-base-selection').first()
  if (await sel.isVisible().catch(() => false)) {
    await sel.click()
    const opt = page.locator('.n-base-select-option', { hasText: '115 學年度第 1 學期' }).first()
    if (await opt.isVisible().catch(() => false)) await opt.click()
    else await page.keyboard.press('Escape')
  }
  await page.waitForLoadState('networkidle')
}

test('產生操作手冊截圖(03–10)', async ({ page }) => {
  test.setTimeout(300_000)

  // 登入 + 確保精靈已完成(否則路由守衛會把每一頁導回精靈)
  const r = await page.request.post('/api/auth/login', { data: { username: ADMIN, password: PW } })
  expect(r.ok(), '請確認測試站 admin 密碼為 ' + PW).toBeTruthy()
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  const st = await get(page, '/api/wizard/state')
  expect(st.completed, '精靈未標記完成,頁面會被導回精靈').toBeTruthy()

  // ── 03 配課管理 ──
  await page.goto('/scheduling/assignments')
  await selectSemester(page)
  await expect(page.getByRole('heading', { name: '配課管理' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/03-assignments.png` })

  // ── 04 排課工作台 ──
  await page.goto('/scheduling/workbench')
  await selectSemester(page)
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/04-workbench.png` })

  // ── 05 自動排課(真的跑一次,截進度與達成度報告)──
  await page.goto('/scheduling/auto')
  await selectSemester(page)
  const done = page.getByTestId('as-status')
  if (!(await done.isVisible().catch(() => false))) {
    await expect(page.getByText('資料檢查通過,可以開始排課')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('as-start').click()
    // 3 班的示範學校數秒即解完,不必按「提前結束」(按鈕會直接變灰),等它自己完成即可
    await expect(done).toHaveText('已完成', { timeout: 180_000 })
  }
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/05-auto-schedule.png` })

  // ── 06 版本與發布(發布自排結果)──
  await page.goto('/scheduling/versions')
  await selectSemester(page)
  const pub = page.locator('[data-testid="v-row-115-1 草稿 自排結果"]').getByTestId('v-publish')
  if (await pub.isVisible().catch(() => false)) {
    await pub.click()
    const force = page.getByTestId('v-force-publish')
    if (await force.isVisible().catch(() => false)) await force.click()
    await page.waitForTimeout(800)
  }
  await page.screenshot({ path: `${SHOTS}/06-versions.png` })

  // ── 準備請假 + 代課(供 07/08 截圖)──
  const leaveDay = await pickLeaveDay(page)
  const teachers = await get(page, `/api/teachers?semester_id=${SID}`)
  const wang = teachers.find((t: { name: string }) => t.name === '王大明')
  const existing = await get(page, `/api/leaves?semester_id=${SID}`)
  if (!existing.length && wang) {
    const aps = (await post(page, `/api/leaves?semester_id=${SID}`, {
      teacher_id: wang.id, leave_type: 'sick', start_date: leaveDay, end_date: leaveDay,
    })).affected_periods
    for (const ap of aps.slice(0, 2)) {
      const rec = await get(page, `/api/affected-periods/${ap.id}/recommendations`)
      if (rec.candidates?.length) {
        await page.request.put(`/api/affected-periods/${ap.id}/substitution`,
          { data: { type: 'substitute', handler_teacher_id: rec.candidates[0].teacher_id } })
      }
    }
  }

  // ── 07 請假登記 ──
  await page.goto('/leaves')
  await selectSemester(page)
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/07-leaves.png` })

  // ── 08 今日調代課看板 ──
  await page.goto(`/daily-board?semester_id=${SID}&date=${leaveDay}`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/08-daily-board.png` })

  // ── 09 課表查詢(含匯出按鈕)──
  await page.goto(`/timetable-query?semester_id=${SID}`)
  await expect(page.getByRole('heading', { name: '課表查詢' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/09-timetable-query.png` })

  // ── 10 系統管理:備份與還原 ──
  await page.goto('/settings/system')
  await expect(page.getByTestId('backup-card')).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/10-backup.png` })
})
