/** Formatting helpers. Every number the UI shows passes through one of these. */

import type { Priority, Provenance } from '../types/api'

let currencySymbol = '₹'

export function setCurrencySymbol(symbol: string) {
  if (symbol) currencySymbol = symbol
}

export function money(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${currencySymbol}${value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

export function kwh(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)} kWh`
}

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return value.toFixed(digits)
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${value.toFixed(precisionFor(value, digits))}%`
}

export function signedPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  const shown = value.toFixed(precisionFor(value, digits))
  // A rounded-to-zero value must not read as "-0%".
  if (Number(shown) === 0) return '0%'
  return `${value > 0 ? '+' : ''}${shown}%`
}

/** Raise precision when a non-zero value would otherwise round away to zero. */
function precisionFor(value: number, digits: number): number {
  if (value === 0) return digits
  const magnitude = Math.abs(value)
  if (magnitude < 0.05) return Math.max(digits, 2)
  if (magnitude < 1) return Math.max(digits, 1)
  return digits
}

/** Counts are whole numbers; scores are not. Used for model-metric tables. */
export function metricValue(key: string, value: number): string {
  const isCount = /(_days|_positives|count|estimators)$/.test(key)
  return isCount ? String(Math.round(value)) : value.toFixed(3)
}

const ACRONYMS: Record<string, string> = {
  roc: 'ROC',
  auc: 'AUC',
  pr: 'PR',
  f1: 'F1',
  r2: 'R2',
}

/** Title-case that keeps metric acronyms upper-case: "Roc Auc" -> "ROC AUC". */
export function metricLabel(key: string): string {
  return key
    .split('_')
    .map((part) => ACRONYMS[part.toLowerCase()] ?? part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function watts(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} kW` : `${Math.round(value)} W`
}

export function hours(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${value.toFixed(1)} h`
}

export function carbon(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return `${value.toFixed(digits)} kg`
}

export function dateLabel(iso: string): string {
  const date = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function shortDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`
}

/** Turn [1,2,3,10] into "01:00-04:00 & 10:00-11:00". */
export function hourWindow(hoursList: number[]): string {
  if (!hoursList.length) return '--'
  const sorted = [...hoursList].sort((a, b) => a - b)
  const runs: number[][] = [[sorted[0]]]
  for (const hour of sorted.slice(1)) {
    const last = runs[runs.length - 1]
    if (hour === last[last.length - 1] + 1) last.push(hour)
    else runs.push([hour])
  }
  return runs
    .map((run) => `${hourLabel(run[0])}-${hourLabel((run[run.length - 1] + 1) % 24)}`)
    .join(' & ')
}

export const provenanceLabel: Record<Provenance, string> = {
  measured: 'Measured',
  predicted: 'Predicted',
  estimated: 'Estimated',
  simulated: 'Simulated',
  unavailable: 'Unavailable',
}

export const provenanceHelp: Record<Provenance, string> = {
  measured: 'Read directly from the meter data.',
  predicted: 'Model output, with a measured error band.',
  estimated: 'Derived from configured rates, not from a real bill or meter.',
  simulated: 'Modelled for demonstration. Not a real measurement.',
  unavailable: 'Not present in this dataset.',
}

export const priorityLabel: Record<Priority, string> = {
  high: 'High priority',
  medium: 'Medium priority',
  low: 'Low priority',
  info: 'For information',
}

export function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
