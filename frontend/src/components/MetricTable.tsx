import clsx from 'clsx'
import type { MetricDescriptor, MetricValue } from '@/api/hooks'
import { formatNumber, signClass, toText, type NumberFormat } from '@/lib/format'

interface Props {
  descriptors: MetricDescriptor[]
  values: Record<string, MetricValue>
  groups?: string[]
  showBenchmark?: boolean
}

const SIGNED = new Set(['Return'])

/** Grouped metric table rendered purely from API descriptors (no per-metric code). */
export function MetricTable({ descriptors, values, groups, showBenchmark = true }: Props) {
  const scalars = descriptors.filter(
    (d) => d.kind === 'scalar' && (!groups || groups.includes(d.group)) && values[d.key],
  )
  const byGroup = new Map<string, MetricDescriptor[]>()
  for (const d of scalars) byGroup.set(d.group, [...(byGroup.get(d.group) ?? []), d])
  const hasBench = showBenchmark && scalars.some((d) => values[d.key]?.benchmark != null)
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {[...byGroup.entries()].map(([group, items]) => (
        <div key={group} className="rounded-lg border border-border bg-surface">
          <div className="border-b border-border px-3 py-2 text-2xs font-medium uppercase tracking-wide text-muted">
            {group}
          </div>
          <table className="w-full text-sm">
            <thead className="sr-only">
              <tr>
                <th>Metric</th>
                <th>Strategy</th>
                {hasBench && <th>Benchmark</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((d) => {
                const v = values[d.key]
                const fmt = d.format
                return (
                  <tr key={d.key} className="border-b border-border/60 last:border-0">
                    <td className="px-3 py-1.5 text-secondary" title={d.description}>
                      {d.label}
                    </td>
                    <td
                      className={clsx(
                        'px-3 py-1.5 text-right font-mono tabular-nums',
                        SIGNED.has(group) && signClass(v?.value),
                      )}
                    >
                      {formatNumber(v?.value, fmt)}
                    </td>
                    {hasBench && (
                      <td className="px-3 py-1.5 text-right font-mono tabular-nums text-muted">
                        {d.benchmark ? formatNumber(v?.benchmark, fmt) : ''}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}

/** Render a table-kind metric (e.g. top drawdowns) generically. */
export function MetricRowsTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return null
  const cols = Object.keys(rows[0] ?? {})
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-2xs uppercase tracking-wide text-muted">
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 font-medium">
                {c.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border/60 last:border-0">
              {cols.map((c) => {
                const v = row[c]
                const numeric = typeof v === 'number'
                const fmt: NumberFormat =
                  c === 'depth' || c === 'loading'
                    ? c === 'depth'
                      ? 'percent'
                      : 'number'
                    : 'number'
                return (
                  <td
                    key={c}
                    className={clsx('px-3 py-1.5', numeric && 'text-right font-mono tabular-nums')}
                  >
                    {numeric
                      ? Number.isInteger(v) && c !== 'loading'
                        ? String(v)
                        : formatNumber(v, fmt)
                      : toText(v)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
