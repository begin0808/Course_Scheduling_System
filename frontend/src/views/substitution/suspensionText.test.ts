import { describe, expect, it } from 'vitest'
import type { ClassUnit } from '@/api/basedata'
import { dateRangeText, gradeGroups } from './suspensionText'

function klass(id: number, name: string, grade: number, track: ClassUnit['track'] = 'junior_high'): ClassUnit {
  return {
    id, name, grade, track, semester_id: 1, department: null, student_count: null,
    homeroom_teacher_id: null, homeroom_teacher: null, period_table_id: null,
  }
}

describe('停課對象的年級分組', () => {
  it('依年級分組,年級小的在前', () => {
    const groups = gradeGroups([klass(3, '801', 8), klass(1, '702', 7), klass(2, '701', 7)])
    expect(groups.map((g) => g.label)).toEqual(['七年級', '八年級'])
    expect(groups[0].classes.map((c) => c.name)).toEqual(['701', '702'])
  })

  it('國中小並存時寫出學制', () => {
    const groups = gradeGroups([klass(1, '101', 1, 'elementary'), klass(2, '701', 7)])
    expect(groups.map((g) => g.label)).toEqual(['國小一年級', '國中七年級'])
  })
})

describe('停課日期', () => {
  it('一天、一段期間', () => {
    expect(dateRangeText('2026-11-20', '2026-11-20')).toBe('11/20(五)')
    expect(dateRangeText('2026-11-20', '2026-11-24')).toBe('11/20(五)~11/24(二)')
  })
})
