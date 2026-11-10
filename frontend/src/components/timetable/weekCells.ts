// 某一週實際課表(v1.4.15)→ 課表格子。後端已套用調代課,這裡只負責對到格線:
// 班級課表直接用節次;教師課表依「第幾節」對到目前格線那一天的一般課節次。
import type { TimetableWeek } from '@/api/timetables'
import type { GridEntry, PeriodCell } from './types'

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

export function weekEntries(week: TimetableWeek, periods: PeriodCell[]): GridEntry[] {
  const regular = (weekday: number) => periods
    .filter((p) => p.weekday === weekday && p.type === 'regular')
    .sort((a, b) => a.period_no - b.period_no)
  const out: GridEntry[] = []
  for (const c of week.cells) {
    const periodNo = c.period_no ?? regular(c.weekday)[c.ordinal - 1]?.period_no
    if (periodNo === undefined) continue
    out.push({
      id: `${c.date}-${c.ordinal}`,
      weekday: c.weekday,
      period_no: periodNo,
      span: 1,
      subject: c.subject,
      teacher: c.teacher || undefined,
      room: c.room || undefined,
      note: c.note || undefined,
      change: c.kind === 'normal' ? undefined : c.kind,
    })
  }
  return out
}

/** 表頭「11/23(一)」 */
export function dayLabels(week: TimetableWeek): Record<number, string> {
  const out: Record<number, string> = {}
  week.dates.forEach((iso, i) => {
    const [, m, d] = iso.split('-').map(Number)
    out[i + 1] = `${m}/${d}(${WEEKDAYS[i]})`
  })
  return out
}
