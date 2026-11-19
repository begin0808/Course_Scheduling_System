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
  is_tutoring: boolean  // 寒暑假輔導(v1.4.22):不管基本鐘點與超鐘點
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

// 學期類型。3、4 是寒暑假輔導(v1.4.22):起訖日期必填、不能和其他學期重疊
export const TERM_OPTIONS = [
  { label: '第 1 學期', value: 1 },
  { label: '第 2 學期', value: 2 },
  { label: '寒假輔導', value: 3 },
  { label: '暑期輔導', value: 4 },
]
export const isTutoringTerm = (term: number) => term === 3 || term === 4

function todayIso(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 學期下拉選單需要的欄位(教師登入時來自已發布課表的學期清單,只有這幾欄)。 */
export interface SemesterPick {
  id: number
  label: string
  start_date?: string | null
  end_date?: string | null
}

/**
 * 各頁預設選的學期:今天落在起訖日期內的那一個,沒有才選清單第一個(最新的)。
 * 輔導學期常在學期進行中就先建好,只取第一個會讓每天的請假、代課都跳到還沒開始的輔導。
 * 呼叫端要先確認清單不是空的。
 */
export function defaultSemester<T extends { start_date?: string | null; end_date?: string | null }>(
  list: T[], today: string = todayIso(),
): T {
  return list.find((s) => !!s.start_date && !!s.end_date
    && s.start_date <= today && today <= s.end_date) ?? list[0]
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

export interface CopyOptions {
  academic_year: number
  term: number
  // 新學期的起訖日:少了它,請假展開與今日看板的判定會失準,且畫面上看不出哪裡不對
  start_date: string | null
  end_date: string | null
  period_tables: boolean
  subjects: boolean
  teachers: boolean
  rooms: boolean
  classes: boolean
  grade_promotion: boolean
  constraint_config: boolean  // 軟約束權重(不帶則新學期回到預設值)
}
export const copySemester = (id: number, body: CopyOptions) =>
  apiPost<Semester>(`/semesters/${id}/copy`, body)

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
