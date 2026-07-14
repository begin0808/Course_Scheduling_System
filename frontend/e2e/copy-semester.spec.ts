import { expect, test } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SRC = 122
const DST = 123
const SHOTS = 'e2e/screenshots'

// 來源學期的起訖日;複製時應自動往後推半年帶入預設值(M6-4)
const SRC_START = '2026-09-01'
const SRC_END = '2027-01-20'
const EXPECT_START = '2027-03-01'  // +6 個月
const EXPECT_END = '2027-07-20'

test('開新學期:複製到新學期,帶起訖日與排課偏好設定', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // 前置:清掉測試學期,建立來源學期(國中範本 → 含節次表+科目)
  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
  const src = await (await page.request.post('/api/semesters', {
    data: {
      academic_year: SRC, term: 1, template_key: 'junior_high',
      start_date: SRC_START, end_date: SRC_END,
    },
  })).json()

  // 來源學期調過排課偏好(每日同科上限 3、S2 權重 40)——這些不該在新學期悄悄回到預設值
  await page.request.put(`/api/solver/config?semester_id=${src.id}`, {
    data: { daily_subject_cap: 3, weights: { S2: 40 } },
  })

  await page.goto('/settings/semesters')
  const srcCard = page.locator('.n-card').filter({ hasText: `${SRC} 學年度第 1 學期` })
  await srcCard.getByTestId('copy-semester').first().click()

  // 對話框:目標學年度預設 +1;起訖日預設為來源往後推半年(組長只要確認校曆再改)
  const start = page.getByTestId('copy-start').locator('input')
  const end = page.getByTestId('copy-end').locator('input')
  await expect(start).toHaveValue(EXPECT_START)
  await expect(end).toHaveValue(EXPECT_END)
  await page.screenshot({ path: `${SHOTS}/copy-1-dialog.png` })

  await page.getByTestId('copy-confirm').click()

  // 新學期出現於清單
  await expect(page.getByText(`${DST} 學年度第 1 學期`)).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/copy-2-list.png` })

  const list = await (await page.request.get('/api/semesters')).json()
  const dst = list.find((s: { academic_year: number; term: number }) =>
    s.academic_year === DST && s.term === 1)

  // 起訖日確實寫進新學期(漏了它,請假展開與今日看板的判定會整個失準)
  expect(dst.start_date).toBe(EXPECT_START)
  expect(dst.end_date).toBe(EXPECT_END)

  // 排課偏好跟著走(先前會悄悄回到預設值,上學期調好的設定就白調了)
  const cfg = await (await page.request.get(
    `/api/solver/config?semester_id=${dst.id}`)).json()
  expect(cfg.daily_subject_cap).toBe(3)
  expect(cfg.weights.S2).toBe(40)

  const subjects = await (await page.request.get(`/api/subjects?semester_id=${dst.id}`)).json()
  expect(subjects.length).toBeGreaterThan(0)

  await deleteSemesterByYearTerm(page, SRC, 1)
  await deleteSemesterByYearTerm(page, DST, 1)
})
