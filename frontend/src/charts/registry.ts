/**
 * Chart-type registry: maps a backend chart type to a renderer producing an ECharts option.
 *
 * A new chart built from an existing type needs backend code only. A new chart *type* needs
 * one new entry here.
 */
import type {
  EChartsOption,
  SeriesOption,
  XAXisComponentOption,
  YAXisComponentOption,
} from 'echarts'
import type { Schemas } from '@/api/client'
import { formatAxis, formatNumber, type NumberFormat } from '@/lib/format'
import { roleColor } from '@/lib/runColors'
import { divergingScale, tokens } from '@/theme/tokens'

export type ChartSpec = Schemas['ChartSpec']
export type ChartType = Schemas['ChartType']
type Series = Schemas['ChartSeries']
type Axis = Schemas['Axis']

export interface RenderContext {
  /** run_id -> color, so runs keep their colors across charts. */
  colors: Record<string, string>
  /** Show the zoom slider (time series charts). */
  zoom: boolean
}

export type ChartRenderer = (spec: ChartSpec, ctx: RenderContext) => EChartsOption

type Row = unknown[]

const GRID = { left: 64, right: 24, top: 36, bottom: 40, containLabel: false }

function fmtOf(axis: Axis | undefined): NumberFormat | null {
  return axis?.format ?? null
}

function seriesColor(s: Series, ctx: RenderContext): string | undefined {
  if (s.run_id && ctx.colors[s.run_id]) return ctx.colors[s.run_id]
  return roleColor(s.role)
}

function toNumber(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function valueAxis(axis: Axis | undefined, hideSplit = false): YAXisComponentOption {
  const format = fmtOf(axis)
  const common = {
    name: axis?.name ?? '',
    nameLocation: 'middle' as const,
    nameGap: 46,
    nameRotate: 90,
    min: axis?.min ?? undefined,
    max: axis?.max ?? undefined,
    axisLabel: { formatter: (v: number) => formatAxis(v, format) },
    ...(hideSplit ? { splitLine: { show: false } } : {}),
  }
  return axis?.type === 'log'
    ? { type: 'log', ...common }
    : { type: 'value', scale: true, ...common }
}

function xAxisFor(spec: ChartSpec): XAXisComponentOption {
  const axis = spec.x_axis
  if (axis.type === 'time') return { type: 'time' }
  if (axis.type === 'category') return { type: 'category', data: axis.categories ?? [] }
  return valueAxis(axis) as XAXisComponentOption
}

/** Sanitize chart data rows into ECharts values ('-' marks a missing value). */
function cells(rows: Row[]): (string | number)[][] {
  return rows.map((r) => r.map((v) => (typeof v === 'number' || typeof v === 'string' ? v : '-')))
}

function tooltipFormatter(spec: ChartSpec) {
  const formats = spec.y_axes.map((a) => fmtOf(a) ?? 'number')
  return (params: unknown): string => {
    const items = Array.isArray(params) ? params : [params]
    const lines: string[] = []
    let header = ''
    for (const raw of items) {
      if (typeof raw !== 'object' || raw === null) continue
      const item = raw as {
        seriesName?: string
        value?: unknown
        marker?: string
        axisValueLabel?: string
        seriesIndex?: number
      }
      header = item.axisValueLabel ?? header
      const value: unknown = Array.isArray(item.value) ? (item.value as unknown[])[1] : item.value
      const s = spec.series[item.seriesIndex ?? 0]
      const fmt = formats[s?.y_axis ?? 0] ?? 'number'
      lines.push(
        `${item.marker ?? ''}${item.seriesName ?? ''}: <b>${formatNumber(toNumber(value), fmt)}</b>`,
      )
    }
    return [header.slice(0, 19), ...lines].filter(Boolean).join('<br/>')
  }
}

function annotations(spec: ChartSpec): Record<string, unknown> {
  const bands = spec.annotations.filter((a) => a.kind === 'band')
  const vlines = spec.annotations.filter((a) => a.kind === 'vline')
  const hlines = spec.annotations.filter((a) => a.kind === 'hline')
  const out: Record<string, unknown> = {}
  if (bands.length) {
    out.markArea = {
      silent: true,
      itemStyle: { color: tokens.fill.negativeBand },
      label: { color: tokens.text.secondary, fontSize: 10, position: 'insideTop' },
      data: bands.map((b) => [
        { xAxis: b.start as string, name: b.label },
        { xAxis: b.end as string },
      ]),
    }
  }
  if (vlines.length || hlines.length) {
    out.markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: tokens.text.muted, type: 'dashed' },
      data: [
        ...vlines.map((l) => ({ xAxis: l.value as string, name: l.label })),
        ...hlines.map((l) => ({ yAxis: l.value as number, name: l.label })),
      ],
    }
  }
  return out
}

function cartesianSeries(spec: ChartSpec, ctx: RenderContext): SeriesOption[] {
  const extras = annotations(spec)
  return spec.series.map((s, i) => {
    const kind = s.render_as ?? spec.type
    const color = seriesColor(s, ctx)
    const common = {
      name: s.name,
      data: s.data as Row[],
      yAxisIndex: s.y_axis,
      ...(color ? { itemStyle: { color } } : {}),
      ...(i === 0 ? extras : {}),
    }
    if (kind === 'scatter') {
      return { ...common, type: 'scatter', symbolSize: s.symbol_size ?? 6 } as SeriesOption
    }
    if (kind === 'bar' || kind === 'histogram') {
      const colorBySign = spec.options.color_by_sign === true
      const data = colorBySign
        ? (s.data as Row[]).map((row) => {
            const v = toNumber(row[1]) ?? 0
            return { value: row, itemStyle: { color: v >= 0 ? tokens.positive : tokens.negative } }
          })
        : common.data
      return {
        ...common,
        data,
        type: 'bar',
        barMaxWidth: 28,
        ...(kind === 'histogram' ? { barCategoryGap: '2%' } : {}),
        ...(s.stack ? { stack: s.stack } : {}),
      } as SeriesOption
    }
    const area = kind === 'area' || kind === 'stacked_area'
    return {
      ...common,
      type: 'line',
      showSymbol: false,
      sampling: 'lttb',
      lineStyle: {
        width: s.role === 'benchmark' ? 1.2 : 1.6,
        type: s.dashed ? 'dashed' : 'solid',
        ...(color ? { color } : {}),
      },
      ...(area ? { areaStyle: { opacity: kind === 'stacked_area' ? 0.55 : 0.18 } } : {}),
      ...(s.stack ? { stack: s.stack } : {}),
    } as SeriesOption
  })
}

const cartesian: ChartRenderer = (spec, ctx) => {
  const isTime = spec.x_axis.type === 'time'
  const yAxes = spec.y_axes.map((a, i) => valueAxis(a, i > 0))
  return {
    grid: {
      ...GRID,
      right: yAxes.length > 1 ? 56 : GRID.right,
      bottom: ctx.zoom && isTime ? 64 : 40,
    },
    legend: { top: 4, type: 'scroll', show: spec.series.length > 1 },
    tooltip: {
      trigger: isTime || spec.x_axis.type === 'category' ? 'axis' : 'item',
      axisPointer: { type: 'cross', snap: true },
      formatter: tooltipFormatter(spec),
      confine: true,
    },
    xAxis: xAxisFor(spec),
    yAxis: yAxes,
    dataZoom:
      ctx.zoom && isTime
        ? [
            { type: 'inside', filterMode: 'none' },
            { type: 'slider', height: 18, bottom: 12, filterMode: 'none' },
          ]
        : [],
    series: cartesianSeries(spec, ctx),
  }
}

const heatmap: ChartRenderer = (spec) => {
  const s = spec.series[0]
  const data = (s?.data ?? []) as Row[]
  const values = data.map((r) => toNumber(r[2])).filter((v): v is number => v !== null)
  const diverging = spec.options.diverging === true
  const absMax = Math.max(...values.map(Math.abs), 1e-9)
  const min =
    typeof spec.options.min === 'number'
      ? spec.options.min
      : diverging
        ? -absMax
        : Math.min(...values)
  const max =
    typeof spec.options.max === 'number'
      ? spec.options.max
      : diverging
        ? absMax
        : Math.max(...values)
  const format = (spec.options.value_format ?? 'number') as NumberFormat
  return {
    grid: { left: 110, right: 24, top: 16, bottom: 72 },
    tooltip: {
      formatter: (p: unknown) => {
        const item = p as { value?: Row }
        const v = item.value ?? []
        const x = spec.x_axis.categories?.[Number(v[0])] ?? ''
        const y = spec.y_axes[0]?.categories?.[Number(v[1])] ?? ''
        return `${y} ${x}: <b>${formatNumber(toNumber(v[2]), format)}</b>`
      },
    },
    xAxis: { type: 'category', data: spec.x_axis.categories ?? [], splitArea: { show: false } },
    yAxis: { type: 'category', data: spec.y_axes[0]?.categories ?? [], splitArea: { show: false } },
    visualMap: {
      min,
      max,
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 8,
      itemHeight: 120,
      inRange: { color: [...divergingScale] },
      formatter: (v: unknown) => formatAxis(Number(v), format),
    },
    series: [
      {
        type: 'heatmap',
        data: cells(data),
        label: {
          show: data.length <= 400,
          fontSize: 10,
          color: tokens.text.primary,
          formatter: (p: unknown) => formatAxis(Number((p as { value: Row }).value[2]), format),
        },
        itemStyle: { borderColor: tokens.bg.base, borderWidth: 1 },
      },
    ],
  }
}

const boxplot: ChartRenderer = (spec, ctx) => {
  return {
    grid: GRID,
    tooltip: { trigger: 'item' },
    xAxis: { type: 'category', data: spec.x_axis.categories ?? [] },
    yAxis: valueAxis(spec.y_axes[0]),
    series: spec.series.map((s) => ({
      type: 'boxplot',
      name: s.name,
      data: s.data,
      itemStyle: { color: 'transparent', borderColor: seriesColor(s, ctx) ?? tokens.accent },
    })) as SeriesOption[],
  }
}

const radar: ChartRenderer = (spec, ctx) => {
  const indicators = Array.isArray(spec.options.indicators)
    ? (spec.options.indicators as { name: string; max: number }[])
    : []
  return {
    legend: { top: 4, type: 'scroll' },
    tooltip: { trigger: 'item' },
    radar: { indicator: indicators, radius: '62%', center: ['50%', '56%'] },
    series: [
      {
        type: 'radar',
        data: spec.series.map((s) => {
          const color = seriesColor(s, ctx)
          return {
            name: s.name,
            value: (s.data[0] ?? []) as number[],
            ...(color ? { lineStyle: { color }, itemStyle: { color } } : {}),
            areaStyle: { opacity: 0.08 },
          }
        }),
      },
    ],
  }
}

export const chartRegistry: Record<ChartType, ChartRenderer> = {
  line: cartesian,
  area: cartesian,
  stacked_area: cartesian,
  bar: cartesian,
  histogram: cartesian,
  scatter: cartesian,
  heatmap,
  boxplot,
  radar,
}

export function buildOption(spec: ChartSpec, ctx: RenderContext): EChartsOption {
  const renderer = chartRegistry[spec.type]
  return renderer(spec, ctx)
}
