/**
 * Design tokens: the only place color values live.
 *
 * Rule: no purple, violet, indigo, magenta or lavender anywhere (including chart palettes,
 * focus rings, gradients and library defaults).
 */
export const tokens = {
  bg: { base: '#0A0A0A', surface: '#121212', elevated: '#1A1A1A' },
  border: '#262626',
  text: { primary: '#EDEDED', secondary: '#A3A3A3', muted: '#6B6B6B' },
  accent: '#14B8A6',
  accentStrong: '#0D9488',
  positive: '#22C55E',
  negative: '#EF4444',
  warning: '#F59E0B',
  info: '#38BDF8',
  fill: {
    negativeBand: 'rgba(239,68,68,0.10)',
    accentSoft: 'rgba(20,184,166,0.12)',
    accentMedium: 'rgba(20,184,166,0.2)',
  },
} as const

/** Chart series palette, in order. */
export const seriesPalette = [
  '#14B8A6',
  '#F59E0B',
  '#38BDF8',
  '#F97316',
  '#84CC16',
  '#EF4444',
  '#EAB308',
  '#06B6D4',
  '#E5E5E5',
  '#10B981',
] as const

/** Benchmark series are always this gray, dashed. */
export const benchmarkColor = '#8A8A8A'

/** Diverging scale for heatmaps (negative -> neutral -> positive), no purple. */
export const divergingScale = ['#EF4444', '#7F1D1D', '#1A1A1A', '#134E4A', '#14B8A6'] as const

export type SeriesColor = (typeof seriesPalette)[number]
