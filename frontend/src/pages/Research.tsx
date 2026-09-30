import { useMemo, useState } from 'react'
import { useJobStream } from '@/api/useJobStream'
import {
  usePlugins,
  useRegimes,
  useResearchList,
  useResearchResult,
  useRuns,
  useSubmitResearch,
  type BacktestConfig,
  type Plugin,
} from '@/api/hooks'
import { JobProgress } from '@/components/JobProgress'
import { ResearchView } from '@/components/ResearchView'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Label,
  PageHeader,
  Select,
  Skeleton,
  Tabs,
  Toggle,
} from '@/components/ui'
import { configToDraft, draftToConfig } from '@/lib/config'
import { formatDateTime, formatNumber } from '@/lib/format'
import { useLabStore } from '@/store/lab'

const TOOLS = [
  { id: 'sweep', label: 'Parameter sweep' },
  { id: 'walk', label: 'Walk-forward' },
  { id: 'mc', label: 'Monte Carlo' },
  { id: 'sens', label: 'Sensitivity' },
  { id: 'regimes', label: 'Regimes' },
] as const
type Tool = (typeof TOOLS)[number]['id']

const METRICS = ['sharpe', 'sortino', 'cagr', 'max_drawdown', 'ann_vol'] as const

interface Target {
  path: string
  plugin: Plugin | undefined
}

function targets(config: BacktestConfig, plugins: Plugin[]): Target[] {
  const find = (kind: string, name: string | undefined) =>
    plugins.find((p) => p.kind === kind && p.name === name)
  const out: Target[] = [{ path: 'strategy', plugin: find('strategy', config.strategy.name) }]
  if (config.constructor) {
    out.push({
      path: 'constructor',
      plugin: find('portfolio_constructor', config.constructor.name),
    })
  }
  ;(config.overlays ?? []).forEach((o, i) =>
    out.push({ path: `overlays.${i}`, plugin: find('overlay', o.name) }),
  )
  ;(config.costs ?? []).forEach((c, i) =>
    out.push({ path: `costs.${i}`, plugin: find('cost_model', c.name) }),
  )
  if (config.slippage)
    out.push({ path: 'slippage', plugin: find('slippage_model', config.slippage.name) })
  return out
}

function numericParams(plugin: Plugin | undefined): { name: string; type: string }[] {
  const props = (plugin?.params_schema.properties ?? {}) as Record<string, { type?: string }>
  return Object.entries(props)
    .filter(([, s]) => s.type === 'integer' || s.type === 'number')
    .map(([name, s]) => ({ name, type: s.type ?? 'number' }))
}

function parseValues(text: string, type: string): number[] {
  return text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map((v) => (type === 'integer' ? Math.round(Number(v)) : Number(v)))
    .filter((v) => Number.isFinite(v))
}

function GridEditor({
  plugin,
  values,
  onChange,
}: {
  plugin: Plugin | undefined
  values: Record<string, string>
  onChange: (v: Record<string, string>) => void
}) {
  const params = numericParams(plugin)
  if (!params.length)
    return <p className="text-sm text-muted">This plugin has no numeric parameters.</p>
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {params.map((p) => (
        <div key={p.name}>
          <Label htmlFor={`grid-${p.name}`}>
            {p.name} <span className="text-muted">({p.type})</span>
          </Label>
          <Input
            id={`grid-${p.name}`}
            placeholder="e.g. 10, 20, 50 (blank = fixed)"
            value={values[p.name] ?? ''}
            onChange={(e) => onChange({ ...values, [p.name]: e.target.value })}
          />
        </div>
      ))}
    </div>
  )
}

function ActiveJob({ jobId, onDone }: { jobId: string; onDone: (runId: string) => void }) {
  const { job } = useJobStream(jobId)
  const runId = job?.status === 'completed' ? (job.result?.run_id as string | undefined) : undefined
  return (
    <div className="space-y-2">
      <JobProgress jobId={jobId} compact />
      {runId && (
        <Button size="sm" variant="primary" onClick={() => onDone(runId)}>
          View result
        </Button>
      )}
    </div>
  )
}

export function ResearchPage() {
  const draft = useLabStore((s) => s.draft)
  const plugins = usePlugins()
  const runs = useRuns({ status: 'completed', limit: 500 })
  const list = useResearchList()
  const submit = useSubmitResearch()
  const [tool, setTool] = useState<Tool>('sweep')
  const [source, setSource] = useState<string>('lab')
  const [target, setTarget] = useState('strategy')
  const [grid, setGrid] = useState<Record<string, string>>({})
  const [metric, setMetric] = useState<string>('sharpe')
  const [trainBars, setTrainBars] = useState(756)
  const [testBars, setTestBars] = useState(126)
  const [anchored, setAnchored] = useState(false)
  const [mcRun, setMcRun] = useState('')
  const [mcMethod, setMcMethod] = useState<'bootstrap' | 'trades'>('bootstrap')
  const [nPaths, setNPaths] = useState(1000)
  const [sensKind, setSensKind] = useState<'cost' | 'delay' | 'capacity'>('cost')
  const [sensValues, setSensValues] = useState('0, 0.5, 1, 2, 5, 10')
  const [jobId, setJobId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<string | null>(null)
  const result = useResearchResult(viewing)
  const regimes = useRegimes(tool === 'regimes' && mcRun ? mcRun : null)

  const config: BacktestConfig = useMemo(() => {
    if (source === 'lab') return draftToConfig(draft)
    const run = runs.data?.find((r) => r.id === source)
    return run ? draftToConfig(configToDraft(run.config as BacktestConfig)) : draftToConfig(draft)
  }, [source, draft, runs.data])
  const tgts = targets(config, plugins.data ?? [])
  const current = tgts.find((t) => t.path === target) ?? tgts[0]
  const gridBody = Object.fromEntries(
    numericParams(current?.plugin)
      .map((p) => [p.name, parseValues(grid[p.name] ?? '', p.type)] as const)
      .filter(([, v]) => v.length > 0),
  )

  const launch = () => {
    const onSuccess = (job: { id: string }) => setJobId(job.id)
    if (tool === 'sweep') {
      submit.mutate(
        { kind: 'sweep', body: { config, target, grid: gridBody, metric } },
        { onSuccess },
      )
    } else if (tool === 'walk') {
      submit.mutate(
        {
          kind: 'walk-forward',
          body: {
            config,
            target,
            grid: gridBody,
            metric,
            train_bars: trainBars,
            test_bars: testBars,
            anchored,
          },
        },
        { onSuccess },
      )
    } else if (tool === 'mc') {
      submit.mutate(
        {
          kind: 'monte-carlo',
          body: { run_id: mcRun, method: mcMethod, n_paths: nPaths, mean_block: 5, seed: 7 },
        },
        { onSuccess },
      )
    } else if (tool === 'sens') {
      const nums = sensValues
        .split(/[\s,;]+/)
        .filter(Boolean)
        .map(Number)
      const body =
        sensKind === 'cost'
          ? { config, kind: sensKind, multiples: nums }
          : sensKind === 'delay'
            ? { config, kind: sensKind, delays: nums.map(Math.round) }
            : { config, kind: sensKind, capitals: nums }
      submit.mutate({ kind: 'sensitivity', body }, { onSuccess })
    }
  }

  const needsConfig = tool === 'sweep' || tool === 'walk' || tool === 'sens'
  const needsGrid = tool === 'sweep' || tool === 'walk'

  return (
    <div className="space-y-4">
      <PageHeader
        title="Research"
        subtitle="Sweeps, walk-forward, Monte Carlo, cost/delay/capacity sensitivity and regime analysis. Sweep trials count towards the experiment's deflated Sharpe."
      />
      <Tabs tabs={TOOLS} active={tool} onChange={setTool} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title={TOOLS.find((t) => t.id === tool)?.label}>
          <div className="space-y-4">
            {needsConfig && (
              <div className="grid gap-3 md:grid-cols-3">
                <div className="md:col-span-2">
                  <Label htmlFor="cfg-source">Configuration</Label>
                  <Select
                    id="cfg-source"
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                  >
                    <option value="lab">Strategy Lab draft ({draft.strategy?.name})</option>
                    {runs.data?.map((r) => (
                      <option key={r.id} value={r.id}>
                        Run {r.name || r.strategy} · {r.id}
                      </option>
                    ))}
                  </Select>
                </div>
                {needsGrid && (
                  <div>
                    <Label htmlFor="metric">Optimize</Label>
                    <Select id="metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
                      {METRICS.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </Select>
                  </div>
                )}
              </div>
            )}
            {needsGrid && (
              <>
                <div>
                  <Label htmlFor="target">Plugin to vary</Label>
                  <Select
                    id="target"
                    value={target}
                    onChange={(e) => {
                      setTarget(e.target.value)
                      setGrid({})
                    }}
                  >
                    {tgts.map((t) => (
                      <option key={t.path} value={t.path}>
                        {t.path} ({t.plugin?.name ?? 'unknown'})
                      </option>
                    ))}
                  </Select>
                </div>
                <GridEditor plugin={current?.plugin} values={grid} onChange={setGrid} />
              </>
            )}
            {tool === 'walk' && (
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <Label htmlFor="train">Train bars</Label>
                  <Input
                    id="train"
                    type="number"
                    value={trainBars}
                    onChange={(e) => setTrainBars(Number(e.target.value))}
                  />
                </div>
                <div>
                  <Label htmlFor="test">Test bars</Label>
                  <Input
                    id="test"
                    type="number"
                    value={testBars}
                    onChange={(e) => setTestBars(Number(e.target.value))}
                  />
                </div>
                <div className="flex items-end pb-2">
                  <Toggle
                    id="anchored"
                    checked={anchored}
                    onChange={setAnchored}
                    label="Anchored windows"
                  />
                </div>
              </div>
            )}
            {(tool === 'mc' || tool === 'regimes') && (
              <div className="grid gap-3 md:grid-cols-3">
                <div className="md:col-span-2">
                  <Label htmlFor="mc-run">Run</Label>
                  <Select id="mc-run" value={mcRun} onChange={(e) => setMcRun(e.target.value)}>
                    <option value="">Select a completed run…</option>
                    {runs.data?.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name || r.strategy} · {r.id}
                      </option>
                    ))}
                  </Select>
                </div>
                {tool === 'mc' && (
                  <>
                    <div>
                      <Label htmlFor="mc-method">Method</Label>
                      <Select
                        id="mc-method"
                        value={mcMethod}
                        onChange={(e) =>
                          setMcMethod(e.target.value === 'trades' ? 'trades' : 'bootstrap')
                        }
                      >
                        <option value="bootstrap">Stationary block bootstrap</option>
                        <option value="trades">Trade-order shuffle</option>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="paths">Paths</Label>
                      <Input
                        id="paths"
                        type="number"
                        value={nPaths}
                        onChange={(e) => setNPaths(Number(e.target.value))}
                      />
                    </div>
                  </>
                )}
              </div>
            )}
            {tool === 'sens' && (
              <div className="grid gap-3 md:grid-cols-3">
                <div>
                  <Label htmlFor="sens-kind">Kind</Label>
                  <Select
                    id="sens-kind"
                    value={sensKind}
                    onChange={(e) => {
                      const k = e.target.value as 'cost' | 'delay' | 'capacity'
                      setSensKind(k)
                      setSensValues(
                        k === 'cost'
                          ? '0, 0.5, 1, 2, 5, 10'
                          : k === 'delay'
                            ? '0, 1, 2, 3'
                            : '100000, 1000000, 10000000, 100000000',
                      )
                    }}
                  >
                    <option value="cost">Cost multiples</option>
                    <option value="delay">Extra execution delay (bars)</option>
                    <option value="capacity">Capital (capacity)</option>
                  </Select>
                </div>
                <div className="md:col-span-2">
                  <Label htmlFor="sens-values">Values</Label>
                  <Input
                    id="sens-values"
                    value={sensValues}
                    onChange={(e) => setSensValues(e.target.value)}
                  />
                </div>
              </div>
            )}
            {tool !== 'regimes' && (
              <div className="flex justify-end">
                <Button
                  variant="primary"
                  loading={submit.isPending}
                  disabled={
                    (tool === 'mc' && !mcRun) || (needsGrid && Object.keys(gridBody).length === 0)
                  }
                  onClick={launch}
                >
                  Run
                </Button>
              </div>
            )}
            {submit.isError && <ErrorState error={submit.error} />}
            {jobId && tool !== 'regimes' && <ActiveJob jobId={jobId} onDone={setViewing} />}
          </div>
        </Card>
        <Card title="Saved results" padded={false}>
          {list.isPending ? (
            <div className="p-4">
              <Skeleton height={160} />
            </div>
          ) : list.isError ? (
            <div className="p-4">
              <ErrorState error={list.error} />
            </div>
          ) : list.data.length === 0 ? (
            <div className="p-4">
              <EmptyState title="No research yet" />
            </div>
          ) : (
            <ul className="max-h-[480px] overflow-auto">
              {list.data.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setViewing(r.id)}
                    className="flex w-full items-center justify-between gap-2 border-b border-border/60 px-4 py-2 text-left text-sm hover:bg-elevated"
                  >
                    <span>
                      <Badge tone={viewing === r.id ? 'accent' : 'neutral'}>{r.kind}</Badge>{' '}
                      {r.strategy}
                      <div className="text-2xs text-muted">{formatDateTime(r.created_at)}</div>
                    </span>
                    <span className="font-mono text-2xs text-secondary">
                      {r.headline.sharpe !== undefined
                        ? `SR ${formatNumber(r.headline.sharpe, 'ratio')}`
                        : ''}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {tool === 'regimes' &&
        mcRun &&
        (regimes.isPending ? (
          <Skeleton height={200} />
        ) : regimes.isError ? (
          <ErrorState error={regimes.error} />
        ) : (
          <ResearchView result={regimes.data} />
        ))}
      {viewing &&
        tool !== 'regimes' &&
        (result.isPending ? (
          <Skeleton height={300} />
        ) : result.isError ? (
          <ErrorState error={result.error} />
        ) : (
          <ResearchView result={result.data} />
        ))}
    </div>
  )
}
