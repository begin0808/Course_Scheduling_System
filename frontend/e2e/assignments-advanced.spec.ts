import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'

/** Naive 的下拉為虛擬捲動,選項可能不在 DOM;filterable 下拉一律先輸入再點選。 */
async function pickFiltered(page: Page, testId: string, text: string) {
  await page.getByTestId(testId).click()
  await page.keyboard.type(text)
  await page.locator('.n-base-select-option', { hasText: text }).first().click()
}
async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 學年度第 1 學期` }).click()
}
async function api(page: Page, url: string, data: object) {
  return (await page.request.post(url, { data })).json()
}

test('配課管理:跑班群組建立、協同教師+連堂、班級超節數警告', async ({ page }) => {
  const YEAR = 127
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await api(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  for (const [grade, name] of [[2, '201'], [2, '202'], [1, '機械一']] as [number, string][]) {
    await api(page, `/api/class-units?semester_id=${sid}`, { grade, name, track: 'junior_high' })
  }
  for (const n of ['陳師', '林師', '超量師']) {
    await api(page, `/api/teachers?semester_id=${sid}`, { name: n })
  }
  for (const n of ['機械實習', '超量科']) {
    await api(page, `/api/subjects?semester_id=${sid}`, { name: n })
  }

  await page.goto('/scheduling/assignments')
  await selectSemester(page, YEAR)

  // ── ① 跑班群組建立(UI)──
  await page.getByTestId('group-add').click()
  await page.getByTestId('group-name').click()
  await page.locator('.n-base-select-option', { hasText: '高二多元選修' }).click()
  await pickFiltered(page, 'group-classes', '2年201')
  await pickFiltered(page, 'group-classes', '2年202')
  await page.keyboard.press('Escape')
  await page.getByTestId('group-save').click()
  const groupCard = page.locator('.n-card').filter({ hasText: '跑班群組' })
  await expect(groupCard).toContainText('高二多元選修')
  await expect(groupCard).toContainText('2年201')
  await expect(groupCard).toContainText('2年202')
  await page.screenshot({ path: `${SHOTS}/adv-1-group.png` })

  // ── ② 協同教師 + 連堂(機械實習:2 位教師、6 節含 3 連堂×2)──
  await page.getByTestId('assignment-add').click()
  await pickFiltered(page, 'a-class', '1年機械一')
  await pickFiltered(page, 'a-subject', '機械實習')
  await page.getByTestId('a-teachers').click()
  await page.keyboard.type('陳師')
  await page.locator('.n-base-select-option', { hasText: '陳師' }).first().click()
  await page.keyboard.type('林師')
  await page.locator('.n-base-select-option', { hasText: '林師' }).first().click()
  await page.keyboard.press('Escape')
  const periods = page.getByTestId('a-periods').locator('input')
  await periods.fill('6')
  await periods.press('Enter')
  await page.getByTestId('a-add-block').click()
  const bs = page.getByTestId('a-block-size-0').locator('input')
  await bs.fill('3')
  await bs.press('Enter')
  const bc = page.getByTestId('a-block-count-0').locator('input')
  await bc.fill('2')
  await bc.press('Enter')
  await page.screenshot({ path: `${SHOTS}/adv-2-coteach-block.png` })
  await page.getByTestId('a-save').click()

  const row = page.locator('tr', { hasText: '機械實習' })
  await expect(row).toContainText('陳師(主教)')
  await expect(row).toContainText('林師')
  await expect(row).toContainText('3連堂×2')

  // ── ③ 班級超節數警告(機械一 可排 35 節,再配 40 節 → 共 46 > 35)──
  await page.getByTestId('assignment-add').click()
  await pickFiltered(page, 'a-class', '1年機械一')
  await pickFiltered(page, 'a-subject', '超量科')
  await page.getByTestId('a-teachers').click()
  await page.keyboard.type('超量師')
  await page.locator('.n-base-select-option', { hasText: '超量師' }).first().click()
  await page.keyboard.press('Escape')
  const p2 = page.getByTestId('a-periods').locator('input')
  await p2.fill('40')
  await p2.press('Enter')
  await page.getByTestId('a-save').click()

  const warn = page.getByTestId('class-warning')
  await expect(warn).toBeVisible()
  await expect(warn).toContainText('配課 46 節')
  await expect(warn).toContainText('可排 35 節')
  await page.screenshot({ path: `${SHOTS}/adv-3-capacity-warning.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

test('批次匯入:配課 Excel 匯入(單班×協同教師×連堂)', async ({ page }) => {
  const YEAR = 128
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await api(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  // 匯入檔(fixtures/assignments_import.xlsx)引用的名稱須先存在
  await api(page, `/api/class-units?semester_id=${sid}`, { grade: 7, name: '701', track: 'junior_high' })
  await api(page, `/api/subjects?semester_id=${sid}`, { name: '機械實習' })
  for (const n of ['陳師', '林師']) {
    await api(page, `/api/teachers?semester_id=${sid}`, { name: n })
  }

  await page.goto('/basedata')
  await selectSemester(page, YEAR)
  await page.locator('.n-tabs-tab', { hasText: '批次匯入' }).click()
  await page.locator('.n-radio-button', { hasText: '配課' }).click()

  const file = fileURLToPath(new URL('./fixtures/assignments_import.xlsx', import.meta.url))
  await page.locator('input[type="file"]').setInputFiles(file)
  await page.getByRole('button', { name: '開始匯入' }).click()

  await expect(page.getByText('成功匯入 1 筆資料。')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/adv-4-import.png` })

  // 經 API 驗證:2 位教師(陳師為主教)+ 3 連堂×2
  const list = await (await page.request.get(`/api/assignments?semester_id=${sid}`)).json()
  expect(list).toHaveLength(1)
  const a = list[0]
  expect(a.subject.name).toBe('機械實習')
  expect(a.periods_per_week).toBe(6)
  expect(a.teachers.map((t: { name: string }) => t.name).sort()).toEqual(['林師', '陳師'])
  expect(a.teachers.find((t: { is_lead: boolean }) => t.is_lead).name).toBe('陳師')
  expect(a.block_rules[0]).toMatchObject({ block_size: 3, count_per_week: 2 })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
