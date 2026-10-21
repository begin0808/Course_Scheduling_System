import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, WED } from './dates'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 儀表板即時概況(v1.3.3,Issue #50):現在這一節各班實際在上什麼課、誰在上。
 * 已套用當天的調代課;下課時列下一節。
 *
 * 「現在」由後端依學校時區決定,測試時把請求改成指定時刻(週三 08:30 / 09:10),
 * 結果才不會隨執行時間變動。儀表板顯示最新學期,所以學年取比其他測試都大的值。
 */
const YEAR = 166

const post = async (p: Page, url: string, data: object) => {
  const r = await p.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

/** 儀表板向後端要即時概況時,改成指定的時刻 */
async function pretendNow(page: Page, hhmm: string) {
  await page.unroute('**/api/live-overview*')
  await page.route('**/api/live-overview*', (route) =>
    route.continue({ url: `${route.request().url()}&at=${WED}T${hhmm}:00` }))
}

test('即時概況:現在這一節各班的課,代課老師與下一節都正確', async ({ page }) => {
  test.setTimeout(120_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  try {
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high', start_date: SEM_START, end_date: SEM_END,
    })
    const q = `?semester_id=${sem.id}`
    const subjects: { id: number; name: string }[] = await (await page.request.get(`/api/subjects${q}`)).json()
    const sid = (name: string) => subjects.find((s) => s.name === name)!.id
    const teacher = async (name: string, subject: string) =>
      (await post(page, `/api/teachers${q}`, { name, subject_ids: [sid(subject)] })).id as number
    const wang = await teacher('王老師', '國文')
    const chen = await teacher('陳老師', '國文')
    const lee = await teacher('李老師', '數學')
    const c701 = (await post(page, `/api/class-units${q}`, { grade: 7, name: '701', track: 'junior_high' })).id
    await post(page, `/api/class-units${q}`, { grade: 7, name: '702', track: 'junior_high' })
    const periods: { weekday: number; name: string; period_no: number }[] =
      (await (await page.request.get(`/api/class-units/${c701}/period-table`)).json()).periods
    const pno = (name: string) => periods.find((p) => p.weekday === 3 && p.name === name)!.period_no

    const tt = (await post(page, `/api/timetables${q}`, { name: '草稿A' })).id
    const lesson = async (who: number, subject: string, period: string) => {
      const a = await post(page, `/api/assignments${q}`, {
        class_id: c701, subject_id: sid(subject), periods_per_week: 1,
        teachers: [{ teacher_id: who }], block_rules: [],
      })
      await post(page, `/api/timetables/${tt}/entries`,
        { course_assignment_id: a.id, weekday: 3, period_no: pno(period), span: 1 })
    }
    await lesson(wang, '國文', '第一節')
    await lesson(lee, '數學', '第二節')
    expect((await page.request.post(`/api/timetables/${tt}/publish?force=true`)).ok()).toBeTruthy()

    // 王老師週三請假,陳老師代課
    const leave = await post(page, `/api/leaves${q}`,
      { teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED })
    const sub = await page.request.put(`/api/affected-periods/${leave.affected_periods[0].id}/substitution`,
      { data: { type: 'substitute', handler_teacher_id: chen } })
    expect(sub.ok()).toBeTruthy()

    // 週三 08:30:第一節上課中,701 是代課的陳老師
    await pretendNow(page, '08:30')
    await page.goto('/')
    const card = page.getByTestId('dash-live')
    await expect(card).toContainText('08:30')
    await expect(card.getByTestId('live-period')).toHaveText('上課中:第一節(08:20–09:05)')
    const c = card.getByTestId('live-701')
    await expect(c).toContainText('國文')
    await expect(c).toContainText('陳老師')
    await expect(c).toContainText('代課')
    await expect(card.getByTestId('live-702')).toContainText('沒有課')

    // 09:10 下課:列出下一節
    await pretendNow(page, '09:10')
    await page.reload()
    await expect(card.getByTestId('live-period')).toHaveText('下課中,下一節是第二節(09:15–10:00)')
    await expect(card.getByTestId('live-701')).toContainText('李老師')

    // 開啟今天整天的巡堂表(新分頁)
    const [sheet] = await Promise.all([
      page.waitForEvent('popup'),
      card.getByRole('button', { name: '看今天整天的巡堂表' }).click(),
    ])
    await expect(sheet.getByTestId('patrol-page').first()).toContainText('巡堂紀錄', { timeout: 20_000 })
    await sheet.close()
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
