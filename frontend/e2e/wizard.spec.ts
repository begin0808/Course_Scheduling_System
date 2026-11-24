import { expect, test } from '@playwright/test'
import { iso } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 120 // 使用不與既有資料衝突的學年度
const SHOTS = 'e2e/screenshots'

test('設定精靈:五步驟建立學期並於儀表板顯示摘要', async ({ page }) => {
  await login(page)

  // 前置:重設精靈狀態、清掉測試學期(含混合學制用的 121),確保從頭跑且不受干擾
  await page.request.post('/api/wizard/reset')
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await deleteSemesterByYearTerm(page, 121, 1)

  await page.goto('/wizard')
  await expect(page.getByRole('heading', { name: '設定精靈' })).toBeVisible()

  // Step 0:選國中範本
  await page.getByTestId('tpl-junior_high').click()
  await page.screenshot({ path: `${SHOTS}/wizard-1-template.png` })
  await page.getByTestId('wizard-next').click()

  // Step 1:設定學年度(改成 120 避免與既有 115 衝突)與起訖日期 → 建立學期
  const yearInput = page.getByTestId('wizard-year').locator('input')
  await yearInput.fill(String(YEAR))
  await yearInput.press('Enter')

  // 沒填起訖日期不讓過:少了它請假會被擋,而使用者當下看不出哪裡不對(#15)
  await page.getByTestId('wizard-next').click()
  await expect(page.getByText('請填學期起訖日期(請假與調代課需要)')).toBeVisible()

  // 從今天開始:儀表板預設選「今天所在、最新開始」的學期(v1.4.22),
  // 測試資料庫裡其他測試建的學期也涵蓋今天,不從今天開始就不一定選到這一個
  const today = new Date()
  const startInput = page.getByTestId('wizard-start').locator('input')
  await startInput.fill(iso(today))
  await startInput.press('Enter')
  const endInput = page.getByTestId('wizard-end').locator('input')
  await endInput.fill(iso(new Date(today.getFullYear(), today.getMonth() + 5, today.getDate())))
  await endInput.press('Enter')
  await page.screenshot({ path: `${SHOTS}/wizard-2-year.png` })
  await page.getByTestId('wizard-next').click()

  // Step 2:建立學期後進入節次表步驟
  await expect(page.getByText('已依範本帶入預設節次表')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-3-periods.png` })
  await page.getByTestId('wizard-next').click()

  // Step 3:匯入(略過)→ 下一步
  await page.screenshot({ path: `${SHOTS}/wizard-4-import.png` })
  await page.getByTestId('wizard-next').click()

  // Step 4:完成頁應顯示資料摘要
  await expect(page.getByText('初始設定即將完成')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-5-done.png` })
  await page.getByTestId('wizard-finish').click()

  // 完成後導向基礎資料頁
  await expect(page.getByRole('heading', { name: '基礎資料' })).toBeVisible()

  // 儀表板顯示該學期摘要(驗收①)
  await page.goto('/')
  await expect(page.getByText(`${YEAR} 學年度第 1 學期 · 資料摘要`)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wizard-6-dashboard.png` })

  // 清理:移除測試學期
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
