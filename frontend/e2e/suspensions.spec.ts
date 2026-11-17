import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 停課日(v1.4.19,LINE 社群組長:「停課日在哪邊可以設定?」)。
 *
 * 勾年級 = 勾整個年級的班;停課時段裡已經安排的請假節次,儲存時列出來讓組長處理;
 * 可以改成指定節次、可以刪除。
 */
const YEAR = 182

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('停課日:勾整個年級、列出已安排的請假、改成指定節次、刪除', async ({ page }) => {
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
    const wang = (await post(page, `/api/teachers${q}`, { name: '停課王師' })).id
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })
    await post(page, `/api/class-units${q}`, { grade: 8, name: '801', track: 'junior_high' })
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const first = (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json())
      .periods.find((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
    const s = (await post(page, `/api/subjects${q}`, { name: '停課國文' })).id
    const a = await post(page, `/api/assignments${q}`, {
      class_id: c701, subject_id: s, periods_per_week: 1,
      teachers: [{ teacher_id: wang }], block_rules: [],
    })
    await post(page, `/api/timetables/${tt}/entries`,
      { course_assignment_id: a.id, weekday: 3, period_no: first.period_no, span: 1 })
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    await post(page, `/api/leaves${q}`, {
      teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED,
    })

    await page.goto('/suspensions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    await expect(page.getByText('尚未設定停課日')).toBeVisible()

    // 一、七年級整天停課:勾年級就勾到 701、702
    await page.getByTestId('susp-new').click()
    const inputs = page.getByTestId('susp-range').locator('input')
    for (const i of [0, 1]) {
      await inputs.nth(i).click()
      await inputs.nth(i).fill(WED)
      await inputs.nth(i).press('Enter')
    }
    await page.getByTestId('susp-classes').click()
    await page.getByTestId('susp-grade-junior_high-7').click()
    const modal = page.getByTestId('susp-modal')
    await expect(modal.getByRole('checkbox', { name: '701' })).toBeChecked()
    await expect(modal.getByRole('checkbox', { name: '702' })).toBeChecked()
    await expect(modal.getByRole('checkbox', { name: '801' })).not.toBeChecked()
    await page.getByTestId('susp-reason').locator('input').fill('探索活動')
    await page.getByTestId('susp-save').click()

    // 二、王師那天第一節已經請假:列出來,不自動改
    const conflicts = page.getByTestId('susp-conflicts')
    await expect(conflicts).toContainText('701 停課國文:停課王師 病假')
    await conflicts.getByRole('button', { name: '知道了' }).click()
    const row = page.getByTestId('susp-row')
    await expect(row).toHaveCount(1)
    await expect(row).toContainText('七年級')
    await expect(row).toContainText('整天')
    await expect(row).toContainText('探索活動')

    // 三、改成第 5~7 節:王師那一節不在裡面,不再列出
    await row.getByRole('button', { name: '編輯' }).click()
    await page.getByTestId('susp-periods').click()
    await page.getByTestId('susp-from').locator('input').fill('5')
    await page.getByTestId('susp-to').locator('input').fill('7')
    await page.getByTestId('susp-save').click()
    await expect(row).toContainText('第 5~7 節')
    await expect(conflicts).toBeHidden()

    // 四、刪除
    await row.getByRole('button', { name: '刪除' }).click()
    await page.getByRole('button', { name: '確定' }).click()
    await expect(page.getByText('尚未設定停課日')).toBeVisible()
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
