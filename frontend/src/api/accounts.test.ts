import { beforeEach, describe, expect, it, vi } from 'vitest'

import { exportAccounts } from './accounts'
import { API_TOKEN_STORAGE_KEY, storeApiToken } from './apiToken'


beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})


describe('exportAccounts', () => {
  it('sends the stored API token on the raw binary export fetch', async () => {
    storeApiToken('export-secret')
    const fetchMock = vi.fn().mockResolvedValue(new Response('bundle'))
    vi.stubGlobal('fetch', fetchMock)

    await exportAccounts(['main'], 'bundle-passphrase')

    expect(fetchMock).toHaveBeenCalledWith('/api/accounts/export', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer export-secret',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ names: ['main'], passphrase: 'bundle-passphrase' }),
    })
  })

  it('preserves the token for a non-gate export 401 and clears it for a gate rejection', async () => {
    storeApiToken('rejected-export-secret')
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Nope' }), { status: 401 }),
    ).mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: 'Nope' }),
      { status: 401, headers: { 'WWW-Authenticate': 'Bearer' } },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(exportAccounts(['main'], 'passphrase')).rejects.toThrow('Export failed: Nope')
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('rejected-export-secret')

    await expect(exportAccounts(['main'], 'passphrase')).rejects.toThrow('Export failed: Nope')
    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
  })
})
