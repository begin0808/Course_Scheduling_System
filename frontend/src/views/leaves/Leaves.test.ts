import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import Leaves from './Leaves.vue'

const MAX_LEAVE_ROWS = 1000

const leave = (id: number) => ({
  id, semester_id: 1, teacher_id: 1, teacher_name: '王師', leave_type: 'sick',
  leave_type_label: '病假', start_date: '2026-09-02', start_time: null,
  end_date: '2026-09-02', end_time: null, reason: '', status: 'registered',
  created_by_name: 'admin', created_at: '2026-09-01T08:00:00',
  affected_count: 0, pending_count: 0, affected_periods: [],
})

function stubFetch(rows: number) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: unknown = Array.from({ length: rows }, (_, i) => leave(i + 1))
    if (url.includes('/leave-types')) body = { sick: '病假' }
    else if (url.includes('/teachers')) body = []
    else if (url.includes('/semesters')) body = [{ id: 1, label: '149 學年度第 1 學期' }]
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

async function mountLeaves(rows: number) {
  stubFetch(rows)
  const Host = { render: () => h(NMessageProvider, () => h(Leaves)) }
  const wrapper = mount(Host, { global: { plugins: [createPinia()] } })
  await flushPromises()
  return wrapper
}

describe('Leaves 清單上限', () => {
  it('取到上限筆數時提示被截斷', async () => {
    const wrapper = await mountLeaves(MAX_LEAVE_ROWS)
    expect(wrapper.find('[data-testid="lv-truncated"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('只顯示最新的 1000 張假單')
  })

  it('未達上限時不提示', async () => {
    const wrapper = await mountLeaves(2)
    expect(wrapper.find('[data-testid="lv-truncated"]').exists()).toBe(false)
  })
})
