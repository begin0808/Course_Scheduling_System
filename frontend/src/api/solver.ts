// 排課引擎 API:pre-flight 檢查、軟約束設定、自動排課任務與進度。

import { apiGet, apiPost, apiPut } from '@/api/client'

export interface PreflightIssue {
  level: 'error' | 'warning'
  code: string
  message: string
  subject_type: string
  subject_id: number
}
export interface PreflightReport {
  semester_id: number
  semester_label: string
  ok: boolean
  error_count: number
  warning_count: number
  issues: PreflightIssue[]
  class_count: number
  teacher_count: number
  assignment_count: number
  total_periods: number
}

export interface SoftScore {
  code: string
  name: string
  weight: number
  opportunities: number
  satisfied: number
  violations: number
  penalty: number
  rate: number
  details: string[]
}
export interface SoftReport {
  total_penalty: number
  items: SoftScore[]
}

export type JobStatus = 'queued' | 'running' | 'finished' | 'failed' | 'cancelled'
export type JobPhase = 'solving' | 'explaining'

/** 無解時的一條原因:message 說發生什麼事,suggestion 說可以怎麼辦。 */
export interface ConflictCause {
  code: string
  scope_type: string
  scope_id: number
  scope_name: string
  message: string
  suggestion: string
  relaxable: boolean
  detail: Record<string, number | string>
}
export interface ConflictReport {
  status: string
  source: 'preflight' | 'analysis' | 'none'
  mode: 'each' | 'joint' | 'structural' | ''
  headline: string
  complete: boolean
  relaxable_codes: string[]
  causes: ConflictCause[]
}

export interface UnscheduledCourse {
  assignment_id: number
  subject_name: string
  class_names: string[]
  periods: number
}

export interface RelaxableOption {
  code: string
  name: string
}

export interface SolveJob {
  job_id: string
  status: JobStatus
  semester_id: number
  source_timetable_id: number
  source_name: string
  max_seconds: number
  elapsed: number
  solutions: number
  objective: number | null
  result_timetable_id: number | null
  result_name: string | null
  error: string | null
  report: SoftReport | null
  phase: JobPhase
  partial: boolean
  conflict: ConflictReport | null
  unscheduled: UnscheduledCourse[] | null
}

export interface ConstraintConfig {
  semester_id: number
  daily_subject_cap: number
  teacher_daily_max: number
  teacher_consecutive_max: number
  weights: Record<string, number>
  weight_names: Record<string, string>
}

export const preflight = (semesterId: number): Promise<PreflightReport> =>
  apiGet(`/solver/preflight?semester_id=${semesterId}`)

export const getConstraintConfig = (semesterId: number): Promise<ConstraintConfig> =>
  apiGet(`/solver/config?semester_id=${semesterId}`)

export const saveConstraintConfig = (
  semesterId: number,
  body: Omit<ConstraintConfig, 'semester_id' | 'weight_names'>,
): Promise<ConstraintConfig> => apiPut(`/solver/config?semester_id=${semesterId}`, body)

export const listRelaxable = (): Promise<RelaxableOption[]> => apiGet('/solver/relaxable')

export const startAutoSchedule = (
  timetableId: number,
  maxSeconds: number,
  options: { allowPartial?: boolean; relax?: string[] } = {},
): Promise<{ job_id: string }> =>
  apiPost(`/timetables/${timetableId}/auto-schedule`, {
    max_seconds: maxSeconds,
    seed: 0,
    allow_partial: options.allowPartial ?? false,
    relax: options.relax ?? [],
  })

export const getSolveJob = (jobId: string): Promise<SolveJob> => apiGet(`/solver/jobs/${jobId}`)
export const stopSolveJob = (jobId: string): Promise<SolveJob> =>
  apiPost(`/solver/jobs/${jobId}/stop`)
export const cancelSolveJob = (jobId: string): Promise<SolveJob> =>
  apiPost(`/solver/jobs/${jobId}/cancel`)
