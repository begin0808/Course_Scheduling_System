import { defineConfig, devices } from '@playwright/test'

// E2E 驗收:對「執行中的 Docker 全棧」(http://localhost)驅動真實瀏覽器。
// 一般執行(CI/無頭):npm run e2e
// 有頭 + 放慢動作(給人觀看):npm run e2e:headed
const headed = process.env.HEADED === '1'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
    launchOptions: { slowMo: headed ? 500 : 0 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
