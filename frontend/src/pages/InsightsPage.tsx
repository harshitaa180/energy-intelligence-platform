/** AI insights: the score with its arithmetic shown, anomalies, and the model registry. */

import { AlertTriangle, Info, Lightbulb } from 'lucide-react'

import {
  Bar,
  Callout,
  Card,
  CardHeader,
  CardSkeleton,
  EmptyState,
  ErrorState,
  PageHeader,
  PriorityChip,
  ProvenanceBadge,
  ReliabilityChip,
  SectionNote,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync } from '../hooks/useApi'
import { api } from '../services/api'
import { dateLabel, money, num, signedPct } from '../utils/format'

export function InsightsPage() {
  const { siteId, date, currentSite } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.dashboard(siteId as string, date ?? undefined),
    [siteId, date],
  )

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  const score = data.sustainability_score
  const recommendations = data.recommendations

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="AI insights"
        title={currentSite?.display_name ?? 'Insights'}
        description={dateLabel(data.date)}
      />

      {/* --- insight ------------------------------------------------------ */}
      <Card>
        <div className="flex gap-4 p-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent-700">
            <Lightbulb size={17} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="card-title">Daily insight</h2>
              <span className="chip bg-ink-100 text-ink-500">
                {data.insight.llm_available
                  ? data.insight.source.replace('llm:', 'AI · ')
                  : 'Rule-based'}
              </span>
            </div>
            <p className="mt-2 text-[15px] leading-relaxed text-ink-700">{data.insight.insight}</p>
            {data.insight.deterministic_insight &&
            data.insight.deterministic_insight !== data.insight.insight ? (
              <details className="mt-3">
                <summary className="cursor-pointer text-xs font-medium text-ink-500 hover:text-ink-700">
                  Show the rule-based version this was written from
                </summary>
                <p className="mt-2 rounded-lg bg-ink-50 p-3 text-sm leading-relaxed text-ink-600">
                  {data.insight.deterministic_insight}
                </p>
              </details>
            ) : null}
            {data.insight.note ? (
              <p className="mt-2 text-xs text-ink-400">{data.insight.note}</p>
            ) : null}
          </div>
        </div>
      </Card>

      {/* --- score -------------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Sustainability score"
          subtitle={score.methodology}
          action={<ProvenanceBadge provenance="estimated" />}
        />
        <div className="p-5">
          {score.overall === null ? (
            <EmptyState title="Score unavailable" description="No component could be computed for this site." />
          ) : (
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="flex flex-col items-center justify-center rounded-2xl border border-ink-200 bg-ink-50/50 p-6">
                <p className="text-5xl font-semibold tracking-tight text-ink-900 tnum">
                  {num(score.overall, 0)}
                </p>
                <p className="mt-1 text-sm text-ink-400">out of 100</p>
                <span className="chip mt-3 bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200">
                  {score.grade}
                </span>
              </div>

              <ul className="space-y-4 lg:col-span-2">
                {score.components.map((component) => (
                  <li key={component.key}>
                    <div className="flex flex-wrap items-baseline gap-2">
                      <p className="text-sm font-medium text-ink-800">{component.label}</p>
                      {component.available ? (
                        <>
                          <span className="text-sm font-semibold text-ink-900 tnum">
                            {num(component.score, 0)}
                          </span>
                          <span className="text-[11px] text-ink-400">
                            weight {num(component.effective_weight_pct, 0)}%
                          </span>
                        </>
                      ) : (
                        <span className="chip bg-ink-100 text-ink-500">Excluded</span>
                      )}
                    </div>
                    {component.available ? (
                      <Bar value={component.score ?? 0} max={100} className="mt-2" />
                    ) : null}
                    <p className="mt-1.5 text-xs leading-relaxed text-ink-500">{component.detail}</p>
                    <p className="mt-1 font-mono text-[10.5px] leading-relaxed text-ink-400">
                      {component.formula}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <SectionNote>
          Components whose inputs are unavailable are excluded and the remaining weights
          renormalised, so a site is never penalised for missing instrumentation. Excluded here:{' '}
          {score.excluded_components.length ? score.excluded_components.join(', ') : 'none'}.
        </SectionNote>
      </Card>

      {/* --- anomalies ---------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Anomaly log"
          subtitle="Consumption beyond the weather-adjusted expectation, most recent first"
        />
        <div className="p-5">
          {data.anomalies.length ? (
            <ul className="space-y-3">
              {data.anomalies.map((anomaly) => (
                <li
                  key={`${anomaly.appliance}-${anomaly.date}`}
                  className="rounded-xl border border-ink-200 p-4"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`chip ${
                        anomaly.severity === 'high'
                          ? 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200'
                          : 'bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200'
                      }`}
                    >
                      <AlertTriangle size={12} />
                      {anomaly.severity}
                    </span>
                    <p className="text-sm font-semibold text-ink-800">{anomaly.appliance_label}</p>
                    <span className="text-xs text-ink-400">{anomaly.date}</span>
                    {anomaly.deviation_pct !== null ? (
                      <span className="text-sm font-semibold text-rose-600 tnum">
                        {signedPct(anomaly.deviation_pct)}
                      </span>
                    ) : null}
                    <ReliabilityChip reliability={anomaly.reliability} className="ml-auto" />
                  </div>

                  <ul className="mt-2.5 space-y-1.5">
                    {anomaly.types.map((type) => (
                      <li key={type.type} className="flex flex-wrap items-baseline gap-2 text-sm">
                        <span className="chip bg-ink-100 text-ink-600">{type.label}</span>
                        <span className="text-ink-500">{type.detail}</span>
                      </li>
                    ))}
                  </ul>

                  <p className="mt-2.5 text-sm leading-relaxed text-ink-600">{anomaly.explanation}</p>

                  <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink-500 tnum">
                    <div>
                      <dt className="inline text-ink-400">Used </dt>
                      <dd className="inline font-medium">{num(anomaly.energy_kwh, 2)} kWh</dd>
                    </div>
                    {anomaly.expected_energy_kwh !== null ? (
                      <div>
                        <dt className="inline text-ink-400">Expected </dt>
                        <dd className="inline font-medium">
                          {num(anomaly.expected_energy_kwh, 2)} kWh
                        </dd>
                      </div>
                    ) : null}
                    {anomaly.runtime_hours !== null ? (
                      <div>
                        <dt className="inline text-ink-400">Ran </dt>
                        <dd className="inline font-medium">{num(anomaly.runtime_hours)} h</dd>
                      </div>
                    ) : null}
                    <div>
                      <dt className="inline text-ink-400">Temperature </dt>
                      <dd className="inline font-medium">{num(anomaly.temperature_mean)}°C</dd>
                    </div>
                    {anomaly.excess_cost > 0 ? (
                      <div>
                        <dt className="inline text-ink-400">Excess cost </dt>
                        <dd className="inline font-medium">{money(anomaly.excess_cost, 2)}</dd>
                      </div>
                    ) : null}
                  </dl>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No anomalies"
              description="Either nothing exceeded its weather-adjusted expectation, or this site lacks the on/off signal the detector needs."
            />
          )}
        </div>
      </Card>

      {/* --- recommendations ---------------------------------------------- */}
      <Card>
        <CardHeader
          title="All recommendations"
          subtitle={recommendations.method}
          action={
            recommendations.total_monthly_saving > 0 ? (
              <span className="text-sm font-semibold text-accent-700 tnum">
                {money(recommendations.total_monthly_saving, 0)} / month identified
              </span>
            ) : null
          }
        />
        <ul className="divide-y divide-ink-100">
          {recommendations.recommendations.map((entry) => (
            <li key={entry.id} className="px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityChip priority={entry.priority} />
                <p className="text-sm font-semibold text-ink-800">{entry.title}</p>
                <span className="ml-auto text-right">
                  {entry.estimated_saving !== null ? (
                    <span className="text-sm font-semibold text-accent-700 tnum">
                      {money(entry.estimated_saving, 0)}
                      <span className="ml-1 text-xs font-normal text-ink-400">
                        /{entry.saving_period === 'observed_period' ? 'period' : entry.saving_period}
                      </span>
                    </span>
                  ) : (
                    <span className="text-xs text-ink-400">Not quantifiable</span>
                  )}
                </span>
              </div>
              <p className="mt-1.5 text-sm text-ink-600">{entry.recommendation}</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-500">{entry.reason}</p>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-400">
                <span>Impact: {entry.estimated_impact}</span>
                <span>Confidence: {entry.confidence} — {entry.confidence_reason}</span>
              </div>
              {entry.actions.length ? (
                <ul className="mt-2 space-y-1">
                  {entry.actions.map((action) => (
                    <li key={action} className="flex gap-2 text-xs text-ink-500">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                      {action}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>

      {/* --- model registry ------------------------------------------------ */}
      <ModelRegistry />
    </div>
  )
}

function ModelRegistry() {
  const { data, loading } = useAsync(() => api.sites().then(() => fetchModels()), [])

  if (loading) return <CardSkeleton lines={3} />
  if (!data) return null

  return (
    <Card>
      <CardHeader
        title="Model registry"
        subtitle={`Pipeline ${data.pipeline_version ?? 'unknown'} · trained ${
          data.trained_at ? new Date(String(data.trained_at)).toLocaleString('en-GB') : 'unknown'
        }`}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-100 text-left text-[11px] uppercase tracking-wide text-ink-400">
              <th className="px-5 py-2.5 font-medium">Site</th>
              <th className="px-5 py-2.5 font-medium">Appliance</th>
              <th className="px-5 py-2.5 text-right font-medium">Active days</th>
              <th className="px-5 py-2.5 text-right font-medium">Accuracy</th>
              <th className="px-5 py-2.5 text-right font-medium">F1</th>
              <th className="px-5 py-2.5 text-right font-medium">ROC-AUC</th>
              <th className="px-5 py-2.5 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {data.pairs.map((pair) => (
              <tr key={`${pair.site_id}-${pair.appliance}`}>
                <td className="px-5 py-2.5 text-ink-700">{pair.site_id}</td>
                <td className="px-5 py-2.5 text-ink-700">{pair.appliance}</td>
                <td className="px-5 py-2.5 text-right text-ink-600 tnum">{pair.active_days ?? '--'}</td>
                <td className="px-5 py-2.5 text-right text-ink-600 tnum">
                  {metric(pair.metrics?.test_accuracy)}
                </td>
                <td className="px-5 py-2.5 text-right text-ink-600 tnum">
                  {metric(pair.metrics?.test_f1)}
                </td>
                <td className="px-5 py-2.5 text-right text-ink-600 tnum">
                  {metric(pair.metrics?.roc_auc)}
                </td>
                <td className="px-5 py-2.5">
                  <span className="chip bg-ink-100 text-ink-600">{pair.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <SectionNote>
        Metrics come from a chronological 70/30 split over each pair's active days. Where too few
        inefficient days fall in the validation window, the classifier is not used to decide the
        verdict — the expected-energy comparison is.
      </SectionNote>
      <div className="px-5 pb-5">
        <Callout tone="neutral" icon={<Info size={14} />}>
          Labels are self-generated from a residual percentile rather than externally verified
          ground truth, so these scores measure agreement with a statistical definition of
          inefficiency, not with an audited one.
        </Callout>
      </div>
    </Card>
  )
}

interface RegistryPair {
  site_id: string
  appliance: string
  status: string
  active_days: number | null
  metrics?: Record<string, number | string>
}

interface RegistryPayload {
  pipeline_version?: string
  trained_at?: string
  pairs: RegistryPair[]
}

async function fetchModels(): Promise<RegistryPayload> {
  const response = await fetch('/api/models')
  return (await response.json()) as RegistryPayload
}

function metric(value: number | string | undefined): string {
  return typeof value === 'number' ? value.toFixed(2) : '--'
}
