import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

// v1.6.1:「同班同科目每日節數上限」以前只有 API 改得到,組長在畫面上找不到。
// 改在「自動排課」頁的排課規則設定;手動拖課、自動排課、檢查課表都照這個值。
test('自動排課頁可設定同班同科目每日節數上限,手動排課隨即照新上限判斷', async ({ page }) => {
  const YEAR = 188
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const post = async (url: string, data: object) => (await page.request.post(url, { data })).json()
  const sem = await post('/api/semesters', { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  const sid = sem.id as number
  // 先存一個非預設的軟約束權重,確認畫面儲存上限時不會把其他設定蓋回預設
  const before = await (await page.request.get(`/api/solver/config?semester_id=${sid}`)).json()
  const firstWeight = Object.keys(before.weights)[0]
  await page.request.put(`/api/solver/config?semester_id=${sid}`, {
    data: { ...before, weights: { ...before.weights, [firstWeight]: 7 }, teacher_daily_max: 5 },
  })

  const cls = await post(`/api/class-units?semester_id=${sid}`, { grade: 7, name: '701', track: 'junior_high' })
  const subj = await post(`/api/subjects?semester_id=${sid}`, { name: '每日上限測試科' })
  const teacher = await post(`/api/teachers?semester_id=${sid}`, { name: '上限測試師', base_periods: 20 })
  const asg = await post(`/api/assignments?semester_id=${sid}`, {
    class_id: cls.id, subject_id: subj.id, periods_per_week: 4,
    teachers: [{ teacher_id: teacher.id }], block_rules: [],
  })
  const tt = await post(`/api/timetables?semester_id=${sid}`, { name: '草稿A' })
  const periods = (await (await page.request.get(`/api/class-units/${cls.id}/period-table`)).json()).periods
  const mon = periods.filter((p: { weekday: number, type: string }) => p.weekday === 1 && p.type === 'regular')
    .map((p: { period_no: number }) => p.period_no)
  const place = (pno: number) => page.request.post(`/api/timetables/${tt.id}/entries`, {
    data: { course_assignment_id: asg.id, weekday: 1, period_no: pno, span: 1 },
  })
  expect((await place(mon[0])).status()).toBe(201)
  expect((await place(mon[1])).status()).toBe(201)
  const blocked = await place(mon[2])
  expect(blocked.status()).toBe(409)
  expect(JSON.stringify(await blocked.json())).toContain('自動排課')

  await page.goto('/scheduling/auto')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

  const rules = page.getByTestId('as-rules')
  await expect(rules).toBeVisible()
  const cap = page.getByTestId('as-daily-cap').locator('input')
  await expect(cap).toHaveValue('2')
  await expect(page.getByTestId('as-rules-save')).toBeDisabled()

  await cap.fill('3')
  await cap.blur()
  await expect(page.getByTestId('as-rules-dirty')).toBeVisible()
  await page.getByTestId('as-rules-save').click()
  await expect(page.getByText('已儲存:同班同科目每天最多 3 節')).toBeVisible()
  await expect(page.getByTestId('as-rules-dirty')).toHaveCount(0)

  const after = await (await page.request.get(`/api/solver/config?semester_id=${sid}`)).json()
  expect(after.daily_subject_cap).toBe(3)
  expect(after.teacher_daily_max).toBe(5)
  expect(after.weights[firstWeight]).toBe(7)

  // 同一格現在放得下,第 4 節才被擋
  expect((await place(mon[2])).status()).toBe(201)
  const blocked4 = await place(mon[3])
  expect(blocked4.status()).toBe(409)
  expect(JSON.stringify(await blocked4.json())).toContain('每日上限 3 節')

  // 重新整理後仍是 3
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await expect(page.getByTestId('as-daily-cap').locator('input')).toHaveValue('3')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
