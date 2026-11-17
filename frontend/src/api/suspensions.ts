// 停課日(v1.4.19):全校、年級或指定班級,整天或第幾節到第幾節不上課。

import { apiDelete, apiGet, apiPost, apiPut } from '@/api/client'

export interface Suspension {
  id: number
  start_date: string
  end_date: string
  whole_school: boolean
  class_ids: number[]
  all_day: boolean
  from_ordinal: number | null
  to_ordinal: number | null
  reason: string
  target_text: string // 「全校」「七年級」「701、801」
  period_text: string // 「整天」「第 5~7 節」
  created_by_name: string
}

export interface SuspensionIn {
  start_date: string
  end_date: string
  whole_school: boolean
  class_ids: number[]
  all_day: boolean
  from_ordinal: number | null
  to_ordinal: number | null
  reason: string
}

export interface SuspensionSaved {
  item: Suspension
  /** 停課時段裡已經安排好的請假節次、調課補課、代導(系統不自動改) */
  conflicts: string[]
}

export const listSuspensions = (semesterId: number) =>
  apiGet<Suspension[]>(`/suspensions?semester_id=${semesterId}`)
export const createSuspension = (semesterId: number, body: SuspensionIn) =>
  apiPost<SuspensionSaved>(`/suspensions?semester_id=${semesterId}`, body)
export const updateSuspension = (id: number, body: SuspensionIn) =>
  apiPut<SuspensionSaved>(`/suspensions/${id}`, body)
export const deleteSuspension = (id: number) => apiDelete<void>(`/suspensions/${id}`)
