/**
 * Shared UI primitives.
 *
 * `ProvenanceBadge` is the important one. The backend tags every figure with where it
 * came from, and this component is how that tag reaches the reader -- so an estimate
 * never looks like a measurement.
 */

import type { ReactNode } from 'react'
import { AlertTriangle, Ban, CircleHelp, Gauge, Info, Sparkles, TrendingDown, TrendingUp } from 'lucide-react'

import type { DayStatus, Priority, Provenance, Reliability } from '../types/api'
import { priorityLabel, provenanceHelp, provenanceLabel } from '../utils/format'

// --- layout ----------------------------------------------------------------

export function Card({
  children,
  className = '',
  hover = false,
}: {
  children: ReactNode
  className?: string
  hover?: boolean
}) {
  return <section className={`card ${hover ? 'card-hover' : ''} ${className}`}>{children}</section>
}

export function CardHeader({
  title,
  subtitle,
  action,
  icon,
}: {
  title: string
  subtitle?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <header className="card-header">
      <div className="min-w-0">
        <h2 className="card-title flex items-center gap-2">
          {icon}
          {title}
        </h2>
        {subtitle ? <p className="mt-1 text-sm text-ink-500">{subtitle}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? (
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-accent-700">{eyebrow}</p>
        ) : null}
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink-900">{title}</h1>
        {description ? <p className="mt-1.5 max-w-3xl text-sm text-ink-500">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

// --- provenance ------------------------------------------------------------

const PROVENANCE_STYLES: Record<Provenance, string> = {
  measured: 'bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200',
  predicted: 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200',
  estimated: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200',
  simulated: 'bg-fuchsia-50 text-fuchsia-700 ring-1 ring-inset ring-fuchsia-200',
  unavailable: 'bg-ink-100 text-ink-500 ring-1 ring-inset ring-ink-200',
}

export function ProvenanceBadge({
  provenance,
  className = '',
  label,
}: {
  provenance: Provenance
  className?: string
  label?: string
}) {
  return (
    <span
      className={`chip ${PROVENANCE_STYLES[provenance]} ${className}`}
      title={provenanceHelp[provenance]}
    >
      {label ?? provenanceLabel[provenance]}
    </span>
  )
}

// --- metrics ---------------------------------------------------------------

export function MetricTile({
  label,
  value,
  unit,
  delta,
  deltaLabel,
  provenance,
  icon,
  footnote,
  invertDelta = false,
}: {
  label: string
  value: string
  unit?: string
  delta?: number | null
  deltaLabel?: string
  provenance?: Provenance
  icon?: ReactNode
  footnote?: ReactNode
  /** For cost and carbon, a rise is bad; for a score, a rise is good. */
  invertDelta?: boolean
}) {
  const hasDelta = delta !== null && delta !== undefined && Number.isFinite(delta)
  const rising = hasDelta && (delta as number) >= 0
  const good = invertDelta ? rising : !rising
  return (
    <div className="card card-hover p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-medium text-ink-500">{label}</p>
        {icon ? <span className="text-ink-400">{icon}</span> : null}
      </div>
      <p className="metric mt-2">
        {value}
        {unit ? <span className="ml-1 text-base font-medium text-ink-400">{unit}</span> : null}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {hasDelta ? (
          <span
            className={`chip ${
              good ? 'bg-accent-50 text-accent-700' : 'bg-rose-50 text-rose-700'
            }`}
          >
            {rising ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
            {`${rising ? '+' : ''}${(delta as number).toFixed(0)}%`}
          </span>
        ) : null}
        {deltaLabel ? <span className="text-xs text-ink-400">{deltaLabel}</span> : null}
        {provenance ? <ProvenanceBadge provenance={provenance} /> : null}
      </div>
      {footnote ? <p className="mt-3 text-xs leading-relaxed text-ink-400">{footnote}</p> : null}
    </div>
  )
}

// --- status ----------------------------------------------------------------

const STATUS_STYLES: Record<DayStatus, { label: string; className: string; icon: ReactNode }> = {
  normal: {
    label: 'Normal',
    className: 'bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200',
    icon: <Gauge size={12} />,
  },
  abnormal: {
    label: 'Above expectation',
    className: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
    icon: <AlertTriangle size={12} />,
  },
  idle: {
    label: 'Did not run',
    className: 'bg-ink-100 text-ink-500 ring-1 ring-inset ring-ink-200',
    icon: <Ban size={12} />,
  },
  not_assessable: {
    label: 'Not assessable',
    className: 'bg-ink-100 text-ink-500 ring-1 ring-inset ring-ink-200',
    icon: <CircleHelp size={12} />,
  },
}

export function StatusChip({ status, className = '' }: { status: DayStatus; className?: string }) {
  const style = STATUS_STYLES[status]
  return (
    <span className={`chip ${style.className} ${className}`}>
      {style.icon}
      {style.label}
    </span>
  )
}

const RELIABILITY_STYLES: Record<Reliability, { label: string; className: string }> = {
  good: { label: 'Model validated', className: 'bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200' },
  limited: { label: 'Model limited', className: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200' },
  insufficient: {
    label: 'Too little data to validate',
    className: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200',
  },
  unavailable: { label: 'No model', className: 'bg-ink-100 text-ink-500 ring-1 ring-inset ring-ink-200' },
}

export function ReliabilityChip({
  reliability,
  note,
  className = '',
}: {
  reliability: Reliability
  note?: string
  className?: string
}) {
  const style = RELIABILITY_STYLES[reliability]
  return (
    <span className={`chip ${style.className} ${className}`} title={note}>
      <Sparkles size={12} />
      {style.label}
    </span>
  )
}

const PRIORITY_STYLES: Record<Priority, string> = {
  high: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
  medium: 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200',
  low: 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200',
  info: 'bg-ink-100 text-ink-500 ring-1 ring-inset ring-ink-200',
}

export function PriorityChip({ priority }: { priority: Priority }) {
  return <span className={`chip ${PRIORITY_STYLES[priority]}`}>{priorityLabel[priority]}</span>
}

// --- states ----------------------------------------------------------------

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

export function CardSkeleton({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div className={`card p-5 ${className}`}>
      <Skeleton className="h-4 w-32" />
      <Skeleton className="mt-4 h-8 w-24" />
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className="mt-3 h-3 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-ink-200 bg-ink-50/60 px-6 py-10 text-center">
      <span className="text-ink-300">{icon ?? <Info size={24} />}</span>
      <p className="text-sm font-medium text-ink-700">{title}</p>
      {description ? <p className="max-w-md text-sm text-ink-500">{description}</p> : null}
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-rose-200 bg-rose-50/70 px-6 py-8 text-center">
      <AlertTriangle className="text-rose-500" size={22} />
      <p className="text-sm font-medium text-rose-800">Something went wrong</p>
      <p className="max-w-md text-sm text-rose-700">{message}</p>
      {onRetry ? (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  )
}

/**
 * The pattern used everywhere a service can be unavailable: state plainly that the
 * figure does not exist, and give the reason, instead of rendering a zero.
 */
export function UnavailableNote({ title, reason }: { title: string; reason?: string | null }) {
  return (
    <div className="rounded-xl border border-ink-200 bg-ink-50/70 p-4">
      <div className="flex items-center gap-2">
        <Info size={15} className="text-ink-400" />
        <p className="text-sm font-medium text-ink-700">{title}</p>
        <ProvenanceBadge provenance="unavailable" className="ml-auto" />
      </div>
      {reason ? <p className="mt-2 text-sm leading-relaxed text-ink-500">{reason}</p> : null}
    </div>
  )
}

export function Callout({
  tone = 'neutral',
  icon,
  children,
}: {
  tone?: 'neutral' | 'warning' | 'accent'
  icon?: ReactNode
  children: ReactNode
}) {
  const styles = {
    neutral: 'border-ink-200 bg-ink-50/70 text-ink-600',
    warning: 'border-amber-200 bg-amber-50/70 text-amber-900',
    accent: 'border-accent-200 bg-accent-50/70 text-accent-900',
  }[tone]
  return (
    <div className={`flex gap-2.5 rounded-xl border p-3.5 text-sm leading-relaxed ${styles}`}>
      {icon ? <span className="mt-0.5 shrink-0">{icon}</span> : null}
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function SectionNote({ children }: { children: ReactNode }) {
  return <p className="px-5 pb-4 text-xs leading-relaxed text-ink-400">{children}</p>
}

export function Bar({ value, max, className = '' }: { value: number; max: number; className?: string }) {
  const width = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-ink-100 ${className}`}>
      <div
        className="h-full rounded-full bg-accent-500 transition-[width] duration-500"
        style={{ width: `${width}%` }}
      />
    </div>
  )
}
