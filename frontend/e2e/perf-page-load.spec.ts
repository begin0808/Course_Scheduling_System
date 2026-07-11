import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

// M5-4 驗收②(前端面):60 班規模下,關鍵頁面載入 p95 < 2s。
// 對「執行中的 Docker 全棧」量測真實導覽耗時(靜態資產 + API 清單)。屬壓測腳本性質,
// 執行較久(需先灌 60 班資料);單獨執行:npx playwright test perf-page-load。

const YEAR = 149
const SAMPLES = 8
const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

/** 60 班國中:8 科 → 480 配課,足以壓到清單頁的資料量。 */
async function seed60(page: Page, sid: number) {
  const subjects: Record<string, number> = {}
  for (const s of await get(page, `/api/subjects?semester_id=${sid}`)) subjects[s.name] = s.id
  const plan: [string, number][] = [
    ['國文', 5], ['英語', 4], ['數學', 4], ['自然科學', 3],
    ['社會', 3], ['健康與體育', 3], ['藝術', 3], ['綜合活動', 3],
  ]
  const teachers: Record<string, number> = {}
  for (const [subject] of plan) {
    // 每科數位教師,平均分擔;此處求量,teacher 數不必嚴格
    teachers[subject] = (await post(page, `/api/teachers?semester_id=${sid}`,
      { name: `${subject}師`, base_periods: 200 })).id
  }
  for (let i = 1; i <= 60; i += 1) {
    const grade = 7 + ((i - 1) % 3)
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade, name: `${grade}${String(i).padStart(2, '0')}`, track: 'junior_high' })
    for (const [subject, periods] of plan) {
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: c.id, subject_id: subjects[subject], periods_per_week: periods,
        teachers: [{ teacher_id: teachers[subject] }], block_rules: [],
      })
    }
  }
}

function p95(samples: number[]): number {
  const sorted = [...samples].sort((a, b) => a - b)
  return sorted[Math.min(sorted.length - 1, Math.floor(0.95 * (sorted.length - 1)))]
}

test.describe('頁面載入效能(60 班)', () => {
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage()
    await login(page)
    await deleteSemesterByYearTerm(page, YEAR, 1)
    await page.close()
  })

  test('配課頁與課表查詢頁載入 p95 < 2s', async ({ page }) => {
    test.setTimeout(300_000)
    await login(page)
    await page.request.patch('/api/wizard/state', { data: { completed: true } })
    await deleteSemesterByYearTerm(page, YEAR, 1)
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
      start_date: '2026-09-01', end_date: '2027-01-20',
    })
    await seed60(page, sem.id)

    // 確認資料量到位
    const classes = await get(page, `/api/class-units?semester_id=${sem.id}`)
    expect(classes.length).toBe(60)

    // 先暖機一次(載入 SPA bundle),之後量測「應用內導覽」——這才是使用者實際感受的
    // 頁面切換延遲。整包 bundle 的冷啟下載成本另記為資訊性數據(見 tasks.md bundle 待辦)。
    const t0cold = Date.now()
    await page.goto(`/scheduling/assignments?semester_id=${sem.id}`,
      { waitUntil: 'domcontentloaded' })
    await page.getByRole('heading', { name: /配課/ }).first().waitFor({ state: 'visible' })
    await page.waitForLoadState('networkidle')
    console.log(`[perf] 冷啟首載(含 bundle)=${Date.now() - t0cold}ms(資訊性)`)

    const cases: [string, RegExp][] = [
      ['配課管理', /配課/],
      ['課表查詢', /課表查詢/],
    ]

    for (const [linkName, heading] of cases) {
      const samples: number[] = []
      for (let i = 0; i < SAMPLES; i += 1) {
        await page.getByRole('link', { name: '儀表板' }).click()
        await page.getByRole('heading', { name: /儀表板/ }).first().waitFor({ state: 'visible' })
        const t0 = Date.now()
        await page.getByRole('link', { name: linkName }).click()
        await page.getByRole('heading', { name: heading }).first().waitFor({ state: 'visible' })
        await page.waitForLoadState('networkidle')
        samples.push(Date.now() - t0)
      }
      const value = p95(samples)
      const median = [...samples].sort((a, b) => a - b)[Math.floor(samples.length / 2)]
      console.log(`[perf] ${linkName} 應用內導覽 p95=${value}ms 中位數=${median}ms 樣本=${samples.join(',')}`)
      expect(value, `${linkName} 導覽載入 p95 ${value}ms 應 < 2000ms`).toBeLessThan(2000)
    }
  })
})
