<script setup lang="ts">
import { NButton, NCard, NForm, NFormItem, NInput, NText, useMessage } from 'naive-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()

const MIN_LEN = 8
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)

const forced = auth.mustChangePassword

async function onSubmit() {
  if (newPassword.value.length < MIN_LEN) {
    message.warning(`新密碼至少需 ${MIN_LEN} 個字元`)
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    message.warning('兩次輸入的新密碼不一致')
    return
  }
  loading.value = true
  try {
    await auth.changePassword(oldPassword.value, newPassword.value)
    message.success('密碼已更新')
    router.push({ name: 'dashboard' })
  } catch (e) {
    message.error((e as ApiError).detail || '變更密碼失敗')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px">
    <n-card title="變更密碼" style="max-width: 420px">
      <n-text v-if="forced" depth="3" style="display: block; margin-bottom: 12px">
        這是您的首次登入,請設定新密碼後繼續使用系統。
      </n-text>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="原密碼">
          <n-input v-model:value="oldPassword" type="password" show-password-on="click" />
        </n-form-item>
        <n-form-item :label="`新密碼(至少 ${MIN_LEN} 字元)`">
          <n-input v-model:value="newPassword" type="password" show-password-on="click" />
        </n-form-item>
        <n-form-item label="確認新密碼">
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-button type="primary" block :loading="loading" attr-type="submit" @click="onSubmit">
          更新密碼
        </n-button>
      </n-form>
    </n-card>
  </div>
</template>
