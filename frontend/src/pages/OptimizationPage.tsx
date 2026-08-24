/** Optimization: current vs optimised schedule, the price curve, and demand response. */

import { useState } from 'react'
import { Coins, Lock, Moon, Sun, Zap } from 'lucide-react'

import { LoadShapeChart, ScheduleComparisonChart } from '../charts/Charts'
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
import { hourLabel, hourWindow, kwh, money, num, pct } from '../utils/format'

const QUIET_PRESETS: { label: string; hours: number[] | undefined }[] = [
  { label: 'Default (00:00–06:00)', hours: undefined },
  { label: 'Late sleeper (23:00–08:00)', hours: [23, 0, 1, 2, 3, 4, 5, 6, 7] },
  { label: 'No quiet hours', hours: [] },
]

export function OptimizationPage() {
  const { siteId, currentSite } = useSite()
  const [preset, setPreset] = useState(0)
  const quiet = QUIET_PRESETS[preset].hours

  const { data, loading, error, reload } = useAsync(
    () => api.optimization(siteId as string, quiet),
    [siteId, preset],
  )
  const demand = useAsync(() => api.demandResponse(siteId as string), [siteId])

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  const shiftable = data.plans.filter((plan) => plan.shiftable)
  const blocked = data.plans.filter((plan) => !plan.shiftable)

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Optimization"
        title={currentSite?.display_name ?? 'Optimization'}
        description="Each appliance's measured hourly energy repriced at the cheapest feasible hours under the configured tariff."
        action={
          <label className="flex items-center gap-2 text-sm">
            <Moon size={14} className="text-ink-400" />
            <select
              className="field py-1.5 text-sm"
              value={preset}
              onChange={(event) => setPreset(Number(event.target.value))}
            >
              {QUIET_PRESETS.map((option, index) => (
                <option key={option.label} value={index}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="Current daily cost"
          value={money(data.totals.current_cost_per_day, 2)}
          provenance="estimated"
          icon={<Coins size={16} />}
        />
        <MetricTile
          label="Optimised daily cost"
          value={money(data.totals.optimized_cost_per_day, 2)}
          provenance="estimated"
          icon={<Zap size={16} />}
        />
        <MetricTile
          label="Estimated saving"
          value={money(data.totals.saving_per_month, 0)}
          unit="/ month"
          provenance="estimated"
          icon={<Sun size={16} />}
          footnote={`${money(data.totals.saving_per_day, 2)} per day, ${pct(data.totals.saving_pct)} of cost.`}
        />
        <MetricTile
          label="Peak-hour share"
          value={demand.data ? pct(demand.data.peak_share_pct) : '--'}
          provenance="measured"
          icon={<Lock size={16} />}
          footnote={
            demand.data
              ? `Peak window ${hourWindow(demand.data.peak_hours)}, ${pct(demand.data.peak_cost_share_pct)} of daily cost.`
              : undefined
          }
        />
      </div>

      <Card>
        <CardHeader
          title="Current schedule against optimised"
          subtitle="Per appliance, priced at the configured tariff"
        />
        <div className="p-5">
          {data.plans.length ? (
            <ScheduleComparisonChart
              data={data.plans.map((plan) => ({
                label: plan.label,
                current_cost: plan.current_cost,
                optimized_cost: plan.optimized_cost,
              }))}
            />
          ) : (
            <EmptyState title="No loads to optimise" />
          )}
        </div>
        <SectionNote>{data.method}</SectionNote>
      </Card>

      <Card>
        <CardHeader title="Recommended moves" />
        <div className="overflow-x-auto">
          {shiftable.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-100 text-left text-[11px] uppercase tracking-wide text-ink-400">
                  <th className="px-5 py-2.5 font-medium">Appliance</th>
                  <th className="px-5 py-2.5 font-medium">Currently</th>
                  <th className="px-5 py-2.5 font-medium">Recommended</th>
                  <th className="px-5 py-2.5 text-right font-medium">Energy</th>
                  <th className="px-5 py-2.5 text-right font-medium">Current</th>
                  <th className="px-5 py-2.5 text-right font-medium">Optimised</th>
                  <th className="px-5 py-2.5 text-right font-medium">Saving</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {shiftable.map((plan) => (
                  <tr key={plan.channel}>
                    <td className="px-5 py-3">
                      <p className="font-medium text-ink-800">{plan.label}</p>
                      {plan.reason ? (
                        <p className="mt-0.5 max-w-sm text-[11px] leading-relaxed text-ink-400">
                          {plan.reason}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-5 py-3 text-ink-500 tnum">{hourWindow(plan.current_hours)}</td>
                    <td className="px-5 py-3 font-medium text-accent-700 tnum">
                      {hourWindow(plan.recommended_hours)}
                    </td>
                    <td className="px-5 py-3 text-right text-ink-600 tnum">
                      {kwh(plan.daily_energy_kwh)}
                    </td>
                    <td className="px-5 py-3 text-right text-ink-600 tnum">
                      {money(plan.current_cost, 2)}
                    </td>
                    <td className="px-5 py-3 text-right text-ink-600 tnum">
                      {money(plan.optimized_cost, 2)}
                    </td>
                    <td className="px-5 py-3 text-right font-semibold text-accent-700 tnum">
                      {money(plan.saving, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-5">
              <EmptyState
                title="Nothing worth moving"
                description="Every flexible load at this site already runs in low-cost hours."
              />
            </div>
          )}
        </div>
      </Card>

      {blocked.length ? (
        <Card>
          <CardHeader title="Not moved, and why" />
          <ul className="divide-y divide-ink-100">
            {blocked.map((plan) => (
              <li key={plan.channel} className="flex flex-wrap items-start gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-ink-800">{plan.label}</p>
                    {plan.flexibility === 'critical' ? (
                      <span className="chip bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200">
                        <Lock size={11} /> Critical load
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-ink-500">{plan.reason}</p>
                </div>
                <span className="text-sm text-ink-400 tnum">{kwh(plan.daily_energy_kwh)}/day</span>
              </li>
            ))}
          </ul>
          <SectionNote>
            Critical loads are excluded by classification, not by heuristic: they are never
            proposed for shifting or shedding regardless of cost.
          </SectionNote>
        </Card>
      ) : null}

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Load shape against the price curve"
            subtitle="Average energy by hour, coloured by tariff period"
          />
          <div className="p-5">
            {demand.data ? (
              <LoadShapeChart data={demand.data.profile} />
            ) : (
              <div className="skeleton h-[240px] w-full" />
            )}
          </div>
          {demand.data ? <SectionNote>{demand.data.note}</SectionNote> : null}
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Tariff in use"
              action={<ProvenanceBadge provenance="estimated" />}
            />
            <div className="p-5">
              <dl className="grid grid-cols-3 gap-4">
                <div>
                  <dt className="text-[11px] text-ink-400">Peak</dt>
                  <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                    {money(data.tariff.peak_rate, 2)}
                  </dd>
                  <dd className="text-[11px] text-ink-400">{hourWindow(data.tariff.peak_hours)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-ink-400">Shoulder</dt>
                  <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                    {money(data.tariff.shoulder_rate, 2)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-ink-400">Off-peak</dt>
                  <dd className="mt-0.5 text-lg font-semibold text-ink-800 tnum">
                    {money(data.tariff.offpeak_rate, 2)}
                  </dd>
                  <dd className="text-[11px] text-ink-400">
                    {hourWindow(data.tariff.offpeak_hours)}
                  </dd>
                </div>
              </dl>
              <Callout tone="neutral">{data.tariff.note}</Callout>
            </div>
          </Card>

          <Card>
            <CardHeader title="Renewable alignment" />
            <div className="p-5">
              {data.renewable.available ? (
                <>
                  {data.renewable.warning ? (
                    <Callout tone="warning">{data.renewable.warning}</Callout>
                  ) : null}
                  <ul className="mt-3 grid grid-cols-12 gap-0.5">
                    {data.renewable.hourly.map((entry) => (
                      <li
                        key={entry.hour}
                        className="h-8 rounded-sm"
                        style={{
                          background: `rgba(16,185,129,${0.12 + entry.availability * 0.75})`,
                        }}
                        title={`${hourLabel(entry.hour)} · ${num(entry.availability * 100, 0)}% availability`}
                      />
                    ))}
                  </ul>
                </>
              ) : (
                <UnavailableNote
                  title="Renewable integration ready"
                  reason={data.renewable.reason}
                />
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
