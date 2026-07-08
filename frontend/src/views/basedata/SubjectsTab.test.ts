import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import SubjectsTab from './SubjectsTab.vue'

const fakeSubjects = [
  { id: 1, semester_id: 1, name: '數學', domain: '數學領域', required_room_type: null, default_block_size: 2 },
  { id: 2, semester_id: 1, name: '國文', domain: null, required_room_type: null, default_block_size: 1 },
]

vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fakeSubjects) }),
))

describe('SubjectsTab', () => {
  it('載入並顯示科目清單', async () => {
    const Host = { render: () => h(NMessageProvider, () => h(SubjectsTab, { semesterId: 1 })) }
    const wrapper = mount(Host)
    await flushPromises()
    expect(wrapper.text()).toContain('數學')
    expect(wrapper.text()).toContain('國文')
    expect(wrapper.text()).toContain('2 連堂')
  })
})
