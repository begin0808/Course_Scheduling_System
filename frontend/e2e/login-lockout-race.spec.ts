import { expect, test } from '@playwright/test'
import { login } from './helpers'

/**
 * 同時送出的錯誤密碼也要算進鎖定次數(#60,v1.4.7)。
 *
 * 先前失敗次數是「讀出來、加 1、寫回去」,同一瞬間送出的請求讀到同一個舊數字、互相蓋掉:
 * 同時送 20 次錯誤密碼只記到 2 次,帳號不會被鎖。這要真的 PostgreSQL 與並行請求才測得出來,
 * 單元測試的 SQLite 做不到,故放在 e2e(對 Docker 全棧)。
 */
const ADMIN = ['e2e_admin', 'e2eadmin1234'] as const
const PARALLEL = 20

test('同時送 20 次錯誤密碼:第 5 次就鎖定,其餘都回「已鎖定」,連正確密碼也進不去', async ({ page, playwright }) => {
  test.setTimeout(90_000)
  const username = `e2e_lock_${Date.now()}`
  const password = 'lockrace1234'
  await login(page, ...ADMIN)
  const created = await page.request.post('/api/users', {
    data: { username, password, display_name: '鎖定測試', roles: ['director'] },
  })
  expect(created.status(), await created.text()).toBe(201)
  const userId = (await created.json()).id

  const api = await playwright.request.newContext({ baseURL: test.info().project.use.baseURL })
  try {
    const statuses = await Promise.all(Array.from({ length: PARALLEL }, () =>
      api.post('/api/auth/login', { data: { username, password: 'wrong-password' } })
        .then((r) => r.status())))
    const count = (code: number) => statuses.filter((s) => s === code).length
    // 每一次都要算到:前 4 次「帳號或密碼錯誤」,第 5 次起「已鎖定」
    expect({ 401: count(401), 423: count(423) }).toEqual({ 401: 4, 423: PARALLEL - 4 })

    // 鎖定期間,正確密碼也進不去
    const ok = await api.post('/api/auth/login', { data: { username, password } })
    expect(ok.status()).toBe(423)
  } finally {
    await api.dispose()
    await page.request.post(`/api/users/${userId}/active`, { data: { is_active: false } })
  }
})
