import { fireEvent, render, screen } from '@testing-library/react'
import { SchemaForm } from './SchemaForm'

const schema = {
  type: 'object',
  properties: {
    fast: { type: 'integer', title: 'Fast', default: 20, minimum: 2 },
    allow_short: { type: 'boolean', title: 'Allow Short', default: false },
    mode: { type: 'string', title: 'Mode', enum: ['a', 'b'], default: 'a' },
  },
}

test('renders fields from JSON Schema and reports changes', () => {
  const onChange = vi.fn()
  render(<SchemaForm schema={schema} value={{}} onChange={onChange} />)
  expect(screen.getByLabelText('Fast')).toBeInTheDocument()
  expect(screen.getByLabelText('Allow Short')).toBeInTheDocument()
  expect(screen.getByLabelText('Mode')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Fast'), { target: { value: '7' } })
  const last = onChange.mock.calls.at(-1) as [Record<string, unknown>, boolean]
  expect(last[0].fast).toBe(7)
})

test('flags invalid values', () => {
  const onChange = vi.fn()
  render(<SchemaForm schema={schema} value={{}} onChange={onChange} />)
  fireEvent.change(screen.getByLabelText('Fast'), { target: { value: '1' } })
  const last = onChange.mock.calls.at(-1) as [Record<string, unknown>, boolean]
  expect(last[1]).toBe(false)
})

test('shows a message when there are no parameters', () => {
  render(<SchemaForm schema={{ type: 'object', properties: {} }} value={{}} onChange={vi.fn()} />)
  expect(screen.getByText('No parameters.')).toBeInTheDocument()
})
