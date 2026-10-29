// 代導(v1.4.0):導師請假當天,由誰代他帶班。

import { apiDelete, apiGet, apiPut } from '@/api/client'
import type { HomeroomCover } from '@/api/leaves'

export interface CoverOption {
  teacher_id: number
  teacher_name: string
  group: 'same_grade_homeroom' | 'class_teacher' | 'other'
  group_label: string // 同年級導師 / 該班任課老師 / 其他老師
  note: string // 「702 導師」「教 701 國文」
}

export interface CoverSkip {
  cover_id: number
  date: string
  class_name: string
  reason: string
}

export interface CoverAssign {
  handler_teacher_id?: number | null
  no_cover?: boolean // 標記「不需代導」
  whole_leave?: boolean // 同一張假單、同一班其他還沒安排的日子一起指派
}

/** 代導紀錄的一列:多帶請假導師與假別 */
export interface CoverLog extends HomeroomCover {
  absent_teacher_name: string
  leave_type_label: string
}

export interface CoverSlipRow {
  date: string
  weekday: number
  part_label: string
  class_name: string
  absent_teacher_name: string
  leave_type_label: string
}

export interface CoverSlips {
  school_name: string
  semester_label: string
  slips: { teacher_name: string; rows: CoverSlipRow[] }[]
}

export const getCoverOptions = (coverId: number): Promise<{ options: CoverOption[] }> =>
  apiGet(`/homeroom-covers/${coverId}/options`)

export const assignCover = (
  coverId: number, body: CoverAssign,
): Promise<{ assigned: number; skipped: CoverSkip[] }> =>
  apiPut(`/homeroom-covers/${coverId}`, body)

export const clearCover = (coverId: number): Promise<{ ok: boolean }> =>
  apiDelete(`/homeroom-covers/${coverId}`)

export const listCovers = (
  semesterId: number,
  f: { teacherId?: number | null; dateFrom?: string | null; dateTo?: string | null } = {},
): Promise<CoverLog[]> => {
  const p = new URLSearchParams({ semester_id: String(semesterId) })
  if (f.teacherId) p.set('teacher_id', String(f.teacherId))
  if (f.dateFrom) p.set('date_from', f.dateFrom)
  if (f.dateTo) p.set('date_to', f.dateTo)
  return apiGet(`/homeroom-covers?${p}`)
}

export const getCoverSlips = (semesterId: number, coverIds: number[]): Promise<CoverSlips> => {
  const q = new URLSearchParams({ semester_id: String(semesterId) })
  for (const id of coverIds) q.append('cover_ids', String(id))
  return apiGet(`/homeroom-cover-slips?${q}`)
}

/** 在新分頁開啟代導通知單(列印頁不套側邊欄) */
export function openCoverSlips(semesterId: number, coverIds: number[]): void {
  window.open(
    `/homeroom-cover-slips/print?semester_id=${semesterId}&ids=${coverIds.join(',')}`, '_blank')
}
