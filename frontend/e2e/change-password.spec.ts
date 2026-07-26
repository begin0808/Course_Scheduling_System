import { expect, test } from '@playwright/test'

/**
 * 首次登入強制改密——**每一位新使用者進入系統的第一個畫面**。
 *
 * 為什麼值得一支專屬測試:這一頁只有在「被強制改密」的狀態下進得去(路由守衛會把
 * 非強制狀態的人導回儀表板),先前所有測試都是走 API 改密碼,從沒有人點過這個畫面。
 * 而 v1.1.1 修掉的那隻蟲(系統管理頁整頁渲染失敗)正是這樣溜過兩個版本的——
 * 沒有 e2e 覆蓋的頁面,壞掉時沒有任何人會知道。這一頁若壞了,新使用者連門都進不來。
 *
 * 帳號 e2e_newuser 由 seed_e2e 每次重設回「首次登入」狀態(本測試會把它用掉)。
 */

const USER = 'e2e_newuser'
const OLD_PW = 'e2enewuser1234'
const NEW_PW = 'e2echanged5678'

const SHOTS = 'e2e/screenshots'

test('首次登入:強制改密頁擋住去路、驗證輸入,改完才能進入系統', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill(USER)
  await page.getByPlaceholder('請輸入密碼').fill(OLD_PW)
  await page.getByRole('button', { name: '登入' }).click()

  // ① 登入後被導到改密頁,而且**頁面真的渲染出來**(這是本測試的核心:整頁空白就必紅)
  await page.waitForURL(/change-password/, { timeout: 15_000 })
  await expect(page.getByText('變更密碼')).toBeVisible()
  await expect(page.getByTestId('cp-forced')).toContainText('首次登入')
  await expect(page.getByTestId('cp-submit')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/cp-1-forced.png` })

  // ② 後端也擋(不是只有前端導向):未改密前功能性 API 一律 403
  const blocked = await page.request.get('/api/semesters')
  expect(blocked.status(), '強制改密期間後端就該擋住,不能只靠前端守衛').toBe(403)

  // ③ 想繞過去看別頁?守衛會把人送回來
  await page.goto('/')
  await page.waitForURL(/change-password/, { timeout: 15_000 })

  const oldInput = page.getByTestId('cp-old').locator('input')
  const newInput = page.getByTestId('cp-new').locator('input')
  const confirmInput = page.getByTestId('cp-confirm').locator('input')

  // ④ 新密碼太短 → 前端就擋下,不必等後端。
  //    順帶守住「一次送出只跑一次」:按鈕先前同時掛了 submit 與 @click,每次送出跑兩遍,
  //    在成功路徑上等於送出兩次改密請求,第二次必然回「原密碼錯誤」。
  await oldInput.fill(OLD_PW)
  await newInput.fill('short')
  await confirmInput.fill('short')
  await page.getByTestId('cp-submit').click()
  const tooShort = page.getByText('新密碼至少需 8 個字元')
  await expect(tooShort.first()).toBeVisible()
  expect(await tooShort.count(), '同一次送出不該出現兩則訊息(重複觸發)').toBe(1)

  // ⑤ 兩次輸入不一致(最常見的手誤)。這裡用 Enter 送出,順便確認鍵盤操作也走得通
  await newInput.fill(NEW_PW)
  await confirmInput.fill(`${NEW_PW}x`)
  await confirmInput.press('Enter')
  const mismatch = page.getByText('兩次輸入的新密碼不一致')
  await expect(mismatch.first()).toBeVisible()
  expect(await mismatch.count(), '同一次送出不該出現兩則訊息(重複觸發)').toBe(1)

  // ⑥ 原密碼打錯 → 後端的訊息要真的傳到畫面上(不是籠統的「變更密碼失敗」)
  await oldInput.fill('wrongpassword')
  await confirmInput.fill(NEW_PW)
  await page.getByTestId('cp-submit').click()
  await expect(page.getByText('原密碼錯誤')).toBeVisible()

  // ⑦ 正確填寫 → 改密成功並離開這一頁
  await oldInput.fill(OLD_PW)
  await newInput.fill(NEW_PW)
  await confirmInput.fill(NEW_PW)
  await page.getByTestId('cp-submit').click()
  await expect(page.getByText('密碼已更新')).toBeVisible()
  await expect(page).not.toHaveURL(/change-password/)

  // ⑧ 改完之後 API 就通了(強制狀態確實解除,不是只有畫面跳走)
  await expect.poll(async () => (await page.request.get('/api/semesters')).status())
    .toBe(200)

  // ⑨ 新密碼真的能用,而且不會再被要求改密
  await page.request.post('/api/auth/logout')
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill(USER)
  await page.getByPlaceholder('請輸入密碼').fill(NEW_PW)
  await page.getByRole('button', { name: '登入' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 15_000 })
  await expect(page).not.toHaveURL(/change-password/)
})
