import { defineConfig, devices } from '@playwright/test'

// E2E 驗收:對「執行中的 Docker 全棧」(http://localhost)驅動真實瀏覽器。
// 一般執行(CI/無頭):npm run e2e        → chromium(迴歸套件)
// 有頭 + 放慢動作(給人觀看):npm run e2e:headed
// 壓測 / 手冊截圖(非迴歸,CI 不跑):npm run e2e:perf / npm run e2e:manual
const headed = process.env.HEADED === '1'
const ci = !!process.env.CI

const chrome = { ...devices['Desktop Chrome'] }

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  // CI 失敗時留下可診斷產物(trace + HTML 報告);本機維持輕量 list
  retries: 0,
  reporter: ci ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost',
    screenshot: 'only-on-failure',
    trace: ci ? 'retain-on-failure' : 'on-first-retry',
    launchOptions: { slowMo: headed ? 500 : 0 },
  },
  projects: [
    {
      // 迴歸驗收套件(CI 跑這個)。排除兩支「非驗收」spec:
      //   manual-shots:操作手冊截圖產生器,需另一台已灌示範資料的 :8081 測試站
      //   perf-page-load:60 班壓測,執行久且 p95 門檻受 runner 效能影響易 flaky
      name: 'chromium',
      use: chrome,
      testIgnore: ['**/manual-shots.spec.ts', '**/perf-page-load.spec.ts'],
    },
    { name: 'perf', use: chrome, testMatch: '**/perf-page-load.spec.ts' },
    { name: 'manual', use: chrome, testMatch: '**/manual-shots.spec.ts' },
  ],
})
