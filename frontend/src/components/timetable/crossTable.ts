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
interface TableLike<P extends PeriodLike = PeriodLike> {
  id: number
  is_default: boolean
  periods: P[]
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

/** 這一格所屬的節次表:班級指定的那套,沒指定就是學期預設表。 */
function ownTable<P extends PeriodLike>(
  entry: EntryLike, classes: ClassLike[], tables: TableLike<P>[],
): TableLike<P> | undefined {
  const fallback = tables.find((t) => t.is_default) ?? tables[0]
  const cls = classes.find((c) => entry.class_ids.includes(c.id))
  return tables.find((t) => t.id === cls?.period_table_id) ?? fallback
}

/**
 * 畫面那套節次表沒有、但這些格位用得到的節次列(取自格位自己的節次表)。
 *
 * 國中七節、高中八節的完全中學,跨部老師在高中第八節有課;教師課表照國中那套畫只有七列,
 * 不補這一列,那堂課會整個從課表上消失。只補用得到的,沒跨部的老師不會多出空列。
 */
export function extraRows<P extends PeriodLike>(
  entries: (EntryLike & { span?: number })[], classes: ClassLike[],
  tables: TableLike<P>[], shown: TableLike<P> | null,
): P[] {
  if (!shown || tables.length < 2) return []
  const have = new Set(shown.periods.map((p) => p.period_no))
  const out: P[] = []
  for (const e of entries) {
    const own = ownTable(e, classes, tables)
    if (!own || own.id === shown.id) continue
    for (let no = e.period_no; no < e.period_no + (e.span ?? 1); no++) {
      if (have.has(no)) continue
      have.add(no)
      out.push(...own.periods.filter((p) => p.period_no === no))
    }
  }
  return out
}

/** 這一格的實際上課時間;與畫面那套節次表同一列的時間相同(或就是同一套)時回 undefined。 */
export function crossTableNote(
  entry: EntryLike, classes: ClassLike[], tables: TableLike[], shown: TableLike | null,
): string | undefined {
  if (!shown || tables.length < 2) return undefined
  const own = ownTable(entry, classes, tables)
  if (!own || own.id === shown.id) return undefined
  const at = (t: TableLike) =>
    t.periods.find((p) => p.weekday === entry.weekday && p.period_no === entry.period_no)
  const mine = at(own)
  if (!mine?.start_time || !mine.end_time) return undefined
  const row = at(shown)
  if (row && row.start_time === mine.start_time && row.end_time === mine.end_time) return undefined
  return `${hhmm(mine.start_time)}–${hhmm(mine.end_time)}`
}
