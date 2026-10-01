import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * #15:學期沒有起訖日期就不能登記請假,但畫面上沒有任何地方填得了——
 * 建立學期表單沒有日期欄位、學期卡片沒有編輯、設定精靈也不問,
 * 等於照正常流程建立的學期一定卡住,使用者自己救不回來。
 */
const YEAR = 153
const START = '2026-08-30'
const END = '2027-01-20'

test('學期起訖日期:建立時可填,已建立的也能編輯補上', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 先用 API 建一個「沒有日期」的學期,重現使用者的處境
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()

  const teacher = await (await page.request.post(`/api/teachers?semester_id=${sem.id}`, {
    data: { name: '王師' },
  })).json()

  // 這種狀態下請假會被擋,而且訊息要指路
  const blocked = await page.request.post(`/api/leaves?semester_id=${sem.id}`, {
    data: {
      teacher_id: teacher.id, leave_type: 'sick',
      start_date: '2026-10-07', end_date: '2026-10-07',
    },
    failOnStatusCode: false,
  })
  expect(blocked.status()).toBe(400)
  expect((await blocked.json()).detail).toContain('編輯學期')

  // 畫面上看得出「尚未設定起訖日期」,而且有地方可以補
  await page.goto('/settings/semesters')
  const card = page.locator('.n-card').filter({ hasText: `${YEAR} 學年度第 1 學期` }).first()
  await expect(card.getByTestId('sem-no-range')).toBeVisible()
  await card.getByTestId('sem-edit').click()
  await page.getByTestId('sem-edit-start').locator('input').fill(START)
  await page.getByTestId('sem-edit-start').locator('input').press('Enter')
  await page.getByTestId('sem-edit-end').locator('input').fill(END)
  await page.getByTestId('sem-edit-end').locator('input').press('Enter')
  await page.getByTestId('sem-edit-save').click()
  await expect(page.getByText('學期已更新')).toBeVisible()
  await expect(card.getByTestId('sem-range')).toContainText(`${START} ~ ${END}`)

  // 補完之後請假就通了
  const ok = await page.request.post(`/api/leaves?semester_id=${sem.id}`, {
    data: {
      teacher_id: teacher.id, leave_type: 'sick',
      start_date: '2026-10-07', end_date: '2026-10-07',
    },
  })
  expect(ok.status(), '補上日期後應該可以登記請假').toBe(201)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

test('學期起訖日期:建立學期表單要求填日期,填了就直接帶入', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR + 1, 1)

  await page.goto('/settings/semesters')
  const yearInput = page.locator('.n-input-number input').first()
  await yearInput.fill(String(YEAR + 1))
  await yearInput.press('Enter')

  // 沒填日期就按建立 → 擋下來並說明原因
  await page.getByTestId('sem-create').click()
  await expect(page.getByText('請填學期起訖日期(請假與調代課需要)')).toBeVisible()

  await page.getByTestId('sem-start').locator('input').fill(START)
  await page.getByTestId('sem-start').locator('input').press('Enter')
  await page.getByTestId('sem-end').locator('input').fill(END)
  await page.getByTestId('sem-end').locator('input').press('Enter')
  await page.getByTestId('sem-create').click()
  await expect(page.getByText('學期已建立')).toBeVisible()

  const card = page.locator('.n-card').filter({ hasText: `${YEAR + 1} 學年度第 1 學期` }).first()
  await expect(card.getByTestId('sem-range')).toContainText(`${START} ~ ${END}`)

  await deleteSemesterByYearTerm(page, YEAR + 1, 1)
})
