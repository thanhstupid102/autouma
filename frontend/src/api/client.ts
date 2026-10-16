import { getSelectedAccount } from '../stores/account'
import { apiTokenHeaders, handleApiUnauthorized } from './apiToken'

export class ApiError extends Error {
  override readonly name = 'ApiError' as const
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

type Opts = { method?: string; body?: unknown; account?: string }

export async function apiJson<T = unknown>(url: string, opts: Opts = {}): Promise<T> {
  const init: RequestInit = { method: opts.method ?? 'GET' }
  const headers: Record<string, string> = apiTokenHeaders()
  // backend ignores X-Account on shared (non-account) endpoints
  const account = opts.account ?? getSelectedAccount()
  if (account) headers['X-Account'] = account
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(opts.body)
  }
  init.headers = headers
  const res = await fetch(url, init)
  handleApiUnauthorized(res)
  let data: unknown = null
  try { data = await res.json() } catch { /* non-JSON */ }
  if (!res.ok) {
    const errBody = data as { detail?: string; message?: string } | null
    throw new ApiError(errBody?.detail ?? errBody?.message ?? `HTTP ${res.status}`, res.status)
  }
  if (res.ok && data === null) throw new ApiError('Non-JSON response', res.status)
  return data as T
}
