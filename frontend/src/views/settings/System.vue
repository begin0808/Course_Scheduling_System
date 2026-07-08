<script setup lang="ts">
import { NButton, NCard, NPopconfirm, NSpace, NText, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { resetWizard } from '@/api/wizard'
import { useWizardStore } from '@/stores/wizard'

const router = useRouter()
const message = useMessage()
const wizard = useWizardStore()

async function onResetWizard() {
  await resetWizard()
  await wizard.fetch()
  message.success('已重新啟動設定精靈')
  router.push({ name: 'wizard' })
}
</script>

<template>
  <n-space vertical size="large">
    <h1 style="margin: 0">系統管理</h1>
    <n-card title="設定精靈">
      <n-space vertical>
        <n-text depth="3">重新執行首次設定的引導流程(不會刪除既有資料)。</n-text>
        <n-popconfirm @positive-click="onResetWizard">
          <template #trigger>
            <n-button>重新啟動設定精靈</n-button>
          </template>
          確定重新啟動設定精靈?
        </n-popconfirm>
      </n-space>
    </n-card>
  </n-space>
</template>
