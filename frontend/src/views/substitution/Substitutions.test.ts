import { flushPromises, mount } from '@vue/test-utils'
import { NMessageProvider } from 'naive-ui'
import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import Substitutions from './Substitutions.vue'

// 調課的前端只做兩件事:把後端算好的可對調節次列出來,點一下把「對調誰、哪一節、哪一天」送回去。
// 送錯任何一個欄位,後端都會驗到別的組合,所以這裡把送出的內容釘死。

const affected = {
  id: 11, date: '2026-10-07', weekday: 3, period_no: 2, period_name: '第一節',
  start_time: null, end_time: null, subject_name: '國文', class_names: '701', room_name: '',
  status: 'pending', handler_teacher_id: null, handler_name: null, sub_type: null,
  swap_date: null, swap_period_name: '',
}
const leave = {
  id: 5, semester_id: 1, teacher_id: 1, teacher_name: '王師', leave_type: 'sick',
  leave_type_label: '病假', start_date: '2026-10-07', start_time: null, end_date: '2026-10-07',
  end_time: null, reason: '', status: 'registered', created_by_name: 'admin',
  created_at: '2026-10-01T08:00:00', affected_count: 1, pending_count: 1,
  affected_periods: [affected],
}
const swapOptions = {
  affected_period_id: 11, date_from: '2026-10-05', date_to: '2026-10-18',
  partners: [
    {
      teacher_id: 2, teacher_name: '陳師', teaches_same_class: true, blocked_reason: '',
      options: [{
        entry_id: 77, date: '2026-10-08', weekday: 4, period_no: 3, period_name: '第二節',
        class_names: '701', subject_name: '數學', same_class: true, in_block: false,
      }, {
        entry_id: 78, date: '2026-10-14', weekday: 3, period_no: 3, period_name: '第二節',
        class_names: '702', subject_name: '自然', same_class: false, in_block: true,
      }],
    },
    {
      teacher_id: 3, teacher_name: '林師', teaches_same_class: true,
      blocked_reason: '林師 2026-10-07 第一節 該時段有自己的課', options: [],
    },
  ],
}

function stubFetch() {
  const calls: { url: string; method: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn((url: string, init: RequestInit) => {
    calls.push({ url, method: init.method ?? 'GET', body: init.body && JSON.parse(String(init.body)) })
    let body: unknown = []
    if (url.includes('/swap-options')) body = swapOptions
    else if (url.includes('/recommendations')) {
      body = { affected_period_id: 11, candidates: [], no_candidate_hint: '無人可代' }
    } else if (url.includes('/substitution-types')) body = { swap: '調課' }
    else if (url.includes('/semesters')) body = [{ id: 1, label: '115 學年度第 1 學期' }]
    else if (url.includes('/teachers')) body = []
    else if (url.includes('/leaves')) body = [leave]
    else if (url.includes('/substitution')) body = { id: 1 }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
  return calls
}

async function openSwap() {
  const calls = stubFetch()
  const wrapper = mount({ render: () => h(NMessageProvider, () => h(Substitutions)) })
  await flushPromises()
  await wrapper.find('[data-testid="sub-handle"]').trigger('click')
  await flushPromises()
  await wrapper.find('[data-testid="sub-swap"]').trigger('click')
  await flushPromises()
  return { wrapper, calls }
}

describe('調代課處理:調課', () => {
  it('列出可對調節次,來不了的老師說明原因', async () => {
    const { wrapper } = await openSwap()
    const partners = wrapper.findAll('[data-testid="sub-swap-partner"]')
    expect(partners).toHaveLength(2)
    expect(partners[0].text()).toContain('10/8(週四) 第二節')
    expect(partners[1].text()).toContain('無法對調')
    expect(partners[1].text()).toContain('該時段有自己的課')
  })

  it('先只列同班節次,其他班收起來,展開後才出現', async () => {
    const { wrapper } = await openSwap()
    const first = () => wrapper.findAll('[data-testid="sub-swap-partner"]')[0]
    expect(first().findAll('[data-testid="sub-swap-option"]')).toHaveLength(1)
    expect(first().text()).toContain('顯示其他班級的 1 個節次')

    await first().find('[data-testid="sub-swap-more"]').trigger('click')
    await flushPromises()
    const opts = first().findAll('[data-testid="sub-swap-option"]')
    expect(opts).toHaveLength(2)
    expect(opts[1].text()).toContain('連堂之一')
    expect(first().find('[data-testid="sub-swap-more"]').exists()).toBe(false)
  })

  it('預設找兩週,放寬週數後重新查詢', async () => {
    const { wrapper, calls } = await openSwap()
    const swapCalls = () => calls.filter((c) => c.url.includes('/swap-options'))
    expect(swapCalls()[0].url).toContain('weeks=2')

    const Swap = wrapper.findComponent(Substitutions)
    await (Swap.vm as unknown as { onSwapWeeksChange: (p: unknown, w: number) => Promise<void> })
      .onSwapWeeksChange({ id: 11 }, 4)
    await flushPromises()
    expect(swapCalls().at(-1)?.url).toContain('weeks=4')
  })

  it('點選節次送出調課:對調老師、那一節、補課日期', async () => {
    const { wrapper, calls } = await openSwap()
    await wrapper.find('[data-testid="sub-swap-option"]').trigger('click')
    await flushPromises()
    const put = calls.find((c) => c.method === 'PUT')
    expect(put?.url).toBe('/api/affected-periods/11/substitution')
    expect(put?.body).toEqual({
      type: 'swap', handler_teacher_id: 2, swap_entry_id: 77, swap_date: '2026-10-08',
      swap_period_no: 3,
    })
  })
})
