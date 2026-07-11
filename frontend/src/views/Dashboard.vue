<script setup lang="ts">
import { NButton, NCard, NEmpty, NSpace, NStatistic, NTag } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { getDailyBoard } from '@/api/substitutionLog'
import type { DailyBoard } from '@/api/substitutionLog'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六']

const router = useRouter()
const semester = ref<SemesterListItem | null>(null)
const summary = ref<SemesterSummary | null>(null)
const board = ref<DailyBoard | null>(null)
const loading = ref(true)

const boardDateLabel = computed(() =>
  board.value ? `${board.value.date}(${WEEKDAYS[board.value.weekday % 7]})` : '')
const pendingCount = computed(() =>
  board.value ? board.value.entries.filter((e) => !e.disposed).length : 0)

onMounted(async () => {
  try {
    const semesters = await listSemesters()
    if (semesters.length) {
      semester.value = semesters[0]
      ;[summary.value, board.value] = await Promise.all([
        getSemesterSummary(semesters[0].id),
        getDailyBoard(semesters[0].id).catch(() => null),
      ])
    }
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">儀表板</h1>

    <n-card v-if="semester" :title="`${semester.label} · 資料摘要`">
      <n-space size="large">
        <n-statistic label="科目" :value="summary?.subjects ?? 0" />
        <n-statistic label="教師" :value="summary?.teachers ?? 0" />
        <n-statistic label="班級" :value="summary?.classes ?? 0" />
        <n-statistic label="場地" :value="summary?.rooms ?? 0" />
      </n-space>
    </n-card>

    <n-card v-else-if="!loading">
      <n-empty description="尚未建立任何學期資料">
        <template #extra>
          <n-button type="primary" @click="router.push({ name: 'wizard' })">
            前往設定精靈
          </n-button>
        </template>
      </n-empty>
    </n-card>

    <n-card v-if="semester && board" data-testid="dash-today" :title="`今日調代課 · ${boardDateLabel}`">
      <n-space v-if="board.entries.length" vertical>
        <n-space align="center">
          <n-statistic label="今日異動" :value="board.entries.length" />
          <n-tag v-if="pendingCount" type="warning" data-testid="dash-pending">
            尚有 {{ pendingCount }} 節待安排
          </n-tag>
          <n-tag v-else type="success">今日皆已安排</n-tag>
        </n-space>
        <div>
          <n-button type="primary" @click="router.push({ name: 'daily-board' })">
            查看今日看板
          </n-button>
        </div>
      </n-space>
      <n-empty v-else description="今日無調代課" data-testid="dash-noboard" />
    </n-card>
  </n-space>
</template>
