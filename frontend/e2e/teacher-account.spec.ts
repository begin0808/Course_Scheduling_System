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

/**
 * #9:匯入時沒建帳號的老師,事後要能直接補一個。
 * 先前帳號只能在 Excel 匯入時勾選建立,重新匯入同一位老師又會被重複檢查擋下,
 * 於是那位老師永遠拿不到帳號。順便驗 #10 回覆裡答應的「重設密碼」。
 */
test('教師帳號:事後補開登入帳號,可登入;重設密碼後舊密碼失效', async ({ page }) => {
  test.setTimeout(120_000)
  const PW = 'teacherpw1234'
  const NEW_PW = 'teacherpw5678'
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const username = `e2e_late_${Date.now()}`

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '教師' }).click()

  // 先建一位沒有帳號的老師(模擬匯入時沒勾「建立帳號」)
  await page.getByTestId('teacher-add').click()
  await page.getByTestId('teacher-name').locator('input').fill('林老師')
  await page.getByTestId('teacher-save').click()
  await expect(page.getByRole('cell', { name: '林老師' })).toBeVisible()

  // 編輯 → 補開帳號
  await page.getByRole('row', { name: /林老師/ }).getByTestId('teacher-edit').click()
  await page.getByTestId('teacher-new-username').locator('input').fill(username)
  await page.getByTestId('teacher-new-password').locator('input').fill(PW)
  await page.getByTestId('teacher-create-account').click()
  await expect(page.getByText(/已建立帳號/)).toBeVisible()
  // 建好即綁定,畫面改成顯示帳號與重設密碼
  await expect(page.getByTestId('teacher-reset-submit')).toBeVisible()

  const teachers = await (await page.request.get(`/api/teachers?semester_id=${sem.id}`)).json()
  const lin = teachers.find((t: { name: string }) => t.name === '林老師')
  expect(lin.user_id, '補開的帳號要自動綁定這位老師').toBeTruthy()

  // 重設密碼 → 舊密碼失效、新密碼可用
  await page.getByTestId('teacher-reset-password').locator('input').fill(NEW_PW)
  await page.getByTestId('teacher-reset-submit').click()
  await page.getByRole('button', { name: '確定' }).click()
  await expect(page.getByText(/密碼已重設/)).toBeVisible()

  // 以下改用 API 驗證登入(會換掉目前的登入身分,所以放在 UI 操作之後)
  await page.request.post('/api/auth/logout')
  const bad = await page.request.post('/api/auth/login', {
    data: { username, password: PW }, failOnStatusCode: false,
  })
  expect(bad.status(), '重設後舊密碼應該失效').toBe(401)
  const good = await page.request.post('/api/auth/login', {
    data: { username, password: NEW_PW },
  })
  expect(good.ok(), '新密碼應該可以登入').toBeTruthy()
  expect((await good.json()).must_change_password, '重設後對方下次登入須自行改密碼').toBe(true)

  // 清理(換回組長身分)
  await page.request.post('/api/auth/logout')
  await login(page)
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
