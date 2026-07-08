<script setup lang="ts">
import { NCard, NSpace, NTag, NText } from 'naive-ui'
import { onMounted, ref } from 'vue'
import { apiGet } from '@/api/client'

// 後端連線狀態(驗證前後端連通);真正的儀表板內容(今日調代課看板)於 M4 實作。
const backendStatus = ref<'checking' | 'ok' | 'error'>('checking')
onMounted(async () => {
  try {
    const data = await apiGet<{ status: string }>('/health')
    backendStatus.value = data.status === 'ok' ? 'ok' : 'error'
  } catch {
    backendStatus.value = 'error'
  }
})
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">儀表板</h1>
    <n-card>
      <n-space vertical>
        <n-text>系統已就緒。從左側「基礎資料 → 學期與節次表」開始建置本學期資料。</n-text>
        <n-space align="center">
          <n-text>後端連線狀態:</n-text>
          <n-tag v-if="backendStatus === 'checking'" type="info">檢查中…</n-tag>
          <n-tag v-else-if="backendStatus === 'ok'" type="success">正常</n-tag>
          <n-tag v-else type="error">無法連線</n-tag>
        </n-space>
      </n-space>
    </n-card>
  </n-space>
</template>
