import { describe, expect, it } from 'vitest'
import type { TriangleOption } from '@/api/substitutions'
import { triangleDisposition, triangleSteps } from './triangleText'

const lesson = (date: string, period: string, subject: string, teacher: string) => ({
  entry_id: 1, date, weekday: 4, period_no: 2, period_name: period, class_names: '701',
  subject_name: subject, in_block: false, teacher_id: 1, teacher_name: teacher,
})

const opt: TriangleOption = {
  partner_id: 2, partner_name: '林師', mid: lesson('2026-11-19', '第二節', '數學', '林師'),
  third_id: 3, third_name: '陳師', makeup: lesson('2026-11-20', '第三節', '英語', '陳師'),
}

describe('三角調課的文字(v1.4.20)', () => {
  it('清單上一組寫成三個步驟', () => {
    expect(triangleSteps('王師', opt)).toEqual([
      '林師 來上這一節',
      '陳師 上林師的 11/19(週四) 第二節 數學',
      '王師 上陳師的 11/20(週五) 第三節 英語',
    ])
  })

  it('成立後的處置寫出另外兩位各上哪一節', () => {
    expect(triangleDisposition({
      handler: '林師', absent: '王師', third: '陳師', triDate: '2026-11-19',
      triPeriod: '第二節', swapDate: '2026-11-20', swapPeriod: '第三節',
    })).toBe('三角調課 → 林師(陳師 11/19(週四) 第二節代林師、王師 11/20(週五) 第三節補課)')
  })
})
