<script setup lang="ts">
import { NAlert, NCard, NRadioButton, NRadioGroup, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { computed, reactive, ref } from 'vue'
import TimetableGrid from '@/components/timetable/TimetableGrid.vue'
import type { DragData, DropFeedback, GridEntry, PeriodCell } from '@/components/timetable/types'

const message = useMessage()

// ── 兩套範例節次表(國小 40 分、技高 50 分)──
function pad(n: number) { return String(n).padStart(2, '0') }
function slot(start: number, len: number) {
  const s = `${pad(Math.floor(start / 60))}:${pad(start % 60)}`
  const e = start + len
  return { start: s, end: `${pad(Math.floor(e / 60))}:${pad(e % 60)}` }
}

function buildElementary(): PeriodCell[] {
  const cells: PeriodCell[] = []
  const starts = [480, 530, 580, 630, 680, 720, 790, 840] // 分鐘
  for (let w = 1; w <= 5; w++) {
    starts.forEach((st, i) => {
      const p = i + 1
      const t = slot(st, p === 6 ? 60 : 40)
      let type = 'regular'
      let name = `第${p}節`
      if (p === 6) { type = 'lunch'; name = '午休' }
      // 週三下午不排課(第 7、8 節)
      if (w === 3 && p >= 7) { type = 'reserved'; name = '週三不排' }
      cells.push({ weekday: w, period_no: p, name, type, start_time: t.start, end_time: t.end })
    })
  }
  return cells
}
function buildVocational(): PeriodCell[] {
  const cells: PeriodCell[] = []
  const starts = [480, 540, 600, 660, 720, 790, 850, 910]
  for (let w = 1; w <= 5; w++) {
    starts.forEach((st, i) => {
      const p = i + 1
      const t = slot(st, p === 5 ? 60 : 50)
      let type = 'regular'
      let name = `第${p}節`
      if (p === 5) { type = 'lunch'; name = '午休' }
      cells.push({ weekday: w, period_no: p, name, type, start_time: t.start, end_time: t.end })
    })
  }
  return cells
}

const sample = ref<'elementary' | 'vocational'>('elementary')
const periods = computed(() => (sample.value === 'elementary' ? buildElementary() : buildVocational()))

// 各範例獨立的已排格位與未排清單
interface TrayItem { assignmentId: number; subject: string; teacher: string; room?: string; span?: number }
const state = reactive<Record<string, { entries: GridEntry[]; tray: TrayItem[] }>>({
  elementary: {
    entries: [
      { id: 1, weekday: 1, period_no: 1, subject: '導師時間', teacher: '王師', locked: true },
      { id: 2, weekday: 2, period_no: 2, subject: '數學', teacher: '李師' },
    ],
    tray: [
      { assignmentId: 11, subject: '國語', teacher: '王師' },
      { assignmentId: 12, subject: '英語', teacher: '陳師' },
      { assignmentId: 13, subject: '自然', teacher: '林師', room: '自然教室' },
    ],
  },
  vocational: {
    entries: [
      { id: 21, weekday: 1, period_no: 1, subject: '國文', teacher: '張師', locked: true },
      { id: 22, weekday: 1, period_no: 6, subject: '機械實習', teacher: '陳師', room: '實習工場', span: 2 },
    ],
    tray: [
      { assignmentId: 31, subject: '數學', teacher: '李師' },
      { assignmentId: 32, subject: '製圖', teacher: '陳師', room: '製圖室', span: 2 },
    ],
  },
})
const current = computed(() => state[sample.value])

// 衝突模擬:某些教師在特定時段「已在他處有課」,拖入即紅框
const busy: Record<string, Set<string>> = {
  王師: new Set(['1-2']), // 王師 週一第 2 節已有課
  張師: new Set(['2-3']),
}

const dragging = ref<DragData | null>(null)
const feedback = ref<DropFeedback | null>(null)

function teacherOf(data: DragData | null): string | undefined {
  if (!data) return undefined
  if (data.source === 'tray') return data.teacher as string
  const e = current.value.entries.find((x) => x.id === data.entryId)
  return e?.teacher
}

function onTrayDragStart(item: TrayItem, ev: DragEvent) {
  const data: DragData = { source: 'tray', ...item }
  dragging.value = data
  ev.dataTransfer?.setData('application/json', JSON.stringify(data))
  if (ev.dataTransfer) ev.dataTransfer.effectAllowed = 'move'
}
function onGridDragStart(data: DragData) {
  dragging.value = data
}
function onCheck(payload: { weekday: number; period_no: number; data: DragData | null }) {
  const teacher = teacherOf(payload.data ?? dragging.value)
  const k = `${payload.weekday}-${payload.period_no}`
  const conflict = teacher ? busy[teacher]?.has(k) : false
  feedback.value = {
    weekday: payload.weekday, period_no: payload.period_no,
    ok: !conflict,
    reason: conflict ? `${teacher} 此時段已有課` : undefined,
  }
}
function onDrop(payload: { weekday: number; period_no: number; data: DragData | null }) {
  const data = payload.data ?? dragging.value
  const teacher = teacherOf(data)
  const k = `${payload.weekday}-${payload.period_no}`
  if (teacher && busy[teacher]?.has(k)) {
    message.error(`無法放入:${teacher} 此時段已有課`)
    clearDrag()
    return
  }
  if (data?.source === 'tray') {
    const idx = current.value.tray.findIndex((t) => t.assignmentId === data.assignmentId)
    if (idx >= 0) {
      const item = current.value.tray[idx]
      current.value.tray.splice(idx, 1)
      current.value.entries.push({
        id: `e${item.assignmentId}`, weekday: payload.weekday, period_no: payload.period_no,
        subject: item.subject, teacher: item.teacher, room: item.room, span: item.span,
      })
    }
  } else if (data?.source === 'grid') {
    const e = current.value.entries.find((x) => x.id === data.entryId)
    if (e) { e.weekday = payload.weekday; e.period_no = payload.period_no }
  }
  clearDrag()
}
function onTrayDrop(ev: DragEvent) {
  ev.preventDefault()
  const raw = ev.dataTransfer?.getData('application/json')
  const data: DragData | null = raw ? JSON.parse(raw) : dragging.value
  if (data?.source === 'grid') {
    const idx = current.value.entries.findIndex((x) => x.id === data.entryId)
    if (idx >= 0) {
      const e = current.value.entries[idx]
      if (e.locked) { message.warning('鎖定格位不可移除'); clearDrag(); return }
      current.value.entries.splice(idx, 1)
      current.value.tray.push({
        assignmentId: Number(String(e.id).replace('e', '')) || Date.now(),
        subject: e.subject, teacher: e.teacher ?? '', room: e.room, span: e.span,
      })
    }
  }
  clearDrag()
}
function onSelect(entry: GridEntry) {
  const e = current.value.entries.find((x) => x.id === entry.id)
  if (e) {
    e.locked = !e.locked
    message.info(e.locked ? `已鎖定「${e.subject}」` : `已解鎖「${e.subject}」`)
  }
}
function clearDrag() {
  dragging.value = null
  feedback.value = null
}
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">課表元件示範(TimetableGrid)</h1>
    <n-alert type="info" :show-icon="true">
      拖動右側未排課務到格子:綠框可放、紅框衝突(模擬:王師週一第2節、張師週二第3節已有課)。
      點格內卡片可切換鎖定;把格內卡片拖回右側清單可移除。連堂課以較高卡片呈現。
    </n-alert>

    <n-radio-group v-model:value="sample">
      <n-radio-button value="elementary" data-testid="demo-elementary">國小(40 分/節)</n-radio-button>
      <n-radio-button value="vocational" data-testid="demo-vocational">技高(50 分/節)</n-radio-button>
    </n-radio-group>

    <div class="demo-layout">
      <n-card :title="sample === 'elementary' ? '國小週課表' : '技高週課表'" size="small" style="flex: 1; min-width: 0">
        <TimetableGrid
          :key="sample"
          :periods="periods" :entries="current.entries"
          :dragging="dragging" :feedback="feedback"
          @dragstart="onGridDragStart" @dragend="clearDrag"
          @check="onCheck" @drop="onDrop" @select="onSelect"
        />
      </n-card>

      <n-card
        title="未排課務" size="small" class="tray"
        @dragover.prevent @drop="onTrayDrop"
      >
        <n-space vertical size="small">
          <n-text v-if="current.tray.length === 0" depth="3">全部已排入</n-text>
          <div
            v-for="item in current.tray" :key="item.assignmentId"
            class="tray-item" :data-testid="`tray-${item.subject}`" draggable="true"
            @dragstart="onTrayDragStart(item, $event)" @dragend="clearDrag"
          >
            <div class="tray-subject">
              {{ item.subject }}
              <n-tag v-if="item.span && item.span > 1" size="tiny" type="warning">{{ item.span }}連堂</n-tag>
            </div>
            <div class="tray-teacher">{{ item.teacher }}<span v-if="item.room"> · {{ item.room }}</span></div>
          </div>
          <n-text depth="3" style="font-size: 12px">（拖曳到左側課表格子）</n-text>
        </n-space>
      </n-card>
    </div>
  </n-space>
</template>

<style scoped>
.demo-layout { display: flex; gap: 20px; align-items: flex-start; }
.tray { width: 240px; flex-shrink: 0; }
.tray-item {
  border: 1px solid var(--n-border-color, #e2e2e2); border-radius: 6px; padding: 8px 10px;
  cursor: grab; background: rgba(24, 160, 88, 0.08);
}
.tray-subject { font-weight: 600; display: flex; align-items: center; gap: 6px; }
.tray-teacher { font-size: 12px; opacity: 0.75; }
@media (max-width: 900px) { .demo-layout { flex-direction: column; } .tray { width: 100%; } }
</style>
