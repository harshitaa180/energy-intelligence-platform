/** Carbon intelligence. Every figure here is an estimate, and the page says so. */

import { Info, Leaf, TreePine } from 'lucide-react'

import { BreakdownChart, CarbonChart } from '../charts/Charts'
import {
  Callout,
  Card,
  CardHeader,
  CardSkeleton,
  EmptyState,
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
import { kwh, num, titleCase } from '../utils/format'

export function CarbonPage() {
  const { siteId, date, currentSite } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.carbon(siteId as string, date ?? undefined),
    [siteId, date],
  )

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Carbon intelligence"
        title={currentSite?.display_name ?? 'Carbon'}
        description={`Energy multiplied by a grid emission factor of ${data.emission_factor} ${data.unit}.`}
        action={<ProvenanceBadge provenance="estimated" />}
      />

      <Callout tone="neutral" icon={<Info size={16} />}>
        {data.note} Factor source: {data.emission_factor_source}.
      </Callout>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="This day"
          value={num(data.daily.carbon_kg, 2)}
          unit="kg CO2e"
          provenance="estimated"
          icon={<Leaf size={16} />}
          footnote={`From ${kwh(data.daily.energy_kwh)}.`}
        />
        <MetricTile
          label="Month to date"
          value={num(data.month_to_date.carbon_kg, 1)}
          unit="kg CO2e"
          provenance="estimated"
          footnote={`From ${kwh(data.month_to_date.energy_kwh, 1)}.`}
        />
        <MetricTile
          label="Whole record"
          value={num(data.lifetime.carbon_kg, 0)}
          unit="kg CO2e"
          provenance="estimated"
          footnote={`${data.lifetime.days} days, ${kwh(data.lifetime.energy_kwh, 0)}.`}
        />
        <MetricTile
          label="Projected annual"
          value={num(data.projected_annual_kg, 0)}
          unit="kg CO2e"
          provenance="estimated"
          icon={<TreePine size={16} />}
          footnote="Daily average scaled to 365 days. Seasonal loads make this uncertain."
        />
      </div>

      <Card>
        <CardHeader
          title="Carbon over time"
          subtitle="Tracks consumption exactly, since the emission factor is constant"
        />
        <div className="p-5">
          {data.daily_series.length ? (
            <CarbonChart data={data.daily_series} />
          ) : (
            <EmptyState title="No daily series available" />
          )}
        </div>
      </Card>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Carbon by appliance" subtitle="For the selected day" />
          <div className="p-5">
            {data.by_channel.length ? (
              <BreakdownChart
                unit="kg"
                valueLabel="Carbon"
                data={data.by_channel.map((entry) => ({
                  key: entry.key,
                  label: entry.label ?? titleCase(entry.key),
                  energy_kwh: entry.carbon_kg,
                  share_pct:
                    data.daily.carbon_kg > 0 ? (entry.carbon_kg / data.daily.carbon_kg) * 100 : 0,
                }))}
              />
            ) : (
              <EmptyState title="No appliance consumption on this day" />
            )}
          </div>
          <SectionNote>
            Bars are kilograms of CO2e. Because the emission factor is constant, this is the
            energy breakdown rescaled — it does not reflect time-of-day grid intensity.
          </SectionNote>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Renewable contribution" />
            <div className="p-5">
              <UnavailableNote title="Avoided carbon" reason={data.renewable.note} />
            </div>
          </Card>

          <Card>
            <CardHeader title="For scale" />
            <div className="space-y-3 p-5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-ink-500">Trees needed for a year</span>
                <span className="text-sm font-semibold text-ink-800 tnum">
                  {num(data.equivalences.trees_year_equivalent, 0)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-ink-500">Equivalent petrol car distance</span>
                <span className="text-sm font-semibold text-ink-800 tnum">
                  {data.equivalences.petrol_car_km_equivalent.toLocaleString()} km
                </span>
              </div>
              <p className="text-[11px] leading-relaxed text-ink-400">
                {data.equivalences.note} These are illustrative comparisons, not measurements.
              </p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
