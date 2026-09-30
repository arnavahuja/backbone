import clsx from 'clsx'
import type { ResearchResult } from '@/api/hooks'
import { formatNumber, toText, type NumberFormat } from '@/lib/format'
import { ChartRenderer } from './ChartRenderer'
import { Card, Stat } from './ui'

function formatCell(value: unknown, format: string | null | undefined): string {
  if (typeof value === 'number') return formatNumber(value, (format ?? 'number') as NumberFormat)
  return toText(value)
}

/** Renders any research result (summary, tables, chart specs) with no per-tool code. */
export function ResearchView({ result }: { result: ResearchResult }) {
  const summary = Object.entries(result.summary)
  return (
    <div className="space-y-4">
      {summary.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          {summary.map(([k, v]) => (
            <Stat
              key={k}
              label={k.replace(/_/g, ' ')}
              value={
                <span className="text-sm">
                  {typeof v === 'number'
                    ? formatNumber(v, Math.abs(v) < 5 && !Number.isInteger(v) ? 'ratio' : 'number')
                    : toText(v)}
                </span>
              }
            />
          ))}
        </div>
      )}
      <div className="grid gap-4 2xl:grid-cols-2">
        {result.charts.map((spec) => (
          <Card key={spec.id} title={spec.title}>
            <ChartRenderer spec={spec} height={320} />
          </Card>
        ))}
      </div>
      {result.tables.map((table) => (
        <Card key={table.title} title={table.title} padded={false}>
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-border text-2xs uppercase tracking-wide text-muted">
                  {table.columns.map((c) => (
                    <th
                      key={c.key}
                      className={clsx(
                        'px-3 py-2 font-medium',
                        c.format ? 'text-right' : 'text-left',
                      )}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, i) => (
                  <tr key={i} className="border-b border-border/60 last:border-0">
                    {table.columns.map((c) => (
                      <td
                        key={c.key}
                        className={clsx(
                          'px-3 py-1.5',
                          typeof row[c.key] === 'number' && 'text-right font-mono tabular-nums',
                        )}
                      >
                        {formatCell(row[c.key], c.format)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </div>
  )
}
