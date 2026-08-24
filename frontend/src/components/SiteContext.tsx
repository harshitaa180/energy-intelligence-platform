/**
 * Which site and which day the whole app is looking at.
 *
 * The initial value comes from `/api/demo`, so the product opens on a populated,
 * defensible dashboard rather than an empty picker.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { useLocalStorage } from '../hooks/useApi'
import { api } from '../services/api'
import { setCurrencySymbol } from '../utils/format'
import type { Demo, Site } from '../types/api'

interface SiteContextValue {
  siteId: string | null
  date: string | null
  sites: Site[]
  demo: Demo | null
  loading: boolean
  error: string | null
  setSite: (siteId: string) => void
  setDate: (date: string) => void
  currentSite: Site | null
  resetToDemo: () => void
}

const Context = createContext<SiteContextValue | null>(null)

export function SiteProvider({ children }: { children: ReactNode }) {
  const [storedSite, setStoredSite] = useLocalStorage<string | null>('ei.site', null)
  const [siteId, setSiteId] = useState<string | null>(storedSite)
  const [date, setDateState] = useState<string | null>(null)
  const [sites, setSites] = useState<Site[]>([])
  const [demo, setDemo] = useState<Demo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([api.demo(), api.sites(), api.tariff()])
      .then(([demoPayload, sitePayload, tariff]) => {
        if (cancelled) return
        setDemo(demoPayload)
        setSites(sitePayload)
        setCurrencySymbol(tariff.currency_symbol)

        const known = sitePayload.some((site) => site.site_id === storedSite)
        const initial = known && storedSite ? storedSite : demoPayload.site_id
        setSiteId(initial)
        // Open on the showcase day, not merely the newest one: at some sites the last
        // complete day falls outside the season the appliance runs in, so the newest
        // day has nothing to analyse. The date picker still offers every day.
        const match = sitePayload.find((site) => site.site_id === initial)
        setDateState(match ? (match.showcase_date ?? match.latest_date) : demoPayload.date)
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : 'Could not load sites')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // Runs once: the stored site is only an initial preference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const setSite = useCallback(
    (next: string) => {
      setSiteId(next)
      setStoredSite(next)
      // Each site has its own history, so the selected day must move with it.
      const match = sites.find((site) => site.site_id === next)
      setDateState(match ? (match.showcase_date ?? match.latest_date) : null)
    },
    [sites, setStoredSite],
  )

  const resetToDemo = useCallback(() => {
    if (!demo) return
    setSite(demo.site_id)
    setDateState(demo.date)
  }, [demo, setSite])

  const currentSite = useMemo(
    () => sites.find((site) => site.site_id === siteId) ?? null,
    [sites, siteId],
  )

  const value = useMemo<SiteContextValue>(
    () => ({
      siteId,
      date,
      sites,
      demo,
      loading,
      error,
      setSite,
      setDate: setDateState,
      currentSite,
      resetToDemo,
    }),
    [siteId, date, sites, demo, loading, error, setSite, currentSite, resetToDemo],
  )

  return <Context.Provider value={value}>{children}</Context.Provider>
}

export function useSite(): SiteContextValue {
  const context = useContext(Context)
  if (!context) throw new Error('useSite must be used inside SiteProvider')
  return context
}
