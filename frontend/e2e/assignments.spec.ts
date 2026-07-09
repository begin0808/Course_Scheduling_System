import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 125 // 專用測試學年度
const SHOTS = 'e2e/screenshots'

// M2-1:單班配課 + 教師鐘點即時統計(超鐘點紅字)。
test('配課管理:建立單班配課並顯示教師超鐘點', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置(API):建學期(國中範本含節次表)+ 班級、科目、教師(基本鐘點 2)
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const sid = sem.id
  await page.request.post(`/api/class-units?semester_id=${sid}`, {
    data: { grade: 3, name: '301', track: 'junior_high' },
  })
  await page.request.post(`/api/subjects?semester_id=${sid}`, { data: { name: '配課測試科' } })
  await page.request.post(`/api/teachers?semester_id=${sid}`, {
    data: { name: '王師', base_periods: 2 },
  })

  // 進入配課管理 → 選學期
  await page.goto('/scheduling/assignments')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

  // 新增配課:301 班 × 國文 × 王師 × 每週 5 節(> 基本鐘點 2 → 超鐘點)
  await page.getByTestId('assignment-add').click()
  await page.getByTestId('a-class').click()
  await page.locator('.n-base-select-option', { hasText: '3年301' }).click()
  await page.getByTestId('a-subject').click()
  await page.keyboard.type('配課測試科') // 篩選(科目清單經虛擬捲動,直接輸入定位)
  await page.locator('.n-base-select-option', { hasText: '配課測試科' }).click()
  await page.getByTestId('a-teachers').click()
  await page.locator('.n-base-select-option', { hasText: '王師' }).click()
  await page.keyboard.press('Escape')
  await page.getByTestId('a-periods').locator('input').fill('5')
  await page.getByTestId('a-periods').locator('input').press('Enter')
  await page.screenshot({ path: `${SHOTS}/assignment-1-form.png` })
  await page.getByTestId('a-save').click()

  // 配課清單出現該筆
  await expect(page.getByRole('cell', { name: '配課測試科' })).toBeVisible()
  // 側欄教師鐘點顯示超鐘點(已配 5 > 應授 2 → +3)
  const loadPanel = page.getByTestId('teacher-load')
  await expect(loadPanel.getByText('王師')).toBeVisible()
  await expect(loadPanel.getByText('+3 超鐘點')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/assignment-2-load.png` })

  // 清理
  await deleteSemesterByYearTerm(page, YEAR, 1)
})
