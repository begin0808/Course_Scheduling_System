// 調代課處理:代課推薦、指派處置(M4-2)、可對調節次(v1.2.1)、通知單(v1.2.2/v1.2.5)。

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

/** 未指定教師時,只找也教這個班的老師;weeks = 從請假那週起找幾週(1–4) */
export const getSwapOptions = (
  affectedId: number, teacherId?: number | null, weeks = 2,
): Promise<SwapOptions> => {
  const q = new URLSearchParams({ weeks: String(weeks) })
  if (teacherId) q.set('teacher_id', String(teacherId))
  return apiGet(`/affected-periods/${affectedId}/swap-options?${q}`)
}

// ── 通知單(調課單 v1.2.2、代課單 v1.2.5;兩者版面相同,表頭與格子內容不同)──

export interface SlipRow {
  ordinal: number // 第幾節(只數一般課)
  start_time: string | null
  end_time: string | null
  afternoon_starts: boolean // 下午第一節:紙本在這裡畫粗線
}

export interface SlipCell {
  date: string
  weekday: number
  ordinal: number
  subject_name: string
  actor: string // 第三行:調課單寫上課老師;代課單寫「班級[代]」或「老師[代]」
  code: string // 「調09-15_25」:與 9/15 星期二第 5 節對調;代課單沒有
}

export interface SlipWeek {
  monday: string
  days: string[]
  cells: SlipCell[]
}

export interface Slip {
  kind: 'teacher' | 'class'
  teacher_name: string
  class_names: string
  date_from: string
  date_to: string
  absent_teacher_name: string // 代課單:請假教師
  leave_type_name: string // 代課單:假別
  funding_label: string // 代課單:計費方式
  rows: SlipRow[]
  weeks: SlipWeek[]
}

export interface Slips {
  title: string
  kind: 'swap' | 'substitute'
  slips: Slip[]
}

const slipsQuery = (semesterId: number, affectedIds: number[]): string => {
  const q = new URLSearchParams({ semester_id: String(semesterId) })
  for (const id of affectedIds) q.append('affected_period_ids', String(id))
  return String(q)
}

export const getSwapSlips = (semesterId: number, affectedIds: number[]): Promise<Slips> =>
  apiGet(`/swap-slips?${slipsQuery(semesterId, affectedIds)}`)

export const getSubstituteSlips = (semesterId: number, affectedIds: number[]): Promise<Slips> =>
  apiGet(`/substitute-slips?${slipsQuery(semesterId, affectedIds)}`)

export const listFundingSources = (): Promise<string[]> =>
  apiGet('/substitution-funding-sources')

/** 在新分頁開啟通知單(列印頁不套側邊欄);kind 決定印調課單還是代課單 */
export function openSlips(
  kind: 'swap' | 'substitute', semesterId: number, affectedIds: number[],
): void {
  const path = kind === 'swap' ? '/swap-slips/print' : '/substitute-slips/print'
  window.open(`${path}?semester_id=${semesterId}&ids=${affectedIds.join(',')}`, '_blank')
}
