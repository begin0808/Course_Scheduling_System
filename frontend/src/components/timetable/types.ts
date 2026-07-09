// TimetableGrid 元件的共用型別。此元件為純展示+事件元件,不含商業邏輯:
// 拖曳中的內容、衝突判定、放下結果一律由父層決定並以 props/events 溝通。

export interface PeriodCell {
  weekday: number // 1=週一 …
  period_no: number // 當日節次順序(含休息時段)
  name: string // 顯示名稱,如「第一節」「午休」
  type: string // 'regular'(可排課)| morning/lunch/homeroom/reserved(反灰)
  start_time?: string | null // 'HH:MM' 或 'HH:MM:SS'
  end_time?: string | null
}

export interface GridEntry {
  id: number | string
  weekday: number
  period_no: number
  subject: string
  teacher?: string
  room?: string
  locked?: boolean
  span?: number // 連堂長度(佔用連續節數),預設 1
}

// 拖曳中的內容(對元件不透明,僅用於回傳給父層決策)
export interface DragData {
  source: 'tray' | 'grid'
  entryId?: number | string
  [k: string]: unknown
}

export interface DropTarget {
  weekday: number
  period_no: number
}

// 父層在拖曳過程回填的可放/衝突判定,元件據此渲染綠框/紅框與原因
export interface DropFeedback extends DropTarget {
  ok: boolean
  reason?: string
}

export interface DragEventPayload extends DropTarget {
  data: DragData | null
}
