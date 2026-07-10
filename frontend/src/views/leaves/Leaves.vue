<script setup lang="ts">
import {
  NAlert, NButton, NCard, NDatePicker, NEmpty, NInput, NPopconfirm, NSelect, NSpace, NSwitch,
  NTag, NText, NTimePicker, useMessage,
} from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import type { ApiError } from '@/api/client'
import { listTeachers } from '@/api/basedata'
import { cancelLeave, createLeave, listLeaveTypes, listLeaves } from '@/api/leaves'
import type { AffectedPeriod, LeaveRequest } from '@/api/leaves'
import { listSemesters } from '@/api/semesters'
import { publishedSemesters } from '@/api/timetables'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()

// 組長/主任可代登、可看全校;教師只登記自己的假、只看自己的假單
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const leaveTypes = ref<Record<string, string>>({})
const teachers = ref<{ id: number; name: string }[]>([])
const leaves = ref<LeaveRequest[]>([])
const saving = ref(false)

const form = ref({
  teacherId: null as number | null,
  leaveType: 'sick',
  // NDatePicker 給的是 timestamp,送出前才轉成 YYYY-MM-DD
  startDate: null as number | null,
  endDate: null as number | null,
  halfDay: false,
  startTime: null as number | null,
  endTime: null as number | null,
  reason: '',
})

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))
const teacherOptions = computed(() => teachers.value.map((t) => ({ label: t.name, value: t.id })))
const typeOptions = computed(() =>
  Object.entries(leaveTypes.value).map(([value, label]) => ({ label, value })))

/** 本機日期,不用 toISOString——那會轉成 UTC,台灣時區的凌晨會倒退一天。 */
function toDate(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function toTime(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function reload() {
  if (!sid.value) return
  leaves.value = await listLeaves(sid.value)
  if (canManage.value) {
    teachers.value = await listTeachers(sid.value)
  }
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  leaveTypes.value = await listLeaveTypes()
  semesters.value = canManage.value ? await listSemesters() : await publishedSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

const canSubmit = computed(() =>
  !!sid.value && !!form.value.startDate && !!form.value.endDate
  && (!canManage.value || !!form.value.teacherId))

async function onSubmit() {
  if (!sid.value || !canSubmit.value) return
  saving.value = true
  try {
    const created = await createLeave(sid.value, {
      teacher_id: canManage.value ? form.value.teacherId : null,
      leave_type: form.value.leaveType,
      start_date: toDate(form.value.startDate)!,
      end_date: toDate(form.value.endDate)!,
      start_time: form.value.halfDay ? toTime(form.value.startTime) : null,
      end_time: form.value.halfDay ? toTime(form.value.endTime) : null,
      reason: form.value.reason,
    })
    message.success(
      created.affected_count
        ? `已登記,共 ${created.affected_count} 節課受影響`
        : '已登記(這段期間沒有課)',
    )
    form.value.reason = ''
    await reload()
  } catch (e) {
    message.error((e as ApiError).message || '登記失敗')
  } finally {
    saving.value = false
  }
}

async function onCancel(leave: LeaveRequest) {
  const result = await cancelLeave(leave.id)
  if (result.notified_teachers.length) {
    message.success(`已銷假,已通知 ${result.notified_teachers.join('、')} 取消代課`)
  } else {
    message.success('已銷假')
  }
  await reload()
}

// 已取消不該和「待處理」一樣搶眼——組長掃過這張表時,要一眼看出還有幾節沒人處理。
// (Naive 的 type="default" 在此情境仍沿用前一次的主題色,索性不用 tag。)
const STATUS_TAG: Record<AffectedPeriod['status'], { type: string; label: string }> = {
  pending: { type: 'warning', label: '待處理' },
  resolved: { type: 'info', label: '已確認' },
  completed: { type: 'success', label: '已完成' },
  cancelled: { type: 'default', label: '已取消' },
}

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']

/** 「2026-11-11(週三)」——沒有星期,教學組長無從一眼看出為什麼跨了六天卻只有一天有課。 */
function withWeekday(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return `${iso}(${WEEKDAYS[new Date(y, m - 1, d).getDay()]})`
}

function rangeText(l: LeaveRequest): string {
  if (l.start_date !== l.end_date) {
    return `${withWeekday(l.start_date)} ~ ${withWeekday(l.end_date)}`
  }
  if (l.start_time || l.end_time) {
    const from = l.start_time?.slice(0, 5) ?? '上課起'
    const to = l.end_time?.slice(0, 5) ?? '放學'
    return `${withWeekday(l.start_date)} ${from}~${to}`
  }
  return `${withWeekday(l.start_date)} 整天`
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h2 style="margin: 0">請假登記</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
    </n-space>

    <n-empty v-if="!sid" description="尚無可登記請假的學期" />

    <template v-else>
      <n-card :title="canManage ? '登記請假(可代教師登記)' : '登記我的請假'" size="small">
        <n-space vertical>
          <n-space align="center" :wrap="true">
            <template v-if="canManage">
              <n-text>教師</n-text>
              <n-select
                v-model:value="form.teacherId" :options="teacherOptions" filterable
                style="width: 160px" placeholder="選擇教師" data-testid="lv-teacher"
              />
            </template>
            <n-text>假別</n-text>
            <n-select
              v-model:value="form.leaveType" :options="typeOptions"
              style="width: 120px" data-testid="lv-type"
            />
            <n-text>起</n-text>
            <n-date-picker v-model:value="form.startDate" type="date" data-testid="lv-start" />
            <n-text>訖</n-text>
            <n-date-picker v-model:value="form.endDate" type="date" data-testid="lv-end" />
          </n-space>

          <n-space align="center">
            <n-switch v-model:value="form.halfDay" data-testid="lv-halfday" />
            <n-text>指定時間(半天假)</n-text>
            <template v-if="form.halfDay">
              <n-time-picker
                v-model:value="form.startTime" format="HH:mm" data-testid="lv-start-time"
              />
              <n-text>~</n-text>
              <n-time-picker
                v-model:value="form.endTime" format="HH:mm" data-testid="lv-end-time"
              />
            </template>
          </n-space>

          <n-input
            v-model:value="form.reason" placeholder="事由(選填)" maxlength="200"
            data-testid="lv-reason"
          />
          <n-text depth="3">
            受影響節次依「已發布課表」自動展開;週末與沒有課的日子不會列入。
          </n-text>
          <div>
            <n-button
              type="primary" :loading="saving" :disabled="!canSubmit"
              data-testid="lv-submit" @click="onSubmit"
            >
              登記請假
            </n-button>
          </div>
        </n-space>
      </n-card>

      <n-empty v-if="!leaves.length" description="尚無請假紀錄" />
      <n-card
        v-for="l in leaves" :key="l.id" size="small" data-testid="lv-card"
        :title="`${l.teacher_name} · ${l.leave_type_label} · ${rangeText(l)}`"
      >
        <template #header-extra>
          <n-space align="center">
            <n-tag v-if="l.status === 'cancelled'" type="default" size="small">已銷假</n-tag>
            <n-tag v-else type="warning" size="small" data-testid="lv-pending">
              待處理 {{ l.pending_count }} 節
            </n-tag>
            <n-popconfirm v-if="l.status === 'registered'" @positive-click="onCancel(l)">
              <template #trigger>
                <n-button size="small" tertiary type="error" data-testid="lv-cancel">銷假</n-button>
              </template>
              銷假將取消所有受影響節次的處置,已被指派的代課教師會收到取消通知。確定?
            </n-popconfirm>
          </n-space>
        </template>

        <n-space vertical size="small">
          <n-text v-if="l.reason" depth="3">事由:{{ l.reason }}</n-text>
          <n-alert v-if="!l.affected_count" type="info" :bordered="false">
            這段期間沒有課(週末,或課表尚未發布)
          </n-alert>
          <table v-else class="data-table" data-testid="lv-affected">
            <thead>
              <tr><th>日期</th><th>節次</th><th>班級</th><th>科目</th><th>場地</th><th>狀態</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in l.affected_periods" :key="p.id">
                <td>{{ withWeekday(p.date) }}</td>
                <td>{{ p.period_name }}</td>
                <td>{{ p.class_names }}</td>
                <td>{{ p.subject_name }}</td>
                <td>{{ p.room_name || '—' }}</td>
                <td>
                  <n-text v-if="p.status === 'cancelled'" depth="3" data-testid="lv-status">
                    已取消
                  </n-text>
                  <n-tag
                    v-else size="small" data-testid="lv-status"
                    :type="STATUS_TAG[p.status].type as never"
                  >
                    {{ STATUS_TAG[p.status].label }}
                  </n-tag>
                  <n-text v-if="p.handler_name" depth="3"> · {{ p.handler_name }}</n-text>
                </td>
              </tr>
            </tbody>
          </table>
          <n-text depth="3">登記人:{{ l.created_by_name }}</n-text>
        </n-space>
      </n-card>
    </template>
  </n-space>
</template>

<style scoped>
.data-table { border-collapse: collapse; width: 100%; }
.data-table th, .data-table td {
  border: 1px solid var(--n-border-color, #e0e0e0); padding: 6px 10px; text-align: left;
}
.data-table th { background: rgba(128, 128, 128, 0.08); font-weight: 600; }
</style>
