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

/**
 * 王師週三第一節國文請假。陳師同科空堂、周師非本科當天在校、吳師該節有課(被過濾)。
 * 回傳 { sid, affectedId }。
 */
async function seed(page: Page, year: number) {
  const sem = await post(page, '/api/semesters', {
    academic_year: year, term: 1, template_key: 'junior_high',
    start_date: '2026-09-01', end_date: '2027-01-20',
  })
  const sid = sem.id
  const subjects: Record<string, number> = {}
  for (const s of await (await page.request.get(`/api/subjects?semester_id=${sid}`)).json()) {
    subjects[s.name] = s.id
  }
  const subject = async (name: string) => {
    if (!subjects[name]) {
      subjects[name] = (await post(page, `/api/subjects?semester_id=${sid}`, { name })).id
    }
    return subjects[name]
  }
  const teacher = async (name: string, subs: string[]) => (await post(
    page, `/api/teachers?semester_id=${sid}`,
    { name, base_periods: 20, subject_ids: await Promise.all(subs.map(subject)) })).id
  const klass = async (name: string) => (await post(
    page, `/api/class-units?semester_id=${sid}`, { grade: 7, name, track: 'junior_high' })).id

  const T: Record<string, number> = {
    王師: await teacher('王師', ['國文']),
    陳師: await teacher('陳師', ['國文']),
    周師: await teacher('周師', ['數學']),
    吳師: await teacher('吳師', ['數學']),
  }
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const c0 = await klass('701')
  const wed = (await (await page.request.get(
    `/api/class-units/${c0}/period-table`)).json()).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')

  const place = async (t: string, subj: string, kls: string, pidx: number) => {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: await klass(kls), subject_id: await subject(subj), periods_per_week: 1,
      teachers: [{ teacher_id: T[t] }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: wed[pidx].period_no, span: 1 },
    })
  }
  await place('王師', '國文', '701', 0) // 被請假
  await place('周師', '數學', '703', 2) // 當天在校,第一節空
  await place('吳師', '數學', '704', 0) // 該節有課 → 過濾
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)

  const leave = await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: T['王師'], leave_type: 'sick',
    start_date: '2026-11-11', end_date: '2026-11-11',
  })
  return { sid, affectedId: leave.affected_periods[0].id as number }
}

// ── 驗收①:推薦排序(同科第一)+ 硬性過濾 + 指派 ──
test('調代課處理:推薦同科優先、過濾有課者,指派後標記已確認', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 140
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)
  await seed(page, YEAR)

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)

  // 展開待處理節次 → 看推薦
  await page.getByTestId('sub-handle').first().click()
  const panel = page.getByTestId('sub-panel')
  await expect(panel).toBeVisible()

  const candidates = panel.getByTestId('sub-candidate')
  await expect(candidates).toHaveCount(2) // 陳師(同科)、周師(當天在校);吳師有課被過濾
  await expect(candidates.first()).toContainText('陳師')
  await expect(candidates.first()).toContainText('同科目教師')
  await expect(panel).not.toContainText('吳師')
  await page.screenshot({ path: `${SHOTS}/sub-1-recommend.png` })

  // 指派第一名(陳師)
  await candidates.first().getByTestId('sub-pick').click()
  await expect(page.getByText('已指派 陳師 代課')).toBeVisible()
  const period = page.getByTestId('sub-period').first()
  await expect(period).toContainText('已確認')
  await expect(period.getByTestId('sub-handler')).toContainText('陳師')
  await page.screenshot({ path: `${SHOTS}/sub-2-assigned.png` })

  // 撤回 → 退回待處理
  await period.getByTestId('sub-undo').click()
  await expect(page.getByText('已撤回處置')).toBeVisible()
  await expect(page.getByTestId('sub-period').first()).toContainText('待處理')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── 驗收③:全校無人可代 → 提示併班/自習,可直接改採 ──
test('調代課處理:無人可代時提示併班/自習並可直接設定', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 141
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  // 只有王師與陳師,且陳師該節也有課 → 無人可代
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: '2026-09-01', end_date: '2027-01-20',
  })
  const sid = sem.id
  const guo = (await (await page.request.get(
    `/api/subjects?semester_id=${sid}`)).json()).find(
    (s: { name: string }) => s.name === '國文').id
  const wang = (await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王師', base_periods: 20, subject_ids: [guo] })).id
  const chen = (await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '陳師', base_periods: 20, subject_ids: [guo] })).id
  const c1 = (await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const c2 = (await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '702', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const wed = (await (await page.request.get(
    `/api/class-units/${c1}/period-table`)).json()).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  for (const [tid, cid] of [[wang, c1], [chen, c2]] as const) {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: cid, subject_id: guo, periods_per_week: 1,
      teachers: [{ teacher_id: tid }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: wed[0].period_no, span: 1 },
    })
  }
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: wang, leave_type: 'sick', start_date: '2026-11-11', end_date: '2026-11-11',
  })

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)
  await page.getByTestId('sub-handle').first().click()

  await expect(page.getByTestId('sub-nocandidate')).toContainText('併班')
  await expect(page.getByTestId('sub-nocandidate')).toContainText('自習')
  await page.screenshot({ path: `${SHOTS}/sub-3-nocandidate.png` })

  // 直接改採自習
  await page.getByTestId('sub-selfstudy').click()
  await expect(page.getByText('已設為自習')).toBeVisible()
  await expect(page.getByTestId('sub-period').first()).toContainText('已確認')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
