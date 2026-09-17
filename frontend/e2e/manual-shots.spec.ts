import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter } from './dates'

// 操作手冊補圖產生器(不是驗收測試,CI 不跑)。對示範站逐頁截圖 → docs/manual-img/。
//
// 重拍全部 12 張(整套流程約 1 分鐘):
//   1) 起一套**全新**的棧(空資料庫),.env 設 ADMIN_PASSWORD=DemoSetup2026!,例如
//        docker compose -p manual --env-file <你的.env> up -d
//   2) E2E_BASE_URL=http://localhost:<port> npm run e2e:manual
//
// 兩支測試對站台狀態的要求不同,故分開(執行順序即檔案順序,workers=1):
//   01–02:需**精靈尚未完成**的全新站台。
//   03–12:自己把示範資料備齊(冪等),再逐頁截圖。
//
// 示範資料與改密都刻意做在這支 spec 裡、不靠外部腳本:上一次是臨時手動灌的,
// 結果要重拍時沒人知道當初的資料長什麼樣子,只好整套重猜一遍。

const SHOTS = '../docs/manual-img'
const ADMIN = 'admin'
const INIT_PW = 'DemoSetup2026!' // .env 的 ADMIN_PASSWORD(首次登入會被強制改密)
const PW = 'DemoManual2026!'     // 本 spec 首次執行時改成這個,之後沿用
const YEAR = 115
const TERM = 1

test.use({
  baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081',
  viewport: { width: 1440, height: 900 },
})

const post = async (p: Page, url: string, data: object) => (await p.request.post(url, { data })).json()
const get = async (p: Page, url: string) => (await p.request.get(url)).json()

/** 登入示範站;全新站台的 admin 會被要求改密(路由守衛會把每一頁導去改密頁),這裡一併處理掉。 */
async function loginAsAdmin(page: Page) {
  const r = await page.request.post('/api/auth/login', { data: { username: ADMIN, password: PW } })
  if (r.ok()) return

  const first = await page.request.post('/api/auth/login',
    { data: { username: ADMIN, password: INIT_PW } })
  expect(first.ok(), `admin 密碼不是 ${PW} 也不是 ${INIT_PW};請以空資料庫重起示範站`).toBeTruthy()
  const changed = await page.request.post('/api/auth/change-password',
    { data: { old_password: INIT_PW, new_password: PW } })
  expect(changed.ok(), '首次登入改密失敗').toBeTruthy()
}

/** 示範站學期內、今日之後的第一個週三(代課不能指派已上過的節次,故不可取過去的日子)。 */
async function pickLeaveDay(page: Page, sid: number): Promise<string> {
  const sem = await get(page, `/api/semesters/${sid}`)
  const earliest = new Date()
  earliest.setDate(earliest.getDate() + 1)
  const start = new Date(sem.start_date)
  const from = start > earliest ? start : earliest
  const wed = onOrAfter(3, from)
  if (iso(wed) > sem.end_date) {
    throw new Error(`示範學期(${sem.start_date}~${sem.end_date})已過期,請以空資料庫重跑`)
  }
  return iso(wed)
}

async function selectSemester(page: Page) {
  const sel = page.locator('.n-base-selection').first()
  if (await sel.isVisible().catch(() => false)) {
    await sel.click()
    const opt = page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 ${TERM} 學期` })
    if (await opt.first().isVisible().catch(() => false)) await opt.first().click()
    else await page.keyboard.press('Escape')
  }
  await page.waitForLoadState('networkidle')
}

/** 示範學校:國中 3 班、8 位教師、24 筆配課(冪等:已存在就直接沿用)。 */
async function ensureDemoData(page: Page): Promise<number> {
  const found = (await get(page, '/api/semesters'))
    .find((s: { academic_year: number; term: number }) => s.academic_year === YEAR && s.term === TERM)
  if (found) return found.id

  // 學期起訖取「今天往後推一週」起算的半年,截圖才不會因為日期過期而失效
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setMonth(end.getMonth() + 5)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: TERM, template_key: 'junior_high',
    start_date: iso(start), end_date: iso(end),
  })
  const sid = sem.id as number

  const subjects: Record<string, number> = {}
  for (const s of await get(page, `/api/subjects?semester_id=${sid}`)) subjects[s.name] = s.id

  // 王大明是手冊裡請假的那位(07/08 兩張圖靠他)
  const TEACHERS: [string, string[]][] = [
    ['王大明', ['國文']], ['李淑芬', ['國文']],
    ['陳志明', ['數學']], ['林美惠', ['數學']],
    ['張文華', ['英語']], ['黃建宏', ['自然科學']],
    ['吳雅玲', ['社會', '綜合活動']], ['劉俊傑', ['健康與體育', '藝術']],
  ]
  const tid: Record<string, number> = {}
  for (const [name, subs] of TEACHERS) {
    const t = await post(page, `/api/teachers?semester_id=${sid}`, {
      name, base_periods: 0, subject_ids: subs.map((s) => subjects[s]).filter(Boolean),
    })
    tid[name] = t.id
  }

  const classes: number[] = []
  for (const name of ['701', '702', '703']) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`,
      { grade: 7, name, track: 'junior_high', student_count: 28 })
    classes.push(c.id)
  }

  const PLAN: [string, number, string[]][] = [
    ['國文', 5, ['王大明', '李淑芬']], ['數學', 4, ['陳志明', '林美惠']],
    ['英語', 4, ['張文華']], ['自然科學', 3, ['黃建宏']], ['社會', 3, ['吳雅玲']],
    ['健康與體育', 2, ['劉俊傑']], ['藝術', 2, ['劉俊傑']], ['綜合活動', 2, ['吳雅玲']],
  ]
  const load: Record<string, number> = {}
  for (const [i, cid] of classes.entries()) {
    for (const [subj, periods, pool] of PLAN) {
      if (!subjects[subj]) continue
      const name = pool[i % pool.length]
      await post(page, `/api/assignments?semester_id=${sid}`, {
        class_id: cid, subject_id: subjects[subj], periods_per_week: periods,
        teachers: [{ teacher_id: tid[name] }], block_rules: [],
      })
      load[name] = (load[name] ?? 0) + periods
    }
  }

  // 應授節數對齊實際配課量:否則鐘點表整排紅字「不足」,手冊看起來像系統在報錯
  for (const t of await get(page, `/api/teachers?semester_id=${sid}`)) {
    await page.request.patch(`/api/teachers/${t.id}`, {
      data: {
        name: t.name, base_periods: load[t.name] ?? 0,
        subject_ids: (t.subjects ?? []).map((s: { id: number }) => s.id),
        admin_reduction: 0, is_external: false,
      },
    })
  }
  return sid
}

/**
 * 把預設草稿(草稿A)排到一半:701 的國文與數學各就各位,其餘留在「未排課務」。
 * 手冊的手動排課章節要呈現的正是這個狀態——格子裡有課、右側還有待排的卡片。
 */
async function seedHalfScheduledDraft(page: Page, sid: number) {
  // 「草稿A」是排課工作台首次載入時才自動建立的;這裡搶在它前面,所以得自己建。
  const drafts = await get(page, `/api/timetables?semester_id=${sid}`)
  const draft = drafts.find((t: { name: string }) => t.name === '草稿A')
    ?? await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })
  const full = await get(page, `/api/timetables/${draft.id}`)
  if ((full.entries ?? []).length) return // 已排過就不再動(冪等)

  const classes = await get(page, `/api/class-units?semester_id=${sid}`)
  const c701 = classes.find((c: { name: string }) => c.name === '701')
  const periods = (await get(page, `/api/class-units/${c701.id}/period-table`)).periods
    .filter((p: { type: string }) => p.type === 'regular')
  // 配課的班級在 scheduling_unit.classes、科目在 subject(不是扁平的 class_id/subject_name)
  const assignments = (await get(page, `/api/assignments?semester_id=${sid}`)).filter(
    (a: { scheduling_unit: { classes: { id: number }[] } }) =>
      a.scheduling_unit.classes.some((c) => c.id === c701.id),
  )

  // 國文 5 節排週一~週五第一節;數學 4 節排週一~週四第二節
  const place = async (subject: string, slotIndex: number, days: number[]) => {
    const a = assignments.find((x: { subject: { name: string } }) => x.subject.name === subject)
    if (!a) return
    for (const weekday of days) {
      const target = periods.filter((x: { weekday: number }) => x.weekday === weekday)[slotIndex]
      if (!target) continue
      await page.request.post(`/api/timetables/${draft.id}/entries`, {
        data: {
          course_assignment_id: a.id, weekday, period_no: target.period_no, span: 1,
        },
      })
    }
  }
  await place('國文', 0, [1, 2, 3, 4, 5])
  await place('數學', 1, [1, 2, 3, 4])
}

test('產生操作手冊截圖(01–02,需全新未設定站台)', async ({ page }) => {
  // ── 01 登入頁 ──
  await page.goto('/login')
  await expect(page.getByRole('button', { name: '登入' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${SHOTS}/01-login.png` })

  // ── 02 設定精靈(第一步:選學制範本)──
  await loginAsAdmin(page)
  await page.goto('/wizard')
  await expect(page.getByRole('heading', { name: '設定精靈' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/02-wizard.png` })
})

test('產生操作手冊截圖(03–12)', async ({ page }) => {
  test.setTimeout(300_000)

  await loginAsAdmin(page)
  const sid = await ensureDemoData(page)
  // 精靈標記完成,否則路由守衛會把每一頁導回精靈
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // ── 03 配課管理 ──
  await page.goto('/scheduling/assignments')
  await selectSemester(page)
  await expect(page.getByRole('heading', { name: '配課管理' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/03-assignments.png` })

  // ── 04 排課工作台(排到一半的狀態:手冊要講的是拖拉排課,空白課表講不了故事)──
  await seedHalfScheduledDraft(page, sid)
  await page.goto('/scheduling/workbench')
  await selectSemester(page)
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/04-workbench.png` })

  // ── 05 自動排課(真的跑一次,截進度與達成度報告)──
  await page.goto('/scheduling/auto')
  await selectSemester(page)
  const done = page.getByTestId('as-status')
  if (!(await done.isVisible().catch(() => false))) {
    await expect(page.getByText('資料檢查通過,可以開始排課')).toBeVisible({ timeout: 30_000 })
    await page.getByTestId('as-start').click()
    // 3 班的示範學校數秒即解完,等它自己完成即可
    await expect(done).toHaveText('已完成', { timeout: 180_000 })
  }
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/05-auto-schedule.png` })

  // ── 06 版本與發布(把自排結果發布出去)──
  await page.goto('/scheduling/versions')
  await selectSemester(page)
  const autoRow = page.locator('tr', { hasText: '自排結果' }).first()
  await expect(autoRow).toBeVisible({ timeout: 20_000 })
  if (!(await page.locator('tr', { hasText: '已發布' }).count())) {
    await autoRow.getByTestId('v-publish').click()
    const force = page.getByTestId('v-force-publish')
    if (await force.isVisible().catch(() => false)) await force.click()
    await expect(page.locator('tr', { hasText: '已發布' })).toBeVisible({ timeout: 20_000 })
  }
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${SHOTS}/06-versions.png` })

  // ── 準備請假 + 代課(07/08 兩張圖的素材)──
  const leaveDay = await pickLeaveDay(page, sid)
  const teachers = await get(page, `/api/teachers?semester_id=${sid}`)
  const wang = teachers.find((t: { name: string }) => t.name === '王大明')
  const existing = await get(page, `/api/leaves?semester_id=${sid}`)
  if (!existing.length && wang) {
    const aps = (await post(page, `/api/leaves?semester_id=${sid}`, {
      teacher_id: wang.id, leave_type: 'sick', start_date: leaveDay, end_date: leaveDay,
    })).affected_periods
    expect(aps.length, '請假當天沒有課——課表沒發布成功?').toBeGreaterThan(0)
    for (const ap of aps.slice(0, 2)) {
      const rec = await get(page, `/api/affected-periods/${ap.id}/recommendations`)
      if (rec.candidates?.length) {
        await page.request.put(`/api/affected-periods/${ap.id}/substitution`,
          { data: { type: 'substitute', handler_teacher_id: rec.candidates[0].teacher_id } })
      }
    }
  }

  // ── 07 請假登記 ──
  await page.goto('/leaves')
  await selectSemester(page)
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/07-leaves.png` })

  // ── 08 今日調代課看板 ──
  await page.goto(`/daily-board?semester_id=${sid}&date=${leaveDay}`)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${SHOTS}/08-daily-board.png` })

  // ── 09 課表查詢(含匯出按鈕)──
  await page.goto(`/timetable-query?semester_id=${sid}`)
  await expect(page.getByRole('heading', { name: '課表查詢' })).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${SHOTS}/09-timetable-query.png` })

  // ── 10 系統管理:備份與還原(先真的備一份,空清單的截圖講不清楚這一章)──
  await page.goto('/settings/system')
  await expect(page.getByTestId('backup-card')).toBeVisible({ timeout: 20_000 })
  const rows = page.getByTestId('backup-row')
  if (!(await rows.count())) {
    await page.getByTestId('backup-now').click()
    await expect(rows.first()).toBeVisible({ timeout: 60_000 })
  }
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/10-backup.png` })

  // ── 11 調課:可對調節次清單(08.3)──
  // 07/08 的假單只代了前兩節;若已沒有待處理的節次,就再請一天假(下週三)當素材
  const leaves = await get(page, `/api/leaves?semester_id=${sid}`)
  const hasPending = leaves.some((l: { affected_periods: { status: string }[] }) =>
    l.affected_periods.some((p) => p.status === 'pending'))
  if (!hasPending && wang) {
    const [y, m, d] = leaveDay.split('-').map(Number)
    await post(page, `/api/leaves?semester_id=${sid}`, {
      teacher_id: wang.id, leave_type: 'official',
      start_date: iso(new Date(y, m - 1, d + 7)), end_date: iso(new Date(y, m - 1, d + 7)),
    })
  }
  await page.goto('/substitutions')
  await selectSemester(page)
  await page.getByTestId('sub-handle').first().click()
  await page.getByTestId('sub-swap').click()
  const swapPanel = page.getByTestId('sub-swap-panel')
  await expect(swapPanel.getByTestId('sub-swap-partner').first()).toBeVisible({ timeout: 20_000 })
  await swapPanel.scrollIntoViewIfNeeded()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/11-swap.png` })

  // ── 12 調課通知單(08.3 列印):點第一個可對調節次,再開列印頁 ──
  await swapPanel.getByTestId('sub-swap-option').first().click()
  await expect(page.getByText(/已和 .+ 調課/)).toBeVisible({ timeout: 20_000 })
  const [slips] = await Promise.all([
    page.waitForEvent('popup'),
    page.getByTestId('sub-print-slip').first().click(),
  ])
  await slips.setViewportSize({ width: 1440, height: 900 })
  await expect(slips.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
  await slips.waitForTimeout(700)
  await slips.screenshot({ path: `${SHOTS}/12-swap-slips.png` })
  await slips.close()
})
