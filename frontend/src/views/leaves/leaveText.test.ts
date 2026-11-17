import { describe, expect, it } from 'vitest'
import { coverHint, skippedText } from './leaveText'

describe('登記時沒列入的節次', () => {
  it('沒有就不寫', () => {
    expect(skippedText([])).toBe('')
  })

  it('同一天、同一筆調課的節次寫在一起', () => {
    expect(skippedText([
      { date: '2026-12-02', period_name: '第一節', taken_by: '調課(未請假)' },
      { date: '2026-12-02', period_name: '第五節', taken_by: '調課(未請假)' },
    ])).toBe(';12/2 第一節、第五節已在「調課(未請假)」裡處理,不重複列入')
  })

  it('不同天、不同假單分開寫', () => {
    expect(skippedText([
      { date: '2026-12-02', period_name: '第一節', taken_by: '調課(未請假)' },
      { date: '2026-12-03', period_name: '第二節', taken_by: '調課(未請假)' },
      { date: '2026-12-03', period_name: '第三節', taken_by: '事假' },
    ])).toBe(';12/2 第一節、12/3 第二節已在「調課(未請假)」裡處理;12/3 第三節已在「事假」裡處理,不重複列入')
  })
})

describe('停課的節次', () => {
  it('寫出停課的說明,不必代課', () => {
    expect(skippedText([
      { date: '2026-12-02', period_name: '第五節', taken_by: '停課(探索活動)' },
      { date: '2026-12-02', period_name: '第六節', taken_by: '停課(探索活動)' },
    ])).toBe(';12/2 第五節、第六節停課(探索活動),不必代課')
  })

  it('和已在別張處理的分開寫', () => {
    expect(skippedText([
      { date: '2026-12-02', period_name: '第一節', taken_by: '調課(未請假)' },
      { date: '2026-12-03', period_name: '第五節', taken_by: '停課' },
    ])).toBe(';12/2 第一節已在「調課(未請假)」裡處理,不重複列入;12/3 第五節停課,不必代課')
  })
})

describe('代導那一行的說明', () => {
  it('銷假後不再叫組長去安排', () => {
    expect(coverHint({ status: 'cancelled', cover_pending_count: 1 })).toBe('已銷假,代導已取消')
  })

  it('還有沒安排的', () => {
    expect(coverHint({ status: 'registered', cover_pending_count: 1 })).toBe('請到「調代課處理」安排代導老師')
  })

  it('都安排好了', () => {
    expect(coverHint({ status: 'registered', cover_pending_count: 0 })).toBe('都已處理')
  })
})
