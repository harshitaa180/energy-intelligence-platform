/** Application shell: navigation, site and date pickers, and the health strip. */

import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  Activity,
  Bot,
  CalendarDays,
  CloudSun,
  Gauge,
  Leaf,
  LayoutDashboard,
  Lightbulb,
  Plug,
  Settings2,
  TrendingUp,
} from 'lucide-react'

import { api } from '../services/api'
import type { Health } from '../types/api'
import { useSite } from './SiteContext'
import { dateLabel } from '../utils/format'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/appliances', label: 'Appliances', icon: Plug, end: false },
  { to: '/insights', label: 'AI Insights', icon: Lightbulb, end: false },
  { to: '/forecast', label: 'Forecast', icon: TrendingUp, end: false },
  { to: '/optimization', label: 'Optimization', icon: Settings2, end: false },
  { to: '/carbon', label: 'Carbon', icon: Leaf, end: false },
  { to: '/assistant', label: 'Assistant', icon: Bot, end: false },
]

export function Layout() {
  const { sites, siteId, setSite, date, setDate, currentSite, demo, resetToDemo } = useSite()
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-200/80 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink-900 text-white">
              <Activity size={17} />
            </span>
            <div className="leading-tight">
              <p className="text-sm font-semibold tracking-tight text-ink-900">Energy Intelligence</p>
              <p className="text-[11px] text-ink-400">
                {currentSite ? `${currentSite.display_name} · ${currentSite.kind}` : 'Loading site'}
              </p>
            </div>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="site-select">
              Site
            </label>
            <div className="relative">
              <Gauge
                size={14}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400"
              />
              <select
                id="site-select"
                className="field appearance-none py-1.5 pl-8 pr-8 text-sm"
                value={siteId ?? ''}
                onChange={(event) => setSite(event.target.value)}
              >
                {sites.map((site) => (
                  <option key={site.site_id} value={site.site_id}>
                    {site.display_name} ({site.day_count}d)
                  </option>
                ))}
              </select>
            </div>

            <label className="sr-only" htmlFor="date-select">
              Date
            </label>
            <div className="relative">
              <CalendarDays
                size={14}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400"
              />
              <select
                id="date-select"
                className="field appearance-none py-1.5 pl-8 pr-8 text-sm"
                value={date ?? ''}
                onChange={(event) => setDate(event.target.value)}
              >
                {(currentSite?.available_dates ?? (date ? [date] : [])).map((value) => (
                  <option key={value} value={value}>
                    {dateLabel(value)}
                  </option>
                ))}
              </select>
            </div>

            {demo && siteId !== demo.site_id ? (
              <button type="button" className="btn-secondary py-1.5" onClick={resetToDemo}>
                Load demo
              </button>
            ) : null}
          </div>
        </div>

        <nav className="mx-auto max-w-[1400px] px-3">
          <ul className="flex gap-1 overflow-x-auto pb-1">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `flex items-center gap-2 whitespace-nowrap rounded-t-lg border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
                      isActive
                        ? 'border-accent-600 text-ink-900'
                        : 'border-transparent text-ink-500 hover:border-ink-200 hover:text-ink-800'
                    }`
                  }
                >
                  <Icon size={15} />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-[1400px] flex-1 px-5 py-7">
        <Outlet />
      </main>

      <footer className="border-t border-ink-200/80 bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-5 gap-y-1.5 px-5 py-3 text-xs text-ink-400">
          <span className="flex items-center gap-1.5">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health?.status === 'ok' ? 'bg-accent-500' : 'bg-amber-500'
              }`}
            />
            API {health?.status ?? 'connecting'}
          </span>
          {health ? (
            <>
              <span>{health.data.readings.toLocaleString()} readings</span>
              <span>{health.data.sites.length} sites</span>
              <span>{String(health.model_registry.pairs_with_classifier)} trained models</span>
              <span className="flex items-center gap-1.5">
                <CloudSun size={12} />
                {String(health.services.weather_provider)}
              </span>
              <span>
                AI assistant: {health.services.llm.configured ? health.services.llm.provider : 'not configured'}
              </span>
            </>
          ) : null}
          <span className="ml-auto">
            Every figure is labelled measured, predicted, estimated, simulated or unavailable.
          </span>
        </div>
      </footer>
    </div>
  )
}
