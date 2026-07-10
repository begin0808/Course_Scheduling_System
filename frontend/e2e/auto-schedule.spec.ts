import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 學年度第 1 學期` }).click()
}

/** 12 班國中:規模夠大,solver 需要幾秒收斂,才看得到進度與「提前結束」。 */
async function seedSchool(page: Page, sid: number) {
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const plan: [string, number, number][] = [
    ['國文', 5, 3], ['英語', 4, 3], ['數學', 4, 4], ['自然科學', 3, 2], ['社會', 3, 2],
    ['健康與體育', 3, 2], ['藝術', 3, 3], ['綜合活動', 3, 2], ['科技', 2, 2], ['彈性學習', 3, 2],
  ]
  const teachers: Record<string, number[]> = {}
  for (const [subject, , count] of plan) {
    teachers[subject] = []
    for (let i = 0; i < count; i += 1) {
      const t = await post(page, `/api/teachers?semester_id=${sid}`,
        { name: `${subject}師${i + 1}`, base_periods: 20 })
      teachers[subject].push(t.id)
    }
  }
  const classes: number[] = []
  for (let i = 1; i <= 12; i += 1) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name: `70${i}`, track: 'junior_high' })
    classes.push(c.id)
  }
  for (const [subject, periods, count] of plan) {
    for (const [idx, cid] of classes.entries()) {
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: cid, subject_id: subjects[subject], periods_per_week: periods,
        teachers: [{ teacher_id: teachers[subject][idx % count] }], block_rules: [],
      })
    }
  }
}

// ── M3-4 驗收①:啟動 → 進度 → 提前結束 → 結果草稿 + 達成度報告 ──
test('自動排課:顯示進度,提前結束取當前最佳解並產生新草稿', async ({ page }) => {
  test.setTimeout(180_000)
  const YEAR = 134
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters',
    { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  await seedSchool(page, sem.id)
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)

  // pre-flight 通過才會讓人按下去
  await expect(page.getByText('資料檢查通過,可以開始排課')).toBeVisible()
  await expect(page.getByText('12 班')).toBeVisible()

  await page.getByTestId('as-start').click()
  await expect(page.getByTestId('as-job')).toBeVisible()

  // 進度確實在跑:找到至少一個解之後「提前結束」才可按
  await expect(page.getByTestId('as-stop')).toBeEnabled({ timeout: 60_000 })
  await expect(page.getByTestId('as-solutions')).not.toHaveText('已找到 0 個解')
  await page.screenshot({ path: `${SHOTS}/auto-1-progress.png` })

  await page.getByTestId('as-stop').click()
  await expect(page.getByTestId('as-status')).toHaveText('已完成', { timeout: 60_000 })
  await expect(page.getByTestId('as-done')).toContainText('草稿A 自排結果')

  // 軟約束達成度報告(人話明細)
  const report = page.getByTestId('as-report')
  await expect(report).toBeVisible()
  await expect(report).toContainText('同班同科目分散於不同日')
  await expect(report).toContainText('主科優先排上午')
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${SHOTS}/auto-2-report.png` })

  // 結果寫成新草稿(396 節),來源草稿完全沒動
  const tts = await (await page.request.get(`/api/timetables?semester_id=${sem.id}`)).json()
  const source = tts.find((t: { name: string }) => t.name === '草稿A')
  const result = tts.find((t: { name: string }) => t.name === '草稿A 自排結果')
  expect(source.entry_count).toBe(0)
  expect(result.entry_count).toBe(396)
  expect(result.status).toBe('draft')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── 驗收③:pre-flight 擋下 + 失敗時有明確訊息(而非永遠轉圈)──
test('自動排課:資料未通過前置檢查時擋下,並列出待修正項目', async ({ page }) => {
  const YEAR = 135
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters',
    { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  const c = await post(page, `/api/class-units?semester_id=${sem.id}`,
    { grade: 3, name: '301', track: 'junior_high' })
  const s = await post(page, `/api/subjects?semester_id=${sem.id}`, { name: '國文X' })
  const t = await post(page, `/api/teachers?semester_id=${sem.id}`,
    { name: '王師', base_periods: 20 })
  await post(page, `/api/assignments?semester_id=${sem.id}`, { // 40 節 > 35 可排節次
    class_id: c.id, subject_id: s.id, periods_per_week: 40,
    teachers: [{ teacher_id: t.id }], block_rules: [],
  })
  await post(page, `/api/timetables?semester_id=${sem.id}`, { name: '草稿A' })

  await page.goto('/scheduling/auto')
  await selectSemester(page, YEAR)

  await expect(page.getByTestId('pf-issue').first()).toContainText('超過可排節次')
  await page.getByTestId('as-start').click()

  await expect(page.getByTestId('as-blocking').first()).toContainText('301')
  await expect(page.getByTestId('as-job')).toHaveCount(0) // 沒有進度卡 = 沒有丟給 worker
  await page.screenshot({ path: `${SHOTS}/auto-3-blocked.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
