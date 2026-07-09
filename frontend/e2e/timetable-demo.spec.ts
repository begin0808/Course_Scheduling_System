import { expect, test } from '@playwright/test'
import { login } from './helpers'

const SHOTS = 'e2e/screenshots'

// M2-2:TimetableGrid 拖拉課表元件示範頁(純前端,不依賴後端資料)。
test('課表元件:拖曳未排課務置入格子,並切換國小/技高兩套節次表', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await page.goto('/scheduling/timetable-demo')
  await expect(page.getByRole('heading', { name: '課表元件示範(TimetableGrid)' })).toBeVisible()

  // 國小 40 分節次表(預設)截圖
  await page.screenshot({ path: `${SHOTS}/timetable-1-elementary.png` })

  // 拖曳「英語」到週四第1節(週四=4, 第1節=1 為一般課空格)
  const tray = page.getByTestId('tray-英語')
  const target = page.locator('[data-weekday="4"][data-period="1"]')
  await tray.dragTo(target)

  // 該格出現英語卡片
  await expect(target.getByText('英語')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/timetable-2-placed.png` })

  // 切到技高 50 分節次表:應見連堂(機械實習,佔 2 節)
  await page.getByTestId('demo-vocational').click()
  await expect(page.getByText('機械實習')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/timetable-3-vocational.png` })
})
