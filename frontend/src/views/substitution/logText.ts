import type { LogEntry } from '@/api/substitutionLog'

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']

/** 2026-11-20 → 11/20(週五):清單一次列很多日期,年份不必每個都重複。 */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${m}/${d}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

/**
 * 調代課紀錄的「處置」欄。
 *
 * 調課要寫出另一半在哪一天哪一節(v1.4.17,組長回報):原本只寫「調課 · 林師」,
 * 補課排在隔天,班級週課表又只截到當天,看起來像「只有一個人被調」。
 * 寫法與「調代課處理」相同:調課 · 林師(王師 11/20(週五) 第三節補課)。
 */
export function logDisposition(e: LogEntry): string {
  if (!e.disposed) return '—'
  if (e.sub_type === 'swap' && e.swap_date) {
    const when = `${shortDate(e.swap_date)} ${e.swap_period_name}`.trim()
    if (e.row_kind === 'swap_makeup') return `調課補課 · ${e.handler_name}(與 ${when} 對調)`
    return `${e.sub_type_label} · ${e.handler_name}(${e.absent_teacher_name} ${when}補課)`
  }
  if (e.handler_name) return `${e.sub_type_label} · ${e.handler_name}`
  return e.sub_type_label ?? ''
}
