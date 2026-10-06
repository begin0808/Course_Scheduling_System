import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 巡堂表(v1.2.12):調代課之後,原本的巡堂表會指向錯的老師。
 * 從「今日調代課看板」印出當天真正的樣子——代課老師與備註由系統帶出;
 * 社團這種大型跑班群組另出分組巡堂單。
 */
const YEAR = 156

const post = async (p: Page, url: string, data: object) => {
  const r = await p.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('巡堂表:看板開啟列印頁,代課與社團分組單都正確帶出', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 失敗時也要清掉測試學期:殘留的學期會讓後面的設定精靈、教師端測試看到非預期的畫面
  try {
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
  })
  const q = `?semester_id=${sem.id}`
  const subjects: { id: number; name: string }[] = await (await page.request.get(`/api/subjects${q}`)).json()
  const chinese = subjects.find((s) => s.name === '國文')!.id
  const teacher = async (name: string, subject: number) =>
    (await post(page, `/api/teachers${q}`, { name, subject_ids: [subject] })).id as number
  const wang = await teacher('王老師', chinese)
  const chen = await teacher('陳老師', chinese)
  const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
  const c702 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })).id
  const periods: { weekday: number; name: string; period_no: number }[] =
    (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
  const pno = (name: string) => periods.find((p) => p.weekday === 3 && p.name === name)!.period_no

  const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
  const place = (assignment: number, name: string) => post(page, `/api/timetables/${tt}/entries`,
    { course_assignment_id: assignment, weekday: 3, period_no: pno(name), span: 1 })

  // 王老師週三第一節 701 國文
  const a = await post(page, `/api/assignments${q}`, {
    class_id: c701, subject_id: chinese, periods_per_week: 1, teachers: [{ teacher_id: wang }], block_rules: [],
  })
  await place(a.id, '第一節')

  // 社團:兩班一個跑班群組、四個社團,週三第六節
  const room = (await post(page, `/api/rooms${q}`, { name: '體育館' })).id
  const unit = (await post(page, `/api/scheduling-units${q}`, { name: '社團', class_ids: [c701, c702] })).id
  const clubs = ['羽球社', '桌球社', '棒球社', '漫畫社']
  let first = 0
  for (const [i, name] of clubs.entries()) {
    const subject = (await post(page, `/api/subjects${q}`, { name })).id
    const club = await post(page, `/api/assignments${q}`, {
      scheduling_unit_id: unit, subject_id: subject, periods_per_week: 1,
      teachers: [{ teacher_id: await teacher(`社團師${i + 1}`, subject) }], block_rules: [],
      room_id: i === 0 ? room : null,
    })
    if (i === 0) first = club.id
  }
  await place(first, '第六節')     // 群組內的課會一起排進同一時段
  expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()

  // 王老師週三請假,陳老師代課
  const leave = await post(page, `/api/leaves${q}`,
    { teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED })
  const sub = await page.request.put(`/api/affected-periods/${leave.affected_periods[0].id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: chen } })
  expect(sub.ok()).toBeTruthy()

  // 從看板開啟(新分頁)
  await page.goto(`/daily-board?semester_id=${sem.id}&date=${WED}`)
  const [sheet] = await Promise.all([
    page.waitForEvent('popup'),
    page.getByTestId('board-patrol').click(),
  ])
  await expect(sheet.getByTestId('patrol-page')).toHaveCount(2, { timeout: 20_000 })   // 上午、下午

  const morning = sheet.getByTestId('patrol-page').first()
  await expect(morning).toContainText('巡堂紀錄')
  await expect(morning).toContainText('第 1~4 節')
  await expect(morning.getByTestId('patrol-class')).toHaveText(['701', '702'])
  // 701 第一節:代課的陳老師,備註「代課」;請假的王老師不在表上
  const cell = morning.getByTestId('patrol-cell').first()
  await expect(cell).toContainText('國文')
  await expect(cell).toContainText('陳老師')
  await expect(morning).not.toContainText('王老師')
  await expect(morning.getByTestId('patrol-note').first()).toHaveText('代課')
  await expect(morning.getByTestId('patrol-legend')).toContainText('授課情形')

  // 下午第六節:社團塞不進格子,主表只寫群組與組數,另出分組巡堂單
  const afternoon = sheet.getByTestId('patrol-page').nth(1)
  await expect(afternoon).toContainText('共 4 組')
  const list = sheet.getByTestId('patrol-group-list')
  await expect(list).toHaveCount(1)
  await expect(list).toContainText('社團巡堂單')
  await expect(list).toContainText('第六節')
  await expect(list.getByTestId('patrol-group-item')).toHaveCount(4)
  await expect(list.getByTestId('patrol-group-item').first()).toContainText('羽球社')
  await expect(list.getByTestId('patrol-group-item').first()).toContainText('體育館')
  await sheet.screenshot({ path: 'e2e/screenshots/patrol-1-sheet.png', fullPage: true })
  await sheet.close()
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
