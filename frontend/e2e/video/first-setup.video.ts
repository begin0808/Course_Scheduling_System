import path from 'node:path'
import { expect, test } from '@playwright/test'
import { iso } from '../dates'
import { ADMIN, INIT_PW, PW } from '../demo-school'
import { Director, loadScript } from './director'

// 操作示範影片 02:第一次設定。請用 scripts/video/build_video.py first-setup 執行。
// 需要一個「完全空白」的示範站(docker compose -p manual down -v 後重新 up,ADMIN_PASSWORD=DemoSetup2026!):
// 影片從首次登入改密碼開始,一路走完設定精靈。錄完之後,這個站就是 03(配課與自動排課)的起點。

const OUT = process.env.VIDEO_OUT ?? ''
const BASE = process.env.E2E_BASE_URL || 'http://localhost:8120'
const SIZE = { width: 1280, height: 720 }

test.use({ baseURL: BASE })

test('錄影:第一次設定', async ({ browser, request }) => {
  test.setTimeout(600_000)
  expect(OUT, '請用 scripts/video/build_video.py 執行').toBeTruthy()
  const probe = await request.post(`${BASE}/api/auth/login`, { data: { username: ADMIN, password: INIT_PW } })
  expect(probe.ok(), '示範站不是全新的(admin 已改過密碼):請 down -v 後重起').toBeTruthy()
  // 剛才那次登入不算數:用新的瀏覽器分頁從登入頁開始

  const script = loadScript('first-setup')
  const fx = script.fixtures ?? {}
  const ctx = await browser.newContext({
    baseURL: BASE, viewport: SIZE, recordVideo: { dir: OUT, size: SIZE }, locale: 'zh-TW',
  })
  const page = await ctx.newPage()
  const d = new Director(page, OUT)
  d.markStart()
  await Director.setup(page)

  // 學期:下週起算半年(跟 demo-school 一樣),後面幾支影片的請假日期才不會落在學期外
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setMonth(end.getMonth() + 5)

  const next = () => d.click(page.getByTestId('wizard-next'))
  const radio = (label: string) => page.locator('.n-radio-button', { hasText: label }).first()
  const upload = async (file: string) => {
    const [chooser] = await Promise.all([
      page.waitForEvent('filechooser'),
      d.click(page.getByRole('button', { name: '選擇檔案' })),
    ])
    await chooser.setFiles(path.join(OUT, file))
    await page.waitForTimeout(600)
    await d.click(page.getByRole('button', { name: '開始匯入' }))
    const ok = page.getByTestId('import-ok')
    await expect(ok).toBeVisible({ timeout: 20_000 })
    // 成功訊息在頁面下方,會被字幕擋住:捲到畫面中間
    await ok.evaluate((e) => e.scrollIntoView({ block: 'center', behavior: 'smooth' }))
  }
  const clearUpload = async () => {
    // 上傳元件只收一個檔:換類型前先把上一個檔移掉
    const item = page.locator('.n-upload-file').first()
    if (await item.count()) {
      await item.hover()
      await d.click(item.locator('button').last())
    }
  }

  await d.seg('intro', async () => {
    await d.card(script.title, script.subtitle)
  })
  await page.goto('/login')
  await page.waitForLoadState('networkidle')

  await d.seg('login', async () => {
    await d.type(page.getByPlaceholder('請輸入帳號'), ADMIN)
    await d.type(page.getByPlaceholder('請輸入密碼'), INIT_PW)
    await page.waitForTimeout(1800) // 讓登入畫面多停一下,旁白念完再進改密頁
    await d.click(page.getByRole('button', { name: '登入' }))
    await expect(page.getByTestId('cp-forced')).toBeVisible({ timeout: 20_000 })
  })
  await d.seg('change-pw', async () => {
    await d.type(page.getByTestId('cp-old').locator('input'), INIT_PW)
    await d.type(page.getByTestId('cp-new').locator('input'), PW)
    await d.type(page.getByTestId('cp-confirm').locator('input'), PW)
    await d.click(page.getByTestId('cp-submit'))
    await expect(page.getByTestId('tpl-junior_high')).toBeVisible({ timeout: 20_000 })
  })
  await d.seg('wizard', async () => {
    await page.waitForTimeout(800)
    await d.point(page.getByTestId('wizard-demo-load'), 2500)
  })
  await d.seg('template', async () => {
    await d.click(page.getByTestId('tpl-junior_high'))
    await page.waitForTimeout(800)
    await next()
  })
  await d.seg('semester', async () => {
    await d.point(page.getByTestId('wizard-year'), 1200)
    for (const [id, day] of [['wizard-start', start], ['wizard-end', end]] as const) {
      const input = page.getByTestId(id).locator('input')
      await d.click(input)
      await input.pressSequentially(iso(day), { delay: 70 })
      await input.press('Enter')
    }
    await page.waitForTimeout(600)
  })
  await d.seg('period', async () => {
    await next()
    await expect(page.getByRole('button', { name: '開啟節次表編輯器' })).toBeVisible({ timeout: 20_000 })
    await page.waitForTimeout(1500)
    await d.point(page.getByRole('button', { name: '開啟節次表編輯器' }), 1500)
  })
  await d.seg('import-intro', async () => {
    await next()
    await expect(radio('教師')).toBeVisible({ timeout: 20_000 })
    await d.point(page.locator('.n-alert').first(), 1500)
  })
  await d.seg('teachers-download', async () => {
    await d.click(radio('教師'))
    await page.waitForTimeout(400)
    await d.click(page.getByRole('button', { name: /下載「教師」範本/ }))
  })
  await d.seg('teachers-sheet', async () => {
    await d.sheet(fx['teachers.xlsx'])
  })
  await d.seg('teachers-upload', async () => {
    await d.hideSheet()
    await upload('teachers.xlsx')
  })
  await d.seg('classes-sheet', async () => {
    await clearUpload()
    await d.click(radio('班級'))
    await page.waitForTimeout(400)
    await d.click(page.getByRole('button', { name: /下載「班級」範本/ }))
    await page.waitForTimeout(2000)
    await d.sheet(fx['classes.xlsx'])
  })
  await d.seg('classes-upload', async () => {
    await d.hideSheet()
    await upload('classes.xlsx')
  })
  await d.seg('summary', async () => {
    await next()
    await expect(page.getByTestId('wizard-finish')).toBeVisible({ timeout: 20_000 })
    await d.point(page.locator('.n-statistic').nth(1), 1500)
  })
  await d.seg('finish', async () => {
    await d.click(page.getByTestId('wizard-finish'))
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(1500)
  })
  await d.seg('outro', async () => {
    await d.card('設定完成', '下一支影片:03 配課與自動排課')
  })

  d.save()
  const video = page.video()
  await ctx.close()
  await video?.saveAs(`${OUT}/screen.webm`)
})
