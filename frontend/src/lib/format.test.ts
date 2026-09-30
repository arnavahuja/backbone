import { formatAxis, formatNumber, toText } from './format'

test('formats by metric format', () => {
  expect(formatNumber(0.1234, 'percent')).toBe('12.34%')
  expect(formatNumber(1.5, 'ratio')).toBe('1.50')
  expect(formatNumber(1234567, 'currency')).toBe('$1,234,567')
  expect(formatNumber(null, 'percent')).toBe('—')
  expect(formatNumber(Number.NaN)).toBe('—')
  expect(formatAxis(0.25, 'percent')).toBe('25%')
  expect(toText({ a: 1 })).toBe('{"a":1}')
})
