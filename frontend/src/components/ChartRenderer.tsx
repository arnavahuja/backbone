import * as echarts from 'echarts'
import ReactECharts from 'echarts-for-react'
import { useEffect, useMemo, useRef } from 'react'
import { buildOption, type ChartSpec } from '@/charts/registry'
import { ECHARTS_THEME_NAME } from '@/theme/echartsTheme'

export interface ZoomWindow {
  start: string
  end: string
}

interface Props {
  spec: ChartSpec
  colors?: Record<string, string>
  /** Charts with the same group share zoom and crosshair. */
  group?: string
  height?: number
  /** Called (debounced) with the visible time range when the user zooms or brushes. */
  onZoom?: (window: ZoomWindow | null) => void
}

const ZOOM_DEBOUNCE_MS = 450
const EMPTY_COLORS: Record<string, string> = {}

function toIso(value: unknown): string | null {
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value).toISOString()
  if (typeof value === 'string') return value
  return null
}

/** Renders any chart spec through the chart-type registry. */
export function ChartRenderer({ spec, colors = EMPTY_COLORS, group, height = 300, onZoom }: Props) {
  const ref = useRef<ReactECharts>(null)
  const timer = useRef<number | undefined>(undefined)
  const zoomable = spec.time_series
  const option = useMemo(
    () => buildOption(spec, { colors, zoom: zoomable && Boolean(onZoom ?? group) }),
    [spec, colors, zoomable, onZoom, group],
  )

  useEffect(() => {
    const instance = ref.current?.getEchartsInstance()
    if (!instance || !group || !spec.time_series) return
    instance.group = group
    echarts.connect(group)
  }, [group, spec.time_series, option])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const onEvents = useMemo((): Record<string, () => void> => {
    if (!onZoom || !spec.time_series) return {}
    return {
      datazoom: () => {
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => {
          const instance = ref.current?.getEchartsInstance()
          if (!instance) return
          const opt = instance.getOption() as {
            dataZoom?: { start?: number; end?: number; startValue?: unknown; endValue?: unknown }[]
          }
          const dz = opt.dataZoom?.[0]
          if (!dz) return
          if ((dz.start ?? 0) <= 0.01 && (dz.end ?? 100) >= 99.99) {
            onZoom(null)
            return
          }
          const start = toIso(dz.startValue)
          const end = toIso(dz.endValue)
          if (start && end) onZoom({ start, end })
        }, ZOOM_DEBOUNCE_MS)
      },
    }
  }, [onZoom, spec.time_series])

  return (
    <ReactECharts
      ref={ref}
      option={option}
      theme={ECHARTS_THEME_NAME}
      notMerge
      lazyUpdate
      onEvents={onEvents}
      style={{ height, width: '100%' }}
      opts={{ renderer: 'canvas' }}
    />
  )
}
