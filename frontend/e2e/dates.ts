// E2E 測試日期基準:一律由「執行當日」推算,不硬編。
//
// 為什麼:後端 clock.is_past_slot 以真實時鐘判定節次是否已上過。日期一旦成為過去,
// 代課指派被 409 拒絕、銷假不再級聯——測試會在某個沒人動過程式碼的早晨無聲轉紅
// (原本埋的引信是 2026-11-11)。與後端 tests/dates.py 同一套規則。

// 基準週距今至少 14 天:確保基準週的每一節都還沒上過(不受執行時刻影響)。
const LEAD_DAYS = 14

function addDays(day: Date, n: number): Date {
  const out = new Date(day)
  out.setDate(out.getDate() + n)
  return out
}

/** ISO 星期:1=週一 … 7=週日(JS 的 getDay() 是 0=週日)。 */
function isoWeekday(day: Date): number {
  return day.getDay() === 0 ? 7 : day.getDay()
}

/** `day` 當天或之後、最近的指定 ISO 星期。 */
export function onOrAfter(weekday: number, day: Date): Date {
  return addDays(day, (weekday - isoWeekday(day) + 7) % 7)
}

/** yyyy-mm-dd(用本地日期欄位,避免 toISOString() 的 UTC 位移把日期倒退一天)。 */
export function iso(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

/** 基準週的週一:距今 ≥ LEAD_DAYS,且該週一到「下週三」同月。
 *
 * 同月是硬需求:代課推薦的公平計數與月結統計都以「節次那一天的月份」為範圍,
 * 基準週跨月會讓「本月已代 N 節」歸零。與後端 tests/dates.py 的 base_monday 同規則。
 */
function baseMonday(): Date {
  let mon = onOrAfter(1, addDays(new Date(), LEAD_DAYS))
  for (let i = 0; i < 6; i += 1) {
    if (addDays(mon, 9).getMonth() === mon.getMonth()) return mon
    mon = addDays(mon, 7)
  }
  throw new Error('六週內必有一個「當週到下週三同月」的週一')
}

const monday = baseMonday()
const wednesday = addDays(monday, 2)

export const MON = iso(monday)
export const WED = iso(wednesday)                   // 請假日(多數 spec 的主角)
export const THU = iso(addDays(monday, 3))          // 無請假的對照日
export const FRI = iso(addDays(monday, 4))
export const NEXT_MON = iso(addDays(monday, 7))     // 跨週末的請假結束日
export const WED2 = iso(addDays(monday, 9))         // 下週三(調課補課日/第二張假單)

// 學期起訖:包住上面所有日子,前後留緩衝
export const SEM_START = iso(addDays(monday, -30))
export const SEM_END = iso(addDays(monday, 120))

/** 基準週裡指定 ISO 星期的那一天(1=週一 … 7=週日)。給「格位在星期幾就請那天的假」用。 */
export function dayOfBaseWeek(weekday: number): string {
  return iso(addDays(monday, weekday - 1))
}

/** 月結統計的查詢參數,取「該請假日」所屬的年月。
 *
 * 必須用請假日自己算:基準週可能跨月(週一 8/31、週三 9/2),
 * 拿別天的月份去查會查到空月份。
 */
export function statsQuery(day: string): string {
  const [year, month] = day.split('-').map(Number)
  return `&year=${year}&month=${month}`
}

/** 多數 spec 的請假日就是 WED,直接用這個。 */
export const STATS_QUERY = statsQuery(WED)

/** 介面上顯示的日期格式:「2026-11-11(週三)」。 */
const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日']
export function withWeekday(day: string): string {
  const [y, m, d] = day.split('-').map(Number)
  return `${day}(週${WEEK_LABELS[isoWeekday(new Date(y, m - 1, d)) - 1]})`
}
