import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, STATS_QUERY, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 日薪代課與整批指派(使用者回報 #36)。
 *
 * 導師請整天假,由一位代課老師整天接手、按日計酬:
 *  - 假單上「整批指派代課」一次派完;代課老師自己有課的那一節跳過並說明原因
 *  - 計費方式選「日薪代課」→ 月結統計列在「日薪天數」,不計入鐘點
 */
const YEAR = 160

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

async function pick(page: Page, testid: string, text: string | RegExp) {
  await page.getByTestId(testid).click()
  await page.locator('.n-base-select-option', { hasText: text }).last().click()
}

test('整批指派日薪代課:有課的那一節跳過並說明;統計列為日薪天數', async ({ page }) => {
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
    const wang = (await post(page, `/api/teachers${q}`, { name: '日薪王導' })).id
    const chen = (await post(page, `/api/teachers${q}`, { name: '日薪陳代' })).id
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    const c702 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })).id
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const wed: { period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
        .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
    const lesson = async (cls: number, teacher: number, subject: string, idx: number) => {
      const s = (await post(page, `/api/subjects${q}`, { name: subject })).id
      const a = await post(page, `/api/assignments${q}`, {
        class_id: cls, subject_id: s, periods_per_week: 1,
        teachers: [{ teacher_id: teacher }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday: 3, period_no: wed[idx].period_no, span: 1 })
    }
    // 王導週三前三節都在 701(包班);陳代第二節在 702 有自己的課
    await lesson(c701, wang, '日薪國語', 0)
    await lesson(c701, wang, '日薪數學', 1)
    await lesson(c701, wang, '日薪生活', 2)
    await lesson(c702, chen, '日薪美術', 1)
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    await post(page, `/api/leaves${q}`,
      { teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED })

    // 一、整批指派
    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    const card = page.getByTestId('sub-leave').filter({ hasText: '日薪王導' })
    await expect(card).toContainText('待處理 3 節')
    await card.getByTestId('sub-batch-open').click()
    const modal = page.locator('.n-modal')
    await expect(modal).toContainText('整批指派代課')
    // 請假的老師不會出現在代課老師選單
    await page.getByTestId('sub-batch-teacher').click()
    await expect(page.locator('.n-base-select-option', { hasText: '日薪王導' })).toHaveCount(0)
    await page.locator('.n-base-select-option', { hasText: '日薪陳代' }).click()
    await pick(page, 'sub-batch-funding', '日薪代課')
    await page.getByTestId('sub-batch-run').click()

    // 第二節陳代自己有課 → 跳過並說明;其餘兩節已派
    const skipped = page.getByTestId('sub-batch-skipped')
    await expect(skipped).toContainText('已指派 2 節;有 1 節沒有派成')
    await expect(page.getByTestId('sub-batch-skip')).toHaveCount(1)
    await expect(page.getByTestId('sub-batch-skip')).toContainText('第二節')
    await expect(page.getByTestId('sub-batch-skip')).toContainText('日薪陳代')
    // 視窗關得掉(X、關閉鈕)
    await page.getByTestId('sub-batch-close').click()
    await expect(modal).toBeHidden()
    await expect(card).toContainText('待處理 1 節')
    await expect(card.getByTestId('sub-handler')).toHaveCount(2)
    // 只剩一節待處理 → 不再提供整批指派
    await expect(card.getByTestId('sub-batch-open')).toHaveCount(0)

    // 二、月結統計:日薪 1 天(共 2 節),鐘點計費 0 節
    await page.goto(`/substitution-stats?semester_id=${sem.id}${STATS_QUERY}`)
    const row = page.getByTestId('stats-summary-row').filter({ hasText: '日薪陳代' })
    await expect(row.locator('td').nth(1)).toHaveText('2')
    await expect(row.locator('td').nth(2)).toHaveText('0')
    await expect(row.getByTestId('stats-daily-cell')).toContainText('1 天')
    await expect(row.getByTestId('stats-daily-cell')).toContainText('共 2 節')
    await expect(page.getByTestId('stats-total')).toContainText('0')
    await expect(page.getByTestId('stats-total-daily')).toContainText('日薪合計 1 天')
    await expect(page.getByTestId('stats-pay')).toHaveText(['日薪', '日薪'])
    await expect(page.getByTestId('stats-daily-note')).toContainText('按日計酬')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
