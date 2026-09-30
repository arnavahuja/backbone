import { Link } from 'react-router-dom'
import { useJobStream } from '@/api/useJobStream'
import { toText } from '@/lib/format'
import { ProgressBar, StatusBadge } from './ui'

/** Live progress and log lines of a background job (WebSocket). */
export function JobProgress({ jobId, compact = false }: { jobId: string; compact?: boolean }) {
  const { job, logs } = useJobStream(jobId)
  if (!job) return <p className="text-sm text-muted">Connecting…</p>
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-2">
          <StatusBadge status={job.status} />
          <span className="text-secondary">{job.message || job.kind}</span>
        </div>
        {job.run_id && job.status === 'completed' && (
          <Link to={`/runs/${job.run_id}`} className="text-accent hover:underline">
            Open run →
          </Link>
        )}
      </div>
      <ProgressBar value={job.progress} />
      {job.error && <p className="text-sm text-negative">{toText(job.error.message, 'Failed')}</p>}
      {!compact && logs.length > 0 && (
        <pre className="max-h-40 overflow-auto rounded bg-canvas p-2 font-mono text-2xs text-secondary">
          {logs.join('\n')}
        </pre>
      )}
    </div>
  )
}
