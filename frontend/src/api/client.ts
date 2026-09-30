import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

/** Typed API client generated from the backend's OpenAPI schema (never hand-written). */
export const api = createClient<paths>({ baseUrl: '' })

export type Schemas = components['schemas']

export interface ErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
}

/** Structured API error (the backend always returns `{code, message, details}`). */
export class ApiError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>
  readonly status: number

  constructor(body: ErrorBody, status: number) {
    super(body.message)
    this.code = body.code
    this.details = body.details ?? {}
    this.status = status
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'code' in value &&
    'message' in value &&
    typeof (value as { message: unknown }).message === 'string'
  )
}

/** Unwrap an openapi-fetch result, throwing {@link ApiError} on failure. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const body = isErrorBody(result.error)
      ? result.error
      : { code: `http_${result.response.status}`, message: result.response.statusText }
    throw new ApiError(body, result.response.status)
  }
  return result.data as T
}

/** Base path of the API (also used for WebSockets and file downloads). */
export const API_BASE = '/api/v1'

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${API_BASE}${path}`
}
