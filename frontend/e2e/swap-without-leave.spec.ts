import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 新增調課(未請假,v1.4.5,LINE 社群組長回報)。
 *
 * 老師沒請假,只是要和別人調課;先前調課只能從請假展開的節次做。現在「調代課處理」可以
 * 新增調課:選老師、日期、勾節次,直接列出可對調節次。只能調課,也不出現在請假登記。
 */
const YEAR = 178

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('新增調課(未請假):勾節次後直接對調;只能調課;不出現在請假登記;可以取消', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })
  const q = `?semester_id=${sem.id}`

  try {
    const wang = (await post(page, `/api/teachers${q}`, { name: '調課王師' })).id
    const chen = (await post(page, `/api/teachers${q}`, { name: '調課陳師' })).id
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const regular = (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json())
      .periods.filter((p: { type: string }) => p.type === 'regular')
    const slot = (weekday: number, idx: number) =>
      regular.filter((p: { weekday: number }) => p.weekday === weekday)[idx].period_no
    const lesson = async (teacher: number, subject: string, weekday: number, idx: number) => {
      const s = (await post(page, `/api/subjects${q}`, { name: subject })).id
      const a = await post(page, `/api/assignments${q}`, {
        class_id: c701, subject_id: s, periods_per_week: 1,
        teachers: [{ teacher_id: teacher }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday, period_no: slot(weekday, idx), span: 1 })
    }
    // 王師週三第一、二節;陳師週四第一節(和王師互換的對象)
    await lesson(wang, '調課國文', 3, 0)
    await lesson(wang, '調課作文', 3, 1)
    await lesson(chen, '調課數學', 4, 0)
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()

    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

    // 一、新增調課:選老師、日期,列出他那天的兩節,勾第一節
    await page.getByTestId('sub-new-swap').click()
    await page.getByTestId('sub-ns-teacher').click()
    await page.locator('.n-base-select-option', { hasText: '調課王師' }).click()
    const date = page.getByTestId('sub-ns-date').locator('input')
    await date.click()
    await date.fill(WED)
    await date.press('Enter')
    const boxes = page.getByTestId('sub-ns-period')
    await expect(boxes).toHaveCount(2)
    await expect(boxes.first()).toContainText('調課國文')
    await expect(page.getByTestId('sub-ns-create')).toBeDisabled()
    await boxes.first().click()
    await page.getByTestId('sub-ns-create').click()

    // 二、直接列出可對調節次;沒有代課推薦、併班、自習
    const card = page.getByTestId('sub-leave').filter({ hasText: '調課王師' })
    await expect(card).toContainText('調課(未請假)')
    await expect(card).toContainText('待處理 1 節')
    await expect(page.getByTestId('sub-swaponly-hint')).toContainText('只能選調課')
    await expect(page.getByTestId('sub-merge')).toHaveCount(0)
    await expect(page.getByTestId('sub-selfstudy')).toHaveCount(0)
    await expect(page.getByTestId('sub-candidate')).toHaveCount(0)
    const partner = page.getByTestId('sub-swap-partner').filter({ hasText: '調課陳師' })
    await partner.getByTestId('sub-swap-option').first().click()
    await expect(card.getByTestId('sub-handler')).toContainText('調課 → 調課陳師')
    await expect(card.getByTestId('sub-print-leave')).toBeVisible()   // 調課單照樣可以印

    // 三、請假登記看不到這一筆
    await page.goto('/leaves')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    await expect(page.getByText('尚無請假紀錄')).toBeVisible()

    // 四、取消這筆調課 → 卡片消失
    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    await card.getByTestId('sub-cancel-swap').click()
    await page.getByRole('button', { name: '確定' }).click()
    await expect(card).toHaveCount(0)
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
