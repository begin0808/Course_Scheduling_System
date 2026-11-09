// 跑班群組同一節的各組課併成一格(v1.4.13,組長回報:班級課表只看得到一位老師)。
// 群組裡每位老師各是一筆格位,課表格子原本只取其中一筆。寫法同後端匯出、巡堂表與即時概況:
// 組數少時科目、老師以「／」並列;社團這類 4 組以上的大型跑班一格塞不下,只寫群組名稱與組數。

import type { ScheduleEntry } from '@/api/timetables'

export const GROUP_LIST_MIN = 4

/** 依字碼排序(與後端匯出同一個順序;localeCompare 會隨瀏覽器語系而變) */
function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

function join(values: (string | null | undefined)[]): string {
  return [...new Set(values.filter((v): v is string => !!v))].join('／')
}

/** 班級、場地課表用:回傳的每一筆都是一格;subject / teachers / room 已是要顯示的文字 */
export function mergeGroups(entries: ScheduleEntry[]): ScheduleEntry[] {
  const out: ScheduleEntry[] = []
  const groups = new Map<string, ScheduleEntry[]>()
  for (const e of entries) {
    if (e.unit_type !== 'group') {
      out.push(e)
      continue
    }
    const k = `${e.unit_name}|${e.weekday}|${e.period_no}`
    groups.set(k, [...(groups.get(k) ?? []), e])
  }
  for (const members of groups.values()) {
    members.sort((a, b) => cmp(a.subject, b.subject)
      || cmp(a.teachers.join('、'), b.teachers.join('、')))
    const [first] = members
    if (members.length === 1) {
      out.push(first)
      continue
    }
    const span = Math.max(...members.map((m) => m.span))
    if (members.length >= GROUP_LIST_MIN) {
      out.push({ ...first, span, subject: first.unit_name, teachers: [`共 ${members.length} 組`], room: null })
      continue
    }
    out.push({
      ...first,
      span,
      subject: join(members.map((m) => m.subject)),
      teachers: [join(members.map((m) => m.teachers.join('、')))],
      room: join(members.map((m) => m.room)) || null,
    })
  }
  return out
}
