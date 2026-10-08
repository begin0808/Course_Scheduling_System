import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

/**
 * 登入按一次只送一筆請求(使用者回報 #39)。
 *
 * 先前按鈕同時是表單的 submit 又掛了 @click,輸入框也另外掛了 @keyup.enter,按一次送出兩筆:
 * 輸錯密碼一次算兩次失敗,約第 3 次就被鎖定(門檻是連續 5 次)。
 * 用不存在的帳號測,不會動到任何帳號的失敗次數。
 */
async function attempts(page: Page, submit: () => Promise<void>): Promise<number> {
  let count = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/api/auth/login')) count += 1
  })
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill('no-such-user-39')
  await page.getByPlaceholder('請輸入密碼').fill('wrong-password')
  await submit()
  await expect(page.getByText(/帳號或密碼錯誤|登入失敗/).first()).toBeVisible()
  await page.waitForTimeout(500) // 多出來的那一筆若存在,這時也已送出
  return count
}

test('登入:點一次按鈕只送一筆請求', async ({ page }) => {
  expect(await attempts(page, () => page.getByRole('button', { name: '登入' }).click())).toBe(1)
})

test('登入:在密碼欄按 Enter 只送一筆請求', async ({ page }) => {
  expect(await attempts(page, () => page.getByPlaceholder('請輸入密碼').press('Enter'))).toBe(1)
})

test('登入:在帳號欄按 Enter 只送一筆請求', async ({ page }) => {
  expect(await attempts(page, () => page.getByPlaceholder('請輸入帳號').press('Enter'))).toBe(1)
})
