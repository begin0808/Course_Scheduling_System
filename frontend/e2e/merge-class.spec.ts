import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 併班(v1.3.5,LINE 社群使用者回報):先前按「併班」沒有地方選老師,一按就是
 * 「「併班」需要指定教師」。現在列出這一節正在上自己班的老師(同年級優先),選一位併過去。
 */
const YEAR = 170

const post = async (p: Page, url: string, data: object) => {
  const r = await p.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('併班:列出這一節在上課的老師,選一位把班併過去', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  try {
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
    })
    const q = `?semester_id=${sem.id}`
    const subjects: { id: number; name: string }[] = await (await page.request.get(`/api/subjects${q}`)).json()
    const sid = (name: string) => subjects.find((s) => s.name === name)!.id
    const teacher = async (name: string, subject: string) =>
      (await post(page, `/api/teachers${q}`, { name, subject_ids: [sid(subject)] })).id as number
    const klass = async (grade: number, name: string) =>
      (await post(page, `/api/class-units${q}`, { grade, name, track: 'junior_high' })).id as number

    const wang = await teacher('王老師', '國文')
    const chen = await teacher('陳老師', '國文')
    const lee = await teacher('李老師', '國文')
    await teacher('張老師', '國文')     // 空堂:不會出現在併班名單(請用代課)
    const c701 = await klass(7, '701')
    const c702 = await klass(7, '702')
    const c801 = await klass(8, '801')
    const periods: { weekday: number; name: string; period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
    const first = periods.find((p) => p.weekday === 3 && p.name === '第一節')!.period_no

    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    for (const [who, cls] of [[wang, c701], [chen, c702], [lee, c801]]) {
      const a = await post(page, `/api/assignments${q}`, {
        class_id: cls, subject_id: sid('國文'), periods_per_week: 1,
        teachers: [{ teacher_id: who }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday: 3, period_no: first, span: 1 })
    }
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    await post(page, `/api/leaves${q}`, { teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED })

    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    await page.getByTestId('sub-handle').first().click()

    await page.getByTestId('sub-merge').click()
    const panel = page.getByTestId('sub-merge-panel')
    const picks = panel.getByTestId('sub-merge-pick')
    await expect(picks).toHaveText(['併到 陳老師(702)', '併到 李老師(801)'])   // 同年級在前
    await expect(panel).toContainText('同年級')
    await expect(panel).not.toContainText('張老師')

    await picks.first().click()
    await expect(page.getByText('已把 701 併到 陳老師 的 702 一起上')).toBeVisible()
    await expect(page.getByTestId('sub-period').first().getByTestId('sub-handler')).toContainText('併班 → 陳老師')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
