import { expect, test } from '@playwright/test'
import { iso } from './dates'
import {
  ensureDemoData, get, loginAsAdmin, pickLeaveDay, post, seedHalfScheduledDraft, selectSemester,
  waitToastGone,
} from './demo-school'

// 操作手冊補圖產生器(不是驗收測試,CI 不跑)。對示範站逐頁截圖 → docs/manual-img/。
//
// 重拍全部 18 張(整套流程約 1 分鐘):
//   1) 起一套**全新**的棧(空資料庫),.env 設 ADMIN_PASSWORD=DemoSetup2026!,例如
//        docker compose -p manual --env-file <你的.env> up -d
//   2) E2E_BASE_URL=http://localhost:<port> npm run e2e:manual
//
// 兩支測試對站台狀態的要求不同,故分開(執行順序即檔案順序,workers=1):
//   01–02:需**精靈尚未完成**的全新站台。
//   03–18:自己把示範資料備齊(冪等),再逐頁截圖。
//
// 示範資料與改密都刻意做在這支 spec 裡、不靠外部腳本:上一次是臨時手動灌的,
// 結果要重拍時沒人知道當初的資料長什麼樣子,只好整套重猜一遍。

const SHOTS = '../docs/manual-img'

test.use({
  baseURL: process.env.E2E_BASE_URL || 'http://localhost:8081',
  viewport: { width: 1440, height: 900 },
})

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

test('產生操作手冊截圖(03–18)', async ({ page }) => {
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
  await waitToastGone(page)
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
  await waitToastGone(page)
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

  // ── 15 代導(8.2):王大明是 701 導師,整天請假 → 假單下方多一區代導;展開「安排代導」──
  await page.goto('/substitutions')
  await selectSemester(page)
  const sickCard = page.getByTestId('sub-leave').filter({ hasText: '王大明' }).first()
  await expect(sickCard.getByTestId('sub-covers')).toBeVisible({ timeout: 20_000 })
  await sickCard.getByTestId('sub-cover-handle').first().click()
  await expect(sickCard.getByTestId('sub-cover-panel')).toBeVisible()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/15-homeroom-cover.png` })

  // ── 16 新增調課(未請假)(8.3):選老師、日期、勾一節;只截對話框,不真的建立 ──
  await page.reload()
  await selectSemester(page)
  await page.getByTestId('sub-new-swap').click()
  await page.getByTestId('sub-ns-teacher').click()
  await page.locator('.n-base-select-option', { hasText: '陳志明' }).click()
  const nsDate = page.getByTestId('sub-ns-date').locator('input')
  await nsDate.click()
  await nsDate.fill(leaveDay)
  await nsDate.press('Enter')
  const nsBoxes = page.getByTestId('sub-ns-period')
  await expect(nsBoxes.first()).toBeVisible({ timeout: 20_000 })
  await nsBoxes.first().click()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/16-new-swap.png` })
  await page.keyboard.press('Escape')

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
  await waitToastGone(page)
  // 備份卡片在系統管理頁的下半部;捲到它,截圖才看得到備份清單
  await page.getByTestId('backup-card').scrollIntoViewIfNeeded()
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

  // ── 13 代課通知單(08.2 列印):找一節已經代課的,開列印頁 ──
  const subBtn = page.getByTestId('sub-print-slip-sub').first()
  await expect(subBtn).toBeVisible({ timeout: 20_000 })
  const [subSlips] = await Promise.all([
    page.waitForEvent('popup'),
    subBtn.click(),
  ])
  await subSlips.setViewportSize({ width: 1440, height: 900 })
  await expect(subSlips.getByTestId('slip-teacher').first()).toBeVisible({ timeout: 20_000 })
  await subSlips.waitForTimeout(700)
  await subSlips.screenshot({ path: `${SHOTS}/13-substitute-slips.png` })
  await subSlips.close()

  // ── 14 巡堂表(08.8 列印):王大明請假那天,代課老師與備註由系統帶出 ──
  await page.goto(`/patrol-sheets/print?semester_id=${sid}&from=${leaveDay}&to=${leaveDay}`)
  await expect(page.getByTestId('patrol-page').first()).toBeVisible({ timeout: 20_000 })
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/14-patrol-sheet.png` })

  // ── 17 單雙週組(4 章):703 單週藝術、雙週綜合活動(放在最後,前面的截圖不受影響)──
  const q = `?semester_id=${sid}`
  if (!(await get(page, `/api/alternate-units${q}`)).length) {
    const cls = (await get(page, `/api/class-units${q}`)).find((c: { name: string }) => c.name === '703')
    const subs: Record<string, number> = {}
    for (const x of await get(page, `/api/subjects${q}`)) subs[x.name] = x.id
    const tids: Record<string, number> = {}
    for (const t of await get(page, `/api/teachers${q}`)) tids[t.name] = t.id
    const unit = await post(page, `/api/alternate-units${q}`, { class_id: cls.id })
    for (const [subject, teacher, week] of [['藝術', '劉俊傑', 'odd'], ['綜合活動', '吳雅玲', 'even']]) {
      await post(page, `/api/assignments${q}`, {
        scheduling_unit_id: unit.id, subject_id: subs[subject], periods_per_week: 1,
        teachers: [{ teacher_id: tids[teacher], is_lead: true }], block_rules: [], week_parity: week,
      })
    }
  }
  await page.goto('/scheduling/assignments')
  await selectSemester(page)
  const altList = page.getByTestId('alt-list')
  await expect(altList).toBeVisible({ timeout: 20_000 })
  await altList.scrollIntoViewIfNeeded()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/17-alternate-weeks.png` })

  // ── 18 儀表板即時概況(8.9):把時刻換成請假日上午第二節(703 由代課老師上)──
  // API 支援 at 參數(預覽用);畫面不帶,這裡攔下請求補上,截圖才不受拍攝當下的時間影響。
  await page.route('**/api/live-overview?**', (route) => {
    const u = new URL(route.request().url())
    u.searchParams.set('at', `${leaveDay}T09:30:00`)
    return route.continue({ url: u.toString() })
  })
  // 下方「今日調代課」也換成同一天,上下兩張卡才對得起來
  await page.route('**/api/daily-board?**', (route) => {
    const u = new URL(route.request().url())
    u.searchParams.set('on', leaveDay)
    return route.continue({ url: u.toString() })
  })
  await page.goto('/')
  const live = page.getByTestId('dash-live')
  await expect(live.getByTestId('live-period').first()).toBeVisible({ timeout: 20_000 })
  await live.scrollIntoViewIfNeeded()
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${SHOTS}/18-dashboard-live.png` })
})
