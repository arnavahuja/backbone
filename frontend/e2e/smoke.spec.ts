import { expect, test, type Page } from '@playwright/test'

/** Configure a synthetic-data run in the Strategy Lab and launch it; returns the run URL. */
async function buildAndRun(page: Page, strategy: string, name: string): Promise<string> {
  await page.goto('/lab')
  await page.getByRole('button', { name: 'Reset' }).click()
  await page.getByLabel('Source').selectOption('synthetic')
  await page.getByLabel('Instruments (comma separated)').fill('AAA, BBB, CCC')
  await page.getByLabel('Start', { exact: true }).fill('2016-01-01')
  await page.getByLabel('End', { exact: true }).fill('2020-12-31')
  await page.getByLabel('Strategy', { exact: true }).selectOption(strategy)
  await page.getByLabel('Benchmark').fill('MKT')
  await page.getByLabel('Name', { exact: true }).fill(name)
  const run = page.getByRole('button', { name: 'Run backtest' })
  await expect(run).toBeEnabled()
  await run.click()
  const open = page.getByRole('link', { name: 'Open run →' })
  await expect(open).toBeVisible({ timeout: 60_000 })
  await open.click()
  await expect(page).toHaveURL(/\/runs\/[0-9a-f]+$/)
  return page.url()
}

test('build a run, see results, compare two runs', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))

  await buildAndRun(page, 'sma_crossover', 'e2e sma')
  await expect(page.getByText('Equity curve', { exact: true })).toBeVisible()
  await expect(page.getByText('Sharpe', { exact: true }).first()).toBeVisible()
  await expect(page.locator('canvas').first()).toBeVisible()
  await page.getByRole('tab', { name: 'Trades' }).click()
  await expect(page.getByText(/^Trades \(\d+\)$/)).toBeVisible()

  await buildAndRun(page, 'buy_and_hold', 'e2e hold')

  await page.goto('/runs')
  await page.getByLabel('Select all').check()
  await page.getByRole('button', { name: 'Compare' }).click()
  await expect(page).toHaveURL(/\/compare$/)
  await expect(page.getByText('Metrics (best in green, worst in red per row)')).toBeVisible()
  await expect(page.getByText('Equity curves', { exact: true })).toBeVisible()
  await expect(page.getByText('Return correlation', { exact: true })).toBeVisible()

  expect(errors).toEqual([])
})

test('theme contains no purple', async ({ page }) => {
  await page.goto('/')
  const colors = await page.evaluate(() => {
    const seen = new Set<string>()
    for (const el of Array.from(document.querySelectorAll('*'))) {
      const style = getComputedStyle(el)
      for (const prop of ['color', 'backgroundColor', 'borderColor', 'outlineColor'] as const) {
        seen.add(style[prop])
      }
    }
    return Array.from(seen)
  })
  const purple = colors.filter((c) => {
    const m = /rgba?\((\d+), (\d+), (\d+)/.exec(c)
    if (!m) return false
    const [r, g, b] = [Number(m[1]), Number(m[2]), Number(m[3])]
    // hue in the purple/violet/magenta range with meaningful saturation
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    if (max - min < 40) return false
    let h = 0
    if (max === r) h = ((g - b) / (max - min)) % 6
    else if (max === g) h = (b - r) / (max - min) + 2
    else h = (r - g) / (max - min) + 4
    const hue = (h * 60 + 360) % 360
    return hue >= 250 && hue <= 330
  })
  expect(purple).toEqual([])
})

test('research: parameter sweep from the lab draft', async ({ page }) => {
  await page.goto('/lab')
  await page.getByRole('button', { name: 'Reset' }).click()
  await page.getByLabel('Source').selectOption('synthetic')
  await page.getByLabel('Instruments (comma separated)').fill('AAA, BBB')
  await page.getByLabel('Benchmark').fill('MKT')
  await page.goto('/research')
  await page.getByLabel(/^fast/).fill('10, 20')
  await page.getByLabel(/^slow/).fill('50, 100')
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await page.getByRole('button', { name: 'View result' }).click({ timeout: 60_000 })
  await expect(page.getByText('Trials (best first)')).toBeVisible()
  await expect(page.getByText(/by fast and slow/)).toBeVisible()
})
