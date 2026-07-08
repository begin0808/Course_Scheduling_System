// 設定精靈 API。

import { apiGet, request } from '@/api/client'

export interface WizardState {
  current_step: number
  completed: boolean
  semester_id: number | null
  total_steps: number
  has_semesters: boolean
}

export interface SemesterSummary {
  subjects: number
  teachers: number
  classes: number
  rooms: number
}

export const getWizardState = () => apiGet<WizardState>('/wizard/state')
export const updateWizardState = (body: {
  current_step?: number
  completed?: boolean
  semester_id?: number | null
}) => request<WizardState>('PATCH', '/wizard/state', body)
export const resetWizard = () => request<WizardState>('POST', '/wizard/reset')
export const getSemesterSummary = (id: number) =>
  apiGet<SemesterSummary>(`/semesters/${id}/summary`)
