import { expect, test } from '@playwright/test'

/** Visual review helper: `SCREENSHOTS=1 pnpm e2e screenshots` saves page screenshots. */
test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to capture screenshots')

const OUT = process.env.SCREENSHOT_DIR ?? 'test-results/screenshots'

test('capture pages', async ({ page }) => {
  await page.goto('/lab')
  await page.getByRole('button', { name: 'Reset' }).click()
  await page.getByLabel('Source').selectOption('synthetic')
  await page.getByLabel('Instruments (comma separated)').fill('AAA, BBB, CCC, DDD')
  await page.getByLabel('Benchmark').fill('MKT')
  await page.getByLabel('Start', { exact: true }).fill('2012-01-01')
  await page.getByLabel('End', { exact: true }).fill('2022-12-31')
  await page.screenshot({ path: `${OUT}/lab.png`, fullPage: true })
  await page.getByRole('button', { name: 'Run backtest' }).click()
  await page.getByRole('link', { name: 'Open run →' }).click()
  await expect(page.locator('canvas').first()).toBeVisible()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/run-overview.png`, fullPage: true })
  for (const tab of ['Performance', 'Risk', 'Positions', 'Trades']) {
    await page.getByRole('tab', { name: tab }).click()
    await page.waitForTimeout(1200)
    await page.screenshot({ path: `${OUT}/run-${tab.toLowerCase()}.png`, fullPage: true })
  }
  await page.goto('/lab')
  await page.getByLabel('Strategy', { exact: true }).selectOption('buy_and_hold')
  await page.getByRole('button', { name: 'Run backtest' }).click()
  await page.getByRole('link', { name: 'Open run →' }).click()
  await page.goto('/runs')
  await page.screenshot({ path: `${OUT}/runs.png`, fullPage: true })
  await page.getByLabel('Select all').check()
  await page.getByRole('button', { name: 'Compare' }).click()
  await page.waitForTimeout(2500)
  await page.screenshot({ path: `${OUT}/compare.png`, fullPage: true })
  await page.goto('/data')
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/data.png`, fullPage: true })
  await page.goto('/')
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${OUT}/dashboard.png`, fullPage: true })
})
