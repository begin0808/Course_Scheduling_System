// 課表(草稿、格位、衝突檢查)API 型別與呼叫封裝。

import { apiGet, apiPost, request } from '@/api/client'
import type { PeriodTable } from '@/api/semesters'

export interface ScheduleEntry {
  id: number
  course_assignment_id: number
  weekday: number
  period_no: number
  span: number
  locked: boolean
  subject: string
  teachers: string[]
  classes: string[]
  unit_type: 'single' | 'group'
  unit_name: string
  room: string | null
  teacher_ids: number[]
  class_ids: number[]
  room_id: number | null
}
export interface TimetableBrief {
  id: number
  semester_id: number
  name: string
  status: string
  entry_count: number
}
export interface Timetable {
  id: number
  semester_id: number
  name: string
  status: string
  entries: ScheduleEntry[]
}
export interface Conflict {
  code: string
  message: string
}
export interface CheckResponse {
  ok: boolean
  conflicts: Conflict[]
}

export const listTimetables = (semesterId: number) =>
  apiGet<TimetableBrief[]>(`/timetables?semester_id=${semesterId}`)
export const createTimetable = (semesterId: number, name: string) =>
  apiPost<Timetable>(`/timetables?semester_id=${semesterId}`, { name })
export const getTimetable = (id: number) => apiGet<Timetable>(`/timetables/${id}`)
export const deleteTimetable = (id: number) => request<void>('DELETE', `/timetables/${id}`)

export const checkConflict = (
  timetableId: number,
  body: {
    course_assignment_id: number
    weekday: number
    period_no: number
    span?: number
    ignore_entry_id?: number
  },
) => apiPost<CheckResponse>(`/timetables/${timetableId}/check-conflict`, body)

export const placeEntry = (
  timetableId: number,
  body: { course_assignment_id: number; weekday: number; period_no: number; span?: number },
) => apiPost<Timetable>(`/timetables/${timetableId}/entries`, body)

export const moveEntry = (
  timetableId: number,
  entryId: number,
  body: { weekday: number; period_no: number },
) => request<Timetable>('PATCH', `/timetables/${timetableId}/entries/${entryId}`, body)

export const deleteEntry = (timetableId: number, entryId: number) =>
  request<void>('DELETE', `/timetables/${timetableId}/entries/${entryId}`)

export const lockEntry = (timetableId: number, entryId: number, locked: boolean) =>
  apiPost<Timetable>(`/timetables/${timetableId}/entries/${entryId}/lock?locked=${locked}`)

export const getClassPeriodTable = (classId: number) =>
  apiGet<PeriodTable>(`/class-units/${classId}/period-table`)

/** place/move 失敗時後端回 409,detail 可能是字串或 { message, conflicts }。 */
export function conflictText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'conflicts' in detail) {
    const d = detail as { message?: string; conflicts?: Conflict[] }
    const first = d.conflicts?.[0]?.message
    return first ? first : (d.message ?? '無法排入')
  }
  return '無法排入'
}
