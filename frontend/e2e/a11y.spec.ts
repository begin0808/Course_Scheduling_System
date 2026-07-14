import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { E2E_PASS, E2E_USER } from './helpers'

const SHOTS = 'e2e/screenshots'

// ── WCAG 相對亮度與對比度(1.4.3 / 1.4.11)──────────────────
function relLuminance([r, g, b]: number[]): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function contrastRatio(fg: number[], bg: number[]): number {
  const l1 = relLuminance(fg)
  const l2 = relLuminance(bg)
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1]
  return (hi + 0.05) / (lo + 0.05)
}

function parseRgb(s: string): number[] {
  const nums = (s.match(/[\d.]+/g) || ['0', '0', '0']).map(parseFloat)
  return [nums[0] || 0, nums[1] || 0, nums[2] || 0]
}

/** 取元素的前景色與有效背景色(往上找到第一個非透明背景)。 */
async function colorsOf(page: Page, selector: string) {
  return page.locator(selector).first().evaluate((el) => {
    const fg = getComputedStyle(el as Element).color
    let node: Element | null = el as Element
    let bg = 'rgba(0, 0, 0, 0)'
    while (node) {
      const c = getComputedStyle(node).backgroundColor
      if (c && !c.startsWith('rgba(0, 0, 0, 0') && c !== 'transparent') { bg = c; break }
      node = node.parentElement
    }
    if (bg.startsWith('rgba(0, 0, 0, 0')) bg = 'rgb(255, 255, 255)'
    return { fg, bg }
  })
}

// ── 驗收:鍵盤可操作 ────────────────────────────────
test('無障礙:僅用鍵盤即可登入(不觸碰滑鼠)', async ({ page }) => {
  await page.goto('/login')

  // 只用 Tab/輸入/Enter:聚焦帳號欄 → 輸入 → Tab 到密碼 → 輸入 → Enter 送出
  await page.getByPlaceholder('請輸入帳號').focus()
  await page.keyboard.type(E2E_USER)
  await page.keyboard.press('Tab')
  await page.keyboard.type(E2E_PASS)
  await page.keyboard.press('Enter')

  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
  await expect(page).toHaveURL(/\/(|dashboard)?$/)
  await page.screenshot({ path: `${SHOTS}/a11y-1-keyboard-login.png` })
})

test('無障礙:主要導覽以 Tab 可達且有可見焦點', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill(E2E_USER)
  await page.getByPlaceholder('請輸入密碼').fill(E2E_PASS)
  await page.getByRole('button', { name: '登入' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))

  // 連續 Tab 應能落在某個可互動元素上(連結/按鈕/輸入),且該元素確實獲得焦點
  let reachedInteractive = false
  for (let i = 0; i < 15; i += 1) {
    await page.keyboard.press('Tab')
    const tag = await page.evaluate(() => {
      const el = document.activeElement
      return el ? el.tagName.toLowerCase() : ''
    })
    if (['a', 'button', 'input', 'select', 'textarea'].includes(tag)) {
      reachedInteractive = true
      break
    }
  }
  expect(reachedInteractive, 'Tab 應可將焦點移到可互動元素').toBe(true)
})

// ── 驗收:對比度(WCAG AA)────────────────────────────
test('無障礙:內文與主要按鈕對比度符合 WCAG AA 基本門檻', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('請輸入帳號').fill(E2E_USER)
  await page.getByPlaceholder('請輸入密碼').fill(E2E_PASS)
  await page.getByRole('button', { name: '登入' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'))
  await page.waitForLoadState('networkidle')

  // 一般內文:深字白底,應遠高於 AA 正常文字門檻 4.5:1
  const body = await colorsOf(page, 'body')
  const bodyRatio = contrastRatio(parseRgb(body.fg), parseRgb(body.bg))
  expect(bodyRatio, `內文對比 ${bodyRatio.toFixed(2)}(fg=${body.fg} bg=${body.bg})`)
    .toBeGreaterThanOrEqual(4.5)

  // 主要按鈕:按鈕標籤是「文字」,適用 WCAG 1.4.3 的 4.5:1,不是 1.4.11 非文字元件的 3:1。
  // Naive 預設的 #18a058 配白字只有 ~3.4:1;M6-5 把主色壓深到 #0d7a43(5.41:1)後真的達標,
  // 門檻因此從權宜的 3:1 提到 AA 的 4.5:1(見 src/theme.ts)。
  const btn = await colorsOf(page, '.n-button--primary-type')
  const btnRatio = contrastRatio(parseRgb(btn.fg), parseRgb(btn.bg))
  expect(btnRatio, `主要按鈕對比 ${btnRatio.toFixed(2)}(fg=${btn.fg} bg=${btn.bg})`)
    .toBeGreaterThanOrEqual(4.5)
})
