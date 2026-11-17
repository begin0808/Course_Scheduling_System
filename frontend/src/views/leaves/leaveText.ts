// 請假登記頁的提示文字(v1.4.16)

import type { LeaveRequest, SkippedPeriod } from '@/api/leaves'

function md(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}/${d}`
}

/**
 * 登記時沒列入的節次:已經在別張假單或「調課(未請假)」裡,或那一節停課(v1.4.19)。
 * 組長回報:導師先把當天的課調走,再請假讓系統排代導——那幾節不必再處理一次。
 * 回傳接在「已登記…」後面的一段(開頭是分號);沒有就回空字串。
 */
export function skippedText(list: SkippedPeriod[]): string {
  if (!list.length) return ''
  // 停課的節次(v1.4.19):taken_by 是「停課(校慶補假)」,那節本來就不上課
  const off = list.filter((s) => s.taken_by.startsWith('停課'))
  const taken = list.filter((s) => !s.taken_by.startsWith('停課'))
  return takenText(taken) + offText(off)
}

function offText(list: SkippedPeriod[]): string {
  if (!list.length) return ''
  const byReason = new Map<string, Map<string, string[]>>()
  for (const s of list) {
    const days = byReason.get(s.taken_by) ?? new Map<string, string[]>()
    days.set(s.date, [...(days.get(s.date) ?? []), s.period_name])
    byReason.set(s.taken_by, days)
  }
  const parts = [...byReason].map(([why, days]) => {
    const when = [...days].map(([d, names]) => `${md(d)} ${names.join('、')}`).join('、')
    return `${when}${why}`
  })
  return `;${parts.join(';')},不必代課`
}

function takenText(list: SkippedPeriod[]): string {
  if (!list.length) return ''
  const byTaken = new Map<string, Map<string, string[]>>()
  for (const s of list) {
    const days = byTaken.get(s.taken_by) ?? new Map<string, string[]>()
    days.set(s.date, [...(days.get(s.date) ?? []), s.period_name])
    byTaken.set(s.taken_by, days)
  }
  const parts = [...byTaken].map(([taken, days]) => {
    const when = [...days].map(([d, names]) => `${md(d)} ${names.join('、')}`).join('、')
    return `${when}已在「${taken}」裡處理`
  })
  return `;${parts.join(';')},不重複列入`
}

/** 假單上「代導:…」那一行後面的說明。銷假後不能再叫組長去安排。 */
export function coverHint(l: Pick<LeaveRequest, 'status' | 'cover_pending_count'>): string {
  if (l.status === 'cancelled') return '已銷假,代導已取消'
  if (!l.cover_pending_count) return '都已處理'
  return '請到「調代課處理」安排代導老師'
}
