import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 課表檢查(使用者回報 #40、#41)。
 *
 * 課表排好之後才把那一節設成教師「不可排」:
 *  - 儲存規則當下就提示有哪幾節課落在不可排時段(#41)
 *  - 「版本與發布」可以檢查課表,列出衝突;發布前也會擋下,確認後才發布(#40)
 */
const YEAR = 158

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

async function selectSemester(page: Page) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
}

test('課表檢查:事後設不可排時段會當場提示;檢查課表與發布都列出衝突', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', { academic_year: YEAR, term: 1, template_key: 'junior_high' })
  const q = `?semester_id=${sem.id}`

  try {
    const c = await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })
    const s = await post(page, `/api/subjects${q}`, { name: '檢查國文' })
    const t = await post(page, `/api/teachers${q}`, { name: '檢查王師' })
    const a = await post(page, `/api/assignments${q}`, {
      class_id: c.id, subject_id: s.id, periods_per_week: 1,
      teachers: [{ teacher_id: t.id, is_lead: true }], block_rules: [],
    })
    const tt = await post(page, `/api/timetables${q}`, { name: '草稿A' })
    const periods: { weekday: number; name: string; period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c.id}/period-table`)).json()).periods
    const second = periods.find((p) => p.weekday === 3 && p.name === '第二節')!.period_no
    await post(page, `/api/timetables/${tt.id}/entries`,
      { course_assignment_id: a.id, weekday: 3, period_no: second, span: 1 })

    // 一、課表排滿、沒有衝突 → 檢查通過
    await page.goto('/scheduling/versions')
    await selectSemester(page)
    const row = page.locator('[data-testid="v-row-草稿A"]')
    await row.getByTestId('v-check').click()
    await expect(page.getByTestId('v-check-text')).toContainText('課務已排完(1/1 節),沒有衝突')
    await expect(page.locator('.n-modal')).toBeHidden()

    // 二、到教師的時段規則,把週三第二節設成不可排 → 儲存當下就提示(#41)
    await page.goto('/basedata')
    await selectSemester(page)
    await page.locator('tr', { hasText: '檢查王師' }).getByRole('button', { name: '時段規則' }).click()
    const grid = page.locator('.rule-grid')
    await expect(grid).toBeVisible()
    await grid.locator('tr', { has: page.locator('td.rowhead', { hasText: /^第二節$/ }) })
      .locator('td.cell').nth(2).click() // 第 3 欄 = 週三;點一下 = 不可排
    await page.getByTestId('tr-save').click()
    const warn = page.getByTestId('tr-conflicts')
    await expect(warn).toBeVisible()
    await expect(warn).toContainText('規則已儲存')
    await expect(warn).toContainText('草稿A(草稿)')
    await expect(page.getByTestId('tr-conflict')).toHaveText(['週三第二節 701 檢查國文'])
    await page.getByTestId('tr-close').click()
    await expect(grid).toBeHidden()

    // 三、檢查課表 → 列出衝突(#40);這個視窗只能關閉,不會發布
    await page.goto('/scheduling/versions')
    await selectSemester(page)
    await row.getByTestId('v-check').click()
    await expect(page.getByTestId('v-check-text')).toContainText('有 1 項衝突')
    const issues = page.getByTestId('v-issues')
    await expect(issues).toContainText('教師不可排時段')
    await expect(page.getByTestId('v-issue')).toContainText(['檢查王師'])
    await expect(page.getByTestId('v-force-publish')).toHaveCount(0)
    await page.getByTestId('v-warn-close').click()
    await expect(issues).toBeHidden()

    // 四、發布 → 先列出衝突,確認後才發布
    await row.getByTestId('v-publish').click()
    await expect(issues).toContainText('教師不可排時段')
    await expect(page.getByTestId('v-unplaced')).toHaveCount(0) // 課務有排完,不該出現未排清單
    await expect(page.getByTestId('v-status-草稿A')).toHaveText('草稿')
    await page.getByTestId('v-force-publish').click()
    await expect(page.getByTestId('v-status-草稿A')).toHaveText('已發布')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
