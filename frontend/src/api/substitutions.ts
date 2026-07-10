// 調代課處理:代課推薦、指派處置(M4-2)。

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

export interface AssignBody {
  type: string
  handler_teacher_id?: number | null
  counts_toward_hours?: boolean | null
  funding_source?: string
  swap_entry_id?: number | null
  swap_date?: string | null
}

export const listSubstitutionTypes = (): Promise<Record<string, string>> =>
  apiGet('/substitution-types')

export const getRecommendations = (affectedId: number): Promise<Recommendation> =>
  apiGet(`/affected-periods/${affectedId}/recommendations`)

export const assignSubstitution = (affectedId: number, body: AssignBody): Promise<Substitution> =>
  apiPut(`/affected-periods/${affectedId}/substitution`, body)

export const clearSubstitution = (affectedId: number): Promise<{ status: string }> =>
  apiDelete(`/affected-periods/${affectedId}/substitution`)
