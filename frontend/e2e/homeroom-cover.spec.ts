import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, THU, WED, statsQuery } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 代導(v1.4.0,LINE 社群使用者需求):導師請假當天一節課都沒有,班上也要有人帶。
 * 登記導師的假 → 調代課處理出現「待代導」→ 指派整段 → 印代導通知單 → 月結看得到天數。
 */
const YEAR = 172

const post = async (p: Page, url: string, data: object) => {
  const r = await p.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('代導:導師請假兩天,一次指派整段、列印代導單、月結列出天數', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  try {
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
    })
    const q = `?semester_id=${sem.id}`
    const wang = (await post(page, `/api/teachers${q}`, { name: '王老師' })).id
    const chen = (await post(page, `/api/teachers${q}`, { name: '陳老師' })).id
    await post(page, `/api/class-units${q}`,
      { grade: 7, name: '701', track: 'junior_high', homeroom_teacher_id: wang })
    await post(page, `/api/class-units${q}`,
      { grade: 7, name: '702', track: 'junior_high', homeroom_teacher_id: chen })
    // 王老師沒有任何課,課表也沒發布:以前這張假單在調代課處理根本不會出現
    await post(page, `/api/leaves${q}`,
      { teacher_id: wang, leave_type: 'personal', start_date: WED, end_date: THU })

    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    const card = page.getByTestId('sub-leave')
    await expect(card).toContainText('待代導 2 天')
    await expect(card.getByTestId('sub-cover')).toHaveCount(2)

    await card.getByTestId('sub-cover-handle').first().click()
    const panel = page.getByTestId('sub-cover-panel')
    await panel.getByTestId('sub-cover-teacher').click()
    // 同年級導師排最前面,並寫出他帶哪一班
    await page.locator('.n-base-select-option:visible', { hasText: '陳老師(702 導師)' }).click()
    await panel.getByTestId('sub-cover-assign-all').click()
    await expect(page.getByText('已指派 陳老師 代導 701(2 天)')).toBeVisible()
    await expect(card.getByTestId('sub-cover-handler')).toHaveText(['代導 → 陳老師', '代導 → 陳老師'])
    await expect(card).toContainText('待代導 0 天')

    const [slips] = await Promise.all([
      page.waitForEvent('popup'),
      card.getByTestId('sub-print-leave-cover').click(),
    ])
    const slip = slips.getByTestId('slip-cover')
    await expect(slip).toHaveCount(1)
    await expect(slip).toContainText('代導　通知單')
    await expect(slip.getByTestId('slip-cover-teacher')).toHaveText('代導教師：陳老師')
    await expect(slip.getByTestId('slip-cover-row')).toHaveCount(2)
    await expect(slip.getByTestId('slip-cover-row').first()).toContainText(WED)
    await expect(slip.getByTestId('slip-cover-row').first()).toContainText('王老師')
    await slips.close()

    // 月結:同一份報表,代導全天 2 天(WED、THU 同在基準週,必同月)
    await page.goto(`/substitution-stats?semester_id=${sem.id}${statsQuery(WED)}`)
    await expect(page.getByTestId('stats-total-cover')).toContainText('全天 2 天、半天 0 天')
    await expect(page.getByTestId('stats-cover-row')).toHaveCount(2)
    await expect(page.getByTestId('stats-cover-full')).toHaveText('2')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
