import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { wsUrl } from './client'
import type { Job } from './hooks'

interface JobEvent {
  type: string
  job?: Job
  logs?: string[]
  line?: string
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

function parseEvent(raw: unknown): JobEvent | null {
  if (typeof raw !== 'string') return null
  try {
    const value: unknown = JSON.parse(raw)
    if (typeof value === 'object' && value !== null && 'type' in value) return value as JobEvent
  } catch {
    return null
  }
  return null
}

/** Stream a job's progress and log lines over the WebSocket. */
export function useJobStream(jobId: string | null | undefined) {
  const qc = useQueryClient()
  const [job, setJob] = useState<Job | null>(null)
  const [logs, setLogs] = useState<string[]>([])

  useEffect(() => {
    if (!jobId) return
    setJob(null)
    setLogs([])
    const ws = new WebSocket(wsUrl(`/ws/jobs/${encodeURIComponent(jobId)}`))
    ws.onmessage = (msg) => {
      const event = parseEvent(msg.data)
      if (!event) return
      if (event.job) setJob(event.job)
      if (event.type === 'snapshot' && event.logs) setLogs(event.logs)
      if (event.type === 'progress' && event.job) {
        const line = `[${Math.round(event.job.progress * 100)}%] ${event.job.message}`
        setLogs((prev) => [...prev.slice(-499), line])
      }
      if (event.line) {
        const line = event.line
        setLogs((prev) => [...prev.slice(-499), line])
      }
      if (event.job && TERMINAL.has(event.job.status)) {
        void qc.invalidateQueries({ queryKey: ['runs'] })
        void qc.invalidateQueries({ queryKey: ['jobs'] })
        void qc.invalidateQueries({ queryKey: ['catalog'] })
        if (event.job.run_id) void qc.invalidateQueries({ queryKey: ['run', event.job.run_id] })
      }
    }
    return () => ws.close()
  }, [jobId, qc])

  return { job, logs }
}
