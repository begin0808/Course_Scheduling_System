// 請假登記與受影響節次(M4-1)。

import { apiGet, apiPost } from '@/api/client'

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
}

export interface LeaveCancelled {
  id: number
  status: string
  revoked_count: number
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

export const cancelLeave = (leaveId: number): Promise<LeaveCancelled> =>
  apiPost(`/leaves/${leaveId}/cancel`)
