import { expect, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * #18:每學年職務異動(卸任/新任行政職、鐘點與減課調整)要改幾十位老師,
 * 但匯入教師遇到既有教師只會報「重複」、整批不寫入,只能一位位手改。
 * 勾選「既有教師改為更新資料」後,既有的改為更新、新的照舊新增。
 */
const YEAR = 154
const SHOTS = 'e2e/screenshots'

test('匯入教師:勾選更新後,既有教師改為更新資料,空白欄位保留原值', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const post = async (url: string, data: object) => (await page.request.post(url, { data })).json()
  const sem = await post('/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  const subjects = await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()
  const math = subjects.find((s: { name: string }) => s.name === '數學')
    ?? await post(`/api/subjects?semester_id=${sid}`, { name: '數學' })
  if (!subjects.some((s: { name: string }) => s.name === '物理')) {
    await post(`/api/subjects?semester_id=${sid}`, { name: '物理' })
  }

  // 既有教師:教學組長、鐘點 20、減課 4、教數學、有 Email
  const before = await post(`/api/teachers?semester_id=${sid}`, {
    name: '王小明', id_last4: '1234', base_periods: 20, admin_title: '教學組長',
    admin_reduction: 4, subject_ids: [math.id], email: 'wang@example.edu.tw',
  })

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '批次匯入' }).click()
  await page.locator('.n-radio-button', { hasText: '教師' }).click()

  const file = fileURLToPath(new URL('./fixtures/teachers_update.xlsx', import.meta.url))
  await page.locator('input[type="file"]').setInputFiles(file)

  // 沒勾更新 → 既有教師被判重複,整批不寫入
  await page.getByRole('button', { name: '開始匯入' }).click()
  await expect(page.getByText(/重複/)).toBeVisible()
  expect(await (await page.request.get(`/api/teachers?semester_id=${sid}`)).json())
    .toHaveLength(1)

  // 勾選更新後再匯入一次
  await page.getByTestId('import-update').click()
  await page.locator('input[type="file"]').setInputFiles(file)
  await page.getByRole('button', { name: '開始匯入' }).click()
  await expect(page.getByTestId('import-ok')).toContainText('新增 1 筆、更新 1 筆')
  await page.screenshot({ path: `${SHOTS}/import-teacher-update.png` })

  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sid}`)).json()
  expect(teachers).toHaveLength(2)
  const wang = teachers.find((t: { name: string }) => t.name === '王小明')
  expect(wang.id, '應該是更新同一筆,不是新建').toBe(before.id)
  expect(wang.admin_title ?? '', '行政職稱填「無」= 卸任').toBe('')
  expect(wang.base_periods).toBe(22)
  expect(wang.admin_reduction).toBe(0)
  expect(wang.subjects.map((s: { name: string }) => s.name).sort()).toEqual(['數學', '物理'].sort())
  expect(wang.email, '空白欄位要保留原值').toBe('wang@example.edu.tw')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
