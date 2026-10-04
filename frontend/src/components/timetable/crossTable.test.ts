import { describe, expect, it } from 'vitest'
import { crossTableNote, extraRows } from './crossTable'

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

// 完全中學:國中(預設)沒有第八節,高中部有
const senior = {
  id: 3, is_default: false,
  periods: [
    { weekday: 1, period_no: 2, start_time: '08:10:00', end_time: '09:00:00' },
    { weekday: 1, period_no: 10, start_time: '16:20:00', end_time: '17:10:00' },
    { weekday: 2, period_no: 10, start_time: '16:20:00', end_time: '17:10:00' },
  ],
}
const k12Classes = [{ id: 10, period_table_id: null }, { id: 30, period_table_id: 3 }]
const k12Tables = [junior, senior]

describe('extraRows', () => {
  it('畫面那套沒有的節次(高中第八節)→ 補上整列,課才不會從教師課表消失', () => {
    const rows = extraRows(
      [{ weekday: 1, period_no: 10, class_ids: [30] }], k12Classes, k12Tables, junior)
    expect(rows.map((p) => [p.weekday, p.period_no])).toEqual([[1, 10], [2, 10]])
  })
  it('畫面那套本來就有的節次不重複補', () => {
    expect(extraRows(
      [{ weekday: 1, period_no: 2, class_ids: [30] }], k12Classes, k12Tables, junior)).toEqual([])
  })
  it('沒有跨部的老師不會多出空列', () => {
    expect(extraRows(
      [{ weekday: 1, period_no: 2, class_ids: [10] }], k12Classes, k12Tables, junior)).toEqual([])
  })
  it('只補用得到的那一列一次(兩堂課都在第八節)', () => {
    const rows = extraRows([
      { weekday: 1, period_no: 10, class_ids: [30] }, { weekday: 2, period_no: 10, class_ids: [30] },
    ], k12Classes, k12Tables, junior)
    expect(rows).toHaveLength(2)
  })
})
