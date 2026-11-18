import { describe, expect, it } from 'vitest'
import type { TriangleOption } from '@/api/substitutions'
import { checkTitle, triangleDisposition, triangleSteps } from './triangleText'

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

describe('checkTitle(指定老師,v1.4.21)', () => {
  const base = { teacher_id: 2, teacher_name: '陳師', note: '', as_partner: [], as_third: [] }

  it('湊不成時寫原因', () => {
    expect(checkTitle({ ...base, found: 0, as_third: ['王師回來上陳師的 11/26(週四) 第二節 數學:…'] }))
      .toBe('陳師湊不成三角調課,原因:')
  })

  it('湊得成時寫幾組,其他節次的原因接在後面', () => {
    expect(checkTitle({ ...base, found: 2, as_partner: ['不能來上請假那一節 …'] }))
      .toBe('陳師可以湊成 2 組(列在下面);其他節次湊不成的原因:')
    expect(checkTitle({ ...base, found: 3 })).toBe('陳師可以湊成 3 組(列在下面)')
  })
})
