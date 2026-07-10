import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'

// ── M3-3:科目可標記為「主科」(排課引擎 S5 會盡量排上午)──
test('科目管理:勾選主科後清單顯示標籤,重新載入仍保留', async ({ page }) => {
  const YEAR = 133
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1 },
  })).json()

  await page.goto('/basedata')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '科目' }).click()

  // 新增一般科目(不勾主科)
  await page.getByRole('button', { name: '新增科目' }).click()
  await page.getByTestId('sub-name').locator('input').fill('美術')
  await page.getByTestId('sub-save').click()
  await expect(page.getByText('已儲存')).toBeVisible()

  // 新增主科
  await page.getByRole('button', { name: '新增科目' }).click()
  await page.getByTestId('sub-name').locator('input').fill('國文')
  await page.getByTestId('sub-is-major').click()
  await page.getByTestId('sub-save').click()

  await expect(page.getByTestId('sub-major-國文')).toHaveText('主科')
  await expect(page.getByTestId('sub-major-美術')).toHaveCount(0)
  await page.waitForTimeout(350) // 等 modal 淡出完成,截圖才清楚
  await page.screenshot({ path: `${SHOTS}/major-1-list.png` })

  // 重新載入後仍保留(確認真的寫進 DB,不是前端狀態)
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await page.locator('.n-tabs-tab', { hasText: '科目' }).click()
  await expect(page.getByTestId('sub-major-國文')).toBeVisible()

  const subjects = await (await page.request.get(`/api/subjects?semester_id=${sem.id}`)).json()
  expect(subjects.find((s: { name: string }) => s.name === '國文').is_major).toBe(true)
  expect(subjects.find((s: { name: string }) => s.name === '美術').is_major).toBe(false)

  // 軟約束設定端點:預設值 + 關閉 S2
  const cfg = await (await page.request.get(`/api/solver/config?semester_id=${sem.id}`)).json()
  expect(cfg.weights.S2).toBe(8)
  expect(cfg.weight_names.S5).toBe('主科優先排上午')

  const saved = await (await page.request.put(`/api/solver/config?semester_id=${sem.id}`, {
    data: { daily_subject_cap: 2, teacher_daily_max: 6, teacher_consecutive_max: 3,
      weights: { S2: 0 } },
  })).json()
  expect(saved.weights.S2).toBe(0)
  expect(saved.weights.S5).toBe(4)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
