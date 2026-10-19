import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 帳號管理(v1.3.1):教學組長、教務主任的帳號在這裡設定。
 * 先前畫面上無處可設,填了「行政職稱」登入後仍是教師(使用者來信詢問)。
 *
 * 最常見的情況:組長本身也是教師,已經有教師帳號——管理員把同一個帳號加上「教學組長」,
 * 他登入後就看得到排課選單,也仍然是教師。
 */
const YEAR = 164
const ADMIN = ['e2e_admin', 'e2eadmin1234'] as const

test('帳號管理:教師帳號加上教學組長後看得到排課選單;新增行政帳號;視窗關得掉', async ({ page }) => {
  test.setTimeout(120_000)
  const stamp = Date.now()
  const teacherUser = `e2e_t_${stamp}`
  const staffUser = `e2e_s_${stamp}`

  // 準備:一位已有教師帳號的老師(用組長身分建立)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const t = await (await page.request.post(`/api/teachers?semester_id=${sem.id}`,
    { data: { name: '帳號王老師' } })).json()
  const acc = await page.request.post(`/api/teachers/${t.id}/account`,
    { data: { username: teacherUser, password: 'teacherpw1234' } })
  expect(acc.ok()).toBeTruthy()

  try {
    // 組長看不到帳號管理
    await page.goto('/settings/accounts')
    await expect(page).not.toHaveURL(/accounts/)

    // 一、管理員:在「全部帳號」找到這位老師,設定身分 → 教學組長
    await page.request.post('/api/auth/logout')
    await login(page, ...ADMIN)
    await page.goto('/settings/accounts')
    await expect(page.locator('.n-menu-item', { hasText: '帳號管理' })).toBeVisible()
    await expect(page.getByTestId(`acc-row-${teacherUser}`)).toHaveCount(0) // 預設只列行政帳號
    await page.getByTestId('acc-scope').getByText('全部帳號').click()
    await page.getByTestId('acc-search').locator('input').fill('帳號王老師')
    const row = page.getByTestId(`acc-row-${teacherUser}`)
    await expect(row).toContainText('教師')
    await expect(row).toContainText('帳號王老師')
    await row.getByTestId('acc-roles').click()
    const modal = page.locator('.n-modal')
    await expect(modal).toContainText('「教師」身分會保留')
    // 先確認視窗用 X 關得掉,再重新打開設定
    await page.locator('.n-modal .n-base-close').click()
    await expect(modal).toBeHidden()
    await row.getByTestId('acc-roles').click()
    await page.getByTestId('acc-edit-roles').getByText('教學組長').click()
    await page.getByTestId('acc-edit-save').click()
    await expect(page.getByText(/已更新/)).toBeVisible()
    await expect(modal).toBeHidden()
    await expect(row).toContainText('教學組長')
    await expect(row).toContainText('教師')

    // 二、新增一個教務主任帳號
    await page.getByTestId('acc-add').click()
    await page.getByTestId('acc-new-username').locator('input').fill(staffUser)
    await page.getByTestId('acc-new-name').locator('input').fill('林主任')
    await page.getByTestId('acc-new-password').locator('input').fill('staffpw1234')
    await page.getByTestId('acc-new-roles').getByText('教學組長').click() // 取消預設勾選
    await page.getByTestId('acc-new-roles').getByText('教務主任').click()
    await page.getByTestId('acc-new-save').click()
    await expect(page.getByText(/已建立「林主任」的帳號/)).toBeVisible()
    await expect(page.locator('.n-modal')).toBeHidden()
    await page.getByTestId('acc-search').locator('input').fill('')
    await page.getByTestId('acc-scope').getByText('行政帳號').click()
    const staffRow = page.getByTestId(`acc-row-${staffUser}`)
    await expect(staffRow).toContainText('教務主任')
    await expect(staffRow).toContainText('待改密碼')

    // 三、那位老師登入:改完密碼後看得到排課選單,也仍可查自己的課表
    await page.request.post('/api/auth/logout')
    await page.goto('/login')
    await page.getByPlaceholder('請輸入帳號').fill(teacherUser)
    await page.getByPlaceholder('請輸入密碼').fill('teacherpw1234')
    await page.getByRole('button', { name: '登入' }).click()
    await expect(page).toHaveURL(/change-password/)
    const pw = page.locator('input[type="password"]')
    await pw.nth(0).fill('teacherpw1234')
    await pw.nth(1).fill('teacherpw5678')
    await pw.nth(2).fill('teacherpw5678')
    await page.getByTestId('cp-submit').click()
    await expect(page).not.toHaveURL(/change-password/)
    await page.goto('/scheduling/assignments')
    await expect(page).toHaveURL(/scheduling\/assignments/)
    await expect(page.locator('.n-menu-item', { hasText: '配課管理' })).toBeVisible()
    await expect(page.locator('.n-menu-item', { hasText: '帳號管理' })).toHaveCount(0)
  } finally {
    await page.request.post('/api/auth/logout')
    await login(page, ...ADMIN)
    // 測試帳號停用(不留可登入的帳號),學期刪除
    const users = await (await page.request.get('/api/users')).json()
    for (const u of users.filter((x: { username: string }) => [teacherUser, staffUser].includes(x.username))) {
      await page.request.post(`/api/users/${u.id}/active`, { data: { is_active: false } })
    }
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
