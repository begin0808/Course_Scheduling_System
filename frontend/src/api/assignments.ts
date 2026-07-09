// 配課(排課單位 / 配課 / 鐘點統計)API 型別與呼叫封裝。

import { apiGet, apiPost, request } from '@/api/client'
import type { RoomType } from '@/api/basedata'

export interface ClassBrief {
  id: number
  name: string
  grade: number
}
export interface SchedulingUnit {
  id: number
  semester_id: number
  unit_type: 'single' | 'group'
  name: string
  classes: ClassBrief[]
}
export interface AssignmentTeacher {
  teacher_id: number
  is_lead: boolean
  name: string
}
export interface BlockRule {
  id?: number
  block_size: number
  count_per_week: number
}
export interface Assignment {
  id: number
  semester_id: number
  scheduling_unit: SchedulingUnit
  subject: { id: number; name: string }
  periods_per_week: number
  required_room_type: RoomType | null
  room_id: number | null
  lock_room: boolean
  teachers: AssignmentTeacher[]
  block_rules: BlockRule[]
}
export interface TeacherLoad {
  teacher_id: number
  name: string
  base_periods: number
  admin_reduction: number
  target: number
  assigned: number
  delta: number
}
export interface ClassLoad {
  class_id: number
  name: string
  grade: number
  assigned: number
  capacity: number
  over_capacity: boolean
}

export interface AssignmentPayload {
  class_id?: number | null
  scheduling_unit_id?: number | null
  subject_id: number
  periods_per_week: number
  teachers: { teacher_id: number; is_lead: boolean }[]
  block_rules: { block_size: number; count_per_week: number }[]
  required_room_type?: RoomType | null
  room_id?: number | null
  lock_room?: boolean
}

// ── 跑班群組 ──
export const listGroups = (semesterId: number) =>
  apiGet<SchedulingUnit[]>(`/scheduling-units?semester_id=${semesterId}`)
export const createGroup = (semesterId: number, body: { name: string; class_ids: number[] }) =>
  apiPost<SchedulingUnit>(`/scheduling-units?semester_id=${semesterId}`, body)
export const deleteGroup = (id: number) => request<void>('DELETE', `/scheduling-units/${id}`)

// ── 配課 ──
export const listAssignments = (semesterId: number) =>
  apiGet<Assignment[]>(`/assignments?semester_id=${semesterId}`)
export const createAssignment = (semesterId: number, body: AssignmentPayload) =>
  apiPost<Assignment>(`/assignments?semester_id=${semesterId}`, body)
export const updateAssignment = (id: number, body: AssignmentPayload) =>
  request<Assignment>('PATCH', `/assignments/${id}`, body)
export const deleteAssignment = (id: number) => request<void>('DELETE', `/assignments/${id}`)

// ── 統計 ──
export const teacherLoad = (semesterId: number) =>
  apiGet<TeacherLoad[]>(`/assignments/teacher-load?semester_id=${semesterId}`)
export const classLoad = (semesterId: number) =>
  apiGet<ClassLoad[]>(`/assignments/class-load?semester_id=${semesterId}`)
