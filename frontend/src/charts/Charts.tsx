/**
 * The chart library for this app.
 *
 * Rules applied throughout, from the visualisation guidance:
 *
 * - **One axis, ever.** Where two measures of different scale matter (energy and
 *   temperature, say), they are two charts or a tooltip field -- never a second y-axis.
 * - **Fixed categorical order**, never cycled; past six categories the tail folds into
 *   "Other".
 * - **A legend whenever there are two or more series**, so identity is never carried by
 *   colour alone, plus a tooltip on every chart.
 * - **Recessive chrome**: hairline horizontal grid, no vertical rules, muted ticks.
 */

import type { ReactNode } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AXIS_PROPS, CHROME, GRID_PROPS, MAX_SERIES, SERIES, STATUS, TARIFF_PERIOD_COLOR, TARIFF_PERIOD_LABEL } from './theme'
import { hourLabel, kwh, money, num, shortDate } from '../utils/format'

// --- tooltip ---------------------------------------------------------------

interface TooltipRow {
  label: string
  value: string
  color?: string
}

function TooltipShell({ title, rows, footer }: { title: string; rows: TooltipRow[]; footer?: ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-200 bg-white/97 px-3 py-2.5 shadow-lift backdrop-blur">
      <p className="text-xs font-semibold text-ink-800">{title}</p>
      <ul className="mt-1.5 space-y-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 text-xs">
            {row.color ? (
              <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: row.color }} />
            ) : null}
            <span className="text-ink-500">{row.label}</span>
            <span className="ml-auto font-medium text-ink-800 tnum">{row.value}</span>
          </li>
        ))}
      </ul>
      {footer ? <div className="mt-2 border-t border-ink-100 pt-1.5 text-[11px] text-ink-400">{footer}</div> : null}
    </div>
  )
}

// --- legend ----------------------------------------------------------------

export function ChartLegend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink-600">
          <span
            className="h-0.5 w-4 rounded-full"
            style={
              item.dashed
                ? { backgroundImage: `repeating-linear-gradient(90deg, ${item.color} 0 4px, transparent 4px 7px)` }
                : { background: item.color }
            }
          />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

// --- consumption over time -------------------------------------------------

export interface ConsumptionDatum {
  label: string
  energy_kwh: number
  cost: number
  carbon_kg: number
  temperature?: number | null
}

export function ConsumptionChart({
  data,
  height = 260,
  metric = 'energy_kwh',
}: {
  data: ConsumptionDatum[]
  height?: number
  metric?: 'energy_kwh' | 'cost' | 'carbon_kg'
}) {
  const unit = metric === 'energy_kwh' ? 'kWh' : metric === 'cost' ? '' : 'kg'
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="consumptionFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES[0]} stopOpacity={0.22} />
            <stop offset="100%" stopColor={SERIES[0]} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID_PROPS} />
        <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={24} />
        <YAxis {...AXIS_PROPS} width={70} unit={unit ? ` ${unit}` : undefined} />
        <Tooltip
          cursor={{ stroke: CHROME.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const datum = payload[0].payload as ConsumptionDatum
            return (
              <TooltipShell
                title={String(label)}
                rows={[
                  { label: 'Energy', value: kwh(datum.energy_kwh), color: SERIES[0] },
                  { label: 'Cost', value: money(datum.cost, 2) },
                  { label: 'Carbon', value: `${num(datum.carbon_kg, 2)} kg` },
                  ...(datum.temperature !== null && datum.temperature !== undefined
                    ? [{ label: 'Temperature', value: `${num(datum.temperature)} C` }]
                    : []),
                ]}
                footer="Energy measured · cost and carbon estimated"
              />
            )
          }}
        />
        <Area
          type="monotone"
          dataKey={metric}
          stroke={SERIES[0]}
          strokeWidth={2}
          fill="url(#consumptionFill)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// --- actual vs expected ----------------------------------------------------

export interface ActualExpectedDatum {
  date: string
  active_energy_kwh: number
  expected_energy_kwh: number | null
  status: string
  deviation_pct: number | null
  temperature_mean: number
}

export function ActualVsExpectedChart({ data, height = 280 }: { data: ActualExpectedDatum[]; height?: number }) {
  const shaped = data.map((entry) => ({ ...entry, label: shortDate(entry.date) }))
  return (
    <div>
      <ChartLegend
        items={[
          { label: 'Actual', color: SERIES[0] },
          { label: 'Expected for this runtime and weather', color: SERIES[1], dashed: true },
        ]}
      />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={shaped} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={24} />
          <YAxis {...AXIS_PROPS} width={70} unit=" kWh" />
          <Tooltip
            cursor={{ stroke: CHROME.axis, strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const datum = payload[0].payload as ActualExpectedDatum & { label: string }
              return (
                <TooltipShell
                  title={datum.label}
                  rows={[
                    { label: 'Actual', value: kwh(datum.active_energy_kwh), color: SERIES[0] },
                    {
                      label: 'Expected',
                      value: datum.expected_energy_kwh === null ? 'not comparable' : kwh(datum.expected_energy_kwh),
                      color: SERIES[1],
                    },
                    {
                      label: 'Deviation',
                      value:
                        datum.deviation_pct === null
                          ? '--'
                          : `${datum.deviation_pct >= 0 ? '+' : ''}${num(datum.deviation_pct)}%`,
                    },
                    { label: 'Temperature', value: `${num(datum.temperature_mean)} C` },
                  ]}
                  footer={datum.status === 'abnormal' ? 'Flagged above expectation' : undefined}
                />
              )
            }}
          />
          <Bar dataKey="active_energy_kwh" radius={[4, 4, 0, 0]} maxBarSize={22}>
            {shaped.map((entry, index) => (
              <Cell
                key={index}
                fill={entry.status === 'abnormal' ? STATUS.critical : SERIES[0]}
                fillOpacity={entry.status === 'idle' ? 0.25 : 1}
              />
            ))}
          </Bar>
          <Line
            type="monotone"
            dataKey="expected_energy_kwh"
            stroke={SERIES[1]}
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[11px] text-ink-400">
        Bars in red exceeded the weather-adjusted expectation. Faded bars are days the appliance
        did not run.
      </p>
    </div>
  )
}

// --- appliance breakdown ---------------------------------------------------

export interface BreakdownDatum {
  key: string
  label: string
  /** The plotted magnitude. Named for the common case, but the unit is a prop. */
  energy_kwh: number
  share_pct: number
}

/** Past MAX_SERIES categories the tail folds into "Other" rather than cycling hues. */
export function foldToOther(items: BreakdownDatum[]): BreakdownDatum[] {
  if (items.length <= MAX_SERIES) return items
  const head = items.slice(0, MAX_SERIES - 1)
  const tail = items.slice(MAX_SERIES - 1)
  return [
    ...head,
    {
      key: '__other__',
      label: `Other (${tail.length})`,
      energy_kwh: tail.reduce((sum, entry) => sum + entry.energy_kwh, 0),
      share_pct: tail.reduce((sum, entry) => sum + entry.share_pct, 0),
    },
  ]
}

export function BreakdownChart({
  data,
  height = 220,
  unit = 'kWh',
  valueLabel = 'Energy',
}: {
  data: BreakdownDatum[]
  height?: number
  unit?: string
  valueLabel?: string
}) {
  const shaped = foldToOther([...data].sort((a, b) => b.energy_kwh - a.energy_kwh))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={shaped} layout="vertical" margin={{ top: 4, right: 56, left: 4, bottom: 4 }}>
        <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
        <XAxis type="number" {...AXIS_PROPS} unit={` ${unit}`} />
        <YAxis type="category" dataKey="label" {...AXIS_PROPS} width={150} />
        <Tooltip
          cursor={{ fill: 'rgba(15,23,42,0.04)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const datum = payload[0].payload as BreakdownDatum
            return (
              <TooltipShell
                title={datum.label}
                rows={[
                  { label: valueLabel, value: `${num(datum.energy_kwh, 2)} ${unit}` },
                  { label: 'Share of total', value: `${num(datum.share_pct)}%` },
                ]}
              />
            )
          }}
        />
        <Bar dataKey="energy_kwh" radius={[0, 4, 4, 0]} maxBarSize={20}>
          {shaped.map((entry, index) => (
            <Cell key={entry.key} fill={entry.key === '__other__' ? CHROME.axis : SERIES[index % SERIES.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- forecast --------------------------------------------------------------

export interface ForecastDatum {
  label: string
  actual?: number | null
  forecast?: number | null
  lower?: number | null
  band?: number | null
  isForecast: boolean
}

export function ForecastChart({ data, height = 300 }: { data: ForecastDatum[]; height?: number }) {
  const firstForecast = data.findIndex((entry) => entry.isForecast)
  return (
    <div>
      <ChartLegend
        items={[
          { label: 'Measured history', color: SERIES[0] },
          { label: 'Forecast', color: SERIES[1], dashed: true },
          { label: 'Uncertainty band (model error)', color: '#c9d9ef' },
        ]}
      />
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={18} />
          <YAxis {...AXIS_PROPS} width={70} unit=" kWh" />
          {firstForecast > 0 ? (
            <>
              <ReferenceArea
                x1={data[firstForecast].label}
                x2={data[data.length - 1].label}
                fill="#f8fafc"
                fillOpacity={1}
              />
              <ReferenceLine x={data[firstForecast].label} stroke={CHROME.axis} strokeDasharray="3 3" />
            </>
          ) : null}
          <Tooltip
            cursor={{ stroke: CHROME.axis, strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const datum = payload[0].payload as ForecastDatum
              return (
                <TooltipShell
                  title={String(label)}
                  rows={
                    datum.isForecast
                      ? [
                          { label: 'Forecast', value: kwh(datum.forecast ?? 0), color: SERIES[1] },
                          {
                            label: 'Range',
                            value: `${num(datum.lower ?? 0, 2)} - ${num((datum.lower ?? 0) + (datum.band ?? 0), 2)} kWh`,
                          },
                        ]
                      : [{ label: 'Measured', value: kwh(datum.actual ?? 0), color: SERIES[0] }]
                  }
                  footer={datum.isForecast ? 'Predicted · band is the model’s measured error' : 'Measured'}
                />
              )
            }}
          />
          {/* The band is drawn as an invisible base plus a visible span, so it sits
              exactly between lower and upper without needing a second axis. */}
          <Area dataKey="lower" stackId="band" stroke="none" fill="transparent" isAnimationActive={false} />
          <Area dataKey="band" stackId="band" stroke="none" fill="#c9d9ef" fillOpacity={0.55} isAnimationActive={false} />
          <Line type="monotone" dataKey="actual" stroke={SERIES[0]} strokeWidth={2} dot={false} connectNulls />
          <Line
            type="monotone"
            dataKey="forecast"
            stroke={SERIES[1]}
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={{ r: 3, fill: SERIES[1], strokeWidth: 0 }}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- load shape against tariff --------------------------------------------

export interface ProfileDatum {
  hour: number
  mean_energy_kwh: number
  rate: number
  period: string
  cost: number
}

export function LoadShapeChart({ data, height = 240 }: { data: ProfileDatum[]; height?: number }) {
  const periods = Array.from(new Set(data.map((entry) => entry.period)))
  return (
    <div>
      <ChartLegend
        items={periods.map((period) => ({
          label: TARIFF_PERIOD_LABEL[period] ?? period,
          color: TARIFF_PERIOD_COLOR[period] ?? SERIES[0],
        }))}
      />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 12, right: 12, left: 8, bottom: 0 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="hour" {...AXIS_PROPS} tickFormatter={(value) => hourLabel(Number(value))} minTickGap={16} />
          {/* Fractional kWh labels need more room than the default axis width. */}
          <YAxis {...AXIS_PROPS} width={70} unit=" kWh" />
          <Tooltip
            cursor={{ fill: 'rgba(15,23,42,0.04)' }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const datum = payload[0].payload as ProfileDatum
              return (
                <TooltipShell
                  title={hourLabel(datum.hour)}
                  rows={[
                    { label: 'Average energy', value: kwh(datum.mean_energy_kwh, 3) },
                    { label: 'Tariff', value: `${money(datum.rate, 2)} / kWh` },
                    { label: 'Period', value: TARIFF_PERIOD_LABEL[datum.period] ?? datum.period },
                    { label: 'Cost', value: money(datum.cost, 2) },
                  ]}
                  footer="Energy measured · tariff configured"
                />
              )
            }}
          />
          <Bar dataKey="mean_energy_kwh" radius={[4, 4, 0, 0]} maxBarSize={18}>
            {data.map((entry) => (
              <Cell key={entry.hour} fill={TARIFF_PERIOD_COLOR[entry.period] ?? SERIES[0]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- current vs optimised schedule ----------------------------------------

export interface ScheduleDatum {
  label: string
  current_cost: number
  optimized_cost: number
}

export function ScheduleComparisonChart({ data, height = 240 }: { data: ScheduleDatum[]; height?: number }) {
  return (
    <div>
      <ChartLegend
        items={[
          { label: 'Current schedule', color: SERIES[1] },
          { label: 'Optimised schedule', color: SERIES[2] },
        ]}
      />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 0 }} barGap={4} barCategoryGap="35%">
          <CartesianGrid {...GRID_PROPS} />
          <XAxis dataKey="label" {...AXIS_PROPS} />
          <YAxis {...AXIS_PROPS} width={64} />
          <Tooltip
            cursor={{ fill: 'rgba(15,23,42,0.04)' }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const datum = payload[0].payload as ScheduleDatum
              return (
                <TooltipShell
                  title={String(label)}
                  rows={[
                    { label: 'Current', value: money(datum.current_cost, 2), color: SERIES[1] },
                    { label: 'Optimised', value: money(datum.optimized_cost, 2), color: SERIES[2] },
                    { label: 'Saving', value: money(datum.current_cost - datum.optimized_cost, 2) },
                  ]}
                  footer="Estimated from measured energy and the configured tariff"
                />
              )
            }}
          />
          <Bar dataKey="current_cost" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={26} />
          <Bar dataKey="optimized_cost" fill={SERIES[2]} radius={[4, 4, 0, 0]} maxBarSize={26} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// --- carbon ----------------------------------------------------------------

export function CarbonChart({
  data,
  height = 260,
}: {
  data: { date: string; carbon_kg: number; energy_kwh: number }[]
  height?: number
}) {
  const shaped = data.map((entry) => ({ ...entry, label: shortDate(entry.date) }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={shaped} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="carbonFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SERIES[2]} stopOpacity={0.22} />
            <stop offset="100%" stopColor={SERIES[2]} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID_PROPS} />
        <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={24} />
        <YAxis {...AXIS_PROPS} width={64} unit=" kg" />
        <Tooltip
          cursor={{ stroke: CHROME.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const datum = payload[0].payload as { carbon_kg: number; energy_kwh: number }
            return (
              <TooltipShell
                title={String(label)}
                rows={[
                  { label: 'Carbon', value: `${num(datum.carbon_kg, 2)} kg CO2e`, color: SERIES[2] },
                  { label: 'Energy', value: kwh(datum.energy_kwh) },
                ]}
                footer="Estimated: energy x configured grid emission factor"
              />
            )
          }}
        />
        <Area
          type="monotone"
          dataKey="carbon_kg"
          stroke={SERIES[2]}
          strokeWidth={2}
          fill="url(#carbonFill)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

// --- feature importance ----------------------------------------------------

export function ImportanceChart({
  data,
  height = 200,
}: {
  data: { feature: string; importance: number }[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 4 }}>
        <CartesianGrid {...GRID_PROPS} horizontal={false} vertical />
        <XAxis type="number" {...AXIS_PROPS} />
        <YAxis type="category" dataKey="feature" {...AXIS_PROPS} width={150} />
        <Tooltip
          cursor={{ fill: 'rgba(15,23,42,0.04)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const datum = payload[0].payload as { feature: string; importance: number }
            return (
              <TooltipShell
                title={datum.feature}
                rows={[{ label: 'Importance', value: num(datum.importance * 100, 1) + '%' }]}
                footer="Model-wide importance, not a per-day attribution"
              />
            )
          }}
        />
        <Bar dataKey="importance" fill={SERIES[0]} radius={[0, 4, 4, 0]} maxBarSize={16} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- runtime ---------------------------------------------------------------

export function RuntimeChart({
  data,
  height = 200,
}: {
  data: { date: string; runtime_hours: number | null }[]
  height?: number
}) {
  const shaped = data.map((entry) => ({ ...entry, label: shortDate(entry.date) }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={shaped} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid {...GRID_PROPS} />
        <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={24} />
        <YAxis {...AXIS_PROPS} width={44} unit=" h" />
        <Tooltip
          cursor={{ stroke: CHROME.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const datum = payload[0].payload as { runtime_hours: number | null }
            return (
              <TooltipShell
                title={String(label)}
                rows={[
                  {
                    label: 'Runtime',
                    value: datum.runtime_hours === null ? 'unknown' : `${num(datum.runtime_hours)} h`,
                    color: SERIES[3],
                  },
                ]}
              />
            )
          }}
        />
        <Line
          type="monotone"
          dataKey="runtime_hours"
          stroke={SERIES[3]}
          strokeWidth={2}
          dot={false}
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export { Legend }
