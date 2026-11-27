import { expect, test } from '@playwright/test'
import { login } from './helpers'

/**
 * v1.6.0 沒有「系統預設密碼」了:新增帳號時密碼留空,系統為這個帳號產生隨機初始密碼,
 * 只在畫面上顯示這一次(可複製、下載清單、列印通知單),關閉後查不到。
 * 先前留空一律用同一組寫在公開原始碼裡的預設密碼,知道帳號的人就能搶先登入。
 */
const ADMIN = ['e2e_admin', 'e2eadmin1234'] as const

test('帳號初始密碼:留空由系統產生、只顯示一次,用它登入後要先改密碼', async ({ page }) => {
  const staffUser = `e2e_ip_${Date.now()}`
  await login(page, ...ADMIN)
  try {
    await page.goto('/settings/accounts')
    await page.getByTestId('acc-add').click()
    await page.getByTestId('acc-new-username').locator('input').fill(staffUser)
    await page.getByTestId('acc-new-name').locator('input').fill('初始密碼測試')
    await page.getByTestId('acc-new-save').click()

    const dialog = page.getByTestId('initial-passwords')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('只顯示這一次')
    await expect(dialog.getByTestId('initial-password-row')).toContainText(staffUser)
    const password = (await dialog.getByTestId('initial-password').innerText()).trim()
    expect(password).toMatch(/^[A-Za-z2-9]{12}$/)

    // 下載的清單含帳號與密碼(Excel 可開的 CSV)
    const download = page.waitForEvent('download')
    await dialog.getByTestId('initial-passwords-download').click()
    const file = await download
    expect(file.suggestedFilename()).toBe('帳號初始密碼.csv')
    const csv = await (await file.createReadStream()).toArray()
    const text = Buffer.concat(csv).toString('utf-8')
    expect(text).toContain(staffUser)
    expect(text).toContain(password)

    // 列印通知單(v1.7.1 起印本頁的通知單,不再開新視窗):平常看不到,
    // 切到列印模式時只剩通知單,對話框與後面的畫面都不印
    const slips = page.getByTestId('initial-passwords-slips')
    await expect(slips).toBeHidden()
    await page.evaluate(() => { window.print = () => {} }) // 不叫出真的列印對話框
    await dialog.getByTestId('initial-passwords-print').click()
    await page.emulateMedia({ media: 'print' })
    await expect(slips).toBeVisible()
    await expect(slips).toContainText(staffUser)
    await expect(slips).toContainText(password)
    await expect(dialog).toBeHidden()
    await expect(page.locator('#app')).toBeHidden()
    await page.emulateMedia({ media: 'screen' })
    await expect(slips).toBeHidden()
    await expect(dialog).toBeVisible()

    await dialog.getByTestId('initial-passwords-close').click()
    await expect(dialog).toBeHidden()
    await expect(slips).toHaveCount(0) // 對話框關掉,通知單也從頁面上移除

    // 用這組密碼登入 → 先到改密碼頁
    await page.request.post('/api/auth/logout')
    await page.goto('/login')
    await page.getByPlaceholder('請輸入帳號').fill(staffUser)
    await page.getByPlaceholder('請輸入密碼').fill(password)
    await page.getByRole('button', { name: '登入' }).click()
    await expect(page).toHaveURL(/change-password/)
  } finally {
    await page.request.post('/api/auth/logout')
    await login(page, ...ADMIN)
    const users = await (await page.request.get('/api/users')).json()
    const u = users.find((x: { username: string }) => x.username === staffUser)
    if (u) await page.request.post(`/api/users/${u.id}/active`, { data: { is_active: false } })
  }
})
