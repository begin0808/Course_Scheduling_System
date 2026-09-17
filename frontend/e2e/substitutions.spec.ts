import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { SEM_END, SEM_START, THU, WED, WED2 } from './dates'
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
    start_date: SEM_START, end_date: SEM_END,
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
  // get-or-create:同學期班名唯一(M6-5),同一個班不能建第二次
  const classes: Record<string, number> = {}
  const klass = async (name: string) => {
    if (!classes[name]) {
      classes[name] = (await post(page, `/api/class-units?semester_id=${sid}`,
        { grade: 7, name, track: 'junior_high' })).id
    }
    return classes[name]
  }

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
    start_date: WED, end_date: WED,
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
    start_date: SEM_START, end_date: SEM_END,
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
    teacher_id: wang, leave_type: 'sick', start_date: WED, end_date: WED,
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

// ── v1.2.1:調課(使用學校回饋:只有代課、找不到調課)──
// 王師週三第一節 701 國文請假;陳師也教 701(週四第二節數學)、另有 702 週三第二節。
test('調代課處理:調課列出可對調節次,點選後成立並上看板', async ({ page }) => {
  test.setTimeout(120_000)
  const YEAR = 142
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  const sid = (await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
    start_date: SEM_START, end_date: SEM_END,
  })).id
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
  const T: Record<string, number> = {}
  for (const [name, subs] of [['王師', ['國文']], ['陳師', ['數學', '自然']]] as const) {
    T[name] = (await post(page, `/api/teachers?semester_id=${sid}`, {
      name, base_periods: 20, subject_ids: await Promise.all(subs.map(subject)),
    })).id
  }
  const classes: Record<string, number> = {}
  for (const name of ['701', '702']) {
    classes[name] = (await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name, track: 'junior_high' })).id
  }
  const periods = (await (await page.request.get(
    `/api/class-units/${classes['701']}/period-table`)).json()).periods
    .filter((p: { type: string }) => p.type === 'regular')
  const slot = (weekday: number, idx: number) =>
    periods.filter((p: { weekday: number }) => p.weekday === weekday)[idx].period_no
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const place = async (t: string, subj: string, kls: string, weekday: number, idx: number) => {
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: classes[kls], subject_id: await subject(subj), periods_per_week: 1,
      teachers: [{ teacher_id: T[t] }], block_rules: [],
    })
    await page.request.post(`/api/timetables/${tt}/entries`, {
      data: { course_assignment_id: a.id, weekday, period_no: slot(weekday, idx), span: 1 },
    })
  }
  await place('王師', '國文', '701', 3, 0) // 被請假
  await place('陳師', '數學', '701', 4, 1) // 同班 → 可互調
  await place('陳師', '自然', '702', 3, 1) // 別班 → 只有下週三換得成(本週三王師請假)
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)
  await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: T['王師'], leave_type: 'personal', start_date: WED, end_date: WED,
  })

  const short = (iso: string) => {
    const [y, m, d] = iso.split('-').map(Number)
    const wd = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'][new Date(y, m - 1, d).getDay()]
    return `${m}/${d}(${wd})`
  }

  await page.goto('/substitutions')
  await selectSemester(page, YEAR)
  await page.getByTestId('sub-handle').first().click()
  await page.getByTestId('sub-swap').click()

  const swapPanel = page.getByTestId('sub-swap-panel')
  const partner = swapPanel.getByTestId('sub-swap-partner')
  await expect(partner).toHaveCount(1)
  await expect(partner).toContainText('陳師')
  await expect(partner).toContainText('也教這班')
  const options = partner.getByTestId('sub-swap-option')
  await expect(options).toHaveCount(2) // 先只列同班:本週四、下週四
  await expect(options.first()).toContainText(`${short(THU)}`)
  await expect(options.first()).toContainText('701 數學')
  await partner.getByTestId('sub-swap-more').click() // 展開其他班:下週三 702
  await expect(options).toHaveCount(3)
  await expect(options.nth(2)).toContainText(`${short(WED2)}`)
  await expect(swapPanel).not.toContainText(short(WED)) // 請假當天不能補
  await page.screenshot({ path: `${SHOTS}/sub-4-swap-options.png` })

  // 放寬到 4 週:「本週與隔三週」的週四出現
  const [ty, tm, td] = THU.split('-').map(Number)
  const thu3 = new Date(ty, tm - 1, td + 21)
  const thu3Label = `${thu3.getMonth() + 1}/${thu3.getDate()}(週四)`
  await expect(swapPanel).not.toContainText(thu3Label)
  await swapPanel.getByTestId('sub-swap-weeks').click()
  await page.locator('.n-base-select-option', { hasText: '往後共 4 週' }).click()
  await expect(swapPanel).toContainText(thu3Label)

  await options.first().click()
  await expect(page.getByText('已和 陳師 調課')).toBeVisible()
  const period = page.getByTestId('sub-period').first()
  await expect(period).toContainText('已確認')
  await expect(period.getByTestId('sub-handler')).toContainText('陳師')

  // 調課通知單:陳師、王師各一張教師單 + 701 班級單;格子寫「日期/科目/老師/[調MM-DD_星期節次]」
  const [slips] = await Promise.all([
    page.waitForEvent('popup'),
    period.getByTestId('sub-print-slip').click(),
  ])
  await expect(slips.getByTestId('slip-teacher')).toHaveCount(2)
  await expect(slips.getByTestId('slip-class')).toHaveCount(1)
  const mmdd = (iso: string) => iso.slice(5)
  const chenSlip = slips.getByTestId('slip-teacher').first()
  await expect(chenSlip).toContainText('教師調課通知單')
  await expect(chenSlip).toContainText('調課教師：陳師')
  await expect(chenSlip.getByTestId('slip-cell')).toHaveText(
    new RegExp(`${WED}\\s*數學\\s*陳師\\s*\\[調${mmdd(THU)}_42\\]`))
  await expect(slips.getByTestId('slip-teacher').nth(1).getByTestId('slip-cell')).toHaveText(
    new RegExp(`${THU}\\s*國文\\s*王師\\s*\\[調${mmdd(WED)}_31\\]`))
  await expect(slips.getByTestId('slip-class').getByTestId('slip-cell')).toHaveCount(2)
  // 表頭斜線畫在內容裡(SVG),列印不會像背景一樣被瀏覽器略過
  await expect(slips.locator('th.corner svg line')).toHaveCount(3)
  await slips.screenshot({ path: `${SHOTS}/sub-8-swap-slips.png`, fullPage: true })
  await slips.close()

  // 調代課紀錄:篩選結果中的調課可一次列印
  await page.goto('/substitution-log')
  await selectSemester(page, YEAR)
  await expect(page.getByTestId('log-print-slips')).toContainText('1 節')

  // 今日看板(請假那天)標示調課與補課時間
  await page.goto(`/daily-board?semester_id=${sid}&date=${WED}`)
  await expect(page.getByTestId('board-row').first()).toContainText(`調課 · 陳師(補 ${THU}`)
  await page.screenshot({ path: `${SHOTS}/sub-5-swap-board.png` })

  // 補課那天(週四)的看板與 A4 公告單也列出換來的那一節:原任陳師、改由王師上
  await page.goto(`/daily-board?semester_id=${sid}&date=${THU}`)
  const makeup = page.getByTestId('board-row')
  await expect(makeup).toHaveCount(1)
  await expect(makeup).toContainText('701')
  await expect(makeup).toContainText('數學')
  await expect(makeup).toContainText('陳師')
  await expect(makeup).toContainText('調課補課')
  await expect(makeup).toContainText(`調課補課 · 王師(與 ${WED} `)
  await page.screenshot({ path: `${SHOTS}/sub-6-swap-makeup-board.png` })

  await page.goto(`/daily-board/print?semester_id=${sid}&date=${THU}`)
  const printRow = page.getByTestId('print-row')
  await expect(printRow).toHaveCount(1)
  await expect(printRow).toContainText('王師')
  await expect(printRow).toContainText(`與 ${WED}`)
  await page.screenshot({ path: `${SHOTS}/sub-7-swap-makeup-print.png` })

  // 請假的王師也收到補課通知
  const notes = await (await page.request.get(
    `/api/notifications?semester_id=${sid}&teacher_id=${T['王師']}`)).json()
  expect(notes.map((n: { title: string }) => n.title).join()).toContain('調課補課通知')

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
