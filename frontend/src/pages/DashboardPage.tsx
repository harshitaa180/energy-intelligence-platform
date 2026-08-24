/** The main dashboard: one call to /api/houses/{id}/dashboard drives the whole page. */

import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  BatteryCharging,
  CloudSun,
  Coins,
  Gauge,
  Leaf,
  Lightbulb,
  Sun,
  Zap,
} from 'lucide-react'

import { ConsumptionChart, BreakdownChart } from '../charts/Charts'
import {
  Callout,
  Card,
  CardHeader,
  CardSkeleton,
  EmptyState,
  ErrorState,
  MetricTile,
  PriorityChip,
  ProvenanceBadge,
  ReliabilityChip,
  SectionNote,
  StatusChip,
  UnavailableNote,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync, useLocalStorage } from '../hooks/useApi'
import { api } from '../services/api'
import { dateLabel, hourWindow, kwh, money, num, signedPct } from '../utils/format'

type Granularity = 'hourly' | 'daily' | 'weekly' | 'monthly'
const GRANULARITIES: Granularity[] = ['hourly', 'daily', 'weekly', 'monthly']

export function DashboardPage() {
  const { siteId, date } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.dashboard(siteId as string, date ?? undefined),
    [siteId, date],
  )

  if (!siteId) return <CardSkeleton lines={4} />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <DashboardSkeleton />

  const { totals, comparison, appliances, weather, forecast, optimization, carbon: carbonData, sustainability_score: score, recommendations, insight, anomalies, energy_flow } = data

  const topRecommendation = recommendations?.recommendations?.[0]
  const live = weather.live
  const recorded = weather.recorded

  return (
    <div className="space-y-6">
      {/* --- header ------------------------------------------------------- */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-accent-700">
            Energy Intelligence
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink-900">
            {data.site.display_name}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {dateLabel(data.date)} · {data.site.day_count} days of history ·{' '}
            {data.site.reading_count.toLocaleString()} readings
          </p>
        </div>
        {score?.overall !== null && score?.overall !== undefined ? (
          <Link to="/insights" className="card card-hover flex items-center gap-4 px-5 py-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-400">
                Sustainability score
              </p>
              <p className="text-2xl font-semibold tracking-tight text-ink-900 tnum">
                {num(score.overall, 0)}
                <span className="ml-1 text-sm font-medium text-ink-400">/ 100</span>
              </p>
            </div>
            <span className="chip bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200">
              {score.grade}
            </span>
            <ArrowRight size={16} className="text-ink-300" />
          </Link>
        ) : null}
      </div>

      {totals.completeness && !totals.completeness.complete ? (
        <Callout tone="warning" icon={<AlertTriangle size={16} />}>
          {totals.completeness.note}
        </Callout>
      ) : null}

      {/* --- metric row --------------------------------------------------- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="Energy today"
          value={num(totals.total_energy_kwh, 2)}
          unit="kWh"
          delta={comparison?.available ? comparison.change_pct : null}
          deltaLabel={
            comparison?.available ? `vs ${comparison.baseline_days}-day average` : undefined
          }
          provenance="measured"
          icon={<Zap size={16} />}
        />
        <MetricTile
          label="Estimated cost"
          value={money(totals.cost, 2)}
          provenance="estimated"
          icon={<Coins size={16} />}
          footnote="Priced at the configured tariff, not a real bill."
        />
        <MetricTile
          label="Carbon"
          value={num(totals.carbon_kg, 2)}
          unit="kg CO2e"
          provenance="estimated"
          icon={<Leaf size={16} />}
          footnote={`Grid factor ${carbonData?.emission_factor ?? '--'} kg/kWh.`}
        />
        <MetricTile
          label="Peak demand"
          value={num(totals.peak_power_w / 1000, 2)}
          unit="kW"
          provenance="measured"
          icon={<Gauge size={16} />}
          footnote={`Mean ${num(totals.mean_power_w)} W across ${totals.reading_count} readings.`}
        />
      </div>

      {/* --- insight ------------------------------------------------------ */}
      {insight?.insight ? (
        <Card className="overflow-hidden">
          <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent-700">
              <Lightbulb size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="card-title">Today’s energy insight</h2>
                <span className="chip bg-ink-100 text-ink-500">
                  {insight.llm_available ? insight.source.replace('llm:', 'AI · ') : 'Rule-based'}
                </span>
              </div>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-700">{insight.insight}</p>
              {insight.note ? (
                <p className="mt-2 text-xs text-ink-400">{insight.note}</p>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to="/insights" className="btn-secondary py-1.5">
                  Investigate
                </Link>
                <Link to="/assistant" className="btn-ghost py-1.5">
                  Ask the assistant
                </Link>
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {/* --- consumption -------------------------------------------------- */}
      <ConsumptionSection siteId={siteId} />

      {/* --- appliances + weather ---------------------------------------- */}
      <div className="grid items-start gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Appliance intelligence"
            subtitle="Measured consumption against what the model expected for that runtime and weather"
            action={
              <Link to="/appliances" className="btn-ghost py-1.5 text-sm">
                All appliances <ArrowRight size={14} />
              </Link>
            }
          />
          <div className="p-5">
            {totals.channels.length ? (
              <>
                <BreakdownChart data={totals.channels} />
                <ul className="mt-4 divide-y divide-ink-100">
                  {appliances.length ? (
                    appliances.map((appliance) => (
                      <li key={appliance.appliance}>
                        <Link
                          to={`/appliances/${appliance.appliance}`}
                          className="-mx-2 flex flex-wrap items-center gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-ink-50"
                        >
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-ink-800">
                              {appliance.appliance_label}
                            </p>
                            <p className="mt-0.5 text-xs text-ink-500">
                              {kwh(appliance.energy_kwh)}
                              {appliance.expected_energy_kwh !== null
                                ? ` · expected ${kwh(appliance.expected_energy_kwh)}`
                                : ''}
                              {appliance.runtime_hours !== null
                                ? ` · ran ${num(appliance.runtime_hours)} h`
                                : ''}
                            </p>
                          </div>
                          {appliance.deviation_pct !== null ? (
                            <span
                              className={`text-sm font-semibold tnum ${
                                appliance.deviation_pct > 10
                                  ? 'text-rose-600'
                                  : appliance.deviation_pct < -10
                                    ? 'text-accent-700'
                                    : 'text-ink-500'
                              }`}
                            >
                              {signedPct(appliance.deviation_pct)}
                            </span>
                          ) : null}
                          <StatusChip status={appliance.status} />
                        </Link>
                      </li>
                    ))
                  ) : (
                    <li className="py-3">
                      <UnavailableNote
                        title="No appliance is assessable at this site"
                        reason={data.capabilities.flatMap((c) => c.notes)[0]}
                      />
                    </li>
                  )}
                </ul>
              </>
            ) : (
              <EmptyState title="No channel data for this day" />
            )}
          </div>
        </Card>

        <div className="space-y-6">
          {/* weather */}
          <Card>
            <CardHeader title="Weather" icon={<CloudSun size={14} />} />
            <div className="p-5">
              {live.available ? (
                <>
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <p className="metric">{num(live.temperature_c)}°C</p>
                      <p className="mt-1 text-sm text-ink-500">{live.condition}</p>
                    </div>
                    <ProvenanceBadge provenance="measured" label="Live" />
                  </div>
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                    <div>
                      <dt className="text-xs text-ink-400">Feels like</dt>
                      <dd className="font-medium text-ink-700 tnum">{num(live.feels_like_c)}°C</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-400">Humidity</dt>
                      <dd className="font-medium text-ink-700 tnum">{num(live.humidity_pct, 0)}%</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-400">Wind</dt>
                      <dd className="font-medium text-ink-700 tnum">
                        {num(live.wind_speed_kmh)} km/h
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-400">Rain chance</dt>
                      <dd className="font-medium text-ink-700 tnum">
                        {live.precipitation_probability_pct === null ||
                        live.precipitation_probability_pct === undefined
                          ? '--'
                          : `${live.precipitation_probability_pct}%`}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-[11px] text-ink-400">{live.location}</p>
                </>
              ) : (
                <UnavailableNote title="Weather unavailable" reason={live.reason ?? live.message} />
              )}

              {recorded?.available ? (
                <div className="mt-4 rounded-xl border border-ink-200 bg-ink-50/60 p-3.5">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-semibold text-ink-600">Recorded on {data.date}</p>
                    <ProvenanceBadge provenance="measured" className="ml-auto" />
                  </div>
                  <p className="mt-1.5 text-sm text-ink-600 tnum">
                    {num(recorded.temperature_mean_c)}°C mean · {num(recorded.humidity_mean_pct, 0)}%
                    RH · heat index {num(recorded.heat_index)}
                  </p>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-ink-400">
                    This is the weather the model used. Live conditions above are context only.
                  </p>
                </div>
              ) : null}
            </div>
          </Card>

          {/* forecast preview */}
          <Card>
            <CardHeader
              title={
                forecast?.available && forecast.tomorrow
                  ? `Forecast · ${forecast.tomorrow.day_label}`
                  : 'Forecast'
              }
              subtitle={
                forecast?.available
                  ? `The day after the last reading (${forecast.last_observed_date}), not after the day selected above.`
                  : undefined
              }
              action={
                <Link to="/forecast" className="btn-ghost py-1 text-sm">
                  Detail <ArrowRight size={14} />
                </Link>
              }
            />
            <div className="p-5">
              {forecast?.available && forecast.tomorrow ? (
                <>
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <p className="metric">{num(forecast.tomorrow.energy_kwh, 1)}</p>
                      <p className="text-sm text-ink-400">kWh expected</p>
                    </div>
                    <ProvenanceBadge provenance="predicted" />
                  </div>
                  <p className="mt-3 text-sm text-ink-600 tnum">
                    {money(forecast.tomorrow.cost, 0)} estimated ·{' '}
                    {num(forecast.tomorrow.lower_kwh, 1)}–{num(forecast.tomorrow.upper_kwh, 1)} kWh
                    range
                  </p>
                  <p className="mt-2 text-[11px] leading-relaxed text-ink-400">
                    {forecast.model_label}. Mean absolute error {num(forecast.accuracy?.mae_kwh, 2)}{' '}
                    kWh over {forecast.accuracy?.backtest_days} back-tested days.
                  </p>
                  {forecast.warning ? (
                    <Callout tone="warning" icon={<AlertTriangle size={14} />}>
                      {forecast.warning}
                    </Callout>
                  ) : null}
                </>
              ) : (
                <UnavailableNote title="Forecast unavailable" reason={forecast?.reason} />
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* --- anomalies + optimisation ------------------------------------ */}
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Detected anomalies"
            subtitle="Consumption beyond the weather-adjusted expectation"
            action={
              <Link to="/insights" className="btn-ghost py-1 text-sm">
                All <ArrowRight size={14} />
              </Link>
            }
          />
          <div className="p-5">
            {anomalies?.length ? (
              <ul className="space-y-3">
                {anomalies.slice(0, 4).map((anomaly) => (
                  <li
                    key={`${anomaly.appliance}-${anomaly.date}`}
                    className="rounded-xl border border-ink-200 p-3.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`chip ${
                          anomaly.severity === 'high'
                            ? 'bg-rose-50 text-rose-700'
                            : 'bg-amber-50 text-amber-800'
                        }`}
                      >
                        <AlertTriangle size={12} />
                        {anomaly.severity}
                      </span>
                      <p className="text-sm font-medium text-ink-800">{anomaly.appliance_label}</p>
                      <span className="text-xs text-ink-400">{anomaly.date}</span>
                      <ReliabilityChip reliability={anomaly.reliability} className="ml-auto" />
                    </div>
                    <ul className="mt-2 flex flex-wrap gap-1.5">
                      {anomaly.types.map((type) => (
                        <li key={type.type} className="chip bg-ink-100 text-ink-600">
                          {type.label}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-sm leading-relaxed text-ink-600">{anomaly.explanation}</p>
                    {anomaly.excess_cost > 0 ? (
                      <p className="mt-1.5 text-xs text-ink-500">
                        Excess above expectation cost about {money(anomaly.excess_cost, 2)}.
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="Nothing exceeded expectation"
                description="No appliance at this site used more than its weather-adjusted baseline in the available history."
              />
            )}
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Optimization opportunity"
              action={
                <Link to="/optimization" className="btn-ghost py-1 text-sm">
                  View <ArrowRight size={14} />
                </Link>
              }
            />
            <div className="p-5">
              {optimization?.totals?.saving_per_day > 0 ? (
                <>
                  <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
                    <div>
                      <p className="metric">{money(optimization.totals.saving_per_month, 0)}</p>
                      <p className="text-sm text-ink-400">estimated saving per month</p>
                    </div>
                    <ProvenanceBadge provenance="estimated" />
                  </div>
                  <ul className="mt-4 space-y-2">
                    {optimization.plans
                      .filter((plan) => plan.shiftable)
                      .map((plan) => (
                        <li
                          key={plan.channel}
                          className="flex flex-wrap items-center gap-2 rounded-lg bg-ink-50 px-3 py-2 text-sm"
                        >
                          <span className="font-medium text-ink-800">{plan.label}</span>
                          <span className="text-ink-400">
                            {hourWindow(plan.current_hours)} → {hourWindow(plan.recommended_hours)}
                          </span>
                          <span className="ml-auto font-semibold text-accent-700 tnum">
                            {money(plan.saving, 2)}/day
                          </span>
                        </li>
                      ))}
                  </ul>
                </>
              ) : (
                <EmptyState
                  title="Already well scheduled"
                  description="No flexible load at this site would save a material amount by moving under the configured tariff."
                />
              )}
            </div>
            <SectionNote>{optimization?.method}</SectionNote>
          </Card>

          <Card>
            <CardHeader title="Energy flow" icon={<Sun size={14} />} />
            <div className="p-5">
              <EnergyFlow flow={energy_flow} totalKwh={totals.total_energy_kwh} />
            </div>
          </Card>
        </div>
      </div>

      {/* --- recommendations --------------------------------------------- */}
      {topRecommendation ? (
        <Card>
          <CardHeader
            title="Recommended actions"
            subtitle={recommendations.method}
            action={
              <span className="text-sm text-ink-500 tnum">
                {recommendations.total_monthly_saving > 0
                  ? `${money(recommendations.total_monthly_saving, 0)} / month identified`
                  : ''}
              </span>
            }
          />
          <ul className="divide-y divide-ink-100">
            {recommendations.recommendations.slice(0, 4).map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-start gap-3 px-5 py-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <PriorityChip priority={entry.priority} />
                    <p className="text-sm font-semibold text-ink-800">{entry.title}</p>
                  </div>
                  <p className="mt-1.5 text-sm text-ink-600">{entry.recommendation}</p>
                  <p className="mt-1 text-xs leading-relaxed text-ink-400">{entry.reason}</p>
                </div>
                <div className="text-right">
                  {entry.estimated_saving !== null ? (
                    <p className="text-sm font-semibold text-accent-700 tnum">
                      {money(entry.estimated_saving, 0)}
                      <span className="ml-1 text-xs font-normal text-ink-400">
                        /{entry.saving_period === 'observed_period' ? 'period' : entry.saving_period}
                      </span>
                    </p>
                  ) : (
                    <p className="text-xs text-ink-400">Not quantifiable</p>
                  )}
                  <p className="mt-1 text-[11px] text-ink-400">{entry.confidence} confidence</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  )
}

// --- consumption section (own fetch so granularity can change independently) --

function ConsumptionSection({ siteId }: { siteId: string }) {
  const [granularity, setGranularity] = useLocalStorage<Granularity>('ei.granularity', 'daily')
  const { data, loading, error } = useAsync(
    () => api.consumption(siteId, granularity),
    [siteId, granularity],
  )

  return (
    <Card>
      <CardHeader
        title="Energy consumption"
        subtitle="Measured half-hourly, rolled up"
        action={
          <div className="flex rounded-lg border border-ink-200 p-0.5">
            {GRANULARITIES.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setGranularity(value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors ${
                  granularity === value ? 'bg-ink-900 text-white' : 'text-ink-500 hover:text-ink-800'
                }`}
              >
                {value}
              </button>
            ))}
          </div>
        }
      />
      <div className="p-5">
        {error ? (
          <ErrorState message={error} />
        ) : loading || !data ? (
          <div className="skeleton h-[260px] w-full" />
        ) : data.points.length ? (
          <ConsumptionChart data={data.points} />
        ) : (
          <EmptyState title="No readings in this range" />
        )}
      </div>
    </Card>
  )
}

// --- energy flow -----------------------------------------------------------

function EnergyFlow({ flow, totalKwh }: { flow: DashboardFlow; totalKwh: number }) {
  if (!flow) return null
  const solarOn = flow.solar?.available
  const batteryOn = flow.battery?.available

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        {[
          { id: 'solar', label: 'Solar', icon: <Sun size={16} />, on: solarOn },
          { id: 'battery', label: 'Battery', icon: <BatteryCharging size={16} />, on: batteryOn },
          { id: 'grid', label: 'Grid', icon: <Zap size={16} />, on: true },
          { id: 'home', label: 'Home', icon: <Gauge size={16} />, on: true },
        ].map((node, index, all) => (
          <div key={node.id} className="flex flex-1 items-center gap-2">
            <div
              className={`flex flex-1 flex-col items-center gap-1 rounded-xl border px-2 py-3 text-center ${
                node.on
                  ? 'border-accent-200 bg-accent-50/60 text-accent-800'
                  : 'border-dashed border-ink-200 bg-ink-50/60 text-ink-400'
              }`}
            >
              {node.icon}
              <span className="text-[11px] font-medium">{node.label}</span>
            </div>
            {index < all.length - 1 ? <ArrowRight size={14} className="shrink-0 text-ink-300" /> : null}
          </div>
        ))}
      </div>

      <p className="mt-4 text-sm text-ink-600 tnum">
        Grid → Home: {kwh(totalKwh)} <ProvenanceBadge provenance="measured" className="ml-1" />
      </p>

      <div className="mt-3">
        <UnavailableNote title={flow.status === 'renewable_integration_ready' ? 'Renewable integration ready' : 'Renewable status'} reason={flow.message} />
      </div>
    </div>
  )
}

type DashboardFlow = {
  status: string
  message: string
  solar?: { available: boolean }
  battery?: { available: boolean }
} | null

// --- skeleton --------------------------------------------------------------

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="skeleton h-16 w-72" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <CardSkeleton key={index} lines={1} />
        ))}
      </div>
      <div className="skeleton h-[340px] w-full rounded-2xl" />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="skeleton h-[420px] rounded-2xl lg:col-span-2" />
        <div className="skeleton h-[420px] rounded-2xl" />
      </div>
    </div>
  )
}
