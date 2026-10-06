import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 「學期與節次表」的三個視窗(編輯學期、新增節次表、複製到新學期)關不掉:
 * X、Esc、點視窗外都沒反應,只能重新整理(使用者回報)。
 *
 * 原因:視窗原本放在 n-space 裡,和 v-for 產生的學期卡片同一層。n-space 會把每個子節點
 * 包一層沒有 key 的 div,學期清單載入後卡片數量一變,視窗就跟著換位置重掛。
 * **只有正式建置會壞、開發模式正常**,所以單元測試看不出來——這支測試跑的是 Docker 裡的正式建置。
 */
const YEAR = 157

test('學期與節次表:三個視窗都能用 X、Esc、點視窗外關閉', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await page.request.post('/api/semesters', {
    data: {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
      start_date: '2026-08-31', end_date: '2027-01-20',
    },
  })

  try {
    await page.goto('/settings/semesters')
    const card = page.locator('.n-card', { hasText: `${YEAR} 學年度第 1 學期` }).first()
    const modal = page.locator('.n-modal')
    const openers: [string, () => Promise<void>][] = [
      ['編輯學期', () => card.getByTestId('sem-edit').click()],
      ['新增節次表', () => card.getByRole('button', { name: /新增節次表/ }).click()],
      ['複製到新學期', () => card.getByTestId('copy-semester').click()],
    ]
    const closers: [string, () => Promise<void>][] = [
      ['X', () => page.locator('.n-modal .n-base-close').click()],
      ['Esc', () => page.keyboard.press('Escape')],
      ['點視窗外', () => page.mouse.click(15, 500)],
    ]
    for (const [name, open] of openers) {
      for (const [how, close] of closers) {
        await open()
        await expect(modal, `${name} 應該打得開`).toBeVisible()
        await close()
        await expect(modal, `${name} 用「${how}」關不掉`).toBeHidden()
      }
    }
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
