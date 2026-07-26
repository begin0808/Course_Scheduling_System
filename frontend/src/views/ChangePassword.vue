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
  // 送出中就不再受理:避免連點兩下送出兩次改密請求——第二次必然因為密碼已被改掉而
  // 回「原密碼錯誤」,使用者會同時看到成功與失敗兩則訊息。
  if (loading.value) return
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
      <n-text v-if="forced" depth="3" style="display: block; margin-bottom: 12px" data-testid="cp-forced">
        這是您的首次登入,請設定新密碼後繼續使用系統。
      </n-text>
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="原密碼">
          <n-input
            v-model:value="oldPassword" type="password" show-password-on="click"
            data-testid="cp-old"
          />
        </n-form-item>
        <n-form-item :label="`新密碼(至少 ${MIN_LEN} 字元)`">
          <n-input
            v-model:value="newPassword" type="password" show-password-on="click"
            data-testid="cp-new"
          />
        </n-form-item>
        <n-form-item label="確認新密碼">
          <n-input
            v-model:value="confirmPassword"
            type="password"
            show-password-on="click"
            data-testid="cp-confirm"
          />
        </n-form-item>
        <!-- 送出只走表單的 submit 這一條路(按鈕是 type=submit,輸入框按 Enter 也會觸發它)。
             先前按鈕另外掛了 @click、確認欄另外掛了 @keyup.enter,於是每次送出都跑兩遍。 -->
        <n-button type="primary" block :loading="loading" attr-type="submit" data-testid="cp-submit">
          更新密碼
        </n-button>
      </n-form>
    </n-card>
  </div>
</template>
