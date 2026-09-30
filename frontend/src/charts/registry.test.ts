import { benchmarkColor, divergingScale, seriesPalette, tokens } from '@/theme/tokens'
import { buildOption, chartRegistry, type ChartSpec } from './registry'

const base: Omit<ChartSpec, 'id' | 'title' | 'type' | 'series'> = {
  x_axis: { type: 'time', name: '', format: null, categories: null, min: null, max: null },
  y_axes: [{ type: 'value', name: 'y', format: 'percent', categories: null, min: null, max: null }],
  annotations: [],
  time_series: true,
  options: {},
  warnings: [],
}

function series(name: string, role: ChartSpec['series'][number]['role'], runId: string | null) {
  return {
    name,
    data: [
      ['2020-01-01T00:00:00Z', 1],
      ['2020-01-02T00:00:00Z', 1.1],
    ],
    role,
    run_id: runId,
    render_as: null,
    stack: null,
    y_axis: 0,
    dashed: role === 'benchmark',
    symbol_size: null,
    labels: null,
  }
}

test('every chart type has a renderer', () => {
  const types = [
    'line',
    'area',
    'stacked_area',
    'bar',
    'histogram',
    'scatter',
    'heatmap',
    'boxplot',
    'radar',
  ]
  expect(Object.keys(chartRegistry).sort()).toEqual(types.sort())
})

test('line chart keeps run colors and dashes the benchmark', () => {
  const spec: ChartSpec = {
    ...base,
    id: 'eq',
    title: 'Equity',
    type: 'line',
    series: [series('run', 'series', 'r1'), series('bench', 'benchmark', null)],
  }
  const option = buildOption(spec, { colors: { r1: '#F59E0B' }, zoom: true })
  const out = option.series as { itemStyle?: { color?: string }; lineStyle?: { type?: string } }[]
  expect(out[0]?.itemStyle?.color).toBe('#F59E0B')
  expect(out[1]?.itemStyle?.color).toBe(benchmarkColor)
  expect(out[1]?.lineStyle?.type).toBe('dashed')
  expect(option.dataZoom).toHaveLength(2)
})

function hue(hex: string): number {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  if (max === min) return -1
  let h = 0
  if (max === r) h = ((g - b) / (max - min)) % 6
  else if (max === g) h = (b - r) / (max - min) + 2
  else h = (r - g) / (max - min) + 4
  return (h * 60 + 360) % 360
}

test('no purple, violet, indigo or magenta in palettes and tokens', () => {
  const colors = [
    ...seriesPalette,
    ...divergingScale,
    benchmarkColor,
    tokens.accent,
    tokens.positive,
    tokens.negative,
    tokens.warning,
    tokens.info,
  ]
  for (const c of colors) {
    const h = hue(c)
    expect(h >= 250 && h <= 330, `${c} has hue ${h}`).toBe(false)
  }
})
