<script setup lang="ts">
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText } from 'naive-ui'
import { computed, h, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const ROLE_LABELS: Record<string, string> = {
  admin: '系統管理員',
  director: '教務主任',
  scheduler: '教學組長',
  teacher: '教師',
}
const roleLabels = computed(() => (auth.user?.roles ?? []).map((r) => ROLE_LABELS[r] ?? r))

const collapsed = ref(false)

function menuLink(name: string, label: string) {
  return () => h(RouterLink, { to: { name } }, { default: () => label })
}

const menuOptions = [
  { label: menuLink('dashboard', '儀表板'), key: 'dashboard' },
  {
    label: '基礎資料',
    key: 'basedata-group',
    children: [
      { label: menuLink('semesters', '學期與節次表'), key: 'semesters' },
      { label: menuLink('basedata', '教師/班級/科目/場地'), key: 'basedata' },
    ],
  },
  { label: menuLink('system', '系統管理'), key: 'system' },
]

const activeKey = computed(() => route.name as string)

async function onLogout() {
  await auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      show-trigger
      :collapsed="collapsed"
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div style="padding: 16px; font-weight: 700; white-space: nowrap; overflow: hidden">
        {{ collapsed ? '排課' : '排課與調代課系統' }}
      </div>
      <n-menu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
        :default-expanded-keys="['basedata-group']"
      />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered style="padding: 12px 24px">
        <n-space justify="end" align="center">
          <n-text v-if="auth.user">{{ auth.user.display_name }}</n-text>
          <n-tag v-for="label in roleLabels" :key="label" type="info" size="small">
            {{ label }}
          </n-tag>
          <n-button size="small" @click="onLogout">登出</n-button>
        </n-space>
      </n-layout-header>

      <n-layout-content content-style="padding: 24px" style="background: transparent">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>
