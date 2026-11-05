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

/** 代導明細(v1.4.0):以天為單位,全天/半天分開記 */
export interface CoverDetail {
  handler_teacher_id: number
  handler_name: string
  date: string
  class_name: string
  part_label: string
  is_half_day: boolean
  absent_teacher_name: string
  leave_type_label: string
}

export interface TeacherSummary {
  teacher_id: number
  teacher_name: string
  handled_count: number
  billable_count: number // 鐘點計費節數(不含日薪)
  daily_days: number // 日薪天數
  daily_periods: number // 日薪那幾天共代了幾節
  daily_shared_days: number // 其中幾天與其他日薪代課老師分擔
  cover_full_days: number // 代導全天(一班一天算一次)
  cover_half_days: number // 代導半天
}

export interface MonthlyReport {
  date_from: string | null // 統計期間(含當天)
  date_to: string | null
  year: number | null // 按月查時才有;自訂區間(v1.4.11)為 null
  month: number | null
  summaries: TeacherSummary[]
  details: StatDetail[]
  cover_details: CoverDetail[]
}

/** 按月,或自訂區間(v1.4.11:有的學校每月 15 日結算,例如 10/16~11/15) */
export type StatsPeriod = { year: number; month: number } | { from: string; to: string }

function qs(sid: number, period: StatsPeriod, teacherId?: number | null): string {
  const p = new URLSearchParams({ semester_id: String(sid) })
  if ('from' in period) {
    p.set('date_from', period.from)
    p.set('date_to', period.to)
  } else {
    p.set('year', String(period.year))
    p.set('month', String(period.month))
  }
  if (teacherId) p.set('teacher_id', String(teacherId))
  return p.toString()
}

export const getStats = (
  sid: number, period: StatsPeriod, teacherId?: number | null,
): Promise<MonthlyReport> => apiGet(`/substitution-stats?${qs(sid, period, teacherId)}`)

export const getMyStats = (sid: number, period: StatsPeriod): Promise<MonthlyReport> =>
  apiGet(`/substitution-stats/mine?${qs(sid, period)}`)

export const statsExportUrl = (
  sid: number, period: StatsPeriod, teacherId?: number | null,
): string => `/api/substitution-stats/export?${qs(sid, period, teacherId)}`
