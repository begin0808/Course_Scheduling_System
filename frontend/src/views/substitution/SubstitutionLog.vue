<script setup lang="ts">
import { NButton, NDatePicker, NEmpty, NSelect, NSpace, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { listTeachers } from '@/api/basedata'
import { listLeaveTypes } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { getSubstitutionLog } from '@/api/substitutionLog'
import type { LogEntry } from '@/api/substitutionLog'

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']

function toISODate(ts: number): string {
  const d = new Date(ts)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const teacherOptions = ref<{ label: string; value: number }[]>([])
const leaveTypes = ref<Record<string, string>>({})

const teacherId = ref<number | null>(null)
const range = ref<[number, number] | null>(null)
const leaveType = ref<string | null>(null)
const entries = ref<LogEntry[]>([])
const loading = ref(false)

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const leaveTypeOptions = computed(() =>
  Object.entries(leaveTypes.value).map(([value, label]) => ({ label, value })))

async function reload() {
  if (sid.value === null) return
  loading.value = true
  try {
    entries.value = await getSubstitutionLog(sid.value, {
      teacherId: teacherId.value,
      dateFrom: range.value ? toISODate(range.value[0]) : null,
      dateTo: range.value ? toISODate(range.value[1]) : null,
      leaveType: leaveType.value,
    })
  } finally {
    loading.value = false
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  teacherOptions.value = (await listTeachers(id)).map((t) => ({ label: t.name, value: t.id }))
  await reload()
}

function resetFilters() {
  teacherId.value = null
  range.value = null
  leaveType.value = null
  reload()
}

onMounted(async () => {
  ;[semesters.value, leaveTypes.value] = await Promise.all([listSemesters(), listLeaveTypes()])
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

function dispositionText(e: LogEntry): string {
  if (!e.disposed) return '—'
  if (e.handler_name) return `${e.sub_type_label} · ${e.handler_name}`
  return e.sub_type_label ?? ''
}

function statusType(e: LogEntry): string {
  if (e.status === 'pending') return 'warning'
  if (e.status === 'cancelled') return 'default'
  if (e.status === 'completed') return 'info'
  return 'success'
}
</script>

<template>
  <n-space vertical size="large">
    <h2 style="margin: 0">調代課紀錄</h2>

    <n-space align="center" :wrap="true">
      <n-select
        :value="sid" :options="semesterOptions" style="width: 200px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
      <n-select
        v-model:value="teacherId" :options="teacherOptions" clearable filterable
        placeholder="教師(缺課或代課)" style="width: 200px"
        data-testid="log-teacher" @update:value="reload"
      />
      <n-date-picker
        v-model:value="range" type="daterange" clearable style="width: 260px"
        data-testid="log-range" @update:value="reload"
      />
      <n-select
        v-model:value="leaveType" :options="leaveTypeOptions" clearable
        placeholder="假別" style="width: 130px"
        data-testid="log-leavetype" @update:value="reload"
      />
      <n-button quaternary data-testid="log-reset" @click="resetFilters">清除</n-button>
    </n-space>

    <n-text depth="3" data-testid="log-count">共 {{ entries.length }} 筆</n-text>

    <n-empty
      v-if="!entries.length && !loading" description="沒有符合條件的紀錄"
      data-testid="log-empty"
    />
    <table v-else-if="entries.length" class="data-table" data-testid="log-table">
      <thead>
        <tr>
          <th>日期</th><th>節次</th><th>班級</th><th>科目</th>
          <th>原任教師</th><th>假別</th><th>處置</th><th>狀態</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.affected_period_id" data-testid="log-row">
          <td>{{ withWeekday(e.date) }}</td>
          <td>{{ e.period_name }}</td>
          <td>{{ e.class_names }}</td>
          <td>{{ e.subject_name }}</td>
          <td>{{ e.absent_teacher_name }}</td>
          <td>{{ e.leave_type_label }}</td>
          <td>{{ dispositionText(e) }}</td>
          <td><n-tag size="small" :type="statusType(e) as never">{{ e.status_label }}</n-tag></td>
        </tr>
      </tbody>
    </table>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
  white-space: nowrap;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
