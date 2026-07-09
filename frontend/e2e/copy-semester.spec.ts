import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SRC = 122
const DST = 123
const SHOTS = 'e2e/screenshots'

test('開新學期:從既有學期複製到新學期', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置:清掉測試學期,建立來源學期(國中範本 → 含節次表+科目)
  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
  await page.request.post('/api/semesters', {
    data: { academic_year: SRC, term: 1, template_key: 'junior_high' },
  })

  await page.goto('/settings/semesters')
  const srcCard = page.locator('.n-card').filter({ hasText: `${SRC} 學年度第 1 學期` })
  await srcCard.getByTestId('copy-semester').first().click()

  // 對話框:目標學年度預設為來源+1(123),直接建立
  await page.screenshot({ path: `${SHOTS}/copy-1-dialog.png` })
  await page.getByTestId('copy-confirm').click()

  // 新學期出現於清單
  await expect(page.getByText(`${DST} 學年度第 1 學期`)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/copy-2-list.png` })

  // 驗證複製結果:新學期含科目(經 API 確認)
  const list = await (await page.request.get('/api/semesters')).json()
  const dst = list.find((s: { academic_year: number; term: number }) =>
    s.academic_year === DST && s.term === 1)
  const subjects = await (await page.request.get(`/api/subjects?semester_id=${dst.id}`)).json()
  expect(subjects.length).toBeGreaterThan(0)

  // 清理
  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
})
