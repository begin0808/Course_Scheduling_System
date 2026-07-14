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
  stale_affected?: number // 發布後:依舊課表展開、今日之後的調代課數(>0 需重新檢視)
}
export interface Conflict {
  code: string
  message: string
}
export interface CheckResponse {
  ok: boolean
  conflicts: Conflict[]
}

// ── 版本管理與發布 ──
export interface UnplacedItem {
  course_assignment_id: number
  subject: string
  classes: string[]
  teachers: string[]
  required: number
  placed: number
  remaining: number
  reason: string  // 自動排課當時 solver 說的「為什麼排不下」;手動未排完則為空
}
export interface Completeness {
  required: number
  placed: number
  remaining: number
  complete: boolean
  unplaced: UnplacedItem[]
}

// ── 全員唯讀查詢 ──
export interface PublicSemester { id: number; label: string }
export interface NamedBrief { id: number; name: string }
export interface PublicClass {
  id: number
  name: string
  grade: number
  period_table_id: number | null
}
export interface PublishedTimetable {
  id: number
  semester_id: number
  semester_label: string
  name: string
  status: string
  entries: ScheduleEntry[]
  classes: PublicClass[]
  teachers: NamedBrief[]
  rooms: NamedBrief[]
  period_tables: PeriodTable[]
}

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已發布',
  archived: '已封存',
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

export const renameTimetable = (id: number, name: string) =>
  request<Timetable>('PATCH', `/timetables/${id}`, { name })
export const duplicateTimetable = (id: number, name: string) =>
  apiPost<Timetable>(`/timetables/${id}/duplicate`, { name })
export const getCompleteness = (id: number) =>
  apiGet<Completeness>(`/timetables/${id}/completeness`)
export const publishTimetable = (id: number, force = false) =>
  apiPost<Timetable>(`/timetables/${id}/publish${force ? '?force=true' : ''}`)

export const publishedSemesters = () => apiGet<PublicSemester[]>('/published/semesters')
export const getPublishedTimetable = (semesterId: number) =>
  apiGet<PublishedTimetable | null>(`/published/timetable?semester_id=${semesterId}`)
export const getMyTeacher = (semesterId: number) =>
  apiGet<NamedBrief | null>(`/published/my-teacher?semester_id=${semesterId}`)

/** 發布被擋(409)時,detail 內含完整性報告。 */
export function publishReport(detail: unknown): Completeness | null {
  if (detail && typeof detail === 'object' && 'completeness' in detail) {
    return (detail as { completeness: Completeness }).completeness
  }
  return null
}

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
