import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import SubstitutionStats from './SubstitutionStats.vue'

// 自訂統計區間(v1.4.11,組長回報):有的學校每月 15 日結算,要能選 10/16~11/15 這種期間。

const empty = {
  date_from: null, date_to: null, year: null, month: null,
  summaries: [], details: [], cover_details: [],
}

function stubFetch(statsBody: unknown = empty, statsStatus = 200) {
  const urls: string[] = []
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    urls.push(url)
    let body: unknown = []
    let status = 200
    if (url.includes('/substitution-stats')) {
      body = statsBody
      status = statsStatus
    } else if (url.includes('/semesters')) body = [{ id: 1, label: '115 學年度第 1 學期' }]
    return Promise.resolve({
      ok: status < 400, status, json: () => Promise.resolve(body),
    })
  }))
  return urls
}

async function mountStats() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  ;(auth as unknown as { user: unknown }).user = { id: 1, username: 's', roles: ['scheduler'] }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: SubstitutionStats }],
  })
  const wrapper = mount(SubstitutionStats, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

const statsCalls = (urls: string[]) => urls.filter((u) => u.includes('/substitution-stats'))

describe('代課鐘點統計:按月與自訂區間', () => {
  beforeEach(() => {
    try {
      localStorage.clear()
    } catch {
      // 測試環境沒有 localStorage 也沒關係
    }
  })

  it('預設按月查詢(和原本一樣)', async () => {
    const urls = stubFetch()
    const wrapper = await mountStats()
    const last = statsCalls(urls).at(-1)!
    expect(last).toContain('year=')
    expect(last).not.toContain('date_from')
    expect(wrapper.find('[data-testid="stats-month"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="stats-range"]').exists()).toBe(false)
  })

  it('切到自訂區間:送起訖日期,畫面寫出區間與說明', async () => {
    const urls = stubFetch()
    const wrapper = await mountStats()
    const btns = wrapper.findAll('[data-testid="stats-mode"] input')
    await btns[1].setValue(true)
    await flushPromises()

    const last = statsCalls(urls).at(-1)!
    expect(last).toMatch(/date_from=\d{4}-\d{2}-\d{2}&date_to=\d{4}-\d{2}-\d{2}/)
    expect(last).not.toContain('year=')
    expect(wrapper.find('[data-testid="stats-range"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="stats-range-hint"]').text()).toContain('起訖兩天都算在內')
    expect(wrapper.text()).toMatch(/\d{4}\/\d{2}\/\d{2} ~ \d{4}\/\d{2}\/\d{2}/)
    expect(wrapper.text()).toContain('這段期間沒有代課紀錄')
  })

  it('查詢被拒(例如區間超過一年)時顯示原因', async () => {
    stubFetch({ detail: '統計區間最長 366 天' }, 400)
    const wrapper = await mountStats()
    expect(wrapper.find('[data-testid="stats-error"]').text()).toContain('最長 366 天')
  })
})

describe('代課鐘點統計:網址帶期間', () => {
  it('網址帶 year/month 時一律按月,不受上次選擇影響', async () => {
    try {
      localStorage.setItem('stats-period-mode', 'range')
    } catch {
      // 沒有 localStorage 時這個測試等同預設情況
    }
    const urls = stubFetch()
    const pinia = createPinia()
    setActivePinia(pinia)
    ;(useAuthStore() as unknown as { user: unknown }).user = { id: 1, username: 's', roles: ['scheduler'] }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: SubstitutionStats }],
    })
    await router.push('/?year=2026&month=10')
    mount(SubstitutionStats, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(statsCalls(urls).at(-1)).toContain('year=2026&month=10')
  })
})
