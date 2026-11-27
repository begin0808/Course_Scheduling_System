import { mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import InitialPasswords from './InitialPasswords.vue'

// 測試用密碼執行時隨機產生(v1.7.1,程式碼不寫死密碼字串)
const randomPassword = () => crypto.randomUUID().replace(/-/g, '').slice(0, 12)
// 姓名來自組長匯入的 Excel,通知單上要原樣顯示、不能被當成 HTML 執行
const accounts = [
  { name: '<img src=x onerror=alert(1)>', username: 'wang001', password: randomPassword() },
  { name: '李"小華', username: 'lee001', password: randomPassword() },
]

function mountDialog() {
  const Wrapper = defineComponent(() => () => h(NMessageProvider, null, {
    default: () => h(InitialPasswords, { accounts, show: true }),
  }))
  return mount(Wrapper, { attachTo: document.body })
}

describe('InitialPasswords', () => {
  it('列出每個帳號的初始密碼,並提醒只顯示這一次', () => {
    const wrapper = mountDialog()
    const text = document.body.textContent ?? ''
    expect(text).toContain('只顯示這一次')
    expect(text).toContain(accounts[0].password)
    expect(text).toContain(accounts[1].password)
    expect(document.querySelectorAll('[data-testid="initial-password-row"]')).toHaveLength(2)
    wrapper.unmount()
  })

  it('列印通知單印的是本頁的通知單,姓名等內容不會被當成 HTML', () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    const open = vi.spyOn(window, 'open')
    const wrapper = mountDialog()
    ;(document.querySelector('[data-testid="initial-passwords-print"]') as HTMLElement).click()
    expect(print).toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled() // 不再開新視窗寫入密碼
    const slips = document.querySelector('[data-testid="initial-passwords-slips"]') as HTMLElement
    expect(slips.parentElement).toBe(document.body) // 放在 body 底下,列印樣式才能只留它
    expect(slips.querySelectorAll('.slip')).toHaveLength(2)
    expect(slips.querySelector('img')).toBeNull()
    expect(slips.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(slips.textContent).toContain('李"小華')
    expect(slips.textContent).toContain(accounts[0].password)
    print.mockRestore()
    open.mockRestore()
    wrapper.unmount()
  })
})
