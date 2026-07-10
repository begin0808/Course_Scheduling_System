import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

const YEAR = 126
const SHOTS = 'e2e/screenshots'

// 國中範本可排課節次(period_no):1=早自習、6=午休,其餘為一般課
const SLOTS = [2, 3, 4, 5, 7, 8, 9]
const SUBJECTS = ['國文', '數學', '英文', '自然', '社會', '藝文', '健體']

/** 以 dispatchEvent + 真實 DataTransfer 驅動 HTML5 拖放,才能在「放下前」斷言衝突紅框。 */
async function newDataTransfer(page: Page) {
  return page.evaluateHandle(() => new DataTransfer())
}
async function dragOver(page: Page, source: Locator, target: Locator) {
  const dt = await newDataTransfer(page)
  await source.dispatchEvent('dragstart', { dataTransfer: dt })
  await target.dispatchEvent('dragenter', { dataTransfer: dt })
  return { dt, end: () => source.dispatchEvent('dragend', { dataTransfer: dt }) }
}
async function dragDrop(page: Page, source: Locator, target: Locator) {
  const dt = await newDataTransfer(page)
  await source.dispatchEvent('dragstart', { dataTransfer: dt })
  await target.dispatchEvent('dragenter', { dataTransfer: dt })
  await target.dispatchEvent('drop', { dataTransfer: dt })
}
const cell = (page: Page, weekday: number, period: number) =>
  page.locator(`[data-weekday="${weekday}"][data-period="${period}"]`)

test('排課工作台:衝突紅框、拖放排課、鎖定、拖回移除、Ctrl+Z、三視角一致、排滿歸零', async ({ page }) => {
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })

  // ── 前置(API):學期 + 2 班 + 8 位教師 + 8 科 + 配課 ──
  await deleteSemesterByYearTerm(page, YEAR, 1)
  const sem = await (await page.request.post('/api/semesters', {
    data: { academic_year: YEAR, term: 1, template_key: 'junior_high' },
  })).json()
  const sid = sem.id
  const post = async (url: string, data: object) =>
    (await page.request.post(url, { data })).json()

  const c301 = await post(`/api/class-units?semester_id=${sid}`, { grade: 3, name: '301', track: 'junior_high' })
  const c302 = await post(`/api/class-units?semester_id=${sid}`, { grade: 3, name: '302', track: 'junior_high' })

  // 王師教 301 國文,同時教 302 數學二(用來製造教師衝突)
  const wang = await post(`/api/teachers?semester_id=${sid}`, { name: '王師' })
  const others = []
  for (let i = 1; i < SUBJECTS.length; i++) {
    others.push(await post(`/api/teachers?semester_id=${sid}`, { name: `師${i}` }))
  }
  const teacherOf = (i: number) => (i === 0 ? wang : others[i - 1])

  const aIds: number[] = []
  for (let i = 0; i < SUBJECTS.length; i++) {
    const s = await post(`/api/subjects?semester_id=${sid}`, { name: SUBJECTS[i] })
    const a = await post(`/api/assignments?semester_id=${sid}`, {
      class_id: c301.id, subject_id: s.id, periods_per_week: 5,
      teachers: [{ teacher_id: teacherOf(i).id, is_lead: true }], block_rules: [],
    })
    aIds.push(a.id)
  }
  const s302 = await post(`/api/subjects?semester_id=${sid}`, { name: '數學二' })
  const a302 = await post(`/api/assignments?semester_id=${sid}`, {
    class_id: c302.id, subject_id: s302.id, periods_per_week: 5,
    teachers: [{ teacher_id: wang.id, is_lead: true }], block_rules: [],
  })

  // ── 進入工作台(首次載入自動建立草稿)──
  await page.goto('/scheduling/workbench')
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 節')

  // 取得草稿 id,並讓王師在 302 班的週五第七節(period_no 9)先有課
  const tts = await (await page.request.get(`/api/timetables?semester_id=${sid}`)).json()
  const ttId = tts[0].id
  await page.request.post(`/api/timetables/${ttId}/entries`, {
    data: { course_assignment_id: a302.id, weekday: 5, period_no: 9, span: 1 },
  })
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

  // ── ① 衝突紅框:拖 301 國文(王師)到週五第七節 ──
  const tray國文 = page.getByTestId('wb-tray-國文')
  const conflictCell = cell(page, 5, 9)
  const drag = await dragOver(page, tray國文, conflictCell)
  await expect(conflictCell).toHaveClass(/is-conflict/)
  await expect(conflictCell).toContainText('教師王師')
  // 該格在寬表右側,整頁截圖看不到 → 直接截該格元素以便人工檢視紅框與原因
  await conflictCell.screenshot({ path: `${SHOTS}/wb-1-conflict-cell.png` })
  await page.screenshot({ path: `${SHOTS}/wb-1-conflict.png` })
  await drag.end()

  // ── ② 可放綠框 + 放入:週一第一節(period_no 2)──
  const okCell = cell(page, 1, 2)
  const d2 = await dragOver(page, tray國文, okCell)
  await expect(okCell).toHaveClass(/is-droppable/)
  await okCell.dispatchEvent('drop', { dataTransfer: d2.dt })
  await expect(okCell).toContainText('國文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 34 節')
  await page.screenshot({ path: `${SHOTS}/wb-2-placed.png` })

  // ── ③ Ctrl+Z 復原 ──
  await page.keyboard.press('Control+z')
  await expect(okCell).not.toContainText('國文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 節')

  // 重新放入供後續步驟使用
  await dragDrop(page, page.getByTestId('wb-tray-國文'), okCell)
  await expect(okCell).toContainText('國文')

  // ── ④ 點卡片鎖定 → 不可拖曳;再點解鎖 ──
  const card = okCell.locator('.tg-card')
  await card.click()
  await expect(okCell.locator('.tg-lock')).toBeVisible()
  await expect(card).toHaveAttribute('draggable', 'false')
  await card.click()
  await expect(okCell.locator('.tg-lock')).toHaveCount(0)
  await expect(card).toHaveAttribute('draggable', 'true')

  // ── ⑤ 拖回未排清單 → 移除 ──
  await dragDrop(page, card, page.getByTestId('wb-tray'))
  await expect(okCell).not.toContainText('國文')
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 35 節')

  // ── ⑥ 排完整班:其餘經 API 依計畫排入(每科一天一節,不觸發 H2/H10)──
  for (let i = 0; i < SUBJECTS.length; i++) {
    for (let d = 1; d <= 5; d++) {
      const r = await page.request.post(`/api/timetables/${ttId}/entries`, {
        data: { course_assignment_id: aIds[i], weekday: d, period_no: SLOTS[i], span: 1 },
      })
      expect(r.status(), `${SUBJECTS[i]} 週${d} 節次${SLOTS[i]}`).toBe(201)
    }
  }
  await page.reload()
  await page.locator('.n-base-selection').first().click()
  await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

  // 未排清單歸零(驗收①)
  await expect(page.getByTestId('wb-remaining')).toHaveText('剩 0 節')
  await expect(page.getByTestId('wb-tray-empty')).toBeVisible()
  await page.screenshot({ path: `${SHOTS}/wb-3-full.png` })

  // ── ⑦ 三視角一致(驗收②):班級視角排的課,教師視角立即可見 ──
  await page.getByTestId('wb-view-teacher').click()
  await page.getByTestId('wb-teacher').click()
  await page.locator('.n-base-select-option', { hasText: '王師' }).first().click()
  // 王師:301 國文(週一~週五第一節)+ 302 數學二(週五第七節)
  await expect(cell(page, 1, 2)).toContainText('國文')
  await expect(cell(page, 5, 9)).toContainText('數學二')
  await page.screenshot({ path: `${SHOTS}/wb-4-teacher-view.png` })

  await deleteSemesterByYearTerm(page, YEAR, 1)
})
