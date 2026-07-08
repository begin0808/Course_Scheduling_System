import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Dashboard from './Dashboard.vue'

// 無學期時 listSemesters 回空陣列 → 顯示空狀態
vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) }),
))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Dashboard },
      { path: '/wizard', name: 'wizard', component: { template: '<div />' } },
    ],
  })
}

describe('Dashboard', () => {
  it('無學期時顯示空狀態與前往精靈', async () => {
    const wrapper = mount(Dashboard, {
      global: { plugins: [createPinia(), makeRouter()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('儀表板')
    expect(wrapper.text()).toContain('尚未建立任何學期資料')
  })
})
