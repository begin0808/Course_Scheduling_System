import type { TriangleOption, TriangleTeacherCheck } from '@/api/substitutions'
import { shortDate } from './logText'

/**
 * 三角調課(v1.4.20)的文字:同一班三位老師輪流換課。
 * 乙來上請假那節、丙來上乙原本的一節、請假老師回來上丙原本的一節。
 */

/** 清單上一組的三個步驟:「林師 來上這一節」「陳師 上林師的 11/20(週四) 第二節 數學」… */
export function triangleSteps(absentName: string, o: TriangleOption): string[] {
  const slot = (x: TriangleOption['mid']) =>
    `${shortDate(x.date)} ${x.period_name} ${x.subject_name}`.trim()
  return [
    `${o.partner_name} 來上這一節`,
    `${o.third_name} 上${o.partner_name}的 ${slot(o.mid)}`,
    `${absentName} 上${o.third_name}的 ${slot(o.makeup)}`,
  ]
}

export interface TriangleParts {
  handler: string // 乙:來上請假那節
  absent: string // 請假(發起)的老師
  third: string // 丙
  triDate: string | null
  triPeriod: string
  swapDate: string | null
  swapPeriod: string
}

/** 已成立的三角調課:「三角調課 → 林師(陳師 11/20(週四) 第二節代林師、王師 11/21(週五) 第三節補課)」 */
export function triangleDisposition(p: TriangleParts): string {
  const at = (d: string | null, name: string) => `${d ? shortDate(d) : ''} ${name}`.trim()
  return `三角調課 → ${p.handler}(${p.third} ${at(p.triDate, p.triPeriod)}代${p.handler}、`
    + `${p.absent} ${at(p.swapDate, p.swapPeriod)}補課)`
}

/** 指定老師的結果標題(v1.4.21):「陳師可以湊成 2 組(列在下面);其他節次湊不成的原因:」 */
export function checkTitle(c: TriangleTeacherCheck): string {
  const reasons = c.as_partner.length + c.as_third.length > 0
  if (c.found) {
    return `${c.teacher_name}可以湊成 ${c.found} 組(列在下面)${reasons ? ';其他節次湊不成的原因:' : ''}`
  }
  return `${c.teacher_name}湊不成三角調課${reasons ? ',原因:' : ''}`
}
