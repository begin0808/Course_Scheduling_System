import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const YEARS = [147]

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function seed(page: Page, year: number): Promise<number> {
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, year, 1)
  const sid = (await post(page, '/api/semesters', {
    academic_year: year, term: 1, template_key: 'junior_high',
    start_date: '2026-09-01', end_date: '2027-01-20',
  })).id
  const q = `?semester_id=${sid}`
  const guo = (await post(page, `/api/subjects${q}`, { name: '國文' })).id
  const wang = (await post(page, `/api/teachers${q}`, { name: '王老師', base_periods: 20 })).id
  const c701 = (await post(page, `/api/class-units${q}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables${q}`, { name: '正式課表' })).id
  const wed = (await get(page, `/api/class-units/${c701}/period-table`)).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  const a = await post(page, `/api/assignments${q}`, {
    class_id: c701, subject_id: guo, periods_per_week: 1,
    teachers: [{ teacher_id: wang }], block_rules: [],
  })
  await page.request.post(`/api/timetables/${tt}/entries`,
    { data: { course_assignment_id: a.id, weekday: 3, period_no: wed[0].period_no, span: 1 } })
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  return sid
}

test.describe('課表匯出', () => {
  test.afterEach(async ({ page }) => {
    await page.request.post('/api/auth/logout')
    await login(page)
    for (const y of YEARS) await deleteSemesterByYearTerm(page, y, 1)
  })

  test('班級課表 Excel/PNG 下載,全校總表與批次 zip', async ({ page }) => {
    test.setTimeout(180_000)
    await login(page)
    await seed(page, 147)

    await page.goto('/timetable-query')
    await expect(page.getByTestId('tq-grid')).toBeVisible()

    // Excel 下載(api 同步)
    const [xlsx] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-xlsx').click(),
    ])
    expect(xlsx.suggestedFilename()).toContain('.xlsx')

    // PNG 下載(worker WeasyPrint 渲染)→ 存檔目視確認中文
    const [png] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-png').click(),
    ])
    expect(png.suggestedFilename()).toContain('.png')
    await png.saveAs(`${SHOTS}/m51-class.png`)

    // 全校總表 Excel + 批次 zip(管理者)
    const [school] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-school').click(),
    ])
    expect(school.suggestedFilename()).toContain('.xlsx')
    const [zip] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-batch').click(),
    ])
    expect(zip.suggestedFilename()).toContain('.zip')
  })
})
