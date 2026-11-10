import { describe, expect, it } from 'vitest'
import type { TimetableWeek } from '@/api/timetables'
import type { PeriodCell } from './types'
import { dayLabels, weekEntries } from './weekCells'

const periods: PeriodCell[] = [
  { weekday: 3, period_no: 1, name: '早自習', type: 'morning' },
  { weekday: 3, period_no: 2, name: '第一節', type: 'regular' },
  { weekday: 3, period_no: 3, name: '第二節', type: 'regular' },
]

function week(cells: Partial<TimetableWeek['cells'][number]>[]): TimetableWeek {
  return {
    monday: '2026-11-23',
    dates: ['2026-11-23', '2026-11-24', '2026-11-25', '2026-11-26', '2026-11-27', '2026-11-28', '2026-11-29'],
    cells: cells.map((c) => ({
      date: '2026-11-25', weekday: 3, ordinal: 1, period_no: null, subject: '701 國文',
      teacher: '', room: '', kind: 'normal', note: '', ...c,
    })),
  }
}

describe('weekEntries', () => {
  it('教師課表依第幾節對到一般課節次(跳過早自習)', () => {
    const got = weekEntries(week([{ ordinal: 2, kind: 'cover', note: '代王師' }]), periods)
    expect(got).toHaveLength(1)
    expect(got[0]).toMatchObject({ weekday: 3, period_no: 3, change: 'cover', note: '代王師' })
  })

  it('班級課表直接用節次;沒有異動時不設 change', () => {
    const got = weekEntries(week([{ period_no: 2, subject: '國文', teacher: '王師' }]), periods)
    expect(got[0]).toMatchObject({ period_no: 2, teacher: '王師' })
    expect(got[0].change).toBeUndefined()
    expect(got[0].note).toBeUndefined()
  })

  it('對不到格線的節次略過', () => {
    expect(weekEntries(week([{ ordinal: 5 }]), periods)).toEqual([])
  })

  it('表頭寫日期', () => {
    expect(dayLabels(week([]))[3]).toBe('11/25(三)')
  })
})
