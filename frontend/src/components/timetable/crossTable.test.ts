import { describe, expect, it } from 'vitest'
import { crossTableNote } from './crossTable'

// 國中小:國中(預設,45 分)與國小(40 分)兩套節次表
const junior = {
  id: 1, is_default: true,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:20:00', end_time: '09:05:00' },
    { weekday: 1, period_no: 3, start_time: '09:15:00', end_time: '10:00:00' },
  ],
}
const elementary = {
  id: 2, is_default: false,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:30:00', end_time: '09:10:00' },
    { weekday: 1, period_no: 3, start_time: '09:15:00', end_time: '10:00:00' },
  ],
}
const classes = [{ id: 10, period_table_id: null }, { id: 20, period_table_id: 2 }]
const tables = [junior, elementary]

describe('crossTableNote', () => {
  it('另一套節次表、時間不同 → 標出實際時間', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [20] }, classes, tables, junior))
      .toBe('08:30–09:10')
  })
  it('另一套節次表但那一節時間剛好相同 → 不標', () => {
    expect(crossTableNote({ weekday: 1, period_no: 3, class_ids: [20] }, classes, tables, junior))
      .toBeUndefined()
  })
  it('同一套節次表(含沒指定、走預設表的班級)→ 不標', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [10] }, classes, tables, junior))
      .toBeUndefined()
  })
  it('只有一套節次表的學校完全不受影響', () => {
    expect(crossTableNote({ weekday: 1, period_no: 2, class_ids: [10] }, classes, [junior], junior))
      .toBeUndefined()
  })
})
