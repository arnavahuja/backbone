import { describe, expect, it } from 'vitest'
import { parseNumbers, parseWindows } from './reportWindows'

describe('parseWindows', () => {
  it('reads label, start, end lines and keeps commas in labels', () => {
    const { windows, errors } = parseWindows(
      'GFC, 2007-11-01, 2009-03-31\n\nRates, inflation, 2022-01-01, 2022-12-31',
    )
    expect(errors).toEqual([])
    expect(windows).toEqual([
      { label: 'GFC', start: '2007-11-01', end: '2009-03-31' },
      { label: 'Rates, inflation', start: '2022-01-01', end: '2022-12-31' },
    ])
  })

  it('reports malformed lines', () => {
    expect(parseWindows('bad line\nX, 2020-01, 2020-02-01').errors).toHaveLength(2)
  })
})

describe('parseNumbers', () => {
  it('splits on commas and spaces', () => {
    expect(parseNumbers('0, 5 10;20, x')).toEqual([0, 5, 10, 20])
  })
})
