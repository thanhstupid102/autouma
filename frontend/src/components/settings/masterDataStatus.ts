/**
 * Pure status-text logic for MasterDataCard — extracted for unit testing.
 */

import type { MasterDataStatus } from '@/api/types'

export type StatusKind = 'ok' | 'warn'

export interface StatusResult {
  text: string
  kind: StatusKind
}

/**
 * Derives a human-readable status line and its severity from a MasterDataStatus
 * response. Mirrors the 4-branch logic in app.js:275-285.
 */
export function masterDataStatusText(data: MasterDataStatus): StatusResult {
  if (data.exists) {
    if (data.generation_error) {
      return { text: data.generation_error, kind: 'warn' }
    }
    if (data.generated) {
      return { text: 'master.mdb found; data generated', kind: 'ok' }
    }
    return { text: 'master.mdb found', kind: 'ok' }
  }
  return {
    text: data.access_error ?? 'master.mdb not found; update the path',
    kind: 'warn',
  }
}
