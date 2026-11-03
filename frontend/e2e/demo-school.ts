import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { iso, onOrAfter } from './dates'

// 示範學校(國中 3 班、8 位教師、24 筆配課):操作手冊截圖(manual-shots)與操作示範影片(video/)共用。
// 全部冪等:已存在就沿用,所以同一個示範站可以重複執行。

export const ADMIN = 'admin'
export const INIT_PW = 'DemoSetup2026!' // .env 的 ADMIN_PASSWORD(首次登入會被強制改密)
export const PW = 'DemoManual2026!'     // 本 spec 首次執行時改成這個,之後沿用
export const YEAR = 115
export const TERM = 1


export const post = async (p: Page, url: string, data: object) => (await p.request.post(url, { data })).json()
export const get = async (p: Page, url: string) => (await p.request.get(url)).json()

/** 登入示範站;全新站台的 admin 會被要求改密(路由守衛會把每一頁導去改密頁),這裡一併處理掉。 */
export async function loginAsAdmin(page: Page) {
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
export async function pickLeaveDay(page: Page, sid: number): Promise<string> {
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

/** 等右上角的提示訊息(「已產生…」「已發布…」)消失再截圖,畫面才乾淨。 */
export async function waitToastGone(page: Page) {
  await expect(page.locator('.n-message')).toHaveCount(0, { timeout: 15_000 })
}

export async function selectSemester(page: Page) {
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
export async function ensureDemoData(page: Page): Promise<number> {
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

  // 導師:王大明帶 701,他請假那天就有「代導」可以拍(15)
  const HOMEROOM: Record<string, string> = { 701: '王大明', 702: '李淑芬', 703: '陳志明' }
  const classes: number[] = []
  for (const name of ['701', '702', '703']) {
    const c = await post(page, `/api/class-units?semester_id=${sid}`, {
      grade: 7, name, track: 'junior_high', student_count: 28,
      homeroom_teacher_id: tid[HOMEROOM[name]],
    })
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
export async function seedHalfScheduledDraft(page: Page, sid: number) {
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

/** 用 API 跑自動排課並發布(影片要一開始就有已發布課表;手冊截圖則是在畫面上操作)。 */
export async function publishBySolver(page: Page, sid: number): Promise<void> {
  const tts = await get(page, `/api/timetables?semester_id=${sid}`)
  if (tts.some((t: { status: string }) => t.status === 'published')) return
  const draft = tts.find((t: { name: string }) => t.name === '草稿A')
    ?? await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })
  const { job_id: jobId } = await post(page, `/api/timetables/${draft.id}/auto-schedule`,
    { max_seconds: 60 })
  let job = await get(page, `/api/solver/jobs/${jobId}`)
  for (let i = 0; i < 120 && !['finished', 'failed', 'cancelled'].includes(job.status); i++) {
    await page.waitForTimeout(1000)
    job = await get(page, `/api/solver/jobs/${jobId}`)
  }
  expect(job.result_timetable_id, `自動排課沒有產生結果:${job.status} ${job.error ?? ''}`).toBeTruthy()
  const r = await page.request.post(`/api/timetables/${job.result_timetable_id}/publish?force=true`)
  expect(r.ok(), `發布失敗 ${r.status()}`).toBeTruthy()
}

