import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { apiGet, apiPost } from '@/api/client'

export interface CurrentUser {
  id: number
  username: string
  display_name: string
  roles: string[]
  must_change_password: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  // 是否已向後端確認過登入狀態(避免每次路由都重打 /me)
  const loaded = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
  const mustChangePassword = computed(() => user.value?.must_change_password ?? false)

  async function fetchMe(): Promise<void> {
    try {
      user.value = await apiGet<CurrentUser>('/auth/me')
    } catch {
      user.value = null
    } finally {
      loaded.value = true
    }
  }

  async function login(username: string, password: string): Promise<void> {
    user.value = await apiPost<CurrentUser>('/auth/login', { username, password })
    loaded.value = true
  }

  async function logout(): Promise<void> {
    try {
      await apiPost('/auth/logout')
    } finally {
      user.value = null
    }
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
    user.value = await apiPost<CurrentUser>('/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  }

  function hasRole(role: string): boolean {
    return user.value?.roles.includes(role) ?? false
  }

  return {
    user,
    loaded,
    isAuthenticated,
    mustChangePassword,
    fetchMe,
    login,
    logout,
    changePassword,
    hasRole,
  }
})
