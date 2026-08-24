/**
 * Chart palette and chrome.
 *
 * The categorical order is fixed and never cycled: series N always gets slot N, so a
 * filter that changes how many series are on screen cannot repaint the survivors. The
 * order below is validated for colour-vision deficiency separation against this app's
 * white chart surface (worst adjacent CVD dE 9.1, worst normal-vision dE 19.6).
 *
 * Three slots fall below 3:1 contrast on white, so every chart using them also carries
 * a legend and either direct labels or a value list beside it -- colour never carries
 * meaning on its own here.
 */

export const SERIES = [
  '#2a78d6', // 1 blue
  '#eb6834', // 2 orange
  '#1baf7a', // 3 aqua
  '#eda100', // 4 yellow
  '#e87ba4', // 5 magenta
  '#008300', // 6 green
  '#4a3aa7', // 7 violet
  '#e34948', // 8 red
] as const

/** Past this many categories, the tail folds into "Other" rather than cycling hues. */
export const MAX_SERIES = 6

/** Reserved for state. Never reused as a series colour, always paired with a label. */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

/** Single-hue ramp for magnitude. Light to dark. */
export const SEQUENTIAL = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95'] as const

export const CHROME = {
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  muted: '#898781',
  textPrimary: '#0b0b0b',
  textSecondary: '#52514e',
  surface: '#ffffff',
} as const

/** Tariff periods are ordinal, not categorical: cheap to expensive. */
export const TARIFF_PERIOD_COLOR: Record<string, string> = {
  off_peak: '#9ec5f4',
  shoulder: '#3987e5',
  peak: '#184f95',
  flat: '#3987e5',
}

export const TARIFF_PERIOD_LABEL: Record<string, string> = {
  off_peak: 'Off-peak',
  shoulder: 'Shoulder',
  peak: 'Peak',
  flat: 'Flat rate',
}

export const AXIS_PROPS = {
  stroke: CHROME.axis,
  tick: { fill: CHROME.muted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHROME.axis },
} as const

export const GRID_PROPS = {
  stroke: CHROME.grid,
  strokeDasharray: '0',
  vertical: false,
} as const
