<script setup lang="ts">
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText } from 'naive-ui'
import { computed, h, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import NotificationBell from '@/components/NotificationBell.vue'
import { getUpdateStatus, getVersion } from '@/api/system'

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

// 手機尺寸預設收合側邊欄:390px 寬的螢幕若被 220px 側欄佔去,課表幾乎沒有空間
const collapsed = ref(typeof window !== 'undefined' && window.innerWidth < 768)

function menuLink(name: string, label: string) {
  return () => h(RouterLink, { to: { name } }, { default: () => label })
}

// 純教師帳號只看得到課表查詢(其餘頁面的後端 API 需教學組長以上權限)
const canManage = computed(() =>
  auth.hasRole('admin') || auth.hasRole('scheduler') || auth.hasRole('director'))

const menuOptions = computed(() => {
  const query = { label: menuLink('timetable-query', '課表查詢'), key: 'timetable-query' }
  // 請假是教師自己要做的事,純教師帳號也看得到
  const leaves = { label: menuLink('leaves', '請假登記'), key: 'leaves' }
  // 教師可查自己的代課鐘點
  const myStats = { label: menuLink('substitution-stats', '我的代課鐘點'), key: 'substitution-stats' }
  if (!canManage.value) return [query, leaves, myStats]
  return [
    { label: menuLink('dashboard', '儀表板'), key: 'dashboard' },
    query,
    {
      label: '基礎資料',
      key: 'basedata-group',
      children: [
        { label: menuLink('semesters', '學期與節次表'), key: 'semesters' },
        { label: menuLink('basedata', '教師/班級/科目/場地'), key: 'basedata' },
      ],
    },
    {
      label: '排課作業',
      key: 'scheduling-group',
      children: [
        { label: menuLink('assignments', '配課管理'), key: 'assignments' },
        { label: menuLink('workbench', '排課工作台'), key: 'workbench' },
        { label: menuLink('auto-schedule', '自動排課'), key: 'auto-schedule' },
        { label: menuLink('versions', '版本與發布'), key: 'versions' },
        { label: menuLink('timetable-demo', '課表元件(示範)'), key: 'timetable-demo' },
      ],
    },
    {
      label: '調代課',
      key: 'substitution-group',
      children: [
        leaves,
        { label: menuLink('substitutions', '調代課處理'), key: 'substitutions' },
        { label: menuLink('daily-board', '今日調代課'), key: 'daily-board' },
        { label: menuLink('substitution-log', '調代課紀錄'), key: 'substitution-log' },
        { label: menuLink('substitution-stats', '代課鐘點統計'), key: 'substitution-stats' },
        { label: menuLink('notification-board', '通知確認看板'), key: 'notification-board' },
      ],
    },
    { label: menuLink('system', '系統管理'), key: 'system' },
  ]
})

const activeKey = computed(() => route.name as string)

// 版本號:回報問題時要知道對方是哪一版;升級後也靠它確認升級成功
const version = ref('')
// 有新版本時只提醒管理員(升級是管理員的事,別讓教師看了緊張)
const newVersion = ref('')
onMounted(async () => {
  try {
    version.value = (await getVersion()).version
    if (auth.hasRole('admin')) {
      const st = await getUpdateStatus()
      if (st.update_available) newVersion.value = st.latest
    }
  } catch {
    // 版本資訊只是輔助,取不到不影響任何功能
  }
})

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
        :default-expanded-keys="['basedata-group', 'scheduling-group']"
      />
      <div v-if="version && !collapsed" class="version" data-testid="app-version">
        版本 {{ version }}
      </div>
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered style="padding: 12px 24px">
        <n-space justify="end" align="center">
          <router-link
            v-if="newVersion" :to="{ name: 'system' }" class="update-link"
            data-testid="update-badge"
          >
            <n-tag type="warning" size="small" round>有新版本 {{ newVersion }}</n-tag>
          </router-link>
          <notification-bell />
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

<style scoped>
.version { padding: 12px 20px; font-size: 12px; opacity: 0.6; }
.update-link { text-decoration: none; }
</style>
