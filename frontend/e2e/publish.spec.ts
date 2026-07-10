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

// ── M2-5 驗收①②:多草稿並存、未排完發布警告、強制發布、舊版轉封存 ──
test('版本與發布:未排完出現警告清單,確認後強制發布;發布新版舊版轉封存', async ({ page }) => {
  const YEAR = 131
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await post(page, '/api/semesters', {
    academic_year: YEAR, term: 1, template_key: 'junior_high',
  })
  const sid = sem.id
  const c = await post(page, `/api/class-units?semester_id=${sid}`, { grade: 3, name: '301', track: 'junior_high' })
  const s = await post(page, `/api/subjects?semester_id=${sid}`, { name: '國文' })
  const t = await post(page, `/api/teachers?semester_id=${sid}`, { name: '王師' })
  const a = await post(page, `/api/assignments?semester_id=${sid}`, {
    class_id: c.id, subject_id: s.id, periods_per_week: 5,
    teachers: [{ teacher_id: t.id, is_lead: true }], block_rules: [],
  })

  await page.goto('/scheduling/versions')
  await selectSemester(page, YEAR)

  // 建立草稿A,只排 2/5 節(period_no 2 = 第一節)
  await page.getByTestId('v-new').click()
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('草稿')
  const tts = await get(page, `/api/timetables?semester_id=${sid}`)
  const ttId = tts[0].id
  for (const wd of [1, 2]) {
    await page.request.post(`/api/timetables/${ttId}/entries`, {
      data: { course_assignment_id: a.id, weekday: wd, period_no: 2, span: 1 },
    })
  }
  await page.reload()
  await selectSemester(page, YEAR)

  // 完整性檢查提示
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-check').click()
  await expect(page.getByText('尚有 3 節未排')).toBeVisible()

  // 發布 → 警告清單(驗收②)
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-publish').click()
  const unplaced = page.getByTestId('v-unplaced')
  await expect(unplaced).toBeVisible()
  await expect(unplaced).toContainText('國文')
  await expect(unplaced).toContainText('301')
  await page.waitForTimeout(350) // 等 modal 淡入完成,截圖才清楚
  await page.screenshot({ path: `${SHOTS}/pub-1-warning.png` })

  // 確認後仍可強制發布
  await page.getByTestId('v-force-publish').click()
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('已發布')
  await page.screenshot({ path: `${SHOTS}/pub-2-published.png` })

  // 複製為新草稿(驗收①:兩份並存)
  await page.locator('[data-testid="v-row-草稿A"]').getByTestId('v-duplicate').click()
  const copyRow = page.locator('[data-testid="v-row-草稿A 複本"]')
  await expect(copyRow).toBeVisible()
  await expect(page.getByTestId('v-status-草稿A 複本')).toHaveText('草稿')

  // 發布複本 → 原版轉「已封存」
  await copyRow.getByTestId('v-publish').click()
  await page.getByTestId('v-force-publish').click()
  await expect(page.getByTestId('v-status-草稿A 複本')).toHaveText('已發布')
  await expect(page.getByTestId('v-status-草稿A')).toHaveText('已封存')
  await page.screenshot({ path: `${SHOTS}/pub-3-archived.png` })

  // 已發布為快照:格位不可再編輯
  const r = await page.request.post(`/api/timetables/${ttId}/entries`, {
    data: { course_assignment_id: a.id, weekday: 3, period_no: 2, span: 1 },
  })
  expect(r.status()).toBe(409)

  await deleteSemesterByYearTerm(page, YEAR, 1)
})

// ── M2-5 驗收③:teacher 角色以手機瀏覽器查本人課表 ──
test.describe('教師端(手機)', () => {
  test.use({ viewport: { width: 390, height: 844 } }) // iPhone 尺寸

  test('teacher 角色登入手機瀏覽器,課表查詢預設顯示本人課表', async ({ page }) => {
    const YEAR = 132
    await login(page) // 先以教學組長建置資料
    await page.request.patch('/api/wizard/state', { data: { completed: true } })

    await deleteSemesterByYearTerm(page, YEAR, 1)
    const sem = await post(page, '/api/semesters', {
      academic_year: YEAR, term: 1, template_key: 'junior_high',
    })
    const sid = sem.id

    // 建立教師帳號:匯入含「登入帳號」的教師範本(唯一能建立 teacher 帳號的途徑)。
    // 帳號不隨學期刪除,故第二次執行改為建立教師並綁定既有帳號(保持冪等)。
    const file = fileURLToPath(new URL('./fixtures/teachers_with_account.xlsx', import.meta.url))
    const imp = await (await page.request.post(
      `/api/import/teachers?semester_id=${sid}&create_accounts=true`,
      { multipart: { file: { name: 't.xlsx', mimeType: XLSX, buffer: readFileSync(file) } } },
    )).json()

    let teacherId: number
    if (imp.imported === 1) {
      const list = await get(page, `/api/teachers?semester_id=${sid}`)
      teacherId = list.find((x: { name: string }) => x.name === '陳老師').id
    } else {
      const created = await post(page, `/api/teachers?semester_id=${sid}`, { name: '陳老師' })
      const accounts = await get(page, `/api/teachers/bindable-accounts?semester_id=${sid}`)
      const acc = accounts.find((x: { username: string }) => x.username === TEACHER_USER)
      expect(acc, '應可綁定既有的 e2e_teacher 帳號').toBeTruthy()
      await page.request.patch(`/api/teachers/${created.id}`, {
        data: { name: '陳老師', user_id: acc.id },
      })
      teacherId = created.id
    }

    // 陳老師的課,排入並發布(每週 1 節 → 排 1 節即完整,無需強制發布)
    const c = await post(page, `/api/class-units?semester_id=${sid}`, { grade: 7, name: '701', track: 'junior_high' })
    const s = await post(page, `/api/subjects?semester_id=${sid}`, { name: '公民' })
    const a = await post(page, `/api/assignments?semester_id=${sid}`, {
      class_id: c.id, subject_id: s.id, periods_per_week: 1,
      teachers: [{ teacher_id: teacherId, is_lead: true }], block_rules: [],
    })
    const tt = await post(page, `/api/timetables?semester_id=${sid}`, { name: '正式課表' })
    await page.request.post(`/api/timetables/${tt.id}/entries`, {
      data: { course_assignment_id: a.id, weekday: 3, period_no: 4, span: 1 },
    })
    const pubResp = await page.request.post(`/api/timetables/${tt.id}/publish`)
    expect(pubResp.status()).toBe(200)

    // 首登需改密碼 → 以 API 一次設定為固定密碼(非本卡驗收重點);已改過則忽略
    await page.request.post('/api/auth/logout')
    const first = await page.request.post('/api/auth/login', {
      data: { username: TEACHER_USER, password: 'changeme' },
    })
    if (first.ok()) {
      await page.request.post('/api/auth/change-password', {
        data: { old_password: 'changeme', new_password: TEACHER_PASS },
      })
    }
    await page.request.post('/api/auth/logout')

    // ── 以教師身分登入(手機尺寸)──
    await login(page, TEACHER_USER, TEACHER_PASS)
    // 純教師帳號一律導向課表查詢
    await expect(page).toHaveURL(/\/timetable-query/)
    await expect(page.getByRole('heading', { name: '課表查詢' })).toBeVisible()

    // 預設顯示本人課表,且看得到自己的課
    await expect(page.getByText('本人課表')).toBeVisible()
    await expect(page.locator('[data-weekday="3"][data-period="4"]')).toContainText('公民')
    await expect(page.locator('[data-weekday="3"][data-period="4"]')).toContainText('701')

    // 教師看不到排課作業/基礎資料等管理選單
    await expect(page.getByRole('link', { name: '課表查詢' })).toBeVisible()
    await expect(page.getByText('排課作業')).toHaveCount(0)
    await expect(page.getByText('基礎資料')).toHaveCount(0)
    await page.screenshot({ path: `${SHOTS}/pub-4-teacher-mobile.png` })

    // 唯讀:格位不可拖曳
    await expect(page.locator('[data-weekday="3"][data-period="4"] .tg-card'))
      .toHaveAttribute('draggable', 'false')

    // 清理(以教學組長身分)
    await page.request.post('/api/auth/logout')
    await login(page)
    await deleteSemesterByYearTerm(page, YEAR, 1)
  })
})
