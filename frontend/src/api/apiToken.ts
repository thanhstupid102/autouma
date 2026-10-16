export const API_TOKEN_STORAGE_KEY = 'uma_api_token'

export type ApiTokenChangeReason = 'stored' | 'forgotten' | 'unauthorized'

type Listener = (reason: ApiTokenChangeReason) => void
const listeners = new Set<Listener>()

function notify(reason: ApiTokenChangeReason) {
  for (const listener of listeners) listener(reason)
}

export function getApiToken(): string | null {
  const token = localStorage.getItem(API_TOKEN_STORAGE_KEY)
  return token && token.trim() ? token : null
}

export function storeApiToken(token: string): void {
  const normalizedToken = token.trim()
  if (!normalizedToken) {
    forgetApiToken()
    return
  }
  localStorage.setItem(API_TOKEN_STORAGE_KEY, normalizedToken)
  notify('stored')
}

export function forgetApiToken(reason: ApiTokenChangeReason = 'forgotten'): void {
  const hadToken = getApiToken() !== null
  localStorage.removeItem(API_TOKEN_STORAGE_KEY)
  if (hadToken) notify(reason)
}

export function subscribeApiToken(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function apiTokenHeaders(): Record<string, string> {
  const token = getApiToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function isApiTokenRejection(res: Response): boolean {
  const challenge = res.headers.get('WWW-Authenticate')
  return res.status === 401 && challenge !== null && /^\s*Bearer(?:\s|$)/i.test(challenge)
}

export function handleApiUnauthorized(res: Response): void {
  if (isApiTokenRejection(res)) forgetApiToken('unauthorized')
}
