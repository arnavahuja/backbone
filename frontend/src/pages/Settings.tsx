import { usePlugins, useSettings, useWrdsTest } from '@/api/hooks'
import { Badge, Button, Card, ErrorState, PageHeader, Skeleton } from '@/components/ui'

export function SettingsPage() {
  const settings = useSettings()
  const plugins = usePlugins()
  const wrds = useWrdsTest()
  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        subtitle="Settings come from environment variables and .env; secrets never appear here."
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Application">
          {settings.isPending ? (
            <Skeleton height={160} />
          ) : settings.isError ? (
            <ErrorState error={settings.error} />
          ) : (
            <dl className="grid grid-cols-[180px_1fr] gap-y-1.5 text-sm">
              {Object.entries(settings.data).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k.replace(/_/g, ' ')}</dt>
                  <dd className="font-mono text-2xs">{String(v ?? '—')}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-3 text-2xs text-muted">
            Edit <code>.env</code> (see <code>.env.example</code>) and restart to change the data
            directory, default costs benchmark or worker count.
          </p>
        </Card>
        <Card title="WRDS connection">
          <p className="mb-3 text-sm text-secondary">
            Set <code>WRDS_USERNAME</code> in <code>.env</code>; the password is read from{' '}
            <code>~/.pgpass</code> by the wrds library.
          </p>
          <Button loading={wrds.isPending} onClick={() => wrds.mutate()}>
            Test connection
          </Button>
          {wrds.data && (
            <p className="mt-2 text-sm">
              <Badge tone={wrds.data.ok ? 'positive' : 'negative'}>
                {wrds.data.ok ? 'ok' : 'failed'}
              </Badge>{' '}
              <span className="text-secondary">{wrds.data.message}</span>
            </p>
          )}
          {wrds.isError && <ErrorState error={wrds.error} />}
        </Card>
      </div>
      <Card title="Plugins" padded={false}>
        {plugins.isPending ? (
          <div className="p-4">
            <Skeleton height={200} />
          </div>
        ) : plugins.isError ? (
          <div className="p-4">
            <ErrorState error={plugins.error} />
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-2xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2 font-medium">Kind</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Version</th>
                <th className="px-3 py-2 font-medium">Origin</th>
                <th className="px-3 py-2 font-medium">Description</th>
              </tr>
            </thead>
            <tbody>
              {plugins.data.map((p) => (
                <tr key={`${p.kind}:${p.name}`} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-1.5 text-secondary">{p.kind}</td>
                  <td className="px-3 py-1.5 font-mono text-2xs">{p.name}</td>
                  <td className="px-3 py-1.5 font-mono text-2xs">{p.version}</td>
                  <td className="px-3 py-1.5">
                    <Badge tone={p.origin === 'user' ? 'accent' : 'neutral'}>{p.origin}</Badge>
                  </td>
                  <td className="px-3 py-1.5 text-secondary">{p.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
