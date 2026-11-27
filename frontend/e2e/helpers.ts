import { randomBytes } from 'node:crypto'
import type { Page } from '@playwright/test'

/**
 * 測試中臨時建立的帳號用隨機密碼(v1.7.1,數發部源碼檢測:程式碼不寫死密碼字串)。
 * 只有 seed_e2e 預先建立的固定測試帳號(下面的 E2E_USER 等)才用固定值。
 */
export function randomPassword(length = 14): string {
  return randomBytes(length).toString('base64url').slice(0, length)
}

// 專用於 e2e 的教學組長帳號(由驗收前置步驟以 docker exec 建立,不刪除)。
export const E2E_USER = 'e2e_scheduler'
export const E2E_PASS = 'e2etest1234'

export async function login(page: Page, user = E2E_USER, pass = E2E_PASS): Promise<void> {
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill(user)
  await page.getByPlaceholder('請輸入密碼').fill(pass)
  await page.getByRole('button', { name: '登入' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
}

/** 刪除指定學年度學期(idempotent),避免測試資料殘留或衝突。 */
export async function deleteSemesterByYearTerm(page: Page, year: number, term: number): Promise<void> {
  const resp = await page.request.get('/api/semesters')
  const list = (await resp.json()) as Array<{ id: number; academic_year: number; term: number }>
  for (const s of list) {
    if (s.academic_year === year && s.term === term) {
      await page.request.delete(`/api/semesters/${s.id}`)
    }
  }
}
