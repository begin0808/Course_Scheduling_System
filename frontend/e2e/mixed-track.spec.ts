import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 121 // 專用測試學年度
const SHOTS = 'e2e/screenshots'

// 完全中學情境:同學期兩套節次表,班級可指定所屬節次表。
test('混合學制:班級可指定節次表(≥2 套時出現下拉)', async ({ page }) => {
  await login(page)
  // 標記精靈已完成,避免首登守衛把導覽轉向 /wizard
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置(API):清掉測試學期後,建立含兩套節次表的學期
  await deleteSemesterByYearTerm(page, 120, 1)
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const semResp = await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })
  const sem = await semResp.json()
  await page.request.post(`/api/semesters/${sem.id}/period-tables`, {
    data: { name: '高中部節次表', template_key: 'senior_high' },
  })

  // 進入基礎資料 → 選該學期 → 班級分頁
  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '班級' }).click()

  // 新增班級:節次表下拉應出現(因有 2 套)
  await page.getByTestId('class-add').click()
  await page.getByTestId('class-name').locator('input').fill('高中501')
  const ptSelect = page.getByTestId('class-period-table')
  await expect(ptSelect).toBeVisible()
  await ptSelect.click()
  await page.locator('.n-base-select-option', { hasText: '高中部節次表' }).click()
  await page.screenshot({ path: `${SHOTS}/mixed-1-form.png` })
  await page.getByTestId('class-save').click()

  // 列表應出現該班,且節次表欄顯示「高中部節次表」
  await expect(page.getByRole('cell', { name: '高中501' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '高中部節次表' })).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/mixed-2-list.png` })

  // 清理
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
