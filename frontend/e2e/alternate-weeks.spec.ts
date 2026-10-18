import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 單雙週課程(v1.3.0)。使用者的例子:
 * 701 週一三、四節(2 連堂)單週生科(甲師)、雙週資科(乙師);702 同一時段反過來。
 *
 * 走一遍組長會做的事:建單雙週組 → 配單週、雙週的課 → 工作台拖一張卡片放進兩堂 →
 * 發布 → 課表查詢看到「單/雙」→ 甲師請假時只列出那一週真的有上的那一班。
 */
const YEAR = 162

const post = async (page: Page, url: string, data: object) => {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} -> ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

async function selectSemester(page: Page) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
}

async function pick(page: Page, testid: string, text: string) {
  await page.getByTestId(testid).click()
  await page.locator('.n-base-select-option', { hasText: text }).last().click()
}

async function dragDrop(page: Page, source: Locator, target: Locator) {
  const dt = await page.evaluateHandle(() => new DataTransfer())
  await source.dispatchEvent('dragstart', { dataTransfer: dt })
  await target.dispatchEvent('dragenter', { dataTransfer: dt })
  await target.dispatchEvent('drop', { dataTransfer: dt })
}

/** 單週/雙週:學期開始那一週是第 1 週(單週),之後輪流。 */
function weekOf(day: string): 'odd' | 'even' {
  const monday = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
  const [sy, sm, sd] = SEM_START.split('-').map(Number)
  const [y, m, d] = day.split('-').map(Number)
  const weeks = Math.round((monday(new Date(y, m - 1, d)).getTime()
    - monday(new Date(sy, sm - 1, sd)).getTime()) / (7 * 86400000))
  return weeks % 2 === 0 ? 'odd' : 'even'
}

test('單雙週:建組、配課、拖放、發布、查詢、請假只列當週的課', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
  })
  const q = `?semester_id=${sem.id}`

  try {
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    const c702 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })).id
    const tech = (await post(page, `/api/subjects${q}`, { name: '單雙生科' })).id
    const info = (await post(page, `/api/subjects${q}`, { name: '單雙資科' })).id
    const jia = (await post(page, `/api/teachers${q}`, { name: '單雙甲師', base_periods: 20 })).id
    const yi = (await post(page, `/api/teachers${q}`, { name: '單雙乙師', base_periods: 20 })).id

    // 一、畫面上建 701 的單雙週組,配單週、雙週的課
    await page.goto('/scheduling/assignments')
    await selectSemester(page)
    await page.getByTestId('alt-add').click()
    await pick(page, 'alt-class', '701')
    await page.getByTestId('alt-save').click()
    const group = page.getByTestId('alt-701 單雙週')
    await expect(group).toBeVisible()

    // 單週:生科、甲師、2 節(2 連堂)
    await group.getByTestId('alt-add-odd').click()
    await pick(page, 'a-subject', '單雙生科')
    await pick(page, 'a-teachers', '單雙甲師')
    await page.keyboard.press('Escape')
    await page.getByTestId('a-periods').locator('input').fill('2')
    await page.getByTestId('a-add-block').click()
    await page.getByTestId('a-save').click()
    await expect(group).toContainText('單週:單雙生科')

    // 雙週:節數與連堂自動帶入單週那筆,只要選科目與老師
    await group.getByTestId('alt-add-even').click()
    await expect(page.getByTestId('a-periods').locator('input')).toHaveValue('2')
    await pick(page, 'a-subject', '單雙資科')
    await pick(page, 'a-teachers', '單雙乙師')
    await page.keyboard.press('Escape')
    await page.getByTestId('a-save').click()
    await expect(group).toContainText('雙週:單雙資科')

    // 702 反過來(用 API 建,節省時間)
    const u702 = await post(page, `/api/alternate-units${q}`, { class_id: c702 })
    for (const [subject, teacher, week] of [[info, yi, 'odd'], [tech, jia, 'even']] as const) {
      await post(page, `/api/assignments${q}`, {
        scheduling_unit_id: u702.id, subject_id: subject, periods_per_week: 2,
        teachers: [{ teacher_id: teacher, is_lead: true }],
        block_rules: [{ block_size: 2, count_per_week: 1 }], week_parity: week,
      })
    }
    // 鐘點:甲師單週 701、雙週 702 各 2 節 → 每週都上 2 節
    await page.reload()
    await selectSemester(page)
    const load = page.getByTestId('teacher-load').locator('tr', { hasText: '單雙甲師' })
    await expect(load).toContainText('2 / 20')

    // 二、工作台:701 的單雙週組合成一張卡片,拖進週一第三節(2 連堂)
    await page.goto('/scheduling/workbench')
    await selectSemester(page)
    const card = page.getByTestId('wb-tray-單雙生科')
    await expect(card).toContainText('單 單雙生科/雙 單雙資科')
    await expect(card).toContainText('2連堂')
    const periods: { weekday: number; name: string; period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
    const third = periods.find((p) => p.weekday === 1 && p.name === '第三節')!.period_no
    const target = page.locator(`[data-weekday="1"][data-period="${third}"]`)
    await dragDrop(page, card, target)
    const lines = target.getByTestId('tg-week')
    await expect(lines).toHaveCount(2)
    await expect(lines.nth(0)).toContainText('單單雙生科')
    await expect(lines.nth(1)).toContainText('雙單雙資科')
    await expect(page.getByTestId('wb-tray-empty')).toBeVisible()

    // 702 那組用 API 放同一格:甲師單週 701、雙週 702,不衝堂
    const tts = await (await page.request.get(`/api/timetables${q}`)).json()
    const ttId = tts[0].id
    const a702 = (await (await page.request.get(`/api/assignments${q}`)).json())
      .find((a: { scheduling_unit: { id: number }; week_parity: string }) =>
        a.scheduling_unit.id === u702.id && a.week_parity === 'odd')
    await post(page, `/api/timetables/${ttId}/entries`,
      { course_assignment_id: a702.id, weekday: 1, period_no: third, span: 2 })
    const check = await (await page.request.get(`/api/timetables/${ttId}/check`)).json()
    expect(check.issues).toEqual([])
    expect((await page.request.post(`/api/timetables/${ttId}/publish`)).ok()).toBeTruthy()

    // 三、課表查詢:甲師的課表同一格單週 701、雙週 702
    await page.goto('/timetable-query')
    await page.getByTestId('tq-view-class').waitFor()
    if (!(await page.locator('.n-tag', { hasText: `${YEAR} 學年度` }).count())) await selectSemester(page)
    await page.getByTestId('tq-view-teacher').click()
    await pick(page, 'tq-teacher', '單雙甲師')
    const tcell = page.locator(`[data-weekday="1"][data-period="${third}"]`).getByTestId('tg-week')
    await expect(tcell).toHaveCount(2)
    await expect(tcell.nth(0)).toContainText('701')
    await expect(tcell.nth(1)).toContainText('702')

    // 四、甲師請假:週一只列出那一週真的有上的那一班
    const monday = (() => {
      const [y, m, d] = WED.split('-').map(Number)
      const dt = new Date(y, m - 1, d - 2)
      return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
    })()
    const leave = await post(page, `/api/leaves${q}`,
      { teacher_id: jia, leave_type: 'sick', start_date: monday, end_date: monday })
    const expected = weekOf(monday) === 'odd' ? '701' : '702'
    expect(leave.affected_periods.map((p: { class_names: string }) => p.class_names))
      .toEqual([expected, expected]) // 2 連堂 → 兩節
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
