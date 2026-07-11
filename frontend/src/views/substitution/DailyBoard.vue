<script setup lang="ts">
import { NButton, NDatePicker, NEmpty, NSelect, NSpace, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getDailyBoard } from '@/api/substitutionLog'
import type { DailyBoard, LogEntry } from '@/api/substitutionLog'
import { listSemesters } from '@/api/semesters'

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']

// NDatePicker 給的是毫秒時間戳;以本機日期組出 YYYY-MM-DD,避免 toISOString 的 UTC 倒退
function toISODate(ts: number): string {
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
function todayTs(): number {
  const d = new Date()
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function parseISODate(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).getTime()
}

const route = useRoute()
const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const dateTs = ref<number>(
  typeof route.query.date === 'string' ? parseISODate(route.query.date) : todayTs())
const board = ref<DailyBoard | null>(null)
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const dateLabel = computed(() =>
  board.value ? `${board.value.date}(${WEEKDAYS[board.value.weekday % 7]})` : '')

async function reload() {
  if (sid.value === null) return
  loading.value = true
  try {
    board.value = await getDailyBoard(sid.value, toISODate(dateTs.value))
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (!semesters.value.length) return
  const qsid = Number(route.query.semester_id)
  const initial = semesters.value.find((s) => s.id === qsid)?.id ?? semesters.value[0].id
  await onSemesterChange(initial)
})

function openPrint() {
  if (sid.value === null) return
  const url = `/daily-board/print?semester_id=${sid.value}&date=${toISODate(dateTs.value)}`
  window.open(url, '_blank')
}

function dispositionText(e: LogEntry): string {
  if (!e.disposed) return '待安排'
  if (e.sub_type === 'swap' && e.swap_period_name) {
    return `調課 · ${e.handler_name}(補 ${e.swap_date} ${e.swap_period_name})`
  }
  if (e.handler_name) return `${e.sub_type_label} · ${e.handler_name}`
  return e.sub_type_label ?? ''
}

function statusType(e: LogEntry): string {
  if (e.status === 'pending') return 'warning'
  if (e.status === 'completed') return 'info'
  return 'success'
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center" :wrap="true">
      <h2 style="margin: 0">今日調代課看板</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
      <n-date-picker
        v-model:value="dateTs" type="date" style="width: 160px"
        data-testid="board-date" @update:value="reload"
      />
      <n-button
        v-if="board?.entries.length" type="primary" data-testid="board-print"
        @click="openPrint"
      >
        列印通知單
      </n-button>
    </n-space>

    <n-text v-if="board" depth="3" data-testid="board-datelabel">{{ dateLabel }}</n-text>

    <n-empty
      v-if="board && !board.entries.length && !loading"
      description="今日無調代課" data-testid="board-empty" style="padding: 40px 0"
    />

    <table v-else-if="board?.entries.length" class="data-table" data-testid="board-table">
      <thead>
        <tr>
          <th>節次</th><th>班級</th><th>科目</th><th>原任教師</th>
          <th>假別</th><th>處置</th><th>狀態</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in board.entries" :key="e.affected_period_id" data-testid="board-row">
          <td>{{ e.period_name }}</td>
          <td>{{ e.class_names }}<n-text v-if="e.room_name" depth="3"> @{{ e.room_name }}</n-text></td>
          <td>{{ e.subject_name }}</td>
          <td>{{ e.absent_teacher_name }}</td>
          <td>{{ e.leave_type_label }}</td>
          <td :class="{ pending: !e.disposed }">{{ dispositionText(e) }}</td>
          <td>
            <n-tag size="small" :type="statusType(e) as never">{{ e.status_label }}</n-tag>
          </td>
        </tr>
      </tbody>
    </table>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
.pending { color: #e08000; }
</style>
