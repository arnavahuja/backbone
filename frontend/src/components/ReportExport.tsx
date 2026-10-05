import { useState } from 'react'
import { useDownloadReport } from '@/api/hooks'
import { Button, Card, ErrorState, Input, Label, Select, Toggle } from '@/components/ui'
import { parseNumbers, parseWindows } from '@/lib/reportWindows'

const DEFAULT_PERIODS = [
  'Decade 2000s, 2000-01-01, 2009-12-31',
  'Decade 2010s, 2010-01-01, 2019-12-31',
  'Recent, 2020-01-01, 2025-12-31',
  'First half, 2000-01-01, 2012-12-31',
  'Second half, 2013-01-01, 2025-12-31',
].join('\n')

const DEFAULT_CRISES = [
  'Dot-com bust, 2000-03-01, 2002-09-30',
  'Global financial crisis, 2007-11-01, 2009-03-31',
  'COVID crash, 2020-02-01, 2020-04-30',
  '2022 rate shock, 2022-01-01, 2022-12-31',
].join('\n')

const textareaClass =
  'h-32 w-full rounded-md border border-border bg-canvas px-2.5 py-2 font-mono text-xs ' +
  'text-primary placeholder:text-muted focus:border-accent focus:outline-none ' +
  'focus:ring-1 focus:ring-accent'

/** Export any set of runs as CSV tables and PNG charts. Nothing here is strategy-specific. */
export function ReportExport({ runIds }: { runIds: string[] }) {
  const download = useDownloadReport()
  const [periods, setPeriods] = useState(DEFAULT_PERIODS)
  const [crises, setCrises] = useState(DEFAULT_CRISES)
  const [costs, setCosts] = useState('0, 5, 10, 20, 30')
  const [volTarget, setVolTarget] = useState(10)
  const [volScale, setVolScale] = useState('neutral')
  const [rolling, setRolling] = useState(36)
  const [align, setAlign] = useState(true)
  const p = parseWindows(periods)
  const c = parseWindows(crises)
  const invalid = [...p.errors, ...c.errors]

  const submit = () =>
    download.mutate({
      run_ids: runIds,
      align,
      periods: p.windows,
      crisis_windows: c.windows,
      cost_levels_bps: parseNumbers(costs),
      vol_target: volScale === 'none' ? null : volTarget / 100,
      vol_scale: volScale,
      rolling_window: rolling,
      charts: true,
    })

  return (
    <Card
      title="Report export (CSV + PNG)"
      actions={
        <Button
          variant="primary"
          loading={download.isPending}
          disabled={invalid.length > 0}
          onClick={submit}
        >
          Download report
        </Button>
      }
    >
      <p className="mb-3 text-2xs text-muted">
        Returns, metrics (gross and net), CAPM and FF5+MOM regressions, correlations, sub-periods,
        windows, calendar years, holdings counts, cost reconciliation and charts for the selected
        runs. Cost levels re-run each run with its trading costs replaced by one bps-of-notional
        model (borrow and financing kept); leave empty to skip.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <Label htmlFor="report-periods">Sub-periods (label, start, end per line)</Label>
          <textarea
            id="report-periods"
            className={textareaClass}
            value={periods}
            onChange={(e) => setPeriods(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="report-crises">Windows for cumulative returns</Label>
          <textarea
            id="report-crises"
            className={textareaClass}
            value={crises}
            onChange={(e) => setCrises(e.target.value)}
          />
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-5">
        <div>
          <Label htmlFor="report-costs">Cost levels (bps one-way)</Label>
          <Input id="report-costs" value={costs} onChange={(e) => setCosts(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="report-scale">Vol-scaled series</Label>
          <Select id="report-scale" value={volScale} onChange={(e) => setVolScale(e.target.value)}>
            <option value="neutral">market-neutral runs</option>
            <option value="all">all runs</option>
            <option value="none">none</option>
          </Select>
        </div>
        <div>
          <Label htmlFor="report-vol">Vol target (% a year)</Label>
          <Input
            id="report-vol"
            type="number"
            min={1}
            max={100}
            value={volTarget}
            disabled={volScale === 'none'}
            onChange={(e) => setVolTarget(Number(e.target.value))}
          />
        </div>
        <div>
          <Label htmlFor="report-rolling">Rolling Sharpe window (bars)</Label>
          <Input
            id="report-rolling"
            type="number"
            min={3}
            value={rolling}
            onChange={(e) => setRolling(Number(e.target.value))}
          />
        </div>
        <div className="flex items-end pb-1">
          <Toggle id="report-align" checked={align} onChange={setAlign} label="Common dates" />
        </div>
      </div>
      {invalid.length > 0 && (
        <p className="mt-2 text-xs text-negative">
          Fix these lines (expected “label, YYYY-MM-DD, YYYY-MM-DD”): {invalid.join(' | ')}
        </p>
      )}
      {download.isError && <ErrorState error={download.error} />}
    </Card>
  )
}
