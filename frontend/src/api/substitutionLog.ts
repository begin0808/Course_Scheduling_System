// 今日調代課看板與調代課日誌(M4-4)。

import { apiGet, apiPut } from '@/api/client'

export interface LogEntry {
  affected_period_id: number
  date: string
  weekday: number
  period_no: number
  period_name: string
  start_time: string | null
  end_time: string | null
  class_names: string
  subject_name: string
  room_name: string
  absent_teacher_id: number
  absent_teacher_name: string
  leave_type: string
  leave_type_label: string
  status: string
  status_label: string
  disposed: boolean
  sub_type: string | null
  sub_type_label: string | null
  handler_teacher_id: number | null
  handler_name: string | null
  counts_toward_hours: boolean | null
  swap_date: string | null
  swap_period_name: string
  swap_class_names: string
  swap_subject_name: string
  note: string
  // leave:請假的那一節。swap_makeup:調課補課日被換來的那一節——原任教師是對調的老師、
  // 接手是回來補課的請假教師,swap_* 反過來指回請假那一節
  row_kind: 'leave' | 'swap_makeup'
}

export interface DailyBoard {
  date: string
  weekday: number
  school_name: string
  semester_label: string
  entries: LogEntry[]
}

export interface LogFilters {
  teacherId?: number | null
  dateFrom?: string | null
  dateTo?: string | null
  leaveType?: string | null
}

export const getDailyBoard = (semesterId: number, on?: string | null): Promise<DailyBoard> =>
  apiGet(`/daily-board?semester_id=${semesterId}` + (on ? `&on=${on}` : ''))

export const getSubstitutionLog = (
  semesterId: number, f: LogFilters = {},
): Promise<LogEntry[]> => {
  const p = new URLSearchParams({ semester_id: String(semesterId) })
  if (f.teacherId) p.set('teacher_id', String(f.teacherId))
  if (f.dateFrom) p.set('date_from', f.dateFrom)
  if (f.dateTo) p.set('date_to', f.dateTo)
  if (f.leaveType) p.set('leave_type', f.leaveType)
  return apiGet(`/substitution-log?${p.toString()}`)
}

// ── 巡堂表(v1.2.12)──
export interface PatrolCell {
  subject: string
  teacher: string
  room: string
  note: string // 代課/調課/併班/自習/停課/請假待處理;大型群組為「見分組巡堂單」
}
export interface PatrolPage {
  date: string
  table_name: string // 全校只有一套節次表時為空
  first_ordinal: number
  last_ordinal: number
  classes: string[]
  rows: { ordinal: number; name: string; cells: PatrolCell[] }[]
}
export interface PatrolGroupList {
  date: string
  group_name: string
  period_name: string
  items: { no: number; subject: string; teacher: string; room: string; note: string }[]
}
export interface PatrolSheets {
  title: string
  legend: string
  pages: PatrolPage[]
  group_lists: PatrolGroupList[]
}

export const getPatrolSheets = (semesterId: number, from: string, to: string): Promise<PatrolSheets> =>
  apiGet(`/patrol-sheets?semester_id=${semesterId}&date_from=${from}&date_to=${to}`)

/** 在新分頁開啟巡堂表列印頁(不套側邊欄) */
export function openPatrolSheets(semesterId: number, from: string, to: string = from) {
  window.open(`/patrol-sheets/print?semester_id=${semesterId}&from=${from}&to=${to}`, '_blank')
}

export interface PatrolSettings {
  legend: string
}
export const getPatrolSettings = () => apiGet<PatrolSettings>('/settings/patrol')
export const savePatrolSettings = (body: PatrolSettings) =>
  apiPut<PatrolSettings>('/settings/patrol', body)
