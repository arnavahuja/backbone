/** Small UI primitives. Colors and spacing come only from theme tokens (Tailwind classes). */
import clsx from 'clsx'
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from 'react'
import { ApiError } from '@/api/client'

export function Card({
  title,
  actions,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={clsx('rounded-lg border border-border bg-surface', className)}>
      {(title ?? actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h3 className="text-sm font-medium text-primary">{title}</h3>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={clsx(padded && 'p-4')}>{children}</div>
    </section>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  loading = false,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'sm' | 'md'
  loading?: boolean
}) {
  return (
    <button
      type="button"
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-9 px-3.5 text-sm',
        variant === 'primary' && 'bg-accent text-canvas hover:bg-accent-strong',
        variant === 'secondary' &&
          'border border-border bg-elevated text-primary hover:border-muted',
        variant === 'ghost' && 'text-secondary hover:bg-elevated hover:text-primary',
        variant === 'danger' && 'border border-negative/50 text-negative hover:bg-negative/10',
        className,
      )}
      disabled={rest.disabled ?? loading}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={clsx(
        'inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted border-t-accent',
        className,
      )}
    />
  )
}

export function Badge({
  children,
  tone = 'neutral',
  className,
}: {
  children: ReactNode
  tone?: 'neutral' | 'accent' | 'positive' | 'negative' | 'warning' | 'info'
  className?: string
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded px-1.5 py-0.5 text-2xs font-medium',
        tone === 'neutral' && 'bg-elevated text-secondary',
        tone === 'accent' && 'bg-accent/15 text-accent',
        tone === 'positive' && 'bg-positive/15 text-positive',
        tone === 'negative' && 'bg-negative/15 text-negative',
        tone === 'warning' && 'bg-warning/15 text-warning',
        tone === 'info' && 'bg-info/15 text-info',
        className,
      )}
    >
      {children}
    </span>
  )
}

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'positive' | 'negative' | 'warning'> = {
  queued: 'neutral',
  running: 'accent',
  completed: 'positive',
  failed: 'negative',
  cancelled: 'warning',
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? 'neutral'}>{status}</Badge>
}

export function Skeleton({ className, height }: { className?: string; height?: number }) {
  return (
    <div
      aria-hidden
      className={clsx('animate-pulse rounded bg-elevated', className)}
      style={height ? { height } : undefined}
    />
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <p className="text-sm font-medium text-secondary">{title}</p>
      {children && <div className="text-sm text-muted">{children}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? `${error.message} (${error.code})`
      : error instanceof Error
        ? error.message
        : 'Something went wrong'
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-4 rounded-lg border border-negative/40 bg-negative/5 px-4 py-3 text-sm"
    >
      <div>
        <p className="font-medium text-negative">Error</p>
        <p className="text-secondary">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-primary">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-secondary">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Label({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-xs font-medium text-secondary">
      {children}
    </label>
  )
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props
  return (
    <input
      className={clsx(
        'h-9 w-full rounded-md border border-border bg-canvas px-2.5 text-sm text-primary',
        'placeholder:text-muted focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent',
        className,
      )}
      {...rest}
    />
  )
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, children, ...rest } = props
  return (
    <select
      className={clsx(
        'h-9 w-full rounded-md border border-border bg-canvas px-2 text-sm text-primary',
        'focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent',
        className,
      )}
      {...rest}
    >
      {children}
    </select>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: ReactNode
  id?: string
}) {
  return (
    <label
      htmlFor={id}
      className="inline-flex cursor-pointer items-center gap-2 text-sm text-secondary"
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-border bg-canvas accent-accent focus:ring-accent"
      />
      {label}
    </label>
  )
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: readonly { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 border-b border-border">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={active === t.id}
          onClick={() => onChange(t.id)}
          className={clsx(
            '-mb-px border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
            active === t.id
              ? 'border-accent text-primary'
              : 'border-transparent text-secondary hover:text-primary',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function ProgressBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded bg-elevated"
      role="progressbar"
      aria-valuenow={pct}
    >
      <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Stat({
  label,
  value,
  className,
}: {
  label: string
  value: ReactNode
  className?: string
}) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="text-2xs uppercase tracking-wide text-muted">{label}</div>
      <div className={clsx('mt-0.5 font-mono text-lg tabular-nums', className)}>{value}</div>
    </div>
  )
}
