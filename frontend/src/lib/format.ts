/**
 * The single number-formatting utility. Every number shown in the UI goes through here.
 */
export type NumberFormat = 'percent' | 'ratio' | 'number' | 'integer' | 'currency' | 'bars' | 'days'

const DASH = '—'

const percentFmt = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const ratioFmt = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const numberFmt = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
})
const integerFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const currencyFmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})
const compactFmt = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 })

export function formatNumber(
  value: number | null | undefined,
  format: NumberFormat = 'number',
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH
  switch (format) {
    case 'percent':
      return percentFmt.format(value)
    case 'ratio':
      return ratioFmt.format(value)
    case 'integer':
    case 'bars':
    case 'days':
      return integerFmt.format(value)
    case 'currency':
      return currencyFmt.format(value)
    case 'number':
      return numberFmt.format(value)
  }
}

/** Short axis-label formatting. */
export function formatAxis(value: number, format: NumberFormat | null | undefined): string {
  if (!Number.isFinite(value)) return ''
  if (format === 'percent') {
    return `${(value * 100).toFixed(Math.abs(value) < 0.1 ? 1 : 0)}%`
  }
  if (format === 'currency') return `$${compactFmt.format(value)}`
  if (Math.abs(value) >= 10_000) return compactFmt.format(value)
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return DASH
  return value.slice(0, 10)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return DASH
  return value.replace('T', ' ').slice(0, 19)
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return DASH
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

/** Sign class for coloring numbers (positive/negative). */
export function signClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'text-positive' : 'text-negative'
}

/** Display text for an arbitrary JSON value. */
export function toText(value: unknown, empty = '—'): string {
  if (value === null || value === undefined || value === '') return empty
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}
