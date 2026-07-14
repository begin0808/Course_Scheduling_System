import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

// M6-3 驗收:一門「完全排不下」的課(教師整週不可排)不會讓部分排課整鍋失敗,
// 而是列進未排清單並說明原因;force 發布後,版本頁的完整性報告仍講得出那個原因
// (未排清單存進 DB,不再只活在 Redis 24h)。

const SHOTS = 'e2e/screenshots'
const YEAR = 151

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

test('部分排課:完全排不下的課列入未排清單並說明原因,發布後仍查得到', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const sid = sem.id
  const cls = await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '701', track: 'junior_high' })

  // ① 正常課:排得進去
  const chinese = await post(page, `/api/subjects?semester_id=${sid}`, { name: '國文' })
  const wang = await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王師', base_periods: 20 })
  await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: cls.id, subject_id: chinese.id, periods_per_week: 4,
    teachers: [{ teacher_id: wang.id }], block_rules: [],
  })

  // ② 完全排不下的課:美術老師整週每一格都設為「不可排」
  const art = await post(page, `/api/subjects?semester_id=${sid}`, { name: '美術' })
  const lin = await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '林師', base_periods: 20 })
  const table = await get(page, `/api/class-units/${cls.id}/period-table`)
  await page.request.put(`/api/teachers/${lin.id}/time-rules`, {
    data: table.periods.map((p: { weekday: number; period_no: number }) => ({
      weekday: p.weekday, period_no: p.period_no, rule_type: 'unavailable',
    })),
  })
  await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: cls.id, subject_id: art.id, periods_per_week: 2,
    teachers: [{ teacher_id: lin.id }], block_rules: [],
  })

  await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })

  // ── 自動排課頁:勾選部分排課(來源草稿由頁面自己選)──
  await page.goto(`/scheduling/auto?semester_id=${sid}`)
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.getByTestId('as-partial').click()
  await page.getByTestId('as-start').click()

  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 120_000 })

  // 未排清單要列出美術,並說得出為什麼(這正是舊版整鍋失敗的那門課)
  const unscheduled = page.getByTestId('as-unscheduled')
  await expect(unscheduled).toBeVisible()
  await expect(unscheduled).toContainText('美術')
  await expect(unscheduled).toContainText('找不到任何可排的')
  // 其他課照排(部分排課存在的意義)
  await expect(unscheduled).not.toContainText('國文')
  await page.screenshot({ path: `${SHOTS}/m63-1-unscheduled-reason.png` })

  // ── 版本頁:force 發布,完整性報告仍講得出原因(持久化,不靠 Redis)──
  const versions = await get(page, `/api/timetables?semester_id=${sid}`)
  const result = versions.find((v: { name: string }) => v.name.includes('部分排課結果'))
  expect(result, '應產出部分排課結果草稿').toBeTruthy()

  await page.goto(`/scheduling/versions?semester_id=${sid}`)
  await page.locator(`[data-testid="v-row-${result.name}"]`).getByTestId('v-publish').click()
  const unplaced = page.getByTestId('v-unplaced')
  await expect(unplaced).toContainText('美術')
  await expect(unplaced).toContainText('找不到任何可排的')
  await page.screenshot({ path: `${SHOTS}/m63-2-publish-warning-reason.png` })
  await page.getByTestId('v-force-publish').click()

  // 發布之後再查一次:原因還在(先前這份紀錄 24h 後就消失了)
  const report = await get(page, `/api/timetables/${result.id}/completeness`)
  const artItem = report.unplaced.find((u: { subject: string }) => u.subject === '美術')
  expect(artItem.remaining).toBe(2)
  expect(artItem.reason).toContain('找不到任何可排的')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
