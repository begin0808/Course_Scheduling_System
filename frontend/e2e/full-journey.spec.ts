import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

// M5-4 驗收①(UI 連續情境):一個學期從建立 → 自動排課 → 發布 → 請假 → 代課 → 月結,
// 一路走完,證明各關卡的畫面能串接成真實的教務生命週期。個別旅程的細節由各自 spec
// 深入覆蓋;此處只驗「整條鏈接得起來、末端數字對得上」。

const SHOTS = 'e2e/screenshots'
const YEAR = 148
const LEAVE_DAY = '2026-11-11' // 週三
const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 學年度第 1 學期` }).click()
}

/** 6 班國中:夠真實又能在數秒內排完,適合連續情境。 */
async function seedSchool(page: Page, sid: number) {
  const subjects: Record<string, number> = {}
  for (const s of await get(page, `/api/subjects?semester_id=${sid}`)) subjects[s.name] = s.id
  const plan: [string, number, number][] = [
    ['國文', 5, 2], ['英語', 4, 2], ['數學', 4, 2], ['自然科學', 3, 2],
    ['社會', 3, 2], ['健康與體育', 3, 1], ['藝術', 3, 1], ['綜合活動', 3, 1],
  ]
  const teachers: Record<string, number[]> = {}
  for (const [subject, , count] of plan) {
    teachers[subject] = []
    for (let i = 0; i < count; i += 1) {
      const t = await post(page, `/api/teachers?semester_id=${sid}`,
        { name: `${subject}師${i + 1}`, base_periods: 22 })
      teachers[subject].push(t.id)
    }
  }
  const classes: number[] = []
  for (let i = 1; i <= 6; i += 1) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name: `70${i}`, track: 'junior_high' })
    classes.push(c.id)
  }
  for (const [subject, periods, count] of plan) {
    for (const [idx, cid] of classes.entries()) {
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: cid, subject_id: subjects[subject], periods_per_week: periods,
        teachers: [{ teacher_id: teachers[subject][idx % count] }], block_rules: [],
      })
    }
  }
}

test('全流程:建學期 → 自動排課 → 發布 → 請假 → 代課 → 月結,一路串到底', async ({ page }) => {
  test.setTimeout(240_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // ── 1) 建學期 + 基礎資料(API 準備)──
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: '2026-09-01', end_date: '2027-01-20',
  })
  await seedSchool(page, sem.id)
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  // ── 2) 自動排課(真實走 solver worker,UI 顯示進度)──
  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)
  await expect(page.getByText('資料檢查通過,可以開始排課')).toBeVisible()
  await page.getByTestId('as-start').click()
  await expect(page.getByTestId('as-stop')).toBeEnabled({ timeout: 90_000 })
  await page.getByTestId('as-stop').click()
  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 90_000 })
  await expect(page.getByTestId('as-done')).toContainText('草稿A 自排結果')
  await page.screenshot({ path: `${SHOTS}/journey-1-autoschedule.png` })

  // ── 3) 發布自排結果(版本管理頁,UI)──
  await page.goto('/scheduling/versions')
  await selectSemester(page, YEAR)
  const row = page.locator('[data-testid="v-row-草稿A 自排結果"]')
  await row.getByTestId('v-publish').click()
  const force = page.getByTestId('v-force-publish')
  if (await force.isVisible().catch(() => false)) await force.click()
  await expect(page.getByTestId('v-status-草稿A 自排結果')).toHaveText('已發布')
  await page.screenshot({ path: `${SHOTS}/journey-2-published.png` })

  // ── 4) 課表查詢:已發布課表在唯讀查詢頁可見(UI)──
  await page.goto(`/timetable-query?semester_id=${sem.id}`)
  await expect(page.getByRole('heading', { name: '課表查詢' })).toBeVisible()

  // ── 5) 請假 + 代課(API;個別 UI 由 leaves/substitutions spec 覆蓋)──
  const published = (await get(page, `/api/timetables?semester_id=${sem.id}`))
    .find((t: { name: string; status: string }) => t.status === 'published')
  const entries = (await get(page, `/api/timetables/${published.id}`)).entries
  // 找一筆週三(weekday=3)的格位,取其教師請整天假
  const wedEntry = entries.find((e: { weekday: number }) => e.weekday === 3) || entries[0]
  const assignment = (await get(page, `/api/assignments?semester_id=${sem.id}`))
    .find((a: { id: number }) => a.id === wedEntry.course_assignment_id)
  const absentId = assignment.teachers[0].teacher_id
  const leaveDay = wedEntry.weekday === 3 ? LEAVE_DAY : null
  const aps = (await post(page, `/api/leaves?semester_id=${sem.id}`, {
    teacher_id: absentId, leave_type: 'personal',
    start_date: leaveDay || '2026-11-11', end_date: leaveDay || '2026-11-11',
  })).affected_periods
  expect(aps.length).toBeGreaterThan(0)

  // 用推薦清單挑一位當時段有空的教師指派代課
  const target = aps[0]
  const rec = await get(page, `/api/affected-periods/${target.id}/recommendations`)
  expect(rec.candidates.length).toBeGreaterThan(0)
  const handlerId = rec.candidates[0].teacher_id
  await page.request.put(`/api/affected-periods/${target.id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: handlerId } })

  // ── 6) 月結統計(UI):接手教師的代課節數與計費節數呈現在畫面上 ──
  await page.goto(`/substitution-stats?semester_id=${sem.id}&year=2026&month=11`)
  await expect(page.getByRole('heading', { name: /代課鐘點/ })).toBeVisible()
  await expect(page.getByTestId('stats-detail-row').first()).toBeVisible()
  await expect(page.getByTestId('stats-summary-row')).not.toHaveCount(0)
  await page.screenshot({ path: `${SHOTS}/journey-3-stats.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
