import type { UseQueryResult } from '@tanstack/react-query'
import type { ChartSpec } from '@/charts/registry'
import { ChartRenderer, type ZoomWindow } from './ChartRenderer'
import { Card, EmptyState, ErrorState, Skeleton } from './ui'

interface Props {
  title?: string
  query: UseQueryResult<ChartSpec>
  colors?: Record<string, string>
  group?: string
  height?: number
  onZoom?: (window: ZoomWindow | null) => void
}

/** A card showing a chart spec query with skeleton, error and empty states. */
export function ChartPanel({ title, query, colors, group, height = 300, onZoom }: Props) {
  const spec = query.data
  const empty = spec && (spec.series.length === 0 || spec.series.every((s) => s.data.length === 0))
  return (
    <Card title={spec?.title ?? title}>
      {query.isPending ? (
        <Skeleton className="w-full" height={height} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : empty ? (
        <EmptyState title="Nothing to show">
          {spec.warnings.join(' ') || 'No data for this chart.'}
        </EmptyState>
      ) : spec ? (
        <ChartRenderer spec={spec} colors={colors} group={group} height={height} onZoom={onZoom} />
      ) : null}
    </Card>
  )
}
