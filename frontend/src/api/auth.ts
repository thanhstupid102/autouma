import { apiJson } from './client'
import type {
  SessionData,
  LoginBody,
  TransitionCodeChainBody,
  TransitionCodeChainData,
  SteamUnbindBody,
  SteamUnbindPreflightBody,
  SteamUnbindData,
  QrStartData,
  QrPollData,
} from './types'

/** GET /api/auth/session — restore existing session (cache-busted by caller if needed) */
export const getSession = (account?: string) =>
  apiJson<SessionData>('/api/auth/session', { account })

/** POST /api/auth/session/refresh — pull fresh state from the game, then caller reloads */
export const refreshSession = () =>
  apiJson<{ success: boolean; [k: string]: unknown }>('/api/auth/session/refresh', { method: 'POST' })

/**
 * POST /api/auth/login — three call sites in app.js:
 *   1. line 574: full credential login { username, password, code }
 *   2. line 2702: silent auto-login {}
 *   3. line 2758: post-QR-confirm login {}
 * All three send a POST with JSON body (empty or credentials).
 */
export const login = (body: LoginBody = {}, account?: string) =>
  apiJson<SessionData>('/api/auth/login', { method: 'POST', body, account })

/** POST /api/auth/transition-code/chain — preview or commit a Trainer-ID link. */
export const transitionCodeChain = (body: TransitionCodeChainBody, account?: string) =>
  apiJson<TransitionCodeChainData>('/api/auth/transition-code/chain', {
    method: 'POST',
    body,
    account,
  })

/** POST /api/auth/leave-session */
export const leaveSession = () =>
  apiJson<{ success: boolean }>('/api/auth/leave-session', { method: 'POST' })

/** POST /api/auth/steam/unbind/preflight — diagnostic Trainer-ID recovery check only. */
export const preflightSteamUnbind = (body: SteamUnbindPreflightBody, account?: string) =>
  apiJson<SteamUnbindData>('/api/auth/steam/unbind/preflight', {
    method: 'POST',
    body,
    account,
  })

/** POST /api/auth/steam/unbind — explicit final Steam unlink action. */
export const steamUnbind = (body: SteamUnbindBody, account?: string) =>
  apiJson<SteamUnbindData>('/api/auth/steam/unbind', {
    method: 'POST',
    body,
    account,
  })

/** POST /api/auth/steam/qr/start — initiate Steam QR challenge (for `account`) */
export const qrStart = (account?: string) =>
  apiJson<QrStartData>('/api/auth/steam/qr/start', { method: 'POST', account })

/** GET /api/auth/steam/qr/poll — poll for QR scan result (for `account`) */
export const qrPoll = (account?: string) =>
  apiJson<QrPollData>('/api/auth/steam/qr/poll', { account })
