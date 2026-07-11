import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const DAY = '2026-11-11'   // 週三
const YEARS = [146]
const TEACHER_USER = 'e2e_teacher'
const TEACHER_PASS = 'e2eteacher1234'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

/** 綁定 e2e_teacher 帳號的「陳老師」,回傳 teacherId。 */
async function bindTeacher(page: Page, sid: number): Promise<number> {
  const file = fileURLToPath(new URL('./fixtures/teachers_with_account.xlsx', import.meta.url))
  const imp = await (await page.request.post(
    `/api/import/teachers?semester_id=${sid}&create_accounts=true`,
    { multipart: { file: { name: 't.xlsx', mimeType: XLSX, buffer: readFileSync(file) } } },
  )).json()
  if (imp.imported === 1) {
    const list = await get(page, `/api/teachers?semester_id=${sid}`)
    return list.find((x: { name: string }) => x.name === '陳老師').id
  }
  const created = await post(page, `/api/teachers?semester_id=${sid}`, { name: '陳老師' })
  const accounts = await get(page, `/api/teachers/bindable-accounts?semester_id=${sid}`)
  const acc = accounts.find((x: { username: string }) => x.username === TEACHER_USER)
  await page.request.patch(`/api/teachers/${created.id}`,
    { data: { name: '陳老師', user_id: acc.id } })
  return created.id
}

async function ensureTeacherPassword(page: Page) {
  await page.request.post('/api/auth/logout')
  const first = await page.request.post('/api/auth/login',
    { data: { username: TEACHER_USER, password: 'changeme' } })
  if (first.ok()) {
    await page.request.post('/api/auth/change-password',
      { data: { old_password: 'changeme', new_password: TEACHER_PASS } })
  }
  await page.request.post('/api/auth/logout')
}

/** 王師請假,陳老師代課 1 節、併班 1 節。 */
async function seed(page: Page, sid: number, chenId: number) {
  const q = `?semester_id=${sid}`
  const guo = (await post(page, `/api/subjects${q}`, { name: '國文' })).id
  const wang = (await post(page, `/api/teachers${q}`, { name: '王師', base_periods: 20 })).id
  const c701 = (await post(page, `/api/class-units${q}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const c702 = (await post(page, `/api/class-units${q}`,
    { grade: 7, name: '702', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
  const wed = (await get(page, `/api/class-units/${c701}/period-table`)).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  for (const [cls, idx] of [[c701, 0], [c702, 1]] as const) {
    const a = await post(page, `/api/assignments${q}`, {
      class_id: cls, subject_id: guo, periods_per_week: 1,
      teachers: [{ teacher_id: wang }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`,
      { data: { course_assignment_id: a.id, weekday: 3, period_no: wed[idx].period_no, span: 1 } })
  }
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  const aps = (await post(page, `/api/leaves${q}`, {
    teacher_id: wang, leave_type: 'sick', start_date: DAY, end_date: DAY,
  })).affected_periods
  await page.request.put(`/api/affected-periods/${aps[0].id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: chenId } })
  await page.request.put(`/api/affected-periods/${aps[1].id}/substitution`,
    { data: { type: 'merge', handler_teacher_id: chenId } })
}

test.describe('代課鐘點統計', () => {
  test.afterEach(async ({ page }) => {
    await page.request.post('/api/auth/logout')
    await login(page)
    for (const y of YEARS) await deleteSemesterByYearTerm(page, y, 1)
  })

  test('組長看月結彙總與明細,可匯出 Excel;教師只看自己', async ({ page }) => {
    test.setTimeout(180_000)
    await login(page)
    await page.request.patch('/api/wizard/state', { data: { completed: true } })
    await deleteSemesterByYearTerm(page, 146, 1)
    const sem = await post(page, '/api/semesters', {
      academic_year: 146, term: 1, template_key: 'junior_high',
      start_date: '2026-09-01', end_date: '2027-01-20',
    })
    const chenId = await bindTeacher(page, sem.id)
    await seed(page, sem.id, chenId)
    await ensureTeacherPassword(page)

    // ── 組長:2026-11 彙總 + 明細 ──
    await login(page)
    await page.goto(`/substitution-stats?semester_id=${sem.id}&year=2026&month=11`)
    const sumRow = page.getByTestId('stats-summary-row').filter({ hasText: '陳老師' }).first()
    await expect(sumRow).toContainText('陳老師')
    // 代課節數 2、計費節數 1(代課計、併班不計)
    await expect(sumRow.locator('td').nth(1)).toHaveText('2')
    await expect(sumRow.locator('td').nth(2)).toHaveText('1')
    await expect(page.getByTestId('stats-total')).toContainText('1')
    await expect(page.getByTestId('stats-detail-row')).toHaveCount(2)
    await page.screenshot({ path: `${SHOTS}/m45-1-stats.png`, fullPage: true })

    // 匯出 Excel:觸發下載
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('stats-export').click(),
    ])
    expect(download.suggestedFilename()).toContain('.xlsx')

    // ── 教師陳老師:只看自己,無匯出鈕、無教師篩選 ──
    await page.request.post('/api/auth/logout')
    await login(page, TEACHER_USER, TEACHER_PASS)
    await page.goto(`/substitution-stats?semester_id=${sem.id}&year=2026&month=11`)
    await expect(page.getByRole('heading', { name: '我的代課鐘點' })).toBeVisible()
    await expect(page.getByTestId('stats-detail-row')).toHaveCount(2)
    await expect(page.getByTestId('stats-export')).toHaveCount(0)
    await expect(page.getByTestId('stats-teacher')).toHaveCount(0)
    await page.screenshot({ path: `${SHOTS}/m45-2-mine.png`, fullPage: true })

    await page.request.post('/api/auth/logout')
  })
})
