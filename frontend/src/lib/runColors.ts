import { benchmarkColor, seriesPalette, tokens } from '@/theme/tokens'

/**
 * Stable run -> color assignment so a run keeps the same color in every chart on a page.
 * The order of `runIds` decides the palette index.
 */
export function runColorMap(runIds: readonly string[]): Record<string, string> {
  const map: Record<string, string> = {}
  runIds.forEach((id, i) => {
    map[id] = seriesPalette[i % seriesPalette.length] ?? tokens.accent
  })
  return map
}

export type Role = 'series' | 'benchmark' | 'positive' | 'negative' | 'band' | 'reference'

/** Color for a semantic series role. */
export function roleColor(role: Role): string | undefined {
  switch (role) {
    case 'benchmark':
      return benchmarkColor
    case 'positive':
      return tokens.positive
    case 'negative':
      return tokens.negative
    case 'reference':
      return tokens.text.muted
    case 'band':
      return tokens.border
    case 'series':
      return undefined
  }
}
