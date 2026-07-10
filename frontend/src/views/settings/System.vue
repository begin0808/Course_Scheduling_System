<script setup lang="ts">
import {
  NButton, NCard, NCheckbox, NInput, NInputNumber, NPopconfirm, NSpace, NTag, NText, useMessage,
} from 'naive-ui'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { getSmtp, saveSmtp } from '@/api/notifications'
import { resetWizard } from '@/api/wizard'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'

const router = useRouter()
const message = useMessage()
const wizard = useWizardStore()
const auth = useAuthStore()

const isAdmin = () => auth.hasRole('admin')

const smtp = ref({
  host: '', port: 25, user: '', password: '', sender: '', use_tls: false,
})
const configured = ref(false)
const hasPassword = ref(false)
const savingSmtp = ref(false)

onMounted(async () => {
  if (!isAdmin()) return
  const s = await getSmtp()
  smtp.value = { host: s.host, port: s.port, user: s.user, password: '', sender: s.sender, use_tls: s.use_tls }
  configured.value = s.configured
  hasPassword.value = s.has_password
})

async function onSaveSmtp() {
  savingSmtp.value = true
  try {
    const s = await saveSmtp(smtp.value)
    configured.value = s.configured
    hasPassword.value = s.has_password
    smtp.value.password = ''
    message.success('已儲存 SMTP 設定')
  } catch (e) {
    message.error((e as ApiError).message || '儲存失敗')
  } finally {
    savingSmtp.value = false
  }
}

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

    <n-card v-if="isAdmin()" title="通知信件(SMTP)" data-testid="smtp-card">
      <n-space vertical>
        <n-space align="center">
          <n-text depth="3">
            設定後,調代課通知除站內外會加寄 Email;未設定時系統照常運作,僅站內通知。
          </n-text>
          <n-tag :type="configured ? 'success' : 'default'" data-testid="smtp-status">
            {{ configured ? '已設定' : '未設定' }}
          </n-tag>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">主機</n-text>
          <n-input
            v-model:value="smtp.host" placeholder="smtp.example.com" style="width: 220px"
            data-testid="smtp-host"
          />
          <n-text>連接埠</n-text>
          <n-input-number v-model:value="smtp.port" :min="1" :max="65535" style="width: 110px" />
          <n-checkbox v-model:checked="smtp.use_tls">使用 TLS</n-checkbox>
        </n-space>
        <n-space align="center" :wrap="true">
          <n-text style="width: 72px">寄件人</n-text>
          <n-input
            v-model:value="smtp.sender" placeholder="noreply@school.edu.tw"
            style="width: 220px" data-testid="smtp-sender"
          />
          <n-text>帳號</n-text>
          <n-input v-model:value="smtp.user" placeholder="(選填)" style="width: 160px" />
          <n-text>密碼</n-text>
          <n-input
            v-model:value="smtp.password" type="password"
            :placeholder="hasPassword ? '(已設定,留空不變更)' : '(選填)'" style="width: 160px"
          />
        </n-space>
        <div>
          <n-button
            type="primary" :loading="savingSmtp" data-testid="smtp-save" @click="onSaveSmtp"
          >
            儲存 SMTP 設定
          </n-button>
        </div>
      </n-space>
    </n-card>

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
