// 跨節次表的格子要補上實際時間。
//
// 教師/場地課表只能照一套節次表(學期預設表)畫格線。國中小、完全中學的跨部教師,
// 另一部的課會排在「同節次號」那一列,但實際時間不一樣(國小 40 分、國中 45 分)。
// 不標出來,課表上的時間就是錯的。

interface PeriodLike {
  weekday: number
  period_no: number
  start_time?: string | null
  end_time?: string | null
}
interface TableLike {
  id: number
  is_default: boolean
  periods: PeriodLike[]
}
interface ClassLike {
  id: number
  period_table_id: number | null
}
interface EntryLike {
  weekday: number
  period_no: number
  class_ids: number[]
}

const hhmm = (t: string) => t.slice(0, 5)

/** 這一格的實際上課時間;與畫面那套節次表同一列的時間相同(或就是同一套)時回 undefined。 */
export function crossTableNote(
  entry: EntryLike, classes: ClassLike[], tables: TableLike[], shown: TableLike | null,
): string | undefined {
  if (!shown || tables.length < 2) return undefined
  const fallback = tables.find((t) => t.is_default) ?? tables[0]
  const cls = classes.find((c) => entry.class_ids.includes(c.id))
  const own = tables.find((t) => t.id === cls?.period_table_id) ?? fallback
  if (!own || own.id === shown.id) return undefined
  const at = (t: TableLike) =>
    t.periods.find((p) => p.weekday === entry.weekday && p.period_no === entry.period_no)
  const mine = at(own)
  if (!mine?.start_time || !mine.end_time) return undefined
  const row = at(shown)
  if (row && row.start_time === mine.start_time && row.end_time === mine.end_time) return undefined
  return `${hhmm(mine.start_time)}–${hhmm(mine.end_time)}`
}
