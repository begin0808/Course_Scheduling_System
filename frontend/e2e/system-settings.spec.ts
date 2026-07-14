import { expect, test } from '@playwright/test'
import { login } from './helpers'

const SHOTS = 'e2e/screenshots'

/**
 * 系統管理頁的迴歸測試。
 *
 * 這一頁先前**完全沒有 e2e 覆蓋**,於是一個致命 bug 一路上了 v1.0.0 與 v1.1.0:
 * `System.vue` 呼叫 `useDialog()`,但 `App.vue` 沒有掛 `<n-dialog-provider>`——
 * Naive 會在 setup 直接擲錯,整頁渲染不出來(側邊選單還在,內容區一片空白)。
 * 也就是說備份、還原、SMTP、重設精靈這四件事,使用者根本點不進去。
 *
 * 因此本測試的第一個斷言(卡片看得到)就是核心:頁面只要 setup 擲錯就是全白,必紅。
 */
test('系統管理:三張卡片渲染、可立即備份並刪除備份', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page, 'e2e_admin', 'e2eadmin1234')

  await page.goto('/settings/system')
  await expect(page.getByRole('heading', { name: '系統管理' })).toBeVisible()

  // setup 若擲錯(缺 dialog provider),以下三張卡片一張都不會出現
  await expect(page.getByTestId('smtp-status')).toBeVisible()
  await expect(page.getByTestId('backup-card')).toBeVisible()
  await expect(page.getByText('重新啟動設定精靈')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/system-1-page.png` })

  // 立即備份 → 清單多一列(這條路徑會打到 worker-ops 的 pg_dump)
  const rows = page.getByTestId('backup-row')
  const before = await rows.count()
  await page.getByTestId('backup-now').click()
  await expect(page.getByText('已建立備份')).toBeVisible({ timeout: 60_000 })
  await expect(rows).toHaveCount(before + 1)
  await page.screenshot({ path: `${SHOTS}/system-2-backup.png` })

  // 刪除剛才那份,不留垃圾(最新的在最上面)
  await rows.first().getByRole('button', { name: '刪除' }).click()
  await page.getByRole('button', { name: '確定' }).click()
  await expect(page.getByText('已刪除備份')).toBeVisible()
  await expect(rows).toHaveCount(before)
})
