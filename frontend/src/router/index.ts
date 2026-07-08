import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useWizardStore } from '@/stores/wizard'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePassword.vue'),
  },
  {
    path: '/wizard',
    name: 'wizard',
    component: () => import('@/views/wizard/Wizard.vue'),
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
      },
      {
        path: 'settings/semesters',
        name: 'semesters',
        component: () => import('@/views/settings/Semesters.vue'),
      },
      {
        path: 'basedata',
        name: 'basedata',
        component: () => import('@/views/basedata/BaseData.vue'),
      },
      {
        path: 'settings/period-tables/:id',
        name: 'period-table-editor',
        component: () => import('@/views/settings/PeriodTableEditor.vue'),
      },
      {
        path: 'settings/system',
        name: 'system',
        component: () => import('@/views/settings/System.vue'),
      },
    ],
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

const AUTH_PAGES = new Set(['login', 'change-password'])

// 全域守衛:管控登入、強制改密、首次登入引導至設定精靈
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.loaded) {
    await auth.fetchMe()
  }

  if (to.meta.public) {
    if (auth.isAuthenticated && to.name === 'login') {
      return { name: auth.mustChangePassword ? 'change-password' : 'dashboard' }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' }
  }
  if (auth.mustChangePassword && to.name !== 'change-password') {
    return { name: 'change-password' }
  }
  if (!auth.mustChangePassword && to.name === 'change-password') {
    return { name: 'dashboard' }
  }

  // 首次登入引導:教學組長/管理員在尚未完成初始設定時,自動進入精靈(精靈內可略過)
  const canSetup = auth.hasRole('scheduler') || auth.hasRole('admin')
  if (canSetup && to.name !== 'wizard' && !AUTH_PAGES.has(to.name as string)) {
    const wizard = useWizardStore()
    if (!wizard.loaded) await wizard.fetch()
    if (wizard.state && !wizard.state.completed) {
      return { name: 'wizard' }
    }
  }
  return true
})
