import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TimetableGrid from './TimetableGrid.vue'
import type { GridEntry, PeriodCell } from './types'

// 3 天 × 3 節:第2節為午休(反灰),週三第3節為固定用途(反灰),其餘一般課
const periods: PeriodCell[] = []
for (let w = 1; w <= 3; w++) {
  periods.push({ weekday: w, period_no: 1, name: '第一節', type: 'regular', start_time: '08:00:00', end_time: '08:40:00' })
  periods.push({ weekday: w, period_no: 2, name: '午休', type: 'lunch' })
  periods.push({ weekday: w, period_no: 3, name: w === 3 ? '週三不排' : '第三節', type: w === 3 ? 'reserved' : 'regular' })
}
const entries: GridEntry[] = [
  { id: 1, weekday: 1, period_no: 1, subject: '國文', teacher: '王師', locked: true },
  { id: 2, weekday: 2, period_no: 1, subject: '數學', teacher: '李師' },
]

const DT = { getData: () => '', setData: () => {}, effectAllowed: '' }

function cell(wrapper: ReturnType<typeof mount>, w: number, p: number) {
  return wrapper.find(`[data-weekday="${w}"][data-period="${p}"]`)
}

describe('TimetableGrid', () => {
  it('渲染星期表頭、節次名稱與反灰不排課時段', () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    expect(w.text()).toContain('星期一')
    expect(w.text()).toContain('星期三')
    expect(w.text()).toContain('第一節')
    // 午休與週三不排為反灰
    expect(cell(w, 1, 2).classes()).toContain('is-blocked')
    expect(cell(w, 3, 3).classes()).toContain('is-blocked')
    expect(cell(w, 1, 2).text()).toContain('午休')
  })

  it('渲染格位卡片;鎖定卡顯示鎖圖示且不可拖曳', () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    const locked = cell(w, 1, 1)
    expect(locked.text()).toContain('國文')
    expect(locked.text()).toContain('王師')
    expect(locked.find('.tg-lock').exists()).toBe(true)
    expect(locked.find('.tg-card').attributes('draggable')).toBe('false')
    // 未鎖定卡可拖曳
    expect(cell(w, 2, 1).find('.tg-card').attributes('draggable')).toBe('true')
  })

  it('點擊卡片觸發 select', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    await cell(w, 2, 1).find('.tg-card').trigger('click')
    expect(w.emitted('select')?.[0]?.[0]).toMatchObject({ id: 2 })
  })

  it('拖曳未鎖定卡片觸發 dragstart', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries } })
    await cell(w, 2, 1).find('.tg-card').trigger('dragstart', { dataTransfer: { ...DT } })
    expect(w.emitted('dragstart')?.[0]?.[0]).toMatchObject({ source: 'grid', entryId: 2 })
  })

  it('拖入空的一般課格觸發 check,放下觸發 drop(帶目標與 dragging 內容)', async () => {
    const dragging = { source: 'tray' as const, assignmentId: 9 }
    const w = mount(TimetableGrid, { props: { periods, entries, dragging } })
    await cell(w, 1, 3).trigger('dragenter', { dataTransfer: { ...DT } })
    expect(w.emitted('check')?.[0]?.[0]).toMatchObject({ weekday: 1, period_no: 3 })
    await cell(w, 1, 3).trigger('drop', { dataTransfer: { ...DT } })
    expect(w.emitted('drop')?.[0]?.[0]).toMatchObject({
      weekday: 1, period_no: 3, data: { source: 'tray', assignmentId: 9 },
    })
  })

  it('反灰時段不接受放下(不觸發 drop)', async () => {
    const w = mount(TimetableGrid, { props: { periods, entries, dragging: { source: 'tray', assignmentId: 9 } } })
    await cell(w, 1, 2).trigger('drop', { dataTransfer: { ...DT } }) // 午休
    expect(w.emitted('drop')).toBeUndefined()
  })

  it('feedback 衝突時套用紅框樣式並顯示原因', () => {
    const w = mount(TimetableGrid, {
      props: { periods, entries, feedback: { weekday: 1, period_no: 3, ok: false, reason: '王師此時段已有課' } },
    })
    const c = cell(w, 1, 3)
    expect(c.classes()).toContain('is-conflict')
    expect(c.text()).toContain('王師此時段已有課')
  })

  it('readonly 模式下格位不可放下', async () => {
    const w = mount(TimetableGrid, {
      props: { periods, entries, readonly: true, dragging: { source: 'tray', assignmentId: 9 } },
    })
    await cell(w, 1, 3).trigger('drop', { dataTransfer: { ...DT } })
    expect(w.emitted('drop')).toBeUndefined()
  })
})
