import path from 'node:path'
import { expect, test } from '@playwright/test'
import { YEAR, TERM, get, loginAsAdmin } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片 03:配課與自動排課。請用 scripts/video/build_video.py assign-schedule 執行。
// 起點是剛錄完 02(first-setup)的示範站:已有學期、8 位教師、3 個班,還沒有任何配課。
// 錄完之後站上就有已發布的課表,接著可以錄 04(leave-substitute)。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }

test.use({ baseURL: BASE })

test('錄影:配課與自動排課', async ({ browser }) => {
  test.setTimeout(900_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const script = loadScript('assign-schedule')
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)
  await loginAsAdmin(page)

  const sem = (await get(page, '/api/semesters'))
    .find((s: { academic_year: number; term: number }) => s.academic_year === YEAR && s.term === TERM)
  expect(sem, '示範站沒有學期:請先錄 02(first-setup)').toBeTruthy()
  const existing = await get(page, `/api/assignments?semester_id=${sem.id}`)
  expect(existing.length, '示範站已經有配課:請從 02 重新開始(down -v)').toBe(0)

  await d.sync()
  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  await d.seg('open-assign', async () => {
    await page.waitForTimeout(500)
    await d.menu('排課作業', '配課管理')
    await d.point(page.getByTestId('teacher-load'), 1200)
  })
  const modal = page.locator('.n-modal').last()
  await d.seg('add-form', async () => {
    await d.click(page.getByTestId('assignment-add'))
    await expect(modal).toBeVisible()
    await d.pick(page.getByTestId('a-class'), '701')
    await d.pick(page.getByTestId('a-subject'), '國文')
    await d.pick(page.getByTestId('a-teachers'), '王大明')
    await page.keyboard.press('Escape') // 多選的下拉不會自己收起來
    await expect(modal).toBeVisible()
    const periods = page.getByTestId('a-periods').locator('input')
    await d.click(periods)
    await periods.press('Control+A')
    await periods.pressSequentially('5', { delay: 120 })
  })
  await d.seg('block', async () => {
    await d.point(page.getByTestId('a-add-block'), 2000)
    await d.click(page.getByTestId('a-save'))
  })
  await d.seg('saved', async () => {
    await expect(page.locator('.data-table td', { hasText: '王大明' }).first()).toBeVisible({ timeout: 20_000 })
    await d.point(page.locator('.data-table tbody tr').first(), 800)
  })

  await d.seg('import-open', async () => {
    await d.menu('基礎資料', '教師/班級/科目/場地')
    await d.click(page.locator('.n-tabs-tab', { hasText: '批次匯入' }).first())
    await d.click(page.locator('.n-radio-button', { hasText: '配課' }).first())
    await page.waitForTimeout(300)
    await d.click(page.getByRole('button', { name: /下載「配課」範本/ }))
  })
  await d.seg('import-sheet', async () => {
    await d.sheet(script.fixtures!['assignments.xlsx'])
  })
  await d.seg('import-upload', async () => {
    await d.hideSheet()
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      d.click(page.getByRole('button', { name: '選擇檔案' })),
    ])
    await chooser.setFiles(path.join(OUT, 'assignments.xlsx'))
    await page.waitForTimeout(500)
    await d.click(page.getByRole('button', { name: '開始匯入' }))
    const ok = page.getByTestId('import-ok')
    await expect(ok).toBeVisible({ timeout: 20_000 })
    await ok.evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' }))
  })

  await d.seg('load', async () => {
    await d.menu('排課作業', '配課管理')
    await expect(page.getByTestId('teacher-load')).toContainText('剛好')
    await page.waitForTimeout(600)
    await d.point(page.getByTestId('teacher-load'), 1500)
    await d.point(page.getByTestId('teacher-load').locator('.n-tag', { hasText: '超鐘點' }).first(), 1500)
  })

  await d.seg('auto-open', async () => {
    await d.menu('排課作業', '自動排課')
    await expect(page.getByTestId('as-start')).toBeEnabled({ timeout: 20_000 })
    await d.point(page.getByText('排課前置檢查').first(), 1500)
  })
  await d.seg('auto-run', async () => {
    await d.click(page.getByTestId('as-start'))
    await expect(page.getByTestId('as-job')).toBeVisible({ timeout: 20_000 })
    // 小學校通常幾秒就排完;還在跑的話,示範按「提前結束」
    const stop = page.getByTestId('as-stop')
    const done = page.getByTestId('as-done')
    for (let i = 0; i < 120 && !(await done.isVisible()); i++) {
      if (i >= 8 && (await stop.isVisible()) && (await stop.isEnabled())) {
        await d.click(stop)
        break
      }
      await page.waitForTimeout(500)
    }
    await expect(done).toBeVisible({ timeout: 120_000 })
  })
  let draftName = ''
  await d.seg('auto-done', async () => {
    draftName = ((await page.getByTestId('as-done').textContent()) ?? '').match(/「(.+?)」/)?.[1] ?? ''
    expect(draftName).toBeTruthy()
    await d.point(page.getByTestId('as-done'), 1500)
    await page.getByTestId('as-report').evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' }))
    await page.waitForTimeout(800)
    await d.point(page.getByTestId('as-report').locator('tr', { hasText: 'S2' }), 1500)
  })
  const row = () => page.getByTestId(`v-row-${draftName}`)
  await d.seg('versions', async () => {
    await page.getByTestId('as-done').evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' }))
    await page.waitForTimeout(500)
    await d.click(page.getByTestId('as-done').getByRole('button', { name: '前往版本與發布' }))
    await expect(row()).toBeVisible({ timeout: 20_000 })
    await d.point(page.locator('.n-menu-item-content-header', { hasText: /^排課工作台$/ }).first(), 1800)
    await d.point(row().getByTestId('v-publish'), 800)
  })
  await d.seg('published', async () => {
    await d.click(row().getByTestId('v-publish'))
    const force = page.getByTestId('v-force-publish')
    await expect(page.getByTestId(`v-status-${draftName}`).or(force)).toBeVisible()
    if (await force.isVisible()) await d.click(force)
    await expect(page.getByTestId(`v-status-${draftName}`)).toHaveText('已發布', { timeout: 20_000 })
    await d.point(page.getByTestId(`v-status-${draftName}`), 1200)
  })
  await d.seg('query', async () => {
    await d.click(page.locator('.n-menu-item-content-header', { hasText: /^課表查詢$/ }).first())
    await page.waitForLoadState('networkidle')
    await expect(page.getByTestId('tq-grid')).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1200)
    await d.click(page.getByTestId('tq-view-teacher'))
    await page.waitForTimeout(1500)
    await d.point(page.getByTestId('export-xlsx'), 1000)
  })
  await d.seg('outro', async () => {
    await d.card('排課完成', '下一支影片:04 請假與代課')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
