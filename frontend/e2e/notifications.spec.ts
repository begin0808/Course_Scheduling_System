import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const SHOTS = 'e2e/screenshots'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const TEACHER_USER = 'e2e_teacher'
const TEACHER_PASS = 'e2eteacher1234'

const post = async (page: Page, url: string, data: object) =>
  (await page.request.post(url, { data })).json()
const get = async (page: Page, url: string) => (await page.request.get(url)).json()

async function selectSemester(page: Page, year: number) {
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${year} 學年度第 1 學期` }).click()
}

/** 建立/取得綁定 e2e_teacher 帳號的教師「陳老師」。回傳 teacherId。 */
async function bindTeacher(page: Page, sid: number): Promise<number> {
  const file = fileURLToPath(new URL('./fixtures/teachers_with_account.xlsx', import.meta.url))
  const imp = await (await page.request.post(
    `/api/import/teachers?semester_id=${sid}&create_accounts=true`,
    { multipart: { file: { name: 't.xlsx', mimeType: XLSX, buffer: readFileSync(file) } } },
  )).json()
  if (imp.imported === 1) {
    const list = await get(page, `/api/teachers?semester_id=${sid}`)
    return list.find((x: { name: string }) => x.name === '陳老師').id
  }
  const created = await post(page, `/api/teachers?semester_id=${sid}`, { name: '陳老師' })
  const accounts = await get(page, `/api/teachers/bindable-accounts?semester_id=${sid}`)
  const acc = accounts.find((x: { username: string }) => x.username === TEACHER_USER)
  await page.request.patch(`/api/teachers/${created.id}`,
    { data: { name: '陳老師', user_id: acc.id } })
  return created.id
}

async function ensureTeacherPassword(page: Page) {
  await page.request.post('/api/auth/logout')
  const first = await page.request.post('/api/auth/login',
    { data: { username: TEACHER_USER, password: 'changeme' } })
  if (first.ok()) {
    await page.request.post('/api/auth/change-password',
      { data: { old_password: 'changeme', new_password: TEACHER_PASS } })
  }
  await page.request.post('/api/auth/logout')
}

/**
 * 王師(無帳號)請假,指派陳老師(有帳號)代課 → 陳老師收到通知。
 * 回傳 { sid, notificationId }。
 */
async function seedAssignment(page: Page, sid: number, chenId: number) {
  const guo = (await post(page, `/api/subjects?semester_id=${sid}`, { name: '國文' })).id
  const wang = (await post(page, `/api/teachers?semester_id=${sid}`,
    { name: '王師', base_periods: 20 })).id
  const c701 = (await post(page, `/api/class-units?semester_id=${sid}`,
    { grade: 7, name: '701', track: 'junior_high' })).id
  const tt = (await post(page, `/api/timetables?semester_id=${sid}`, { name: '草稿A' })).id
  const wed = (await get(page, `/api/class-units/${c701}/period-table`)).periods
    .filter((p: { weekday: number; type: string }) => p.weekday === 3 && p.type === 'regular')
  const a = await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: c701, subject_id: guo, periods_per_week: 1,
    teachers: [{ teacher_id: wang }], block_rules: [],
  })
  await page.request.post(`/api/timetables/${tt}/entries`,
    { data: { course_assignment_id: a.id, weekday: 3, period_no: wed[0].period_no, span: 1 } })
  await page.request.post(`/api/timetables/${tt}/publish?force=true`)

  const affected = (await post(page, `/api/leaves?semester_id=${sid}`, {
    teacher_id: wang, leave_type: 'sick', start_date: '2026-11-11', end_date: '2026-11-11',
  })).affected_periods[0]
  await page.request.put(`/api/affected-periods/${affected.id}/substitution`,
    { data: { type: 'substitute', handler_teacher_id: chenId } })
}

// ── 驗收①②:教師端鈴鐺確認(手機) + 組長看板再次提醒 ──
// 這些測試共用 e2e_teacher 帳號並發布課表;留下的學期會蓋掉別的測試的「最近學期」
// 預設,故一律以 afterEach 兜底清理(即使測試中途失敗也刪掉)。
const YEARS = [142, 143]

test.describe('通知系統', () => {
  test.afterEach(async ({ page }) => {
    await page.request.post('/api/auth/logout')
    await login(page)
    for (const y of YEARS) await deleteSemesterByYearTerm(page, y, 1)
  })

  test('組長指派代課後,教師手機收到通知並確認;組長看板可再次提醒', async ({ page }) => {
    test.setTimeout(180_000)
    const YEAR = 142
    await login(page)
    await page.request.patch('/api/wizard/state', { data: { completed: true } })
    await deleteSemesterByYearTerm(page, YEAR, 1)

    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
      start_date: '2026-09-01', end_date: '2027-01-20',
    })
    const chenId = await bindTeacher(page, sem.id)
    await seedAssignment(page, sem.id, chenId)
    await ensureTeacherPassword(page)

    // ── 組長看板:陳老師的代課通知未確認,可再次提醒 ──
    await login(page)
    await page.goto('/notification-board')
    await selectSemester(page, YEAR)
    const row = page.getByTestId('board-row').filter({ hasText: '陳老師' }).first()
    await expect(row).toContainText('代課通知')
    await expect(row).toContainText('未讀')
    await row.getByTestId('board-remind').click()
    await expect(page.getByText('已再次提醒 陳老師')).toBeVisible()
    await page.screenshot({ path: `${SHOTS}/notif-1-board.png` })
    await deleteSemesterByYearTerm(page, YEAR, 1)
    await page.request.post('/api/auth/logout')
  })

  test.describe('教師手機端', () => {
    test.use({ viewport: { width: 390, height: 844 } })

    test('教師登入手機看到鈴鐺未讀數,點開確認收到', async ({ page }) => {
      test.setTimeout(180_000)
      const YEAR = 143
      await login(page)
      await page.request.patch('/api/wizard/state', { data: { completed: true } })
      await deleteSemesterByYearTerm(page, YEAR, 1)
      const sem = await post(page, '/api/semesters', {
        academic_year: YEAR, term: 1, template_key: 'junior_high',
        start_date: '2026-09-01', end_date: '2027-01-20',
      })
      const chenId = await bindTeacher(page, sem.id)
      await seedAssignment(page, sem.id, chenId)
      await ensureTeacherPassword(page)

      // 陳老師手機登入 → 鈴鐺有未讀
      await login(page, TEACHER_USER, TEACHER_PASS)
      const badge = page.getByTestId('notif-badge')
      await expect(badge).toContainText('1')

      await page.getByTestId('notif-bell').click()
      const item = page.getByTestId('notif-item').first()
      await expect(item).toContainText('代課通知')
      await expect(item).toContainText('王師')
      await page.screenshot({ path: `${SHOTS}/notif-2-teacher-mobile.png` })

      // 一鍵確認收到
      await item.getByTestId('notif-ack').click()
      await expect(page.getByText('已送出確認回覆')).toBeVisible()
      await expect(item).toContainText('已確認收到')

      // 未讀數歸零(重開鈴鐺 badge 消失)
      await page.keyboard.press('Escape')
      await expect(page.getByTestId('notif-badge')).not.toContainText('1')

      // 清理:留下的已發布學期會蓋掉其他測試的「最近學期」預設,務必刪除
      await page.request.post('/api/auth/logout')
      await login(page)
      await deleteSemesterByYearTerm(page, YEAR, 1)
    })
  })
})
