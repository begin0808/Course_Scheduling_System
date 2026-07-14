<script setup lang="ts">
import { computed } from 'vue'
import type { DragData, DropFeedback, GridEntry, PeriodCell } from './types'

const props = withDefaults(defineProps<{
  periods: PeriodCell[]
  entries?: GridEntry[]
  numWeekdays?: number
  readonly?: boolean
  dragging?: DragData | null // 父層告知目前拖曳中的內容(供 check feedback)
  feedback?: DropFeedback | null // 父層回填的可放/衝突判定
}>(), {
  entries: () => [],
  numWeekdays: undefined,
  readonly: false,
  dragging: null,
  feedback: null,
})

const emit = defineEmits<{
  dragstart: [data: DragData]
  dragend: []
  check: [payload: { weekday: number; period_no: number; data: DragData | null }]
  drop: [payload: { weekday: number; period_no: number; data: DragData | null }]
  select: [entry: GridEntry]
}>()

const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

const weekdays = computed(() => {
  const max = props.numWeekdays ?? Math.max(5, ...props.periods.map((p) => p.weekday))
  return Array.from({ length: max }, (_, i) => i + 1)
})
const periodNos = computed(() =>
  [...new Set(props.periods.map((p) => p.period_no))].sort((a, b) => a - b))

const periodMap = computed(() => {
  const m = new Map<string, PeriodCell>()
  for (const p of props.periods) m.set(`${p.weekday}-${p.period_no}`, p)
  return m
})
// 各節次的代表資訊(取任一天),用於左欄的節次名稱與時間
const periodInfo = computed(() => {
  const m = new Map<number, PeriodCell>()
  for (const p of props.periods) if (!m.has(p.period_no)) m.set(p.period_no, p)
  return m
})
const entryMap = computed(() => {
  const m = new Map<string, GridEntry>()
  for (const e of props.entries) m.set(`${e.weekday}-${e.period_no}`, e)
  return m
})
// 連堂佔用的下方格位(跳過不渲染)
const coveredSet = computed(() => {
  const s = new Set<string>()
  const nos = periodNos.value
  for (const e of props.entries) {
    const span = e.span ?? 1
    if (span <= 1) continue
    const idx = nos.indexOf(e.period_no)
    for (let k = 1; k < span; k++) {
      const pp = nos[idx + k]
      if (pp !== undefined) s.add(`${e.weekday}-${pp}`)
    }
  }
  return s
})

function fmt(t?: string | null): string {
  return t ? t.slice(0, 5) : ''
}
function weekdayLabel(w: number): string {
  return `星期${WEEKDAY_LABELS[w - 1] ?? w}`
}
function periodLabelName(p: number): string {
  return periodInfo.value.get(p)?.name ?? `第${p}節`
}
function periodTime(p: number): string {
  const info = periodInfo.value.get(p)
  if (!info?.start_time) return ''
  return `${fmt(info.start_time)}-${fmt(info.end_time)}`
}
function key(w: number, p: number): string {
  return `${w}-${p}`
}
function periodAt(w: number, p: number): PeriodCell | undefined {
  return periodMap.value.get(key(w, p))
}
function entryAt(w: number, p: number): GridEntry | undefined {
  return entryMap.value.get(key(w, p))
}
function isCovered(w: number, p: number): boolean {
  return coveredSet.value.has(key(w, p))
}
function isRegular(w: number, p: number): boolean {
  return periodAt(w, p)?.type === 'regular'
}
function cardDraggable(e: GridEntry): boolean {
  return !props.readonly && !e.locked
}
function cellStyle(w: number, p: number, rowIdx: number) {
  const e = entryAt(w, p)
  const span = e?.span ?? 1
  return {
    gridColumn: `${w + 1}`,
    gridRow: span > 1 ? `${rowIdx + 2} / span ${span}` : `${rowIdx + 2}`,
  }
}
function cellClass(w: number, p: number) {
  const period = periodAt(w, p)
  const fb = props.feedback
  const isFbCell = fb && fb.weekday === w && fb.period_no === p
  return {
    'is-nodef': !period,
    'is-blocked': !!period && period.type !== 'regular',
    'is-regular': !!period && period.type === 'regular',
    'has-entry': !!entryAt(w, p),
    'is-droppable': !!isFbCell && fb!.ok,
    'is-conflict': !!isFbCell && !fb!.ok,
  }
}
function feedbackReason(w: number, p: number): string | null {
  const fb = props.feedback
  if (fb && !fb.ok && fb.weekday === w && fb.period_no === p) return fb.reason ?? '衝突'
  return null
}

function onCardDragStart(e: GridEntry, ev: DragEvent) {
  if (!cardDraggable(e)) {
    ev.preventDefault()
    return
  }
  const data: DragData = { source: 'grid', entryId: e.id }
  ev.dataTransfer?.setData('application/json', JSON.stringify(data))
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'move'
  emit('dragstart', data)
}
function onCellCheck(w: number, p: number, ev: DragEvent) {
  if (props.readonly || !isRegular(w, p) || entryAt(w, p)) return
  ev.preventDefault() // 允許放下
  emit('check', { weekday: w, period_no: p, data: props.dragging })
}
function onCellDrop(w: number, p: number, ev: DragEvent) {
  if (props.readonly || !isRegular(w, p) || entryAt(w, p)) return
  ev.preventDefault()
  let data: DragData | null = props.dragging
  const raw = ev.dataTransfer?.getData('application/json')
  if (raw) {
    try {
      data = JSON.parse(raw) as DragData
    } catch {
      /* 保留 props.dragging */
    }
  }
  emit('drop', { weekday: w, period_no: p, data })
  emit('dragend')
}
</script>

<template>
  <div class="tg-wrap">
    <div class="tg-grid" :style="{ gridTemplateColumns: `92px repeat(${weekdays.length}, minmax(88px, 1fr))` }">
      <div class="tg-corner" :style="{ gridColumn: '1', gridRow: '1' }" />
      <div
        v-for="w in weekdays" :key="`h${w}`" class="tg-head"
        :style="{ gridColumn: `${w + 1}`, gridRow: '1' }"
      >
        {{ weekdayLabel(w) }}
      </div>

      <template v-for="(p, i) in periodNos" :key="`p${p}`">
        <div class="tg-period" :style="{ gridColumn: '1', gridRow: `${i + 2}` }">
          <div class="tg-period-name">{{ periodLabelName(p) }}</div>
          <div class="tg-period-time">{{ periodTime(p) }}</div>
        </div>

        <template v-for="w in weekdays" :key="`${w}-${p}`">
          <div
            v-if="!isCovered(w, p)"
            class="tg-cell" :class="cellClass(w, p)" :style="cellStyle(w, p, i)"
            :data-weekday="w" :data-period="p"
            @dragenter="onCellCheck(w, p, $event)"
            @dragover="onCellCheck(w, p, $event)"
            @drop="onCellDrop(w, p, $event)"
          >
            <div
              v-if="entryAt(w, p)"
              class="tg-card" :class="{ 'is-locked': entryAt(w, p)!.locked }"
              :draggable="cardDraggable(entryAt(w, p)!)"
              @dragstart="onCardDragStart(entryAt(w, p)!, $event)"
              @dragend="emit('dragend')"
              @click="emit('select', entryAt(w, p)!)"
            >
              <span v-if="entryAt(w, p)!.locked" class="tg-lock" title="已鎖定">🔒</span>
              <div class="tg-subject">{{ entryAt(w, p)!.subject }}</div>
              <div v-if="entryAt(w, p)!.teacher" class="tg-teacher">{{ entryAt(w, p)!.teacher }}</div>
              <div v-if="entryAt(w, p)!.room" class="tg-room">{{ entryAt(w, p)!.room }}</div>
            </div>
            <div v-else-if="!isRegular(w, p)" class="tg-blocked-label">
              {{ periodAt(w, p)?.name ?? '—' }}
            </div>
            <div v-else-if="feedbackReason(w, p)" class="tg-reason" :title="feedbackReason(w, p)!">
              {{ feedbackReason(w, p) }}
            </div>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tg-wrap { overflow-x: auto; }
.tg-grid {
  display: grid;
  gap: 4px;
  min-width: max-content;
}
.tg-corner { }
.tg-head {
  text-align: center; font-weight: 600; padding: 6px 4px;
  background: rgba(128, 128, 128, 0.1); border-radius: 4px;
}
.tg-period {
  display: flex; flex-direction: column; justify-content: center;
  padding: 4px 6px; background: rgba(128, 128, 128, 0.06); border-radius: 4px;
}
.tg-period-name { font-size: 13px; font-weight: 600; }
.tg-period-time { font-size: 11px; opacity: 0.6; }
.tg-cell {
  min-height: 56px; border: 1px solid var(--n-border-color, #e2e2e2);
  border-radius: 4px; padding: 2px;
}
.tg-cell.is-blocked, .tg-cell.is-nodef {
  background: repeating-linear-gradient(45deg, rgba(128,128,128,0.06),
    rgba(128,128,128,0.06) 6px, rgba(128,128,128,0.12) 6px, rgba(128,128,128,0.12) 12px);
}
.tg-cell.is-droppable { outline: 2px solid #0d7a43; outline-offset: -2px; }  /* 主色,見 src/theme.ts */
.tg-cell.is-conflict { outline: 2px solid #d03050; outline-offset: -2px; background: rgba(208,48,80,0.06); }
.tg-blocked-label { font-size: 12px; opacity: 0.55; text-align: center; padding-top: 14px; }
.tg-reason { font-size: 12px; color: #d03050; text-align: center; padding-top: 12px; }
.tg-card {
  height: 100%; box-sizing: border-box; border-radius: 4px; padding: 4px 6px;
  background: rgba(24, 160, 88, 0.12); border: 1px solid rgba(24, 160, 88, 0.4);
  cursor: grab; position: relative;
}
.tg-card.is-locked { background: rgba(128, 128, 128, 0.15); border-color: rgba(128,128,128,0.45); cursor: default; }
.tg-lock { position: absolute; top: 2px; right: 4px; font-size: 11px; }
.tg-subject { font-weight: 600; font-size: 13px; }
.tg-teacher { font-size: 12px; opacity: 0.85; }
.tg-room { font-size: 11px; opacity: 0.65; }
</style>
