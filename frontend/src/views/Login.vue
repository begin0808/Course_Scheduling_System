<script setup lang="ts">
import { NButton, NCard, NForm, NFormItem, NInput, useMessage } from 'naive-ui'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import type { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function onSubmit() {
  if (!username.value || !password.value) {
    message.warning('請輸入帳號與密碼')
    return
  }
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    // 首次登入需改密碼者導向改密碼頁,否則進儀表板
    router.push(auth.mustChangePassword ? { name: 'change-password' } : { name: 'dashboard' })
  } catch (e) {
    message.error((e as ApiError).detail || '登入失敗')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px">
    <n-card title="排課與調代課系統" style="max-width: 400px">
      <n-form @submit.prevent="onSubmit">
        <n-form-item label="帳號">
          <n-input v-model:value="username" placeholder="請輸入帳號" @keyup.enter="onSubmit" />
        </n-form-item>
        <n-form-item label="密碼">
          <n-input
            v-model:value="password"
            type="password"
            show-password-on="click"
            placeholder="請輸入密碼"
            @keyup.enter="onSubmit"
          />
        </n-form-item>
        <n-button type="primary" block :loading="loading" attr-type="submit" @click="onSubmit">
          登入
        </n-button>
      </n-form>
    </n-card>
  </div>
</template>
