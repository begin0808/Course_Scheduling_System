<script setup lang="ts">
import { NButton, NCheckbox, NEmpty, NSelect, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { notificationBoard, remind } from '@/api/notifications'
import type { BoardEntry } from '@/api/notifications'
import { listSemesters } from '@/api/semesters'

const message = useMessage()

const semesters = ref<{ id: number; label: string }[]>([])
const sid = ref<number | null>(null)
const entries = ref<BoardEntry[]>([])
const unackOnly = ref(true) // 預設只看未確認——那才是組長要追的

const semesterOptions = computed(() => semesters.value.map((s) => ({ label: s.label, value: s.id })))

const TYPE_LABEL: Record<string, string> = {
  substitution_assigned: '代課通知',
  substitution_cancelled: '代課取消',
  leave_registered: '請假登記',
  leave_cancelled: '銷假',
  timetable_published: '課表發布',
}

async function reload() {
  if (sid.value === null) return
  entries.value = await notificationBoard(sid.value, { unacknowledgedOnly: unackOnly.value })
}

async function onSemesterChange(id: number) {
  sid.value = id
  await reload()
}

onMounted(async () => {
  semesters.value = await listSemesters()
  if (semesters.value.length) await onSemesterChange(semesters.value[0].id)
})

async function onRemind(e: BoardEntry) {
  try {
    await remind(e.id)
    message.success(`已再次提醒 ${e.teacher_name}`)
    await reload()
  } catch (err) {
    message.error((err as { message?: string }).message || '提醒失敗')
  }
}

function ackTag(e: BoardEntry): { type: string; label: string } {
  if (e.acknowledged_at) return { type: 'success', label: '已確認' }
  if (e.read_at) return { type: 'info', label: '已讀未確認' }
  return { type: 'warning', label: '未讀' }
}
</script>

<template>
  <n-space vertical size="large">
    <n-space align="center">
      <h2 style="margin: 0">通知確認看板</h2>
      <n-select
        :value="sid" :options="semesterOptions" style="width: 220px"
        placeholder="選擇學期" @update:value="onSemesterChange"
      />
      <n-checkbox v-model:checked="unackOnly" data-testid="board-unackonly" @update:checked="reload">
        只看未確認
      </n-checkbox>
    </n-space>

    <n-empty v-if="!entries.length" description="沒有符合條件的通知" />
    <table v-else class="data-table" data-testid="board-table">
      <thead>
        <tr><th>教師</th><th>類型</th><th>內容</th><th>狀態</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.id" data-testid="board-row">
          <td>{{ e.teacher_name }}</td>
          <td>{{ TYPE_LABEL[e.type] ?? e.type }}</td>
          <td>{{ e.title }}</td>
          <td>
            <n-tag size="small" :type="ackTag(e).type as never">{{ ackTag(e).label }}</n-tag>
          </td>
          <td>
            <n-button
              v-if="!e.acknowledged_at" size="tiny" data-testid="board-remind"
              @click="onRemind(e)"
            >
              再次提醒
            </n-button>
            <n-text v-else depth="3">—</n-text>
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
</style>
