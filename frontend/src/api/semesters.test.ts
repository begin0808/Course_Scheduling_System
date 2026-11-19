import { describe, expect, it } from 'vitest'
import { defaultSemester, isTutoringTerm } from './semesters'

// 清單由新到舊(後端排好):暑輔已建好但還沒開始,今天在第 2 學期
const list = [
  { id: 4, label: '115 學年度暑期輔導', start_date: '2027-07-05', end_date: '2027-07-30' },
  { id: 2, label: '115 學年度第 2 學期', start_date: '2027-02-11', end_date: '2027-06-30' },
  { id: 3, label: '115 學年度寒假輔導', start_date: '2027-01-25', end_date: '2027-02-05' },
  { id: 1, label: '115 學年度第 1 學期', start_date: null, end_date: null },
]

describe('defaultSemester', () => {
  it('選今天落在起訖日期內的學期,不是清單第一個', () => {
    expect(defaultSemester(list, '2027-05-20').id).toBe(2)
    expect(defaultSemester(list, '2027-01-25').id).toBe(3)
    expect(defaultSemester(list, '2027-07-30').id).toBe(4)
  })

  it('今天不在任何學期內(例如假期中、輔導還沒開始)就選清單第一個', () => {
    expect(defaultSemester(list, '2027-07-01').id).toBe(4)
    expect(defaultSemester([{ id: 9, start_date: null, end_date: null }], '2027-07-01').id).toBe(9)
  })
})

it('isTutoringTerm:3 寒假輔導、4 暑期輔導', () => {
  expect([1, 2, 3, 4].map(isTutoringTerm)).toEqual([false, false, true, true])
})
