import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 寒暑假輔導(v1.4.22,組長許願)。
 *
 * 從第 2 學期「複製到新學期」選「暑期輔導」:同一學年度、年級不進位、日期要自己填;
 * 日期和第 2 學期重疊會被擋。輔導學期的配課不比基本鐘點、不算超鐘點,只列每週節數。
 * 日期放在很遠的未來,不和其他測試的學期重疊。
 */
const YEAR = 186
const SRC_START = '2097-02-11'
const SRC_END = '2097-06-30'

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

const setDate = async (page: Page, testId: string, value: string) => {
  const input = page.getByTestId(testId).locator('input')
  await input.fill(value)
  await input.press('Enter')
}

test('寒暑假輔導:複製成暑期輔導、日期不能重疊、配課只列節數不算超鐘點', async ({ page }) => {
  test.setTimeout(90_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 2)
  await deleteSemesterByYearTerm(page, YEAR, 4)
  const src = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 2, template_key: 'junior_high',
    start_date: SRC_START, end_date: SRC_END,
  })

  try {
    const q = `?semester_id=${src.id}`
    const subj = (await post(page, `/api/subjects${q}`, { name: '輔導數學' })).id
    await post(page, `/api/teachers${q}`, { name: '輔導王師', base_periods: 2, subject_ids: [subj] })
    await post(page, `/api/class-units${q}`, { grade: 9, name: '901', track: 'junior_high' })

    await page.goto('/settings/semesters')
    const card = page.locator('.n-card').filter({ hasText: `${YEAR} 學年度第 2 學期` })
    await card.getByTestId('copy-semester').first().click()

    await page.getByTestId('copy-term').click()
    await page.locator('.n-base-select-option', { hasText: '暑期輔導' }).click()
    await expect(page.getByTestId('copy-tutoring-hint')).toBeVisible()
    // 同一學年度、日期清空讓組長照校曆填
    await expect(page.getByTestId('copy-start').locator('input')).toHaveValue('')
    await expect(page.getByTestId('copy-confirm')).toBeDisabled()

    // 和第 2 學期重疊 → 擋下並寫出撞到哪一個學期
    await setDate(page, 'copy-start', '2097-06-20')
    await setDate(page, 'copy-end', '2097-07-20')
    await page.getByTestId('copy-confirm').click()
    await expect(page.getByText(`日期和「${YEAR} 學年度第 2 學期」`)).toBeVisible()

    await setDate(page, 'copy-start', '2097-07-05')
    await page.getByTestId('copy-confirm').click()
    await expect(page.getByText(`${YEAR} 學年度暑期輔導`).first()).toBeVisible()

    const list = await (await page.request.get('/api/semesters')).json()
    const tut = list.find((s: { academic_year: number; term: number }) =>
      s.academic_year === YEAR && s.term === 4)
    expect(tut.is_tutoring).toBe(true)
    expect(tut.start_date).toBe('2097-07-05')

    // 輔導王師基本鐘點 2 節,輔導配 6 節:不顯示超鐘點,只列節數
    const tq = `?semester_id=${tut.id}`
    const teacher = (await (await page.request.get(`/api/teachers${tq}`)).json())[0]
    const klass = (await (await page.request.get(`/api/class-units${tq}`)).json())[0]
    const subject = (await (await page.request.get(`/api/subjects${tq}`)).json())
      .find((s: { name: string }) => s.name === '輔導數學')
    await post(page, `/api/assignments${tq}`, {
      class_id: klass.id, subject_id: subject.id, periods_per_week: 6,
      teachers: [{ teacher_id: teacher.id }], block_rules: [],
    })

    await page.goto('/scheduling/assignments')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度暑期輔導` }).click()
    const load = page.getByTestId('teacher-load')
    await expect(load).toContainText('教師輔導節數')
    await expect(page.getByTestId('teacher-load-tutoring')).toContainText('輔導王師')
    await expect(page.getByTestId('teacher-load-tutoring')).toContainText('6')
    await expect(load).not.toContainText('+4')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 4)
    await deleteSemesterByYearTerm(page, YEAR, 2)
  }
})
