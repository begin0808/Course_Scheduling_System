import { describe, expect, it } from 'vitest'
import type { ScheduleEntry } from '@/api/timetables'
import { mergeGroups } from './groupCells'

function entry(id: number, over: Partial<ScheduleEntry>): ScheduleEntry {
  return {
    id, course_assignment_id: id, weekday: 3, period_no: 2, span: 1, locked: false,
    subject: '英語文', teachers: ['師'], classes: ['901', '902'], unit_type: 'group',
    unit_name: '九年級英語分組', room: null, teacher_ids: [id], class_ids: [1, 2], room_id: null,
    ...over,
  }
}

// 組長回報:分組上課的班級課表只出現一位老師
describe('跑班群組併成一格', () => {
  it('兩組:科目只寫一次,兩位老師都列出來', () => {
    const got = mergeGroups([
      entry(1, { teachers: ['張老師'], room: '英A' }),
      entry(2, { teachers: ['王老師'], room: '英B' }),
    ])
    expect(got).toHaveLength(1)
    expect(got[0].subject).toBe('英語文')
    expect(got[0].teachers).toEqual(['張老師／王老師'])
    expect(got[0].room).toBe('英A／英B')
  })

  it('不同科目的組:科目也並列', () => {
    const got = mergeGroups([
      entry(1, { subject: '資訊', teachers: ['甲'] }),
      entry(2, { subject: '生科', teachers: ['乙'] }),
    ])
    expect(got[0].subject).toBe('資訊／生科')
    expect(got[0].teachers).toEqual(['甲／乙'])
  })

  // v1.7.2 組長回報:配課頁排好的順序,課表上卻依姓名字碼排成另一個順序
  it('各組照配課頁的順序(配課建立的先後),不看姓名字碼、也不看格位的順序', () => {
    const got = mergeGroups([
      entry(13, { teachers: ['陳老師'] }),
      entry(11, { teachers: ['方老師'] }),
      entry(14, { teachers: ['李老師'] }),
      entry(12, { teachers: ['張老師'] }),
    ])
    expect(got[0].teachers).toEqual(['方老師／張老師／陳老師／李老師'])
  })

  it('5 組以內:每位老師都列出來(v1.4.16,分組教學常有 4 組)', () => {
    const got = mergeGroups([1, 2, 3, 4, 5].map((i) => entry(i, { teachers: [`師${i}`] })))
    expect(got).toHaveLength(1)
    expect(got[0].subject).toBe('英語文')
    expect(got[0].teachers).toEqual(['師1／師2／師3／師4／師5'])
  })

  it('6 組以上:寫群組名稱與組數', () => {
    const got = mergeGroups([1, 2, 3, 4, 5, 6].map((i) => entry(i, { teachers: [`師${i}`] })))
    expect(got).toHaveLength(1)
    expect(got[0].subject).toBe('九年級英語分組')
    expect(got[0].teachers).toEqual(['共 6 組'])
  })

  it('一般的課、單雙週的課、不同節的群組都不併', () => {
    const got = mergeGroups([
      entry(1, { unit_type: 'single', unit_name: '901' }),
      entry(2, { unit_type: 'alternate', unit_name: '單雙', week_parity: 'odd' }),
      entry(3, { unit_type: 'alternate', unit_name: '單雙', week_parity: 'even' }),
      entry(4, {}),
      entry(5, { period_no: 3 }),
    ])
    expect(got).toHaveLength(5)
  })
})
