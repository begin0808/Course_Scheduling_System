import { mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import InitialPasswords from './InitialPasswords.vue'

// 姓名來自組長匯入的 Excel;列印通知單是把內容寫進新視窗,一定要先跳脫,免得被當成 HTML 執行
const accounts = [
  { name: '<img src=x onerror=alert(1)>', username: 'wang001', password: 'Ab3dEf7hJk9m' },
  { name: '李"小華', username: 'lee001', password: 'Zx8cVb2nMq4w' },
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
    expect(text).toContain('Ab3dEf7hJk9m')
    expect(text).toContain('Zx8cVb2nMq4w')
    expect(document.querySelectorAll('[data-testid="initial-password-row"]')).toHaveLength(2)
    wrapper.unmount()
  })

  it('列印通知單時姓名等內容會跳脫,不會被當成 HTML', () => {
    let written = ''
    const fake = { document: { write: (s: string) => { written += s }, close() {} }, focus() {}, print() {} }
    const open = vi.spyOn(window, 'open').mockReturnValue(fake as unknown as Window)
    const wrapper = mountDialog()
    ;(document.querySelector('[data-testid="initial-passwords-print"]') as HTMLElement).click()
    expect(open).toHaveBeenCalled()
    expect(written).toContain('&lt;img src=x onerror=alert(1)&gt;')
    expect(written).not.toContain('<img src=x')
    expect(written).toContain('李&quot;小華')
    expect(written).toContain('Ab3dEf7hJk9m')
    open.mockRestore()
    wrapper.unmount()
  })
})
