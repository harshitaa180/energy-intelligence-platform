/** One appliance in full: the day, its history, the model behind the verdict, and advice. */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Coins, Info, Leaf, Sparkles, Thermometer, Timer, Zap } from 'lucide-react'

import { ActualVsExpectedChart, ImportanceChart, RuntimeChart } from '../charts/Charts'
import {
  Callout,
  Card,
  CardHeader,
  CardSkeleton,
  EmptyState,
  ErrorState,
  MetricTile,
  PageHeader,
  PriorityChip,
  ProvenanceBadge,
  ReliabilityChip,
  SectionNote,
  StatusChip,
  UnavailableNote,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync } from '../hooks/useApi'
import { api } from '../services/api'
import type { Replacement } from '../types/api'
import { dateLabel, metricLabel, metricValue, money, num, signedPct } from '../utils/format'

export function ApplianceDetailPage() {
  const { appliance = '' } = useParams()
  const { siteId, date } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.applianceDetail(siteId as string, appliance, date ?? undefined),
    [siteId, appliance, date],
  )

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  const { day, model_card: model, weather, series, recommendations, replacement } = data
  const assessed = day.expected_energy_kwh !== null && day.expected_energy_kwh !== undefined

  return (
    <div className="space-y-6">
      <Link to="/appliances" className="btn-ghost -ml-2 py-1 text-sm">
        <ArrowLeft size={14} /> All appliances
      </Link>

      <PageHeader
        eyebrow="Appliance detail"
        title={data.appliance_label}
        description={`${dateLabel(data.date)} · ${series.length} days analysed`}
        action={<StatusChip status={day.status} />}
      />

      {/* --- overview ----------------------------------------------------- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="Consumption"
          value={num(day.energy_kwh, 2)}
          unit="kWh"
          provenance="measured"
          icon={<Zap size={16} />}
          footnote={`${num(day.active_energy_kwh, 2)} kWh of that was while running.`}
        />
        <MetricTile
          label="Expected while running"
          value={assessed ? num(day.expected_energy_kwh, 2) : '--'}
          unit={assessed ? 'kWh' : undefined}
          provenance={assessed ? 'predicted' : 'unavailable'}
          icon={<Sparkles size={16} />}
          footnote="For this much runtime in this weather."
        />
        <MetricTile
          label="Deviation"
          value={day.deviation_pct !== null ? signedPct(day.deviation_pct) : '--'}
          provenance={day.deviation_pct !== null ? 'predicted' : 'unavailable'}
          icon={<Thermometer size={16} />}
          footnote={
            day.deviation_kwh !== null
              ? `${day.deviation_kwh >= 0 ? '+' : ''}${num(day.deviation_kwh, 2)} kWh against expectation.`
              : 'Not comparable on this day.'
          }
        />
        <MetricTile
          label="Runtime"
          value={day.runtime_hours !== null ? num(day.runtime_hours) : '--'}
          unit={day.runtime_hours !== null ? 'h' : undefined}
          provenance={day.runtime_hours !== null ? 'measured' : 'unavailable'}
          icon={<Timer size={16} />}
          footnote={`${day.cycles} start-ups · ${day.short_cycles} short cycles.`}
        />
      </div>

      {/* --- explanation -------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Why this verdict"
          action={<ReliabilityChip reliability={day.reliability} note={day.reliability_note} />}
        />
        <div className="space-y-3 p-5">
          <p className="text-[15px] leading-relaxed text-ink-700">{day.explanation}</p>
          <p className="text-xs leading-relaxed text-ink-400">{day.reliability_note}</p>
          {day.notes.map((note) => (
            <Callout key={note} tone="neutral" icon={<Info size={14} />}>
              {note}
            </Callout>
          ))}
          {day.probability !== null ? (
            <div className="rounded-xl border border-ink-200 p-3.5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-medium text-ink-600">Classifier probability</p>
                <p className="text-sm font-semibold text-ink-800 tnum">
                  {num(day.probability * 100, 0)}%
                </p>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
                <div
                  className={`h-full rounded-full ${
                    day.reliability === 'good' ? 'bg-accent-500' : 'bg-ink-300'
                  }`}
                  style={{ width: `${day.probability * 100}%` }}
                />
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-ink-400">
                {day.reliability === 'good'
                  ? 'This classifier validated well on held-out days, so it leads the verdict.'
                  : 'Shown for transparency. This classifier is not reliable enough to lead the verdict, so the expected-energy comparison decides.'}
              </p>
            </div>
          ) : null}
        </div>
      </Card>

      {/* --- actual vs expected ------------------------------------------ */}
      <Card>
        <CardHeader
          title="Actual against expected"
          subtitle="Every day in this appliance's history"
        />
        <div className="p-5">
          {series.length ? (
            <ActualVsExpectedChart data={series} />
          ) : (
            <EmptyState title="No daily history for this appliance" />
          )}
        </div>
      </Card>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Runtime history" />
          <div className="p-5">
            {series.some((entry) => entry.runtime_hours !== null) ? (
              <RuntimeChart data={series} />
            ) : (
              <UnavailableNote
                title="Runtime unavailable"
                reason="This site records power but not on/off state, so runtime cannot be derived."
              />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Weather context" icon={<Thermometer size={14} />} />
          <div className="p-5">
            {weather.available ? (
              <>
                <dl className="grid grid-cols-2 gap-4">
                  <div>
                    <dt className="text-xs text-ink-400">Mean temperature</dt>
                    <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                      {num(weather.temperature_mean_c)}°C
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-400">Range</dt>
                    <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                      {num(weather.temperature_min_c)}–{num(weather.temperature_max_c)}°C
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-400">Humidity</dt>
                    <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                      {num(weather.humidity_mean_pct, 0)}%
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-400">Heat index</dt>
                    <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                      {num(weather.heat_index)}
                    </dd>
                  </div>
                </dl>
                <Callout tone="accent" icon={<Info size={14} />}>
                  The heat index is an input to the expected-energy baseline, so a hot day
                  raises the expectation. The deviation above is already weather-adjusted.
                </Callout>
              </>
            ) : (
              <UnavailableNote title="No recorded weather for this day" />
            )}
          </div>
        </Card>
      </div>

      {/* --- cost, carbon, metadata --------------------------------------- */}
      <div className="grid items-start gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Cost" icon={<Coins size={14} />} />
          <div className="space-y-3 p-5">
            <Row label="This day" value={money(day.cost, 2)} />
            <Row
              label="Excess above expectation"
              value={day.excess_cost !== null ? money(day.excess_cost, 2) : '--'}
            />
            <ProvenanceBadge provenance="estimated" />
            <p className="text-[11px] leading-relaxed text-ink-400">
              Priced at the configured tariff. Not a real bill.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Carbon" icon={<Leaf size={14} />} />
          <div className="space-y-3 p-5">
            <Row label="This day" value={`${num(day.carbon_kg, 3)} kg CO2e`} />
            <Row
              label="Excess above expectation"
              value={day.excess_carbon_kg !== null ? `${num(day.excess_carbon_kg, 3)} kg` : '--'}
            />
            <ProvenanceBadge provenance="estimated" />
            <p className="text-[11px] leading-relaxed text-ink-400">
              Energy multiplied by the configured grid emission factor.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Appliance metadata" />
          <div className="p-5">
            {day.metadata.available ? (
              <>
                <p className="text-sm text-ink-600">
                  {day.metadata.unit_count} unit(s)
                  {day.metadata.weighted_star_rating
                    ? ` · ${num(day.metadata.weighted_star_rating)}-star weighted average`
                    : ''}
                </p>
                <ul className="mt-3 space-y-1.5">
                  {day.metadata.units?.map((unit) => (
                    <li key={unit.appliance_id} className="flex items-center gap-2 text-sm">
                      <span className="text-ink-700">{unit.brand ?? 'Unknown brand'}</span>
                      <span className="text-xs text-ink-400">×{unit.count}</span>
                      <span className="ml-auto text-xs text-ink-500 tnum">
                        {unit.star_rating !== null ? `${unit.star_rating}★` : 'unrated'}
                      </span>
                    </li>
                  ))}
                </ul>
                {day.metadata.note ? (
                  <p className="mt-3 text-[11px] leading-relaxed text-ink-400">{day.metadata.note}</p>
                ) : null}
              </>
            ) : (
              <UnavailableNote title="No metadata" reason={day.metadata.reason} />
            )}
          </div>
        </Card>
      </div>

      {/* --- model card --------------------------------------------------- */}
      <Card>
        <CardHeader
          title="The model behind this"
          subtitle={model.available ? `Pipeline ${model.pipeline_version}` : undefined}
        />
        <div className="p-5">
          {model.available ? (
            <div className="grid items-start gap-6 lg:grid-cols-2">
              <div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                  {Object.entries(model.metrics ?? {})
                    .filter(([, value]) => typeof value === 'number')
                    .map(([key, value]) => (
                      <div key={key}>
                        <dt className="text-[11px] text-ink-400">{metricLabel(key)}</dt>
                        <dd className="mt-0.5 text-sm font-semibold text-ink-800 tnum">
                          {typeof value === 'number' ? metricValue(key, value) : String(value)}
                        </dd>
                      </div>
                    ))}
                </dl>
                {typeof model.metrics?.reliability_warning === 'string' ? (
                  <Callout tone="warning" icon={<Info size={14} />}>
                    {model.metrics.reliability_warning}
                  </Callout>
                ) : null}
                <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Known limitations
                </h3>
                <ul className="mt-2 space-y-1.5">
                  {model.limitations?.map((limitation) => (
                    <li key={limitation} className="flex gap-2 text-xs leading-relaxed text-ink-500">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                      {limitation}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  What the model weighs
                </h3>
                <div className="mt-2">
                  <ImportanceChart
                    data={Object.entries(model.feature_importance ?? {})
                      .map(([feature, importance]) => ({ feature: metricLabel(feature), importance }))
                      .sort((a, b) => b.importance - a.importance)
                      .slice(0, 6)}
                  />
                </div>
              </div>
            </div>
          ) : (
            <UnavailableNote title="No model for this appliance" reason={model.reason} />
          )}
        </div>
        <SectionNote>
          Feature importance is model-wide, not a per-day attribution: it says what generally
          separates efficient from inefficient days for this appliance.
        </SectionNote>
      </Card>

      {/* --- recommendations + replacement -------------------------------- */}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="What to do" />
          <div className="p-5">
            {recommendations.length ? (
              <ul className="space-y-4">
                {recommendations.map((entry) => (
                  <li key={entry.id}>
                    <div className="flex flex-wrap items-center gap-2">
                      <PriorityChip priority={entry.priority} />
                      <p className="text-sm font-semibold text-ink-800">{entry.title}</p>
                    </div>
                    <p className="mt-1.5 text-sm text-ink-600">{entry.recommendation}</p>
                    <ul className="mt-2 space-y-1">
                      {entry.actions.map((action) => (
                        <li key={action} className="flex gap-2 text-xs text-ink-500">
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                          {action}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[11px] text-ink-400">{entry.confidence_reason}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="Nothing to act on for this appliance" />
            )}
          </div>
        </Card>

        <ReplacementCard
          replacement={replacement}
          siteId={siteId}
          appliance={appliance}
        />
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-ink-500">{label}</span>
      <span className="text-sm font-semibold text-ink-800 tnum">{value}</span>
    </div>
  )
}

function ReplacementCard({
  replacement,
  siteId,
  appliance,
}: {
  replacement: Replacement
  siteId: string
  appliance: string
}) {
  const [price, setPrice] = useState('')
  const [result, setResult] = useState<Replacement | null>(null)
  const [busy, setBusy] = useState(false)
  const shown = result ?? replacement

  async function recompute() {
    const parsed = Number(price)
    if (!Number.isFinite(parsed) || parsed <= 0) return
    setBusy(true)
    try {
      setResult(await api.replacement({ site_id: siteId, appliance, replacement_cost: parsed }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader title="Replacement analysis" />
      <div className="p-5">
        {!shown?.available ? (
          <UnavailableNote title="Cannot be assessed" reason={shown?.reason} />
        ) : !shown.recommended ? (
          <EmptyState title="Replacement not indicated" description={shown.reason} />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border border-ink-200 p-3.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                  Installed
                </p>
                <p className="mt-1.5 text-lg font-semibold text-ink-800 tnum">
                  {num(shown.current?.weighted_star_rating)}★
                </p>
                <p className="mt-1 text-xs text-ink-500 tnum">
                  {num(shown.current?.annual_kwh, 0)} kWh/yr ·{' '}
                  {money(shown.current?.annual_cost, 0)}/yr
                </p>
              </div>
              <div className="rounded-xl border border-accent-200 bg-accent-50/50 p-3.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-accent-700">
                  Replacement
                </p>
                <p className="mt-1.5 text-lg font-semibold text-accent-900 tnum">
                  {num(shown.replacement?.target_star_rating, 0)}★
                </p>
                <p className="mt-1 text-xs text-accent-800 tnum">
                  {num(shown.replacement?.projected_annual_kwh, 0)} kWh/yr ·{' '}
                  {money(shown.replacement?.projected_annual_cost, 0)}/yr
                </p>
              </div>
            </div>

            <Row label="Annual saving" value={money(shown.savings?.annual_cost, 0)} />
            <Row label="Carbon avoided" value={`${num(shown.savings?.annual_carbon_kg, 0)} kg/yr`} />
            <Row
              label="Payback"
              value={shown.payback_years !== null ? `${num(shown.payback_years)} years` : 'Unavailable'}
            />

            <div className="rounded-xl bg-ink-50 p-3.5">
              <p className="text-xs text-ink-500">{shown.payback_note}</p>
              <div className="mt-2 flex gap-2">
                <input
                  className="field py-1.5 text-sm"
                  inputMode="numeric"
                  placeholder="Purchase price"
                  value={price}
                  onChange={(event) => setPrice(event.target.value)}
                />
                <button type="button" className="btn-secondary py-1.5" onClick={recompute} disabled={busy}>
                  {busy ? 'Working' : 'Compute'}
                </button>
              </div>
            </div>

            <ul className="space-y-1.5">
              {shown.assumptions?.map((assumption) => (
                <li key={assumption} className="flex gap-2 text-[11px] leading-relaxed text-ink-400">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                  {assumption}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  )
}
