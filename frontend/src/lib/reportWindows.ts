import type { ReportRequest } from '@/api/hooks'

export type ReportWindow = NonNullable<ReportRequest['periods']>[number]

/** Parse "label, start, end" lines; returns the windows and the lines that failed. */
export function parseWindows(text: string): { windows: ReportWindow[]; errors: string[] } {
  const windows: ReportWindow[] = []
  const errors: string[] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split(',').map((p) => p.trim())
    const [start, end] = parts.slice(-2)
    const label = parts.slice(0, -2).join(', ')
    const iso = /^\d{4}-\d{2}-\d{2}$/
    if (parts.length < 3 || !label || !iso.test(start ?? '') || !iso.test(end ?? '')) {
      errors.push(line)
      continue
    }
    windows.push({ label, start: start as string, end: end as string })
  }
  return { windows, errors }
}

/** Numbers from a comma/space separated list (invalid entries dropped). */
export function parseNumbers(text: string): number[] {
  return text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isFinite(n))
}
