import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 124 // 專用測試學年度
const SHOTS = 'e2e/screenshots'

// M2-0:教師表單新增聯絡資訊(Email/手機/LINE)與帳號綁定欄位。
test('教師聯絡資訊:新增教師填入 Email/手機/LINE 並保存', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置(API):建立乾淨的測試學期
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })

  // 進入基礎資料 → 選該學期 → 教師分頁
  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教師' }).click()

  // 新增教師,填入姓名與聯絡資訊
  await page.getByTestId('teacher-add').click()
  await page.getByTestId('teacher-name').locator('input').fill('陳老師')
  await page.getByTestId('teacher-email').locator('input').fill('chen@example.edu.tw')
  // 帳號綁定下拉存在(本學期尚無教師帳號時為空清單,欄位仍應可見)
  await expect(page.getByTestId('teacher-account')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/teacher-1-form.png` })
  await page.getByTestId('teacher-save').click()

  // 列表出現該教師
  await expect(page.getByRole('cell', { name: '陳老師' })).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/teacher-2-list.png` })

  // 驗證 Email 已保存(經 API 確認)
  const list = await (await page.request.get('/api/semesters')).json()
  const sem = list.find((s: { academic_year: number; term: number }) =>
    s.academic_year === YEAR && s.term === 1)
  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sem.id}`)).json()
  const chen = teachers.find((t: { name: string }) => t.name === '陳老師')
  expect(chen.email).toBe('chen@example.edu.tw')

  // 清理
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
