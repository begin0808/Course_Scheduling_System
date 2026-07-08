// 學期與節次表 API 型別與呼叫封裝。

import { apiGet, apiPost, request } from '@/api/client'

export type PeriodType = 'regular' | 'morning' | 'lunch' | 'homeroom' | 'reserved'

export interface Period {
  id?: number
  weekday: number
  period_no: number
  name: string
  start_time: string | null
  end_time: string | null
  type: PeriodType
}

export interface PeriodTable {
  id: number
  name: string
  num_weekdays: number
  is_default: boolean
  periods: Period[]
}

export interface SemesterListItem {
  id: number
  academic_year: number
  term: number
  label: string
  status: 'preparing' | 'active' | 'archived'
  start_date: string | null
  end_date: string | null
}

export interface Semester extends SemesterListItem {
  period_tables: PeriodTable[]
}

export interface Template {
  key: string
  name: string
  minutes_per_period: number
  subject_count: number
}

export const PERIOD_TYPE_LABELS: Record<PeriodType, string> = {
  regular: '一般課',
  morning: '早自習',
  lunch: '午休',
  homeroom: '導師時間',
  reserved: '固定用途',
}

export const STATUS_LABELS: Record<SemesterListItem['status'], string> = {
  preparing: '準備中',
  active: '進行中',
  archived: '已封存',
}

export const listTemplates = () => apiGet<Template[]>('/school-templates')
export const listSemesters = () => apiGet<SemesterListItem[]>('/semesters')
export const getSemester = (id: number) => apiGet<Semester>(`/semesters/${id}`)
export const createSemester = (body: {
  academic_year: number
  term: number
  template_key?: string | null
  start_date?: string | null
  end_date?: string | null
}) => apiPost<Semester>('/semesters', body)
export const updateSemester = (
  id: number,
  body: { status?: string; start_date?: string | null; end_date?: string | null },
) => request<Semester>('PATCH', `/semesters/${id}`, body)
export const deleteSemester = (id: number) => request<void>('DELETE', `/semesters/${id}`)

export const createPeriodTable = (
  semesterId: number,
  body: { name: string; num_weekdays?: number; is_default?: boolean; template_key?: string | null },
) => apiPost<PeriodTable>(`/semesters/${semesterId}/period-tables`, body)
export const getPeriodTable = (id: number) => apiGet<PeriodTable>(`/period-tables/${id}`)

export interface AvailableSlot {
  weekday: number
  period_no: number
  name: string
  start_time: string | null
  end_time: string | null
}
export const getAvailableSlots = (tableId: number) =>
  apiGet<AvailableSlot[]>(`/period-tables/${tableId}/available-slots`)
export const updatePeriodTable = (id: number, body: { name?: string; is_default?: boolean }) =>
  request<PeriodTable>('PATCH', `/period-tables/${id}`, body)
export const deletePeriodTable = (id: number) => request<void>('DELETE', `/period-tables/${id}`)
export const replacePeriods = (id: number, periods: Period[]) =>
  request<PeriodTable>('PUT', `/period-tables/${id}/periods`, periods)
