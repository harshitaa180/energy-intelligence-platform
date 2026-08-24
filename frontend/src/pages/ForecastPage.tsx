/** Forecast page: prediction, measured accuracy, and the assumptions behind it. */

import { AlertTriangle, Coins, Info, Leaf, TrendingUp } from 'lucide-react'

import { ForecastChart, type ForecastDatum } from '../charts/Charts'
import {
  Callout,
  Card,
  CardHeader,
  CardSkeleton,
  ErrorState,
  MetricTile,
  PageHeader,
  ProvenanceBadge,
  SectionNote,
  UnavailableNote,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync } from '../hooks/useApi'
import { api } from '../services/api'
import { money, num, shortDate } from '../utils/format'

export function ForecastPage() {
  const { siteId, currentSite } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.forecast(siteId as string, 7),
    [siteId],
  )

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  if (!data.available) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Forecast" title={currentSite?.display_name ?? 'Forecast'} />
        <UnavailableNote title="Forecast unavailable for this site" reason={data.reason} />
      </div>
    )
  }

  const tomorrow = data.tomorrow!
  const accuracy = data.accuracy!

  const chartData: ForecastDatum[] = [
    ...(data.recent_history ?? []).map((entry) => ({
      label: shortDate(entry.date),
      actual: entry.energy_kwh,
      forecast: null,
      lower: null,
      band: null,
      isForecast: false,
    })),
    ...data.points.map((point) => ({
      label: shortDate(point.date),
      actual: null,
      forecast: point.energy_kwh,
      lower: point.lower_kwh,
      band: point.upper_kwh - point.lower_kwh,
      isForecast: true,
    })),
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Forecast"
        title={currentSite?.display_name ?? 'Forecast'}
        description={`Next 7 days after ${data.last_observed_date}, from ${data.history_days} complete days of history.`}
        action={<ProvenanceBadge provenance="predicted" />}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label={`Tomorrow (${tomorrow.date})`}
          value={num(tomorrow.energy_kwh, 2)}
          unit="kWh"
          delta={tomorrow.change_vs_recent_pct ?? null}
          deltaLabel="vs recent 7-day mean"
          provenance="predicted"
          icon={<TrendingUp size={16} />}
          footnote={`Range ${num(tomorrow.lower_kwh, 2)}–${num(tomorrow.upper_kwh, 2)} kWh.`}
        />
        <MetricTile
          label="Estimated cost"
          value={money(tomorrow.cost, 2)}
          provenance="estimated"
          icon={<Coins size={16} />}
          footnote="At the configured average tariff."
        />
        <MetricTile
          label="Estimated carbon"
          value={num(tomorrow.carbon_kg, 2)}
          unit="kg CO2e"
          provenance="estimated"
          icon={<Leaf size={16} />}
        />
        <MetricTile
          label="Model error"
          value={`± ${num(accuracy.mae_kwh, 2)}`}
          unit="kWh"
          provenance="measured"
          icon={<Info size={16} />}
          footnote={`Mean absolute error over ${accuracy.backtest_days} back-tested days${
            accuracy.mape_pct !== null ? ` (${num(accuracy.mape_pct, 0)}% of the mean)` : ''
          }.`}
        />
      </div>

      {data.warning ? (
        <Callout tone="warning" icon={<AlertTriangle size={16} />}>
          {data.warning}
        </Callout>
      ) : null}

      <Card>
        <CardHeader
          title="Measured history and forecast"
          subtitle={data.model_label}
          action={
            <span className="chip bg-ink-100 text-ink-600">
              {accuracy.beats_constant_baseline ? 'Beats a flat average' : 'Does not beat a flat average'}
            </span>
          }
        />
        <div className="p-5">
          <ForecastChart data={chartData} />
        </div>
        <SectionNote>
          The shaded band is the model’s own measured error, widened with the square root of the
          horizon. It is not a confidence interval from a distributional model.
        </SectionNote>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Day by day" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-100 text-left text-[11px] uppercase tracking-wide text-ink-400">
                  <th className="px-5 py-2.5 font-medium">Day</th>
                  <th className="px-5 py-2.5 text-right font-medium">Energy</th>
                  <th className="px-5 py-2.5 text-right font-medium">Range</th>
                  <th className="px-5 py-2.5 text-right font-medium">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {data.points.map((point) => (
                  <tr key={point.date}>
                    <td className="px-5 py-2.5 text-ink-700">{point.day_label}</td>
                    <td className="px-5 py-2.5 text-right font-medium text-ink-800 tnum">
                      {num(point.energy_kwh, 2)} kWh
                    </td>
                    <td className="px-5 py-2.5 text-right text-ink-500 tnum">
                      {num(point.lower_kwh, 1)}–{num(point.upper_kwh, 1)}
                    </td>
                    <td className="px-5 py-2.5 text-right text-ink-600 tnum">
                      {money(point.cost, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <SectionNote>
            A table view is provided alongside the chart so the figures are readable without
            relying on colour.
          </SectionNote>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="How this was validated" />
            <div className="space-y-3 p-5">
              <p className="text-sm leading-relaxed text-ink-600">
                Two candidate models competed by walk-forward validation over the last{' '}
                {accuracy.backtest_days} days. The one with the lower mean absolute error was
                selected, and its error is what the band above shows.
              </p>
              <ul className="space-y-2">
                {accuracy.candidates.map((candidate) => (
                  <li
                    key={candidate.name}
                    className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm ${
                      candidate.name === data.model
                        ? 'bg-accent-50 text-accent-900 ring-1 ring-inset ring-accent-200'
                        : 'bg-ink-50 text-ink-600'
                    }`}
                  >
                    <span className="font-medium">
                      {candidate.name === 'ridge' ? 'Ridge regression' : 'Seasonal naive'}
                      {candidate.name === data.model ? ' · selected' : ''}
                    </span>
                    <span className="tnum">{num(candidate.mae_kwh, 2)} kWh error</span>
                  </li>
                ))}
                <li className="flex items-center justify-between rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-600">
                  <span className="font-medium">Flat long-run average</span>
                  <span className="tnum">{num(accuracy.constant_baseline_mae_kwh, 2)} kWh error</span>
                </li>
              </ul>
            </div>
          </Card>

          <Card>
            <CardHeader title="Assumptions" icon={<Info size={14} />} />
            <ul className="space-y-2.5 p-5">
              {data.assumptions?.map((assumption) => (
                <li key={assumption} className="flex gap-2.5 text-sm leading-relaxed text-ink-600">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                  {assumption}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  )
}
