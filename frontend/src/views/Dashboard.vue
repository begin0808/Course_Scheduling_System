<script setup lang="ts">
import { NButton, NCard, NSpace, NTag, NText } from 'naive-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

// 角色代碼 → 中文顯示
const ROLE_LABELS: Record<string, string> = {
  admin: '系統管理員',
  director: '教務主任',
  scheduler: '教學組長',
  teacher: '教師',
}
const roleLabels = computed(() =>
  (auth.user?.roles ?? []).map((r) => ROLE_LABELS[r] ?? r),
)

// 後端連線狀態(驗證前後端連通)
const backendStatus = ref<'checking' | 'ok' | 'error'>('checking')
onMounted(async () => {
  try {
    const data = await apiGet<{ status: string }>('/health')
    backendStatus.value = data.status === 'ok' ? 'ok' : 'error'
  } catch {
    backendStatus.value = 'error'
  }
})

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div style="max-width: 960px; margin: 48px auto; padding: 0 16px">
    <n-space vertical size="large">
      <n-space justify="space-between" align="center">
        <div>
          <h1 style="margin: 0">排課與調代課系統</h1>
          <n-text depth="3">開源免費 · 單校自架 · 適用各級學校</n-text>
        </div>
        <n-space align="center">
          <n-text v-if="auth.user">{{ auth.user.display_name }}</n-text>
          <n-tag v-for="label in roleLabels" :key="label" type="info" size="small">
            {{ label }}
          </n-tag>
          <n-button size="small" @click="onLogout">登出</n-button>
        </n-space>
      </n-space>

      <n-card title="儀表板">
        <n-space vertical>
          <n-text>系統骨架已就緒(M0-2)。後續里程碑將在此顯示今日調代課看板與待辦事項。</n-text>
          <n-space align="center">
            <n-text>後端連線狀態:</n-text>
            <n-tag v-if="backendStatus === 'checking'" type="info">檢查中…</n-tag>
            <n-tag v-else-if="backendStatus === 'ok'" type="success">正常</n-tag>
            <n-tag v-else type="error">無法連線</n-tag>
          </n-space>
        </n-space>
      </n-card>
    </n-space>
  </div>
</template>
