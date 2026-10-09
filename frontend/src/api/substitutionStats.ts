// 代課鐘點月結統計(M4-5)。

import { apiGet } from '@/api/client'

export interface StatDetail {
  handler_teacher_id: number
  handler_name: string
  date: string
  period_name: string
  class_names: string
  subject_name: string
  absent_teacher_name: string
  leave_type: string
  leave_type_label: string
  sub_type: string
  sub_type_label: string
  counts_toward_hours: boolean
  funding_source: string
  pay_kind: 'hourly' | 'daily' | 'none' // 鐘點 / 日薪 / 不計
  daily_shared: boolean // 日薪:當日與其他日薪代課老師分擔
}

export interface TeacherSummary {
  teacher_id: number
  teacher_name: string
  handled_count: number
  billable_count: number // 鐘點計費節數(不含日薪)
  daily_days: number // 日薪天數
  daily_periods: number // 日薪那幾天共代了幾節
  daily_shared_days: number // 其中幾天與其他日薪代課老師分擔
}

export interface MonthlyReport {
  year: number
  month: number
  summaries: TeacherSummary[]
  details: StatDetail[]
}

function qs(sid: number, year: number, month: number, teacherId?: number | null): string {
  const p = new URLSearchParams({
    semester_id: String(sid), year: String(year), month: String(month),
  })
  if (teacherId) p.set('teacher_id', String(teacherId))
  return p.toString()
}

export const getStats = (
  sid: number, year: number, month: number, teacherId?: number | null,
): Promise<MonthlyReport> => apiGet(`/substitution-stats?${qs(sid, year, month, teacherId)}`)

export const getMyStats = (
  sid: number, year: number, month: number,
): Promise<MonthlyReport> => apiGet(`/substitution-stats/mine?${qs(sid, year, month)}`)

export const statsExportUrl = (
  sid: number, year: number, month: number, teacherId?: number | null,
): string => `/api/substitution-stats/export?${qs(sid, year, month, teacherId)}`
