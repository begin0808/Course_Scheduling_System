import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import Dashboard from './Dashboard.vue'

// 攔截 fetch,讓元件測試不需真實後端
vi.stubGlobal('fetch', vi.fn(() =>
  Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ status: 'ok' }) }),
))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: Dashboard },
      { path: '/login', name: 'login', component: { template: '<div />' } },
    ],
  })
}

describe('Dashboard', () => {
  it('渲染系統標題', () => {
    const wrapper = mount(Dashboard, {
      global: { plugins: [createPinia(), makeRouter()] },
    })
    expect(wrapper.text()).toContain('排課與調代課系統')
  })
})
