<script setup lang="ts">
import { NButton, NCard, NEmpty, NSpace, NStatistic, NText } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listSemesters } from '@/api/semesters'
import type { SemesterListItem } from '@/api/semesters'
import { getSemesterSummary } from '@/api/wizard'
import type { SemesterSummary } from '@/api/wizard'

const router = useRouter()
const semester = ref<SemesterListItem | null>(null)
const summary = ref<SemesterSummary | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const semesters = await listSemesters()
    if (semesters.length) {
      semester.value = semesters[0]
      summary.value = await getSemesterSummary(semesters[0].id)
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

    <n-text depth="3">後續里程碑將在此顯示今日調代課看板與待辦事項。</n-text>
  </n-space>
</template>
