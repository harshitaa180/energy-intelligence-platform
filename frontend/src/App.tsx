import { Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { SiteProvider, useSite } from './components/SiteContext'
import { CardSkeleton, ErrorState } from './components/primitives'
import { AppliancesPage } from './pages/AppliancesPage'
import { ApplianceDetailPage } from './pages/ApplianceDetailPage'
import { AssistantPage } from './pages/AssistantPage'
import { CarbonPage } from './pages/CarbonPage'
import { DashboardPage } from './pages/DashboardPage'
import { ForecastPage } from './pages/ForecastPage'
import { InsightsPage } from './pages/InsightsPage'
import { OptimizationPage } from './pages/OptimizationPage'

export function App() {
  return (
    <SiteProvider>
      <Boot>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="appliances" element={<AppliancesPage />} />
            <Route path="appliances/:appliance" element={<ApplianceDetailPage />} />
            <Route path="insights" element={<InsightsPage />} />
            <Route path="forecast" element={<ForecastPage />} />
            <Route path="optimization" element={<OptimizationPage />} />
            <Route path="carbon" element={<CarbonPage />} />
            <Route path="assistant" element={<AssistantPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </Boot>
    </SiteProvider>
  )
}

/** Nothing renders until a site is selected, so no page has to handle a null site. */
function Boot({ children }: { children: React.ReactNode }) {
  const { loading, error, siteId } = useSite()

  if (error) {
    return (
      <div className="mx-auto max-w-2xl p-10">
        <ErrorState message={error} onRetry={() => window.location.reload()} />
        <p className="mt-4 text-center text-sm text-ink-500">
          Start the backend with <code className="rounded bg-ink-100 px-1.5 py-0.5">uvicorn backend.main:app</code>
        </p>
      </div>
    )
  }

  if (loading || !siteId) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-10">
        <div className="skeleton h-10 w-64" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <CardSkeleton key={index} lines={1} />
          ))}
        </div>
        <div className="skeleton h-80 w-full rounded-2xl" />
      </div>
    )
  }

  return <>{children}</>
}
