// 調代課處理:代課推薦、指派處置(M4-2)、可對調節次(v1.2.1)、通知單(v1.2.2/v1.2.5)。

import { apiDelete, apiGet, apiPost, apiPut, request } from '@/api/client'

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
  // 三角調課(v1.4.20):丙來上乙的 tri 那一節;swap_* 是丙那一節(甲回來上)
  tri_teacher_id: number | null
  tri_teacher_name: string
  tri_date: string | null
  tri_period_name: string
  tri_class_names: string
  tri_subject_name: string
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
  blocked_reason: string // 只有 blocked 清單裡的才有:換不了的原因(v1.4.12)
}

export interface SwapPartner {
  teacher_id: number
  teacher_name: string
  teaches_same_class: boolean
  blocked_reason: string // 非空 = 這位老師在請假那節就來不了
  options: SwapOption[]
  blocked: SwapOption[] // 換不了的節次與原因(v1.4.12);已上過、不在學期內的不列
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
  // 三角調課(v1.4.20)
  tri_teacher_id?: number | null
  tri_entry_id?: number | null
  tri_date?: string | null
  tri_period_no?: number | null
}

/** 三角調課的一格:這一班某一天某一節的課(一位老師上) */
export interface TriangleLesson {
  entry_id: number
  date: string
  weekday: number
  period_no: number
  period_name: string
  class_names: string
  subject_name: string
  in_block: boolean
  teacher_id: number
  teacher_name: string
}

/** 一組三角調課:乙(partner)來上請假那節;丙(third)來上乙的 mid;請假老師回來上丙的 makeup */
export interface TriangleOption {
  partner_id: number
  partner_name: string
  mid: TriangleLesson
  third_id: number
  third_name: string
  makeup: TriangleLesson
}

/** 指定老師(v1.4.21):他能湊成幾組,其餘節次為什麼湊不成 */
export interface TriangleTeacherCheck {
  teacher_id: number
  teacher_name: string
  found: number
  note: string // 非空 = 這段期間沒有這一班的課
  as_partner: string[] // 當 ①:來上請假那一節
  as_third: string[] // 當 ②:來上別人讓出的一節,請假老師回來上他的課
}

export interface TriangleOptions {
  affected_period_id: number
  date_from: string
  date_to: string
  unavailable: string // 非空 = 這一節不能三角調課(跑班、協同教學…)
  total: number // 一共幾組(清單最多回 200 組)
  options: TriangleOption[]
  teachers: { teacher_id: number; teacher_name: string }[] // 這一班有課的老師(指定老師的選單)
  check: TriangleTeacherCheck | null
}

export const listSubstitutionTypes = (): Promise<Record<string, string>> =>
  apiGet('/substitution-types')

export const getRecommendations = (affectedId: number): Promise<Recommendation> =>
  apiGet(`/affected-periods/${affectedId}/recommendations`)

export const assignSubstitution = (affectedId: number, body: AssignBody): Promise<Substitution> =>
  apiPut(`/affected-periods/${affectedId}/substitution`, body)

/** 整批指派代課:一張假單(或其中一天)還沒處理的節次,全部派給同一位老師。 */
export interface BatchAssignBody {
  handler_teacher_id: number
  funding_source?: string
  counts_toward_hours?: boolean | null
  date?: string | null // 空 = 整張假單
}
export interface BatchSkip {
  affected_period_id: number
  date: string
  period_name: string
  class_names: string
  subject_name: string
  reason: string
}
export interface BatchAssignResult {
  assigned: number
  skipped: BatchSkip[]
}
export const assignSubstitutionBatch = (
  leaveId: number, body: BatchAssignBody,
): Promise<BatchAssignResult> => apiPost(`/leaves/${leaveId}/substitutions/batch`, body)

// 修改代課的計費方式(v1.4.4):代課老師不變,已經過去的節次也可以改
export interface BillingBody {
  funding_source: string
  counts_toward_hours?: boolean | null
}
export const updateBilling = (affectedId: number, body: BillingBody): Promise<{ updated: number }> =>
  request('PATCH', `/affected-periods/${affectedId}/substitution/billing`, body)
export const updateLeaveBilling = (leaveId: number, body: BillingBody): Promise<{ updated: number }> =>
  request('PATCH', `/leaves/${leaveId}/substitutions/billing`, body)

export const clearSubstitution = (affectedId: number): Promise<{ status: string }> =>
  apiDelete(`/affected-periods/${affectedId}/substitution`)

/** 未指定教師時,只找也教這個班的老師;weeks = 從請假那週起找幾週(1–4) */
// ── 併班(v1.3.5):這一節正在上自己班的老師,把請假老師的班併過去 ──
export interface MergeOption {
  teacher_id: number
  teacher_name: string
  class_names: string // 接手老師這一節在上的班
  subject_name: string
  same_grade: boolean
  same_subject: boolean
}

export const getMergeOptions = (affectedId: number): Promise<{ options: MergeOption[] }> =>
  apiGet(`/affected-periods/${affectedId}/merge-options`)

/** start:從這天所在的那週開始找(YYYY-MM-DD);不給 = 請假那週 */
export const getSwapOptions = (
  affectedId: number, teacherId?: number | null, weeks = 2, start?: string | null,
): Promise<SwapOptions> => {
  const q = new URLSearchParams({ weeks: String(weeks) })
  if (teacherId) q.set('teacher_id', String(teacherId))
  if (start) q.set('start', start)
  return apiGet(`/affected-periods/${affectedId}/swap-options?${q}`)
}

/** 三角調課(v1.4.20):範圍與互調相同 */
export const getTriangleOptions = (
  affectedId: number, weeks = 2, start?: string | null, teacherId?: number | null,
): Promise<TriangleOptions> => {
  const q = new URLSearchParams({ weeks: String(weeks) })
  if (start) q.set('start', start)
  if (teacherId) q.set('teacher_id', String(teacherId))
  return apiGet(`/affected-periods/${affectedId}/triangle-options?${q}`)
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
  code: string // 「調9/15_25」:與 9/15 星期二第 5 節對調;代課單沒有
  time_note?: string // 跨節次表的格子:實際上課時間(與格線那一列不同時才有)
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
