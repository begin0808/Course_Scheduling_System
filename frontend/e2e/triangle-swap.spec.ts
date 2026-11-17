import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { FRI, SEM_END, SEM_START, THU, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 三角調課(v1.4.20,組長:「會出三角調課嗎?」)。
 *
 * 王師週三第一節 701 國文請假;林師週四第二節 701 數學、陳師週五第三節 701 英語。
 * 王師週四第二節有 702 的課(不能和林師互調)、陳師週三第一節有 703 的課(不能來代),
 * 只有三人輪流換得成:林師來上這一節、陳師上林師那節、王師回來上陳師那節。
 */
const YEAR = 184

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

const short = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number)
  const wd = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'][new Date(y, m - 1, d).getDay()]
  return `${m}/${d}(${wd})`
}

test('三角調課:互調湊不出來時列出三人組合,點一下成立,三位老師與班級各有調課單,撤回一起撤', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sid = (await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })).id
  const q = `?semester_id=${sid}`

  try {
    const T: Record<string, number> = {}
    const S: Record<string, number> = {}
    for (const [name, subj] of [['三角王師', '三角國文'], ['三角林師', '三角數學'],
      ['三角陳師', '三角英語']]) {
      S[subj] = (await post(page, `/api/subjects${q}`, { name: subj })).id
      T[name] = (await post(page, `/api/teachers${q}`,
        { name, base_periods: 20, subject_ids: [S[subj]] })).id
    }
    const C: Record<string, number> = {}
    for (const name of ['701', '702', '703']) {
      C[name] = (await post(page, `/api/class-units${q}`,
        { grade: 7, name, track: 'junior_high' })).id
    }
    const periods = (await (await page.request.get(
      `/api/class-units/${C['701']}/period-table`)).json()).periods
      .filter((p: { type: string }) => p.type === 'regular')
    const slot = (weekday: number, idx: number) =>
      periods.filter((p: { weekday: number }) => p.weekday === weekday)[idx].period_no
    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const place = async (t: string, subj: string, kls: string, weekday: number, idx: number) => {
      const a = await post(page, `/api/assignments${q}`, {
        class_id: C[kls], subject_id: S[subj], periods_per_week: 1,
        teachers: [{ teacher_id: T[t] }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday, period_no: slot(weekday, idx), span: 1 })
    }
    await place('三角王師', '三角國文', '701', 3, 0)
    await place('三角林師', '三角數學', '701', 4, 1)
    await place('三角陳師', '三角英語', '701', 5, 2)
    await place('三角王師', '三角國文', '702', 4, 1)
    await place('三角陳師', '三角英語', '703', 3, 0)
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()
    await post(page, `/api/leaves${q}`, {
      teacher_id: T['三角王師'], leave_type: 'personal', start_date: WED, end_date: WED,
    })

    await page.goto('/substitutions')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
    await page.getByTestId('sub-handle').first().click()
    await page.getByTestId('sub-swap').click()
    const panel = page.getByTestId('sub-swap-panel')
    await expect(panel.getByTestId('sub-swap-partner').first()).toBeVisible()
    await expect(panel.getByTestId('sub-swap-option')).toHaveCount(0) // 兩人互調換不成

    // 一、切到三角調課:最早的一組排第一
    await panel.getByTestId('sub-swap-mode-triangle').click()
    const options = panel.getByTestId('sub-tri-option')
    await expect(options).toHaveCount(4)
    const first = options.first()
    await expect(first).toContainText('三角林師 來上這一節')
    await expect(first).toContainText(`三角陳師 上三角林師的 ${short(THU)} 第二節 三角數學`)
    await expect(first).toContainText(`三角王師 上三角陳師的 ${short(FRI)} 第三節 三角英語`)

    // 二、點一下成立;清單寫出三位老師各上哪一節
    await first.click()
    await expect(page.getByText('已三角調課')).toBeVisible()
    const period = page.getByTestId('sub-period').first()
    await expect(period.getByTestId('sub-handler')).toContainText(
      `三角調課 → 三角林師(三角陳師 ${short(THU)} 第二節代三角林師、三角王師 ${short(FRI)} 第三節補課)`)

    // 三、調課單:三位老師各一張、班級一張(三格)
    const [slips] = await Promise.all([
      page.waitForEvent('popup'),
      period.getByTestId('sub-print-slip').click(),
    ])
    await expect(slips.getByTestId('slip-teacher')).toHaveCount(3)
    await expect(slips.getByTestId('slip-class')).toHaveCount(1)
    await slips.close()

    // 四、撤回:三格一起撤,節次回到待處理
    await period.getByTestId('sub-undo').click()
    await expect(page.getByText('已撤回處置')).toBeVisible()
    await expect(period).toContainText('待處理')
    const week = await (await page.request.get(
      `/api/published/week${q}&view=class&target_id=${C['701']}&on=${THU}`)).json()
    const thu = week.cells.filter((c: { date: string; kind: string }) =>
      c.date === THU && c.kind === 'swap')
    expect(thu).toHaveLength(0)
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
