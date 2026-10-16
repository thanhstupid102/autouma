import { apiJson } from './client'
import { apiTokenHeaders, handleApiUnauthorized } from './apiToken'
import { type AccountSnapshot } from './types/account'

export const listAccounts = () =>
  apiJson<{ success: boolean; accounts: AccountSnapshot[] }>('/api/accounts')

export const deleteAccount = (name: string) =>
  apiJson<{ success: boolean; deleted: string[] }>(`/api/accounts/${encodeURIComponent(name)}`, { method: 'DELETE' })

/** Export returns a BINARY bundle (octet-stream), so use raw fetch + blob, not apiJson. */
export async function exportAccounts(names: string[], passphrase: string): Promise<Blob> {
  const headers: Record<string, string> = {
    ...apiTokenHeaders(),
    'Content-Type': 'application/json',
  }
  const res = await fetch('/api/accounts/export', {
    method: 'POST',
    headers,
    body: JSON.stringify({ names, passphrase }),
  })
  handleApiUnauthorized(res)
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); detail = j?.detail ?? detail } catch { /* binary or empty */ }
    throw new Error(`Export failed: ${detail}`)
  }
  return res.blob()
}

/** Import sends the bundle as base64 inside a JSON body (no multipart on the server). */
export async function importAccounts(file: File, passphrase: string, overwrite: boolean) {
  const buf = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let i = 0; i < buf.length; i++) binary += String.fromCharCode(buf[i])
  const bundle_b64 = btoa(binary)
  return apiJson<{ success: boolean; imported: string[]; skipped: string[] }>(
    '/api/accounts/import',
    { method: 'POST', body: { bundle_b64, passphrase, overwrite } },
  )
}
