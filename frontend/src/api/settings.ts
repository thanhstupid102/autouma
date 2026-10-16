import { apiJson } from './client'
import type {
  TurnDelaySettings,
  DiscordWebhookData,
  MasterDataStatus,
  SetMasterDataPathBody,
  SaveWebhookBody,
} from './types'

// ---------------------------------------------------------------------------
// Turn delay
// ---------------------------------------------------------------------------

/** GET /api/settings/turn-delay */
export const getTurnDelay = () => apiJson<TurnDelaySettings>('/api/settings/turn-delay')

/** POST /api/settings/turn-delay — save delay settings */
export const saveTurnDelay = (body: TurnDelaySettings) =>
  apiJson<TurnDelaySettings>('/api/settings/turn-delay', { method: 'POST', body })

// ---------------------------------------------------------------------------
// Discord webhook
// ---------------------------------------------------------------------------

/** GET /api/settings/discord-webhook */
export const getDiscordWebhook = () => apiJson<DiscordWebhookData>('/api/settings/discord-webhook')

/** POST /api/settings/discord-webhook — save webhook URL */
export const saveDiscordWebhook = (body: SaveWebhookBody) =>
  apiJson<DiscordWebhookData>('/api/settings/discord-webhook', { method: 'POST', body })

/** POST /api/settings/discord-webhook/test — send a test message */
export const testDiscordWebhook = () =>
  apiJson<{ success: boolean; detail?: string }>('/api/settings/discord-webhook/test', {
    method: 'POST',
  })

// ---------------------------------------------------------------------------
// Master data
// ---------------------------------------------------------------------------

/** GET /api/master-data/status */
export const getMasterDataStatus = () =>
  apiJson<MasterDataStatus>('/api/master-data/status')

/** POST /api/master-data/config — save master.mdb path and trigger generation */
export const setMasterDataPath = (body: SetMasterDataPathBody) =>
  apiJson<MasterDataStatus>('/api/master-data/config', { method: 'POST', body })
