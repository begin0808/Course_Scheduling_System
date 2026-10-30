import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter, statsQuery } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 補登(v1.4.2,組長回報):臨時找人代課,事後才登記公假。
 *
 * 登記時節次已經過了,還是「待處理」;先前按「處理」只會回「此節次已結束」,鐘點也漏算。
 * 現在標成「待補登」,可以補登代課(不通知老師、不能調課),補登後列入月結。
 * 導師的代導也一樣可以補登。
 */
const YEAR = 174

// 至少一週前的週三:不論幾點跑,那天的課都上完了。學期包住前後各兩個月
const today = new Date()
const daysAgo = (n: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate() - n)
const PAST_WED = iso(onOrAfter(3, daysAgo(14)))
const SEM_START = iso(daysAgo(60))
const SEM_END = iso(daysAgo(-60))

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('事後才登記的公假:過去的節次與代導標示待補登,補登後列入月結', async ({ page }) => {
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
    const wang = (await post(page, `/api/teachers${q}`, { name: '補登王師' })).id
    await post(page, `/api/teachers${q}`, { name: '補登陳師' })
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    expect((await page.request.patch(`/api/class-units/${c701}`, {
      data: { grade: 7, name: '701', track: 'junior_high', homeroom_teacher_id: wang },
    })).ok()).toBeTruthy()
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const wed: { period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
        .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
    for (const [i, subject] of ['補登國文', '補登體育'].entries()) {
      const s = (await post(page, `/api/subjects${q}`, { name: subject })).id
      const a = await post(page, `/api/assignments${q}`, {
        class_id: c701, subject_id: s, periods_per_week: 1,
        teachers: [{ teacher_id: wang }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday: 3, period_no: wed[i].period_no, span: 1 })
    }
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    await post(page, `/api/leaves${q}`,
      { teacher_id: wang, leave_type: 'official', start_date: PAST_WED, end_date: PAST_WED })

    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    const card = page.getByTestId('sub-leave').filter({ hasText: '補登王師' })
    await expect(card).toContainText('待處理 2 節')
    await expect(card.getByTestId('sub-status')).toHaveText(['待補登', '待補登'])

    // 一、補登代課:說明不通知、沒有調課可選
    const first = card.getByTestId('sub-period').first()
    await expect(first.getByTestId('sub-handle')).toHaveText('補登')
    await first.getByTestId('sub-handle').click()
    await expect(page.getByTestId('sub-backfill-hint')).toContainText('不會通知老師')
    await expect(page.getByTestId('sub-swap')).toHaveCount(0)
    await page.getByTestId('sub-pick').filter({ hasText: '補登陳師' }).click()
    await expect(card).toContainText('待處理 1 節')
    await expect(first.getByTestId('sub-status')).toHaveText('已完成')
    await expect(first.getByTestId('sub-handler')).toContainText('補登陳師')
    await expect(first.getByTestId('sub-undo')).toHaveCount(0)   // 補登後不能撤回

    // 二、補登代導
    const cover = card.getByTestId('sub-cover')
    await expect(cover.getByTestId('sub-cover-status')).toHaveText('待補登')
    await cover.getByTestId('sub-cover-handle').click()
    await expect(page.getByTestId('sub-cover-backfill-hint')).toContainText('不會通知老師')
    await page.getByTestId('sub-cover-teacher').click()
    await page.locator('.n-base-select-option', { hasText: '補登陳師' }).click()
    await page.getByTestId('sub-cover-assign').click()
    await expect(cover.getByTestId('sub-cover-status')).toHaveText('已完成')
    await expect(cover.getByTestId('sub-cover-handler')).toContainText('補登陳師')

    // 三、月結:補登的代課 1 節、代導全天 1 天
    await page.goto(`/substitution-stats?semester_id=${sem.id}${statsQuery(PAST_WED)}`)
    const row = page.getByTestId('stats-summary-row').filter({ hasText: '補登陳師' })
    await expect(row.locator('td').nth(1)).toHaveText('1')
    await expect(row.getByTestId('stats-cover-full')).toHaveText('1')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
