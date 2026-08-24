/**
 * The single place the frontend talks to the backend.
 *
 * Vite proxies /api to the FastAPI server in development. No provider key is ever held
 * here -- weather and LLM calls happen server-side.
 */

import type {
  ApplianceDetail,
  AssistantAnswer,
  AssistantStatus,
  CarbonSummary,
  ConsumptionPoint,
  Dashboard,
  DemandResponse,
  Demo,
  Forecast,
  Health,
  Optimization,
  Recommendations,
  Replacement,
  Site,
  SustainabilityScore,
  Tariff,
  Weather,
} from '../types/api'

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError('Cannot reach the API. Is the backend running on port 8000?', 0)
  }

  if (!response.ok) {
    let detail: unknown
    let message = `Request failed (${response.status})`
    try {
      const body = await response.json()
      detail = body.detail ?? body
      if (detail && typeof detail === 'object' && 'message' in detail) {
        message = String((detail as { message: unknown }).message)
      } else if (typeof body.message === 'string') {
        message = body.message
      }
    } catch {
      /* body was not JSON; keep the status-based message */
    }
    throw new ApiError(message, response.status, detail)
  }

  return response.json() as Promise<T>
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const serialised = search.toString()
  return serialised ? `?${serialised}` : ''
}

export interface HourlyProfilePoint {
  hour: number
  mean_energy_kwh: number
  rate: number
  period: string
  cost: number
}

export const api = {
  health: () => request<Health>('/health'),
  demo: () => request<Demo>('/demo'),

  sites: () => request<Site[]>('/houses'),
  site: (siteId: string) => request<Site>(`/houses/${siteId}`),
  dashboard: (siteId: string, date?: string) =>
    request<Dashboard>(`/houses/${siteId}/dashboard${query({ date })}`),

  consumption: (
    siteId: string,
    granularity: string,
    options: { start?: string; end?: string; channel?: string } = {},
  ) =>
    request<{ points: ConsumptionPoint[]; granularity: string }>(
      `/houses/${siteId}/consumption${query({ granularity, ...options })}`,
    ),

  hourlyProfile: (siteId: string, channel?: string) =>
    request<{ hours: HourlyProfilePoint[] }>(`/houses/${siteId}/profile${query({ channel })}`),

  applianceDetail: (siteId: string, appliance: string, date?: string) =>
    request<ApplianceDetail>(`/appliances/${siteId}/${appliance}/analysis${query({ date })}`),

  replacement: (body: {
    site_id: string
    appliance: string
    target_star_rating?: number
    replacement_cost?: number
  }) =>
    request<Replacement>('/appliances/replacement', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  anomalies: (siteId: string, limit = 20) =>
    request<{
      count: number
      anomalies: Dashboard['anomalies']
      types_detected: string[]
      note: string
    }>(`/anomalies/${siteId}${query({ limit })}`),

  score: (siteId: string, date?: string) =>
    request<SustainabilityScore>(`/score/${siteId}${query({ date })}`),

  weather: (siteId: string) => request<Weather>(`/weather${query({ site_id: siteId })}`),

  forecast: (siteId: string, days = 7) =>
    request<Forecast>(`/forecast${query({ site_id: siteId, days })}`),

  optimization: (siteId: string, quietHours?: number[]) =>
    quietHours
      ? request<Optimization>('/optimization', {
          method: 'POST',
          body: JSON.stringify({ site_id: siteId, quiet_hours: quietHours }),
        })
      : request<Optimization>(`/optimization${query({ site_id: siteId })}`),

  demandResponse: (siteId: string) =>
    request<DemandResponse>(`/demand-response${query({ site_id: siteId })}`),

  tariff: () => request<Tariff>('/tariff'),

  renewable: (siteId: string) =>
    request<Dashboard['energy_flow']>(`/renewable${query({ site_id: siteId })}`),

  recommendations: (siteId: string, date?: string) =>
    request<Recommendations>(`/recommendations${query({ site_id: siteId, date })}`),

  carbon: (siteId: string, date?: string) =>
    request<CarbonSummary>(`/carbon${query({ site_id: siteId, date })}`),

  assistantStatus: () => request<AssistantStatus>('/assistant/status'),

  ask: (body: {
    site_id: string
    question: string
    date?: string
    history?: { role: 'user' | 'assistant'; content: string }[]
  }) => request<AssistantAnswer>('/assistant', { method: 'POST', body: JSON.stringify(body) }),

  insight: (siteId: string, date?: string) =>
    request<Dashboard['insight']>(`/assistant/insight${query({ site_id: siteId, date })}`),
}
