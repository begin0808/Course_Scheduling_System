// 今日調代課看板與調代課日誌(M4-4)。

import { apiGet } from '@/api/client'

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
