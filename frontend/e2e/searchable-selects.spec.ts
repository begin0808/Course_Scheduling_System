import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { deleteSemesterByYearTerm, login } from './helpers'

/**
 * 下拉選單可打字搜尋(v1.3.4,使用者詢問):社團、分組多的學校,跑班群組有十幾二十個,
 * 原本只能從下拉清單一個個找。打群組名稱的任何一段就能篩出來。
 */
const YEAR = 168

async function api(page: Page, url: string, data: object) {
  const r = await page.request.post(url, { data })
  expect(r.ok(), `${url} → ${r.status()} ${await r.text()}`).toBeTruthy()
  return r.json()
}

test('新增配課:跑班群組可打字搜尋', async ({ page }) => {
  test.setTimeout(90_000)
  await login(page)
  await page.request.patch('/api/wizard/state', { data: { completed: true } })
  await deleteSemesterByYearTerm(page, YEAR, 1)

  try {
    const sem = await api(page, '/api/semesters', { academic_year: YEAR, term: 1, template_key: 'junior_high' })
    const q = `?semester_id=${sem.id}`
    const classes = []
    for (const name of ['701', '702']) {
      classes.push((await api(page, `/api/class-units${q}`, { grade: 7, name, track: 'junior_high' })).id)
    }
    const groups = ['七年級英語分組', '七年級數學分組', '社團', '多元選修', '班/週會', '彈性學習']
    for (const name of groups) {
      await api(page, `/api/scheduling-units${q}`, { name, class_ids: classes })
    }
    await api(page, `/api/teachers${q}`, { name: '王老師' })

    await page.goto('/scheduling/assignments')
    await page.locator('.n-base-selection').first().click()
    await page.locator('.n-base-select-option', { hasText: `${YEAR} 學年度第 1 學期` }).click()

    await page.getByTestId('assignment-add').click()
    await page.locator('.n-modal').getByText('跑班群組', { exact: true }).click()
    await page.getByTestId('a-group').click()
    await page.keyboard.type('週會')
    const options = page.locator('.n-base-select-option:visible')
    await expect(options).toHaveCount(1)
    await expect(options).toHaveText('班/週會')
    await options.click()
    await expect(page.getByTestId('a-group')).toContainText('班/週會')

    // 換一段字也找得到:「分組」篩出兩個。
    // 下拉選單關閉的動畫結束後才會清掉剛剛打的字;使用者的速度不會碰到,測試要等它關好
    await expect(options).toHaveCount(0)
    await page.waitForTimeout(500)
    await page.getByTestId('a-group').click()
    await page.keyboard.type('分組')
    await expect(options).toHaveCount(2)
    await page.keyboard.press('Escape')
  } finally {
    await deleteSemesterByYearTerm(page, YEAR, 1)
  }
})
