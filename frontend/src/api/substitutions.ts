// 調代課處理:代課推薦、指派處置(M4-2)、可對調節次(v1.2.1)。

import { apiDelete, apiGet, apiPut } from '@/api/client'

export interface Candidate {
  teacher_id: number
  teacher_name: string
  same_subject: boolean
  at_school_that_day: boolean
  sub_periods_this_month: number
  reasons: string[]
}

export interface Recommendation {
  affected_period_id: number
  candidates: Candidate[]
  no_candidate_hint: string
}

export interface Substitution {
  id: number
  affected_period_id: number
  type: string
  type_label: string
  handler_teacher_id: number | null
  handler_name: string | null
  counts_toward_hours: boolean
  funding_source: string
  swap_date: string | null
  swap_period_name: string
  swap_class_names: string
  swap_subject_name: string
  created_by_name: string
}

/** 乙的某一節課、在某一天,可改由請假的甲來補 */
export interface SwapOption {
  entry_id: number
  date: string
  weekday: number
  period_no: number
  period_name: string
  class_names: string
  subject_name: string
  same_class: boolean // 與請假那節同一班(同班互調)
  in_block: boolean // 連堂中的一節(只換這一節)
}

export interface SwapPartner {
  teacher_id: number
  teacher_name: string
  teaches_same_class: boolean
  blocked_reason: string // 非空 = 這位老師在請假那節就來不了
  options: SwapOption[]
}

export interface SwapOptions {
  affected_period_id: number
  date_from: string
  date_to: string
  partners: SwapPartner[]
}

export interface AssignBody {
  type: string
  handler_teacher_id?: number | null
  counts_toward_hours?: boolean | null
  funding_source?: string
  swap_entry_id?: number | null
  swap_date?: string | null
  swap_period_no?: number | null // 連堂格位換其中哪一節
}

export const listSubstitutionTypes = (): Promise<Record<string, string>> =>
  apiGet('/substitution-types')

export const getRecommendations = (affectedId: number): Promise<Recommendation> =>
  apiGet(`/affected-periods/${affectedId}/recommendations`)

export const assignSubstitution = (affectedId: number, body: AssignBody): Promise<Substitution> =>
  apiPut(`/affected-periods/${affectedId}/substitution`, body)

export const clearSubstitution = (affectedId: number): Promise<{ status: string }> =>
  apiDelete(`/affected-periods/${affectedId}/substitution`)

/** 未指定教師時,只找也教這個班的老師 */
export const getSwapOptions = (affectedId: number, teacherId?: number | null): Promise<SwapOptions> =>
  apiGet(`/affected-periods/${affectedId}/swap-options${teacherId ? `?teacher_id=${teacherId}` : ''}`)
