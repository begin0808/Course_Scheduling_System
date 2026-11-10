// 請假登記與受影響節次(M4-1)。

import { apiGet, apiPost, request } from '@/api/client'

export interface AffectedPeriod {
  id: number
  date: string
  weekday: number
  period_no: number
  period_name: string // 「第三節」——節次表的名稱,不是內部 period_no
  start_time: string | null
  end_time: string | null
  subject_name: string
  class_names: string
  room_name: string
  status: 'pending' | 'resolved' | 'completed' | 'cancelled'
  is_past: boolean // 已經過去;還沒處理的話就是「待補登」(v1.4.2,補登不通知、不能調課)
  handler_teacher_id: number | null
  handler_name: string | null
  sub_type: string | null // 已處置時的處置方式(substitute/swap/…)
  swap_date: string | null // 調課才有:請假教師回來補課的日期
  swap_period_name: string
  funding_source: string // 代課的計費方式(v1.4.4 起可事後修改)
  counts_toward_hours: boolean | null
}

/** 代導(v1.4.0):請假的導師帶的班,某一天由誰代導 */
export interface HomeroomCover {
  id: number
  date: string
  weekday: number
  class_name: string
  part_label: string // 全天 / 上午 / 下午 / 10:00~14:00
  is_half_day: boolean
  status: 'pending' | 'resolved' | 'completed' | 'cancelled'
  no_cover: boolean // 已確認「不需代導」
  is_past: boolean // 那天已經過了;還沒安排的話就是「待補登」(v1.4.2)
  handler_teacher_id: number | null
  handler_name: string | null
}

export interface LeaveRequest {
  id: number
  semester_id: number
  teacher_id: number
  teacher_name: string
  leave_type: string
  leave_type_label: string
  start_date: string
  start_time: string | null
  end_date: string
  end_time: string | null
  reason: string
  status: 'registered' | 'cancelled'
  created_by_name: string
  created_at: string
  affected_count: number
  pending_count: number
  affected_periods: AffectedPeriod[]
  homeroom_covers: HomeroomCover[]
  cover_pending_count: number // 還沒安排的代導(天次)
  // 只有登記時回傳:已經在別張假單或調課裡、這次沒列入的節次(v1.4.16)
  skipped?: SkippedPeriod[]
}

export interface SkippedPeriod {
  date: string
  period_name: string
  taken_by: string // 那張的假別名稱,例如「調課(未請假)」
}

export interface LeaveCancelled {
  id: number
  status: string
  revoked_count: number
  revoked_cover_count: number
  notified_teachers: string[]
}

export interface NewLeave {
  teacher_id?: number | null // 組長代登時指定;教師自登留空
  leave_type: string
  start_date: string
  start_time?: string | null
  end_date: string
  end_time?: string | null
  reason?: string
}

export const listLeaveTypes = (): Promise<Record<string, string>> => apiGet('/leave-types')

export const listLeaves = (semesterId: number): Promise<LeaveRequest[]> =>
  apiGet(`/leaves?semester_id=${semesterId}`)

export const createLeave = (semesterId: number, body: NewLeave): Promise<LeaveRequest> =>
  apiPost(`/leaves?semester_id=${semesterId}`, body)

/** 修改假別與事由(v1.4.4)。日期、時間不能改;已安排代課的計費方式不會跟著變 */
export const updateLeave = (
  leaveId: number, body: { leave_type?: string; reason?: string },
): Promise<LeaveRequest> => request<LeaveRequest>('PATCH', `/leaves/${leaveId}`, body)

// 新增調課(未請假,v1.4.5):老師沒請假,只是要和別人調課
export interface DayPeriod {
  period_no: number
  period_name: string
  start_time: string | null
  end_time: string | null
  class_names: string
  subject_name: string
  is_past: boolean // 已經上過:選了就是補登調課(v1.4.10,不通知)
  taken_by: string // 已經在別張假單/調課裡:那張的假別名稱
}
export const getDayPeriods = (
  teacherId: number, semesterId: number, date: string,
): Promise<DayPeriod[]> =>
  apiGet(`/teachers/${teacherId}/day-periods?semester_id=${semesterId}&date=${date}`)
export const createSwapRequest = (
  semesterId: number,
  body: { teacher_id: number; date: string; period_nos: number[]; reason?: string },
): Promise<LeaveRequest> => apiPost(`/swap-requests?semester_id=${semesterId}`, body)

export const cancelLeave = (leaveId: number): Promise<LeaveCancelled> =>
  apiPost(`/leaves/${leaveId}/cancel`)
