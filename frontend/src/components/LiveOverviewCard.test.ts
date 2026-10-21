import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LiveOverviewCard from './LiveOverviewCard.vue'
import type { LiveOverview, LiveSection } from '@/api/substitutionLog'

function section(over: Partial<LiveSection>): LiveSection {
  return {
    table_name: '', state: 'in_class', message: '', now_label: '',
    period_name: '第三節', start: '10:20', end: '11:05', cells: [], ...over,
  }
}

function respond(body: LiveOverview | null, status = 200) {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
    ok: status < 400, status, json: () => Promise.resolve(body ?? { detail: '權限不足' }),
  })))
}

async function render(body: LiveOverview | null, status = 200) {
  respond(body, status)
  const wrapper = mount(LiveOverviewCard, { props: { semesterId: 1 } })
  await flushPromises()
  return wrapper
}

const base = { date: '2026-10-21', weekday: 3, time: '10:23', message: '' }

afterEach(() => vi.unstubAllGlobals())

describe('LiveOverviewCard', () => {
  it('上課中:列出每班的科目與老師,有異動的標出來', async () => {
    const w = await render({ ...base, sections: [section({ cells: [
      { class_name: '701', subject: '國文', teacher: '王師', room: '', note: '' },
      { class_name: '702', subject: '英語', teacher: '陳師', room: '', note: '代課' },
      { class_name: '703', subject: '數學', teacher: '李師', room: '', note: '請假待處理' },
      { class_name: '704', subject: '', teacher: '', room: '', note: '' },
    ] })] })
    expect(w.text()).toContain('即時概況 · 10/21(週三)10:23')
    expect(w.get('[data-testid="live-period"]').text()).toBe('上課中:第三節(10:20–11:05)')
    expect(w.get('[data-testid="live-701"]').text()).toContain('國文王師')
    expect(w.get('[data-testid="live-702"]').classes()).toContain('changed')
    expect(w.get('[data-testid="live-703"]').text()).toContain('請假待處理')
    expect(w.get('[data-testid="live-704"]').text()).toContain('沒有課')
    expect(w.text()).toContain('看今天整天的巡堂表')
  })

  it('下課中列下一節;兩套節次表分開列', async () => {
    const w = await render({ ...base, sections: [
      section({ table_name: '國中節次表', state: 'upcoming', now_label: '下課',
        period_name: '第四節', start: '11:15', end: '12:00' }),
      section({ table_name: '國小節次表', period_name: '第四節', start: '11:10', end: '11:50' }),
    ] })
    const periods = w.findAll('[data-testid="live-period"]').map((x) => x.text())
    expect(periods).toEqual(['下課中,下一節是第四節(11:15–12:00)', '上課中:第四節(11:10–11:50)'])
    expect(w.text()).toContain('國中節次表')
  })

  it('放學後或沒有發布課表:只有一行說明', async () => {
    let w = await render({ ...base, sections: [
      section({ state: 'after_school', message: '今天的課已結束' })] })
    expect(w.get('[data-testid="live-message"]').text()).toBe('今天的課已結束')
    expect(w.find('[data-testid="live-period"]').exists()).toBe(false)

    w = await render({ ...base, message: '這個學期還沒有發布課表', sections: [] })
    expect(w.get('[data-testid="live-message"]').text()).toBe('這個學期還沒有發布課表')
    expect(w.text()).not.toContain('巡堂表')
  })

  it('一般教師沒有權限:不顯示這張卡', async () => {
    const w = await render(null, 403)
    expect(w.find('[data-testid="dash-live"]').exists()).toBe(false)
  })
})
