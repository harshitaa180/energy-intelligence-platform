/** Appliance intelligence: every channel at the site, ranked and assessed. */

import { Link } from 'react-router-dom'
import { ArrowRight, Info, Plug } from 'lucide-react'

import { BreakdownChart } from '../charts/Charts'
import {
  Card,
  CardHeader,
  CardSkeleton,
  EmptyState,
  ErrorState,
  PageHeader,
  ProvenanceBadge,
  ReliabilityChip,
  StatusChip,
  UnavailableNote,
} from '../components/primitives'
import { useSite } from '../components/SiteContext'
import { useAsync } from '../hooks/useApi'
import { api } from '../services/api'
import { dateLabel, kwh, money, num, signedPct, titleCase } from '../utils/format'

const FLEXIBILITY_LABEL: Record<string, string> = {
  flexible: 'Flexible',
  less_flexible: 'Partly flexible',
  critical: 'Critical — never shifted',
}

const FLEXIBILITY_STYLE: Record<string, string> = {
  flexible: 'bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200',
  less_flexible: 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200',
  critical: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
}

export function AppliancesPage() {
  const { siteId, date, currentSite } = useSite()
  const { data, loading, error, reload } = useAsync(
    () => api.dashboard(siteId as string, date ?? undefined),
    [siteId, date],
  )

  if (!siteId) return <CardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading || !data) return <CardSkeleton lines={6} />

  const analysedByKey = new Map(data.appliances.map((entry) => [entry.appliance, entry]))

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Appliance intelligence"
        title={currentSite?.display_name ?? 'Appliances'}
        description={`${dateLabel(data.date)} · ${data.capabilities.length} metered channels. Consumption is measured; expected energy comes from the model trained on this appliance's own history.`}
      />

      <div className="grid items-start gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Consumption ranking" subtitle="Share of the day's energy" />
          <div className="p-5">
            {data.totals.channels.length ? (
              <BreakdownChart data={data.totals.channels} height={Math.max(200, data.totals.channels.length * 34)} />
            ) : (
              <EmptyState title="No consumption recorded on this day" />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="What this site supports" icon={<Info size={14} />} />
          <ul className="divide-y divide-ink-100">
            {data.capabilities.map((capability) => (
              <li key={capability.key} className="px-5 py-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-ink-800">{capability.label}</p>
                  <span className={`chip ${FLEXIBILITY_STYLE[capability.flexibility]}`}>
                    {FLEXIBILITY_LABEL[capability.flexibility]}
                  </span>
                </div>
                <ul className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                  <Flag on={capability.has_power_signal} label="Power" />
                  <Flag on={capability.has_state_signal} label="On/off state" />
                  <Flag on={capability.has_metadata} label="Metadata" />
                  <Flag on={capability.has_baseline} label="Expected-energy baseline" />
                  <Flag on={capability.has_classifier} label="Classifier" />
                </ul>
                {capability.notes.map((note) => (
                  <p key={note} className="mt-1.5 text-[11px] leading-relaxed text-ink-400">
                    {note}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {data.totals.channels.map((channel) => {
          const analysed = analysedByKey.get(channel.key)
          const capability = data.capabilities.find((entry) => entry.key === channel.key)
          return (
            <Card key={channel.key} hover className="flex flex-col">
              <div className="flex items-start justify-between gap-3 p-5 pb-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-ink-900">{channel.label}</p>
                  <p className="mt-0.5 text-xs text-ink-400">
                    {titleCase(capability?.category ?? '')}
                  </p>
                </div>
                {analysed ? (
                  <StatusChip status={analysed.status} />
                ) : (
                  <ProvenanceBadge provenance="measured" />
                )}
              </div>

              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-5 pb-4">
                <Stat label="Consumption" value={kwh(channel.energy_kwh)} />
                <Stat
                  label="Expected"
                  value={
                    analysed?.expected_energy_kwh !== null && analysed?.expected_energy_kwh !== undefined
                      ? kwh(analysed.expected_energy_kwh)
                      : '--'
                  }
                />
                <Stat
                  label="Deviation"
                  value={analysed?.deviation_pct !== null && analysed?.deviation_pct !== undefined ? signedPct(analysed.deviation_pct) : '--'}
                  tone={
                    analysed?.deviation_pct !== null && analysed?.deviation_pct !== undefined
                      ? analysed.deviation_pct > 10
                        ? 'bad'
                        : analysed.deviation_pct < -10
                          ? 'good'
                          : 'neutral'
                      : 'neutral'
                  }
                />
                <Stat
                  label="Runtime"
                  value={
                    analysed?.runtime_hours !== null && analysed?.runtime_hours !== undefined
                      ? `${num(analysed.runtime_hours)} h`
                      : '--'
                  }
                />
                <Stat label="Share of total" value={`${num(channel.share_pct)}%`} />
                <Stat label="Peak power" value={`${num(channel.peak_power_w, 0)} W`} />
                <Stat label="Cost" value={money(channel.cost, 2)} muted />
                <Stat label="Carbon" value={`${num(channel.carbon_kg, 2)} kg`} muted />
              </dl>

              {analysed?.metadata?.available ? (
                <div className="mx-5 mb-4 rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-600">
                  {analysed.metadata.unit_count} unit(s)
                  {analysed.metadata.weighted_star_rating
                    ? ` · ${num(analysed.metadata.weighted_star_rating)}-star weighted`
                    : ''}
                  {analysed.metadata.unrated_units
                    ? ` · ${analysed.metadata.unrated_units} unrated`
                    : ''}
                </div>
              ) : null}

              <div className="mt-auto flex items-center gap-2 border-t border-ink-100 px-5 py-3">
                {analysed ? (
                  <ReliabilityChip
                    reliability={analysed.reliability}
                    note={analysed.reliability_note}
                  />
                ) : (
                  <span className="text-xs text-ink-400">Consumption only</span>
                )}
                <Link
                  to={`/appliances/${channel.key}`}
                  className="btn-ghost ml-auto py-1 text-sm"
                >
                  Detail <ArrowRight size={14} />
                </Link>
              </div>
            </Card>
          )
        })}
      </div>

      {!data.appliances.length ? (
        <UnavailableNote
          title="No appliance at this site can be assessed against a baseline"
          reason={data.capabilities.flatMap((entry) => entry.notes)[0]}
        />
      ) : null}

      {!data.totals.channels.length ? (
        <EmptyState
          icon={<Plug size={24} />}
          title="No metered channels"
          description="This site has no channel carrying a power or state signal."
        />
      ) : null}
    </div>
  )
}

function Flag({ on, label }: { on: boolean; label: string }) {
  return (
    <li
      className={`chip px-2 py-0.5 ${
        on ? 'bg-accent-50 text-accent-800' : 'bg-ink-100 text-ink-400 line-through'
      }`}
    >
      {label}
    </li>
  )
}

function Stat({
  label,
  value,
  tone = 'neutral',
  muted = false,
}: {
  label: string
  value: string
  tone?: 'good' | 'bad' | 'neutral'
  muted?: boolean
}) {
  const toneClass =
    tone === 'bad' ? 'text-rose-600' : tone === 'good' ? 'text-accent-700' : muted ? 'text-ink-500' : 'text-ink-800'
  return (
    <div>
      <dt className="text-[11px] text-ink-400">{label}</dt>
      <dd className={`mt-0.5 text-sm font-semibold tnum ${toneClass}`}>{value}</dd>
    </div>
  )
}
