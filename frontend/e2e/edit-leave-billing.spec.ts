import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 修改假別與計費方式(v1.4.4,LINE 社群組長回報)。
 *
 * 假別先前預設病假,公假被登成病假;計費方式跟著假別帶,也錯了。代課已經上過,
 * 沒有「撤回」可以重派。現在假單可以改假別(計費方式不自動變、會提醒),
 * 代課可以改計費方式——已經上過的也可以,代課老師不變。
 */
const YEAR = 176

// 至少一週前的週三:那天的課都上完了。學期包住前後各兩個月
const today = new Date()
const daysAgo = (n: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate() - n)
const PAST_WED = iso(onOrAfter(3, daysAgo(14)))

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('假別登錯:改成公假時提醒計費方式不會跟著變;已經上過的代課改得了計費方式', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: iso(daysAgo(60)), end_date: iso(daysAgo(-60)),
  })
  const q = `?semester_id=${sem.id}`

  try {
    const wang = (await post(page, `/api/teachers${q}`, { name: '改假王師' })).id
    const chen = (await post(page, `/api/teachers${q}`, { name: '改假陳師' })).id
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const wed: { period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
        .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
    for (const [i, subject] of ['改假美術', '改假生活'].entries()) {
      const s = (await post(page, `/api/subjects${q}`, { name: subject })).id
      const a = await post(page, `/api/assignments${q}`, {
        class_id: c701, subject_id: s, periods_per_week: 1,
        teachers: [{ teacher_id: wang }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday: 3, period_no: wed[i].period_no, span: 1 })
    }
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    // 組長的情況:公假被登成病假,事後補登代課(兩節都已經上過)
    const leave = await post(page, `/api/leaves${q}`,
      { teacher_id: wang, leave_type: 'sick', start_date: PAST_WED, end_date: PAST_WED })
    for (const p of leave.affected_periods) {
      const r = await page.request.put(`/api/affected-periods/${p.id}/substitution`,
        { data: { type: 'substitute', handler_teacher_id: chen, funding_source: '自費代課' } })
      expect(r.ok()).toBeTruthy()
    }

    // 一、請假登記:修改假別 → 提醒計費方式不會跟著變
    await page.goto('/leaves')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    const card = page.getByTestId('lv-card').filter({ hasText: '改假王師' })
    await expect(card).toContainText('改假王師 · 病假')
    await card.getByTestId('lv-edit').click()
    await expect(page.getByTestId('lv-edit-billing-hint')).toHaveCount(0)
    await page.getByTestId('lv-edit-type').click()
    await page.locator('.n-base-select-option', { hasText: '公假' }).click()
    await expect(page.getByTestId('lv-edit-billing-hint')).toContainText('不會自動變更')
    await page.getByTestId('lv-edit-reason').locator('input').fill('校外研習')
    await page.getByTestId('lv-edit-save').click()
    await expect(card).toContainText('改假王師 · 公假')
    await expect(card).toContainText('事由:校外研習')

    // 二、調代課處理:已經上過的兩節,計費方式還是自費代課;一次改成公費代課
    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    const sub = page.getByTestId('sub-leave').filter({ hasText: '改假王師' })
    await expect(sub).toContainText('公假')
    await expect(sub.getByTestId('sub-handler')).toHaveText(
      ['代課 → 改假陳師(自費代課)', '代課 → 改假陳師(自費代課)'])
    await expect(sub.getByTestId('sub-undo')).toHaveCount(0)   // 已經上過:不能撤回
    await sub.getByTestId('sub-billing-open').click()
    await page.getByTestId('sub-billing-funding').click()
    await page.locator('.n-base-select-option', { hasText: '公費代課' }).click()
    await page.getByTestId('sub-billing-save').click()
    await expect(sub.getByTestId('sub-handler')).toHaveText(
      ['代課 → 改假陳師(公費代課)', '代課 → 改假陳師(公費代課)'])

    // 三、只改其中一節:鐘點不計
    await sub.getByTestId('sub-billing-one').first().click()
    await page.getByTestId('sub-billing-counts').click()
    await page.getByTestId('sub-billing-save').click()
    await expect(sub.getByTestId('sub-handler').first()).toHaveText('代課 → 改假陳師(公費代課·鐘點不計)')
    await expect(sub.getByTestId('sub-handler').nth(1)).toHaveText('代課 → 改假陳師(公費代課)')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
