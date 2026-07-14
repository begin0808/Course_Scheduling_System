import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SubstitutionLog from './SubstitutionLog.vue'

// 後端取到上限筆數就代表「還有更早的沒列出來」。不講的話,組長會以為這學期就只有這些紀錄。
const MAX_ROWS = 1000

const entry = (id: number) => ({
  affected_period_id: id, date: '2026-09-02', weekday: 3, period_no: 1, period_name: '第一節',
  start_time: null, end_time: null, class_names: '701', subject_name: '國文', room_name: '',
  absent_teacher_id: 1, absent_teacher_name: '王師', leave_type: 'sick', leave_type_label: '病假',
  status: 'pending', status_label: '待處理', disposed: false, sub_type: null, sub_type_label: null,
  handler_teacher_id: null, handler_name: null, counts_toward_hours: null, swap_date: null,
  swap_period_name: '', swap_class_names: '', swap_subject_name: '', note: '',
})

function stubFetch(rows: number) {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    let body: unknown = Array.from({ length: rows }, (_, i) => entry(i + 1))
    if (url.includes('/leave-types')) body = { sick: '病假' }
    else if (url.includes('/teachers')) body = []
    else if (url.includes('/semesters')) body = [{ id: 1, label: '149 學年度第 1 學期' }]
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

async function mountLog(rows: number) {
  stubFetch(rows)
  const wrapper = mount(SubstitutionLog)
  await flushPromises()
  return wrapper
}

describe('SubstitutionLog 查詢上限', () => {
  it('取到上限筆數時提示被截斷,並告訴使用者怎麼看到更早的', async () => {
    const wrapper = await mountLog(MAX_ROWS)
    expect(wrapper.find('[data-testid="log-truncated"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('只顯示最新的 1000 筆')
    expect(wrapper.text()).toContain('縮小日期區間')
  })

  it('未達上限時不提示(否則每次查詢都在喊狼來了)', async () => {
    const wrapper = await mountLog(3)
    expect(wrapper.find('[data-testid="log-truncated"]').exists()).toBe(false)
  })
})
