import type { Page } from '@playwright/test'

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
