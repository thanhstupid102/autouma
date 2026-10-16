import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiJson, ApiError } from './client'
import { API_TOKEN_STORAGE_KEY, storeApiToken } from './apiToken'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('apiJson', () => {
  it('returns parsed JSON on 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true, x: 1 }))))
    expect(await apiJson('/api/auth/session')).toEqual({ success: true, x: 1 })
  })
  it('throws ApiError with detail on HTTP error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })))
    const err = await apiJson('/api/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ name: 'ApiError', message: 'boom', status: 500 })
  })
  it('throws ApiError on non-JSON 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json', { status: 200 })))
    const err = await apiJson('/api/auth/session').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({ name: 'ApiError', message: 'Non-JSON response', status: 200 })
  })
  it('POSTs JSON body', async () => {
    const f = vi.fn().mockResolvedValue(new Response('{"success":true}'))
    vi.stubGlobal('fetch', f)
    await apiJson('/api/selection', { method: 'POST', body: { selection: { deck: 1 } } })
    expect(f).toHaveBeenCalledWith('/api/selection', expect.objectContaining({
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selection: { deck: 1 } }),
    }))
  })

  it('sends the stored token with every request using the canonical Bearer header', async () => {
    storeApiToken('operator-secret')
    const f = vi.fn().mockResolvedValue(new Response('{"success":true}'))
    vi.stubGlobal('fetch', f)

    await apiJson('/api/accounts')

    expect(f).toHaveBeenCalledWith('/api/accounts', expect.objectContaining({
      headers: { Authorization: 'Bearer operator-secret' },
    }))
  })

  it('preserves the stored token for a non-gate 401 and clears it for a gate rejection', async () => {
    storeApiToken('rejected-secret')
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ success: false, detail: 'Nope' }), { status: 401 }),
    ).mockResolvedValueOnce(new Response(
      JSON.stringify({ success: false, detail: 'Nope' }),
      { status: 401, headers: { 'WWW-Authenticate': 'Bearer' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiJson('/api/accounts')).rejects.toMatchObject({ status: 401 })
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('rejected-secret')

    await expect(apiJson('/api/accounts')).rejects.toMatchObject({ status: 401 })
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
  })
})
