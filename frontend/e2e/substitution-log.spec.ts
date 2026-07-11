import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const DAY = '2026-11-11'   // 週三
const YEARS = [144, 145]

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 學年度第 1 學期` }).click()
}

/** 建學期 + 王師請假 + 指派陳老師代課。回傳 { sid }。 */
async function seed(page: Page, year: number): Promise<number> {
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, year, 1)
  const sid = (await post(page, '/api/semesters', {
    academic_year: year, term: 1, template_key: 'junior_high',
    start_date: '2026-09-01', end_date: '2027-01-20',
  })).id
  const q = `?semester_id=${sid}`
  const guo = (await post(page, `/api/subjects${q}`, { name: '國文' })).id
  const wang = (await post(page, `/api/teachers${q}`, { name: '王師', base_periods: 20 })).id
  const chen = (await post(page, `/api/teachers${q}`,
    { name: '陳老師', base_periods: 20, subject_ids: [guo] })).id
  const c701 = (await post(page, `/api/class-units${q}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
  const wed = (await get(page, `/api/class-units/${c701}/period-table`)).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  const a = await post(page, `/api/assignments${q}`, {
    class_id: c701, subject_id: guo, periods_per_week: 1,
    teachers: [{ teacher_id: wang }], block_rules: [],
  })
  await page.request.post(`/api/timetables/${tt}/entries`,
    { data: { course_assignment_id: a.id, weekday: 3, period_no: wed[0].period_no, span: 1 } })
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  const affected = (await post(page, `/api/leaves${q}`, {
    teacher_id: wang, leave_type: 'sick', start_date: DAY, end_date: DAY,
  })).affected_periods[0]
  await page.request.put(`/api/affected-periods/${affected.id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: chen } })
  return sid
}

test.describe('今日看板與調代課日誌', () => {
  test.afterEach(async ({ page }) => {
    await page.request.post('/api/auth/logout')
    await login(page)
    for (const y of YEARS) await deleteSemesterByYearTerm(page, y, 1)
  })

  test('今日看板顯示當日代課,並可列印 A4 通知單', async ({ page }) => {
    test.setTimeout(120_000)
    await login(page)
    const sid = await seed(page, 144)

    // 直接以日期深連結開啟看板(當日=請假日)
    await page.goto(`/daily-board?semester_id=${sid}&date=${DAY}`)
    const row = page.getByTestId('board-row').filter({ hasText: '王師' }).first()
    await expect(row).toContainText('代課')
    await expect(row).toContainText('陳老師')
    await page.screenshot({ path: `${SHOTS}/m44-1-board.png`, fullPage: true })

    // 列印通知單 → 開新分頁,A4 公告含節次/班級/原教師/代課教師
    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.getByTestId('board-print').click(),
    ])
    await popup.waitForLoadState()
    await expect(popup.getByTestId('print-table')).toBeVisible()
    const printRow = popup.getByTestId('print-row').filter({ hasText: '王師' }).first()
    await expect(printRow).toContainText('陳老師')
    await expect(popup.getByText('調代課通知單')).toBeVisible()
    await popup.screenshot({ path: `${SHOTS}/m44-2-print.png` })
    await popup.close()

    // 無異動日:今日無調代課
    await page.goto(`/daily-board?semester_id=${sid}&date=2026-11-12`)  // 週四,無請假
    await expect(page.getByTestId('board-empty')).toBeVisible()
  })

  test('調代課紀錄可依教師篩選', async ({ page }) => {
    test.setTimeout(120_000)
    await login(page)
    await seed(page, 145)

    await page.goto('/substitution-log')
    await selectSemester(page, 145)
    const row = page.getByTestId('log-row').filter({ hasText: '王師' }).first()
    await expect(row).toContainText('代課')
    await expect(row).toContainText('陳老師')

    // 以「陳老師」(代課者)篩選,仍應命中(缺課或代課皆算相關)
    await page.getByTestId('log-teacher').click()
    await page.locator('.n-base-select-option', { hasText: '陳老師' }).click()
    await expect(page.getByTestId('log-row').filter({ hasText: '王師' })).toBeVisible()
    await expect(page.getByTestId('log-count')).toContainText('1')
    await page.screenshot({ path: `${SHOTS}/m44-3-log.png` })
  })
})
