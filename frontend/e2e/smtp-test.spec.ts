import { expect, test } from '@playwright/test'
import { login } from './helpers'

/**
 * 寄測試信(v1.5.1):手冊一直寫「可按『寄測試信』當場驗證」,但畫面上其實沒有這顆按鈕。
 * v1.5.0 起寄信會驗證郵件伺服器憑證,自簽憑證的學校需要一個當場確認的方法。
 *
 * e2e 環境沒有郵件伺服器:把主機設成保留的 .invalid 網域(一定查不到),
 * 驗證「改了沒儲存不能按 → 儲存後能按 → 失敗時寫出原因」,測完把設定還原。
 */
test('寄測試信:設定改了要先儲存;寄送失敗時寫出原因', async ({ page }) => {
  await login(page, 'e2e_admin', 'e2eadmin1234')
  const original = await page.request.get('/api/settings/smtp').then((r) => r.json())

  try {
    // 等頁面讀完已存的 SMTP 設定再填,否則讀回來的值會蓋掉剛填的
    const loaded = page.waitForResponse((r) => r.url().endsWith('/api/settings/smtp')
      && r.request().method() === 'GET')
    await page.goto('/settings/system')
    await loaded
    const card = page.getByTestId('smtp-card')
    await card.getByTestId('smtp-host').locator('input').fill('smtp.e2e-test.invalid')
    await card.getByTestId('smtp-sender').locator('input').fill('noreply@example.edu.tw')
    await card.getByTestId('smtp-test-to').locator('input').fill('teacher@example.edu.tw')
    await expect(card.getByTestId('smtp-test')).toBeDisabled()

    await card.getByTestId('smtp-save').click()
    await expect(page.getByText('已儲存 SMTP 設定')).toBeVisible()
    await expect(card.getByTestId('smtp-test')).toBeEnabled()

    // 改了連接埠還沒儲存 → 不能按(會測到舊設定);改回原值就恢復
    const port = card.getByTestId('smtp-port').locator('input')
    const saved = await port.inputValue()
    await port.fill('2525')
    await expect(card.getByTestId('smtp-test-dirty')).toBeVisible()
    await expect(card.getByTestId('smtp-test')).toBeDisabled()
    await port.fill(saved)
    await expect(card.getByTestId('smtp-test-dirty')).toBeHidden()

    await card.getByTestId('smtp-test').click()
    const result = card.getByTestId('smtp-test-result')
    await expect(result).toContainText('找不到郵件主機「smtp.e2e-test.invalid」', { timeout: 30_000 })
    await expect(result).toContainText('原始訊息')
    await card.screenshot({ path: 'e2e/screenshots/smtp-test.png' })
  } finally {
    // 還原成測試前的 SMTP 設定(密碼留空 = 不變更)
    await page.request.put('/api/settings/smtp', {
      data: {
        host: original.host, port: original.port, user: original.user, password: '',
        sender: original.sender,
      },
    })
  }
})
