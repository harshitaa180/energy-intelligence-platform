/**
 * Types mirroring the backend's payloads.
 *
 * `Provenance` is the important one: every figure the API returns is tagged with where
 * it came from, and the UI is built to show that tag rather than hide it.
 */

export type Provenance = 'measured' | 'predicted' | 'estimated' | 'simulated' | 'unavailable'

export type DayStatus = 'normal' | 'abnormal' | 'idle' | 'not_assessable'

export type Reliability = 'good' | 'limited' | 'insufficient' | 'unavailable'

export type Flexibility = 'flexible' | 'less_flexible' | 'critical'

export type Priority = 'high' | 'medium' | 'low' | 'info'

export interface Site {
  site_id: string
  display_name: string
  location: string
  kind: 'residential' | 'industrial'
  first_reading: string
  last_reading: string
  reading_count: number
  day_count: number
  total_energy_kwh: number
  channel_count: number
  ml_appliances: string[]
  latest_date: string
  /** The most recent complete day on which an appliance could actually be assessed. */
  showcase_date: string
  last_reading_date?: string
  capabilities?: ChannelCapability[]
  available_dates?: string[]
}

export interface ChannelCapability {
  key: string
  label: string
  category: string
  flexibility: Flexibility
  has_power_signal: boolean
  has_state_signal: boolean
  has_metadata: boolean
  has_baseline: boolean
  has_classifier: boolean
  notes: string[]
}

export interface ChannelTotals {
  key: string
  label: string
  energy_kwh: number
  share_pct: number
  cost: number
  carbon_kg: number
  peak_power_w: number
  mean_power_w: number
}

export interface DayCompleteness {
  reading_count: number
  expected_readings: number
  coverage_pct: number
  complete: boolean
  note: string | null
}

export interface DayTotals {
  site_id: string
  date: string
  available: boolean
  total_energy_kwh: number
  cost: number
  carbon_kg: number
  peak_power_w: number
  mean_power_w: number
  reading_count: number
  completeness: DayCompleteness
  temperature_mean: number
  temperature_max: number
  humidity_mean: number
  channels: ChannelTotals[]
}

export interface Comparison {
  available: boolean
  baseline_kwh: number | null
  baseline_days?: number
  change_pct: number | null
}

export interface Driver {
  feature: string
  importance: number
  value: number | null
}

export interface ApplianceDay {
  available: boolean
  site_id: string
  appliance: string
  appliance_label: string
  date: string
  energy_kwh: number
  active_energy_kwh: number
  expected_energy_kwh: number | null
  deviation_kwh: number | null
  deviation_pct: number | null
  runtime_hours: number | null
  peak_power_w: number
  mean_power_w: number
  cycles: number
  short_cycles: number
  duty_cycle: number
  temperature_mean: number
  humidity_mean: number
  heat_index: number
  status: DayStatus
  inefficient: boolean | null
  probability: number | null
  reliability: Reliability
  reliability_note: string
  star_adjusted: boolean
  provenance: Provenance
  drivers: Driver[]
  explanation: string
  notes: string[]
  cost: number
  carbon_kg: number
  excess_cost: number | null
  excess_carbon_kg: number | null
  has_classifier: boolean
  model_metrics: Record<string, number | string>
  feature_importance: Record<string, number>
  metadata: ApplianceMetadata
  reason?: string
}

export interface ApplianceMetadata {
  available: boolean
  reason?: string
  appliance_type?: string
  unit_count?: number
  units?: { appliance_id: string; brand: string | null; star_rating: number | null; count: number }[]
  weighted_star_rating?: number | null
  unrated_units?: number
  note?: string | null
}

export interface AnomalyType {
  type: string
  label: string
  detail: string
}

export interface Anomaly {
  site_id: string
  appliance: string
  appliance_label: string
  date: string
  types: AnomalyType[]
  severity: 'high' | 'medium' | 'low' | 'info'
  deviation_pct: number | null
  energy_kwh: number
  expected_energy_kwh: number | null
  runtime_hours: number | null
  peak_power_w: number
  temperature_mean: number
  probability: number | null
  reliability: Reliability
  explanation: string
  excess_cost: number
}

export interface ConsumptionPoint {
  timestamp: string
  label: string
  energy_kwh: number
  cost: number
  carbon_kg: number
  peak_power_w: number
  temperature: number | null
  humidity: number | null
}

export interface Weather {
  available: boolean
  provider?: string
  location?: string
  observed_at?: string | null
  temperature_c?: number | null
  feels_like_c?: number | null
  humidity_pct?: number | null
  wind_speed_kmh?: number | null
  precipitation_mm?: number | null
  precipitation_probability_pct?: number | null
  condition?: string
  forecast?: {
    date: string
    temperature_max_c: number | null
    temperature_min_c: number | null
    precipitation_probability_pct: number | null
    condition: string | null
  }[]
  provenance?: Provenance
  reason?: string
  message?: string
  note?: string
}

export interface RecordedWeather {
  available: boolean
  date?: string
  temperature_mean_c?: number
  temperature_max_c?: number
  temperature_min_c?: number
  humidity_mean_pct?: number
  heat_index?: number
  provenance?: Provenance
  note?: string
}

export interface ForecastPoint {
  date: string
  day_label: string
  energy_kwh: number
  lower_kwh: number
  upper_kwh: number
  cost: number
  carbon_kg: number
  horizon_day: number
  change_vs_recent_pct?: number | null
}

export interface Forecast {
  site_id: string
  available: boolean
  reason?: string
  model?: string
  model_label?: string
  accuracy?: {
    mae_kwh: number
    mape_pct: number | null
    backtest_days: number
    beats_constant_baseline: boolean
    constant_baseline_mae_kwh: number
    candidates: { name: string; mae_kwh: number }[]
  }
  history_days?: number
  last_observed_date?: string
  recent_7day_mean_kwh?: number
  tomorrow?: ForecastPoint
  points: ForecastPoint[]
  recent_history?: { date: string; day_label: string; energy_kwh: number }[]
  provenance?: Provenance
  assumptions?: string[]
  warning?: string | null
}

export interface ShiftPlan {
  channel: string
  label: string
  flexibility: Flexibility
  shiftable: boolean
  reason: string | null
  current_hours: number[]
  recommended_hours: number[]
  daily_energy_kwh: number
  current_cost: number
  optimized_cost: number
  saving: number
  saving_pct: number
  renewable_aligned: boolean
}

export interface Optimization {
  site_id: string
  tariff: Tariff
  renewable: RenewableProfile
  plans: ShiftPlan[]
  totals: {
    current_cost_per_day: number
    optimized_cost_per_day: number
    saving_per_day: number
    saving_per_month: number
    saving_pct: number
  }
  constraints: { quiet_hours: number[]; critical_loads_excluded: string[] }
  provenance: Provenance
  method: string
}

export interface Tariff {
  mode: string
  currency: string
  currency_symbol: string
  flat_rate: number
  average_rate: number
  peak_rate: number
  shoulder_rate: number
  offpeak_rate: number
  peak_hours: number[]
  offpeak_hours: number[]
  schedule: { hour: number; period: string; rate: number }[]
  provenance: Provenance
  note: string
}

export interface RenewableProfile {
  available: boolean
  provenance: Provenance
  hourly: { hour: number; availability: number; generation_kw: number }[]
  reason?: string | null
  warning?: string
  capacity_kw?: number
  integration_ready: boolean
}

export interface EnergyFlow {
  site_id: string
  nodes: { id: string; label: string; available: boolean }[]
  edges: { from: string; to: string; energy_kwh: number; provenance: Provenance }[]
  solar: RenewableProfile
  battery: Record<string, unknown> & { available: boolean; reason?: string }
  ev: Record<string, unknown> & { available: boolean; reason?: string }
  status: string
  message: string
}

export interface CarbonSummary {
  site_id: string
  date: string
  emission_factor: number
  emission_factor_source: string
  unit: string
  daily: { energy_kwh: number; carbon_kg: number }
  month_to_date: { energy_kwh: number; carbon_kg: number }
  lifetime: { energy_kwh: number; carbon_kg: number; days: number }
  projected_annual_kg: number
  equivalences: { trees_year_equivalent: number; petrol_car_km_equivalent: number; note: string }
  by_channel: { key: string; label?: string; energy_kwh: number; carbon_kg: number }[]
  daily_series: { date: string; energy_kwh: number; carbon_kg: number }[]
  renewable: { available: boolean; note: string; provenance: Provenance }
  provenance: Provenance
  note: string
}

export interface ScoreComponent {
  key: string
  label: string
  score: number | null
  nominal_weight_pct: number
  effective_weight_pct: number
  formula: string
  detail: string
  available: boolean
}

export interface SustainabilityScore {
  site_id: string
  date: string
  overall: number | null
  grade: string
  components: ScoreComponent[]
  excluded_components: string[]
  provenance: Provenance
  methodology: string
  currency_symbol: string
}

export interface Recommendation {
  id: string
  priority: Priority
  title: string
  recommendation: string
  reason: string
  estimated_impact: string
  estimated_saving: number | null
  saving_period: string | null
  confidence: string
  confidence_reason: string
  appliance: string | null
  category: string
  provenance: Provenance
  actions: string[]
}

export interface Recommendations {
  site_id: string
  date: string
  currency_symbol: string
  recommendations: Recommendation[]
  total_monthly_saving: number
  count_by_priority: Record<Priority, number>
  method: string
}

export interface Insight {
  site_id: string
  date: string
  insight: string
  source: string
  llm_available: boolean
  note?: string
  deterministic_insight?: string
}

export interface Dashboard {
  site: Site
  date: string
  available_dates: string[]
  totals: DayTotals
  comparison: Comparison
  appliances: ApplianceDay[]
  anomalies: Anomaly[]
  weather: { live: Weather; recorded: RecordedWeather }
  forecast: Forecast
  optimization: Optimization
  carbon: CarbonSummary
  sustainability_score: SustainabilityScore
  recommendations: Recommendations
  insight: Insight
  energy_flow: EnergyFlow
  capabilities: ChannelCapability[]
}

export interface ModelCard {
  available: boolean
  site_id: string
  appliance: string
  appliance_label?: string
  reason?: string
  pipeline_version?: string
  trained_at?: string
  has_classifier?: boolean
  reliability?: Reliability
  reliability_note?: string
  baseline?: Record<string, unknown>
  metrics?: Record<string, number | string>
  feature_importance?: Record<string, number>
  model_features?: string[]
  limitations?: string[]
}

export interface ApplianceDetail {
  site_id: string
  appliance: string
  appliance_label: string
  date: string
  day: ApplianceDay
  model_card: ModelCard
  weather: RecordedWeather
  history: {
    date: string
    energy_kwh: number
    peak_power_w: number
    mean_power_w: number
    runtime_hours: number | null
    temperature_mean: number
    humidity_mean: number
    cost: number
  }[]
  series: {
    date: string
    energy_kwh: number
    active_energy_kwh: number
    expected_energy_kwh: number | null
    deviation_pct: number | null
    runtime_hours: number | null
    status: DayStatus
    probability: number | null
    temperature_mean: number
  }[]
  notes: string[]
  recommendations: Recommendation[]
  replacement: Replacement
}

export interface Replacement {
  site_id: string
  appliance: string
  available: boolean
  recommended?: boolean
  reason?: string
  current?: {
    weighted_star_rating: number
    measured_days: number
    annual_kwh: number
    annual_cost: number
    annual_carbon_kg: number
    units: { appliance_id: string; brand: string | null; star_rating: number | null; count: number }[]
  }
  replacement?: {
    target_star_rating: number
    assumed_energy_reduction_pct: number
    projected_annual_kwh: number
    projected_annual_cost: number
    replacement_cost: number | null
  }
  savings?: { annual_kwh: number; annual_cost: number; annual_carbon_kg: number }
  payback_years: number | null
  payback_note?: string
  provenance: Provenance
  assumptions?: string[]
}

export interface AssistantStatus {
  configured: boolean
  provider: string
  model: string | null
  reason: string | null
  suggested_prompts: string[]
}

export interface AssistantAnswer {
  site_id: string
  question: string
  answer: string
  source: string
  model?: string
  llm_available: boolean
  note?: string
  grounding_note?: string
  context_included: string[]
}

export interface DemandResponse {
  site_id: string
  tariff_mode: string
  profile: { hour: number; mean_energy_kwh: number; rate: number; period: string; cost: number }[]
  peak_share_pct: number
  peak_cost_share_pct: number
  peak_energy_kwh: number
  total_energy_kwh: number
  peak_hours: number[]
  shiftable_loads: ShiftPlan[]
  opportunity: Optimization['totals']
  provenance: Provenance
  note: string
}

export interface Health {
  status: 'ok' | 'degraded'
  app: string
  environment: string
  data: {
    sites: string[]
    readings: number
    interval_hours: number
    total_energy_kwh: number
    demo_site_id: string
    validation: Record<string, unknown>
  }
  model_registry: Record<string, unknown>
  services: Record<string, unknown> & { llm: AssistantStatus }
}

export interface Demo {
  site_id: string
  date: string
  reason: string
  sites: { site_id: string; display_name: string; location: string; kind: string; days: number; ml_appliances: string[] }[]
}
