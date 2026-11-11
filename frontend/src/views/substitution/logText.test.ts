import { describe, expect, it } from 'vitest'
import type { LogEntry } from '@/api/substitutionLog'
import { logDisposition, shortDate } from './logText'

const base: LogEntry = {
  affected_period_id: 1, date: '2026-11-19', weekday: 4, period_no: 6, period_name: '第五節',
  start_time: null, end_time: null, class_names: '802', subject_name: '數學', room_name: '',
  absent_teacher_id: 1, absent_teacher_name: '王師', leave_type: 'swap_only',
  leave_type_label: '調課(未請假)', status: 'resolved', status_label: '已處理', disposed: true,
  sub_type: 'swap', sub_type_label: '調課', handler_teacher_id: 2, handler_name: '林師',
  counts_toward_hours: null, swap_date: '2026-11-20', swap_period_name: '第三節',
  swap_class_names: '802', swap_subject_name: '輔導', note: '', row_kind: 'leave',
}

describe('調代課紀錄的處置欄', () => {
  it('短日期帶星期', () => {
    expect(shortDate('2026-11-20')).toBe('11/20(週五)')
  })

  it('調課寫出補課在哪一天哪一節(組長回報:看起來像只有一個人被調)', () => {
    expect(logDisposition(base)).toBe('調課 · 林師(王師 11/20(週五) 第三節補課)')
  })

  it('補課那一列寫回對調的節次', () => {
    expect(logDisposition({ ...base, row_kind: 'swap_makeup', handler_name: '王師',
      swap_date: '2026-11-19', swap_period_name: '第五節' }))
      .toBe('調課補課 · 王師(與 11/19(週四) 第五節 對調)')
  })

  it('代課、待處理照舊', () => {
    expect(logDisposition({ ...base, sub_type: 'substitute', sub_type_label: '代課',
      swap_date: null, swap_period_name: '' })).toBe('代課 · 林師')
    expect(logDisposition({ ...base, disposed: false })).toBe('—')
    expect(logDisposition({ ...base, sub_type: 'self_study', sub_type_label: '自習',
      handler_name: null, swap_date: null })).toBe('自習')
  })
})
