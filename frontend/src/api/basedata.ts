// 基礎資料(教師/科目/場地/班級)API 型別與呼叫封裝。

import { apiGet, apiPost, request } from '@/api/client'

export type RoomType = 'normal' | 'special' | 'workshop' | 'outdoor'
export type ClassTrack = 'elementary' | 'junior_high' | 'senior_high' | 'comprehensive' | 'vocational'
export type TeacherRuleType = 'unavailable' | 'avoid' | 'prefer'

export interface SubjectBrief {
  id: number
  name: string
}
export interface Subject {
  id: number
  semester_id: number
  name: string
  domain: string | null
  required_room_type: RoomType | null
  default_block_size: number
}
export interface Teacher {
  id: number
  semester_id: number
  name: string
  base_periods: number
  admin_title: string | null
  admin_reduction: number
  is_external: boolean
  is_active: boolean
  subjects: SubjectBrief[]
}
export interface TeacherTimeRule {
  id?: number
  weekday: number
  period_no: number
  rule_type: TeacherRuleType
}
export interface Room {
  id: number
  semester_id: number
  name: string
  room_type: RoomType
  capacity: number | null
  subjects: SubjectBrief[]
}
export interface ClassUnit {
  id: number
  semester_id: number
  grade: number
  name: string
  track: ClassTrack
  department: string | null
  student_count: number | null
  homeroom_teacher_id: number | null
  homeroom_teacher: SubjectBrief | null
}

export const ROOM_TYPE_LABELS: Record<RoomType, string> = {
  normal: '普通教室',
  special: '專科教室',
  workshop: '實習工場',
  outdoor: '戶外',
}
export const TRACK_LABELS: Record<ClassTrack, string> = {
  elementary: '國小',
  junior_high: '國中',
  senior_high: '普通型高中',
  comprehensive: '綜合型高中',
  vocational: '技術型高中',
}
export const RULE_TYPE_LABELS: Record<TeacherRuleType, string> = {
  unavailable: '不可排',
  avoid: '盡量避開',
  prefer: '偏好',
}

// ── 科目 ──
export const listSubjects = (semesterId: number, q?: string) =>
  apiGet<Subject[]>(`/subjects?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createSubject = (semesterId: number, body: Partial<Subject>) =>
  apiPost<Subject>(`/subjects?semester_id=${semesterId}`, body)
export const updateSubject = (id: number, body: Partial<Subject>) =>
  request<Subject>('PATCH', `/subjects/${id}`, body)
export const deleteSubject = (id: number) => request<void>('DELETE', `/subjects/${id}`)

// ── 教師 ──
export const listTeachers = (semesterId: number, q?: string) =>
  apiGet<Teacher[]>(`/teachers?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createTeacher = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<Teacher>(`/teachers?semester_id=${semesterId}`, body)
export const updateTeacher = (id: number, body: Record<string, unknown>) =>
  request<Teacher>('PATCH', `/teachers/${id}`, body)
export const deleteTeacher = (id: number) => request<void>('DELETE', `/teachers/${id}`)
export const getTimeRules = (id: number) => apiGet<TeacherTimeRule[]>(`/teachers/${id}/time-rules`)
export const replaceTimeRules = (id: number, rules: TeacherTimeRule[]) =>
  request<TeacherTimeRule[]>('PUT', `/teachers/${id}/time-rules`, rules)

// ── 場地 ──
export const listRooms = (semesterId: number, q?: string) =>
  apiGet<Room[]>(`/rooms?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`)
export const createRoom = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<Room>(`/rooms?semester_id=${semesterId}`, body)
export const updateRoom = (id: number, body: Record<string, unknown>) =>
  request<Room>('PATCH', `/rooms/${id}`, body)
export const deleteRoom = (id: number) => request<void>('DELETE', `/rooms/${id}`)

// ── 班級 ──
export const listClassUnits = (semesterId: number, q?: string) =>
  apiGet<ClassUnit[]>(
    `/class-units?semester_id=${semesterId}${q ? `&q=${encodeURIComponent(q)}` : ''}`,
  )
export const createClassUnit = (semesterId: number, body: Record<string, unknown>) =>
  apiPost<ClassUnit>(`/class-units?semester_id=${semesterId}`, body)
export const updateClassUnit = (id: number, body: Record<string, unknown>) =>
  request<ClassUnit>('PATCH', `/class-units/${id}`, body)
export const deleteClassUnit = (id: number) => request<void>('DELETE', `/class-units/${id}`)
