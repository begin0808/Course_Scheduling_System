import fs from 'node:fs'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'

// 操作示範影片的「導演」:滑鼠游標、平滑移動點擊、逐段計時。
//
// 流程(scripts/video/build_video.py 串起來):
//   1) 先用語音合成把每段旁白念出來,量出每段長度 → <out>/durations.json
//   2) 本模組照段落操作畫面:每段開始記下時間點,動作做完後,停到旁白念完為止 → <out>/timeline.json
//   3) 再把每段語音放到對應的時間點、燒上字幕,合成 MP4。
// 因為畫面一定等旁白念完才進下一段,聲音與畫面不會錯開。

export interface Segment { id: string; text: string; say?: string }
/** 示範用匯入檔:build_video.py 寫成 xlsx,錄影時也用同一份內容畫出試算表畫面。 */
export interface Fixture {
  label: string; columns: string[]; rows: string[][]
  show?: number      // 畫面上只畫前幾欄
  showRows?: number  // 畫面上只畫前幾列,其餘以 ⋮ 表示
}
export interface Script {
  title: string; subtitle: string; segments: Segment[]; fixtures?: Record<string, Fixture>
}

const GAP_MS = 600 // 段與段之間留一點空檔,聽起來不趕

/** 在每個頁面注入假游標與點擊圓圈(錄影本身不會錄到系統游標)。 */
const CURSOR_SCRIPT = `
(() => {
  if (window.__demoCursor) return
  window.__demoCursor = true
  const css = document.createElement('style')
  css.textContent = \`
    #demo-cursor { position: fixed; z-index: 2147483647; pointer-events: none; width: 26px; height: 26px;
      left: -40px; top: -40px; transition: transform .08s ease-out; }
    .demo-ripple { position: fixed; z-index: 2147483646; pointer-events: none; width: 34px; height: 34px;
      margin: -17px 0 0 -17px; border-radius: 50%; border: 3px solid rgba(232, 93, 4, .9);
      animation: demo-ripple .6s ease-out forwards; }
    @keyframes demo-ripple { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.6); opacity: 0 } }
  \`
  const cur = document.createElement('div')
  cur.id = 'demo-cursor'
  cur.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2 L4 20 L9 15.5 L12.5 22 L15.5 20.5 L12 14 L19 14 Z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>'
  const mount = () => { if (document.body && !cur.isConnected) { document.head.appendChild(css); document.body.appendChild(cur) } }
  document.addEventListener('DOMContentLoaded', mount)
  mount()
  addEventListener('mousemove', (e) => { mount(); cur.style.left = e.clientX - 4 + 'px'; cur.style.top = e.clientY - 2 + 'px' }, true)
  addEventListener('mousedown', (e) => {
    const r = document.createElement('div'); r.className = 'demo-ripple'
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'
    document.body.appendChild(r); setTimeout(() => r.remove(), 700)
  }, true)
  // 列印頁原本開新分頁;影片只錄得到同一個分頁,改成在原分頁開啟
  window.open = (url) => { if (url) location.href = String(url); return null }
})()
`

export class Director {
  private t0 = Date.now()
  private timeline: { id: string; start: number; end: number }[] = []
  private durations: Record<string, number>
  private mouse = { x: 640, y: 360 }

  constructor(private page: Page, private outDir: string) {
    const f = path.join(outDir, 'durations.json')
    if (!fs.existsSync(f)) throw new Error(`找不到 ${f}:請用 scripts/video/build_video.py 執行(要先產生語音)`)
    this.durations = JSON.parse(fs.readFileSync(f, 'utf8'))
  }

  static async setup(page: Page) {
    await page.addInitScript(CURSOR_SCRIPT)
  }

  private syncMs = 0

  /** 錄影從頁面建立就開始;以此為零點。 */
  markStart() { this.t0 = Date.now() }

  /**
   * 對時記號:畫面先全黑一下,接著(片頭字卡)一出現就是 syncMs 這個時間點。
   * 合成時在錄影裡找「黑畫面變亮」的那一格對齊聲音,並把它之前的空白剪掉。
   * (錄影實際開始與結束的時間都抓不準,只靠總長度推算會讓聲音慢將近一秒。)
   * 一定要緊接在第一段(片頭字卡)之前呼叫。
   */
  async sync() {
    await this.page.setContent('<!doctype html><body style="margin:0;background:#000"></body>')
    await this.page.waitForTimeout(600)
    this.syncMs = Date.now() - this.t0
  }

  /** 一段旁白:記下開始時間,做完動作後停到旁白念完。 */
  async seg(id: string, actions: () => Promise<void> = async () => {}) {
    const dur = this.durations[id]
    if (dur === undefined) throw new Error(`durations.json 沒有段落 ${id}`)
    const start = Date.now() - this.t0
    await actions()
    const left = start + dur * 1000 + GAP_MS - (Date.now() - this.t0)
    if (left > 0) await this.page.waitForTimeout(left)
    this.timeline.push({ id, start, end: Date.now() - this.t0 })
  }

  /** 游標平滑移到元素中央(看得出點哪裡),停一下再點。 */
  async click(target: Locator, opts: { pause?: number } = {}) {
    await target.scrollIntoViewIfNeeded()
    const box = await target.boundingBox()
    if (!box) throw new Error('元素不在畫面上')
    const x = box.x + box.width / 2
    const y = box.y + box.height / 2
    await this.moveTo(x, y)
    await this.page.waitForTimeout(opts.pause ?? 250)
    await this.page.mouse.click(x, y)
    await this.page.waitForTimeout(350)
  }

  async moveTo(x: number, y: number) {
    const dist = Math.hypot(x - this.mouse.x, y - this.mouse.y)
    await this.page.mouse.move(x, y, { steps: Math.max(8, Math.min(40, Math.round(dist / 25))) })
    this.mouse = { x, y }
  }

  /** 游標移到元素上停留(提示「看這裡」),不點。 */
  async point(target: Locator, hold = 600) {
    await target.scrollIntoViewIfNeeded()
    const box = await target.boundingBox()
    if (!box) return
    await this.moveTo(box.x + Math.min(box.width / 2, 120), box.y + box.height / 2)
    await this.page.waitForTimeout(hold)
  }

  /** 點左側選單:group 是上層(收合時先展開),label 是要進去的那一頁。 */
  async menu(group: string, label: string) {
    const exact = (t: string) =>
      this.page.locator('.n-menu-item-content-header', { hasText: new RegExp(`^${t}$`) }).first()
    const item = exact(label)
    if (!(await item.isVisible())) await this.click(exact(group))
    await this.click(item)
    await this.page.waitForLoadState('networkidle')
  }

  /** 下拉選單選一項(Naive UI 的 n-select)。 */
  async pick(select: Locator, option: string) {
    await this.click(select)
    await this.click(this.page.locator('.n-base-select-option', { hasText: option }).first())
  }

  /** 一個字一個字打進輸入框。 */
  async type(target: Locator, text: string) {
    await this.click(target)
    await target.pressSequentially(text, { delay: 90 })
  }

  /** 片頭/片尾字卡(直接在頁面上畫,不另外合成)。 */
  async card(title: string, sub: string) {
    const subtitle = sub.replace(/,/g, '，').replace(/;/g, '；').replace(/:/g, '：')
    await this.page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{margin:0;height:100%;background:#f7f3ec;font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif}
      .wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px}
      .eyebrow{letter-spacing:.3em;color:#c2410c;font-size:20px}
      h1{margin:0;font-size:64px;color:#1f2937} p{margin:0;font-size:28px;color:#4b5563}
      .bar{width:120px;height:6px;border-radius:3px;background:#0f7a43}
    </style></head><body><div class="wrap"><div class="eyebrow">排課與調代課系統 · 操作示範</div>
      <h1>${title}</h1><div class="bar"></div><p>${subtitle}</p></div></body></html>`)
  }

  // 疊層不做淡入動畫:錄影只在頁面重繪時取格,畫面靜止時會停在淡入的第一格(半透明)

  /** 在畫面上蓋一張「Excel 試算表」,示範範本填好的樣子(影片裡看不到真的 Excel)。 */
  async sheet(fx: Fixture) {
    const cols = fx.show ? fx.columns.slice(0, fx.show) : fx.columns
    const cut = (r: string[]) => (fx.show ? r.slice(0, fx.show) : r)
    const letters = cols.map((_, i) => String.fromCharCode(65 + i))
    const tr = (n: number | string, cells: string[], cls = '') =>
      `<tr class="${cls}"><th>${n}</th>${cells.map((c) => `<td>${c}</td>`).join('')}</tr>`
    const body = [
      tr(1, cols, 'head'),
      tr(2, cols.map(() => '(說明)'), 'muted'),
      tr(3, cols.map(() => '(範例)'), 'muted'),
      ...fx.rows.slice(0, fx.showRows ?? fx.rows.length).map((r, i) => tr(i + 4, cut(r))),
      ...(fx.showRows && fx.rows.length > fx.showRows
        ? [tr('⋮', cols.map(() => '⋮'), 'muted')] : []),
    ].join('')
    await this.page.evaluate(({ label, letters, body }) => {
      document.getElementById('demo-sheet')?.remove()
      const el = document.createElement('div')
      el.id = 'demo-sheet'
      el.innerHTML = `<style>
        #demo-sheet{position:fixed;inset:0;z-index:2147483640;background:rgba(15,23,42,.45);display:flex;
          align-items:center;justify-content:center;font-family:"Microsoft JhengHei",sans-serif}
        #demo-sheet .win{background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.35);max-width:1180px}
        #demo-sheet .bar{background:#107c41;color:#fff;padding:9px 16px;font-size:17px;letter-spacing:.05em}
        #demo-sheet table{border-collapse:collapse;font-size:18px}
        #demo-sheet th,#demo-sheet td{border:1px solid #d4d4d8;padding:6px 14px;white-space:nowrap;text-align:left}
        #demo-sheet th{background:#f3f4f6;color:#6b7280;font-weight:normal;text-align:center;min-width:28px}
        #demo-sheet tr.head td{font-weight:bold;background:#f9fafb}
        #demo-sheet tr.muted td{color:#9ca3af;font-size:15px}
      </style><div class="win"><div class="bar">${label}</div><table>
        <tr><th></th>${letters.map((l: string) => `<th>${l}</th>`).join('')}</tr>${body}</table></div>`
      document.body.appendChild(el)
    }, { label: fx.label, letters, body })
  }

  /** 把下載下來的圖片蓋在畫面上(示範「匯出的檔案長這樣」)。 */
  async image(file: string, label: string) {
    const src = `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`
    await this.page.evaluate(({ src, label }) => {
      document.getElementById('demo-sheet')?.remove()
      const el = document.createElement('div')
      el.id = 'demo-sheet'
      el.innerHTML = `<style>
        #demo-sheet{position:fixed;inset:0;z-index:2147483640;background:rgba(15,23,42,.55);display:flex;
          align-items:center;justify-content:center;font-family:"Microsoft JhengHei",sans-serif}
        #demo-sheet .win{background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.35);
          max-height:620px}
        #demo-sheet .bar{background:#334155;color:#fff;padding:8px 16px;font-size:16px}
        /* 匯出的是直式 A4,課表在上半張:放大、只露出上半部 */
        #demo-sheet img{display:block;width:900px}
      </style><div class="win"><div class="bar">${label}</div><img src="${src}"></div>`
      document.body.appendChild(el)
    }, { src, label })
  }

  async hideSheet() {
    await this.page.evaluate(() => document.getElementById('demo-sheet')?.remove())
  }

  save() {
    fs.writeFileSync(path.join(this.outDir, 'timeline.json'),
      JSON.stringify({ sync: this.syncMs, end: Date.now() - this.t0, segments: this.timeline }, null, 2))
  }
}

export function loadScript(name: string): Script {
  return JSON.parse(fs.readFileSync(path.resolve('e2e/video', `${name}.json`), 'utf8'))
}
